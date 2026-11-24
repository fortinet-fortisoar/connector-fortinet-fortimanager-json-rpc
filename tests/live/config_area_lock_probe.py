"""
Which workspace lock do FortiManager's non-package config areas need?

The connector locks policy packages and devices at their own scope and everything else
at ADOM scope. The "everything else" was never measured: templates, template groups,
provisioning profiles, SD-WAN templates and device groups all fall back to the ADOM
lock by default. For each one this probe runs, in workspace mode:

    UNLOCKED     the write with no lock held
    ADOM         the same write under this session's ADOM lock
    PKG_HELD     the same write under the ADOM lock attempt while ANOTHER session holds
                 a policy-package lock -- shows whether this area really contends with
                 package work, i.e. whether an ADOM lock is the price of writing it

and classifies UNLOCKED/ADOM as NOT_NEEDED / REQUIRED / LOCK_HARMFUL / INCONCLUSIVE.
Everything it creates is named lockprobe-* and deleted at the end.

It also measures two things about lock lifetime:

    stale        a session that takes the ADOM lock and is then abandoned (never logs
                 out): how long until FortiManager frees the lock on its own
    override     whether a second session can release a lock it does not own

Usage (credentials from the env file, workspace mode already on):
    python config_area_lock_probe.py [--adom root] [--package default] [--stale-minutes 20]
"""
import argparse
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

from pyFMG.fortimgr import FortiManager  # noqa: E402


def session():
    host = os.environ["ADDRESS"].split("://")[-1].rstrip("/") + ":" + os.environ["PORT"]
    fmg = FortiManager(host, os.environ["USERNAME"], os.environ["PASSWORD"],
                       verify_ssl=False, disable_request_warnings=True, timeout=120)
    fmg.login()
    return fmg


def code(response):
    status, body = response
    message = body.get("status", {}).get("message") if isinstance(body, dict) else None
    return status, message


def areas(adom):
    """(label, add url, data, delete url) per config area."""
    obj = f"/pm/config/adom/{adom}/obj"
    return [
        ("cli template", f"{obj}/cli/template",
         {"name": "lockprobe-tmpl", "type": "cli", "script": "config system global\nend"},
         f"{obj}/cli/template/lockprobe-tmpl"),
        ("cli template group", f"{obj}/cli/template-group",
         {"name": "lockprobe-tgrp"}, f"{obj}/cli/template-group/lockprobe-tgrp"),
        ("system template (devprof)", f"/pm/devprof/adom/{adom}",
         {"name": "lockprobe-devprof", "type": "devprof"},
         f"/pm/devprof/adom/{adom}/lockprobe-devprof"),
        ("sd-wan template (wanprof)", f"/pm/wanprof/adom/{adom}",
         {"name": "lockprobe-wanprof", "type": "wanprof"},
         f"/pm/wanprof/adom/{adom}/lockprobe-wanprof"),
        ("device group", f"/dvmdb/adom/{adom}/group",
         {"name": "lockprobe-grp", "os_type": "fos"}, f"/dvmdb/adom/{adom}/group/lockprobe-grp"),
        ("firewall address (control)", f"{obj}/firewall/address",
         {"name": "lockprobe-addr", "type": "ipmask", "subnet": ["198.51.100.77", "255.255.255.255"]},
         f"{obj}/firewall/address/lockprobe-addr"),
    ]


def cleanup(adom, entries):
    fmg = session()
    try:
        fmg.lock_adom(adom)
        for _, _, _, delete_url in entries:
            fmg.delete(delete_url)
        fmg.commit_changes(adom)
        fmg.unlock_adom(adom)
    finally:
        fmg.logout()


def exists(fmg, delete_url):
    return fmg.get(delete_url)[0] == 0


def run_areas(adom, package):
    entries = areas(adom)
    cleanup(adom, entries)
    print(f"{'area':30} {'UNLOCKED':28} {'ADOM':28} {'PKG_HELD':22} verdict")
    for label, url, data, delete_url in entries:
        row = {}
        # UNLOCKED
        fmg = session()
        try:
            row["unlocked"] = code(fmg.add(url, **data))
            persisted_unlocked = exists(fmg, delete_url)
        finally:
            fmg.logout()
        cleanup(adom, [(label, url, data, delete_url)])
        # ADOM
        fmg = session()
        try:
            lock = fmg.lock_adom(adom)[0]
            row["adom"] = code(fmg.add(url, **data)) if lock == 0 else (lock, "lock failed")
            fmg.commit_changes(adom)
            fmg.unlock_adom(adom)
            persisted_adom = exists(fmg, delete_url)
        finally:
            fmg.logout()
        cleanup(adom, [(label, url, data, delete_url)])
        # PKG_HELD: another session holds a package; can this area still be written?
        holder = session()
        fmg = session()
        try:
            holder.execute(f"/dvmdb/adom/{adom}/workspace/lock/pkg/{package}")
            lock = fmg.lock_adom(adom)[0]
            row["pkg_held"] = (lock, "adom lock refused" if lock else "adom lock granted")
            if lock == 0:
                fmg.unlock_adom(adom)
        finally:
            holder.execute(f"/dvmdb/adom/{adom}/workspace/unlock/pkg/{package}")
            holder.logout()
            fmg.logout()
        a_ok = row["unlocked"][0] == 0 and persisted_unlocked
        b_ok = row["adom"][0] == 0 and persisted_adom
        verdict = {(True, True): "NOT_NEEDED", (False, True): "REQUIRED",
                   (True, False): "LOCK_HARMFUL", (False, False): "INCONCLUSIVE"}[(a_ok, b_ok)]
        fmt = lambda c, p=None: f"{c[0]} {(c[1] or '')[:18]}" + ("" if p is None else f" saved={p}")
        print(f"{label:30} {fmt(row['unlocked'], persisted_unlocked):28} "
              f"{fmt(row['adom'], persisted_adom):28} {fmt(row['pkg_held']):22} {verdict}")


def lockinfo(fmg, adom):
    data = fmg.get(f"/dvmdb/adom/{adom}/workspace/lockinfo")[1]
    return data if isinstance(data, list) else []


def run_override(adom):
    owner, other = session(), session()
    try:
        print("owner lock:", owner.lock_adom(adom)[0])
        print("other unlock (not owner):", code(other.execute(f"/dvmdb/adom/{adom}/workspace/unlock")))
        print("still locked after other's unlock:", bool(lockinfo(other, adom)))
    finally:
        owner.unlock_adom(adom)
        owner.logout()
        other.logout()


def run_stale(adom, minutes):
    abandoned = session()
    print("abandoned session lock:", abandoned.lock_adom(adom)[0])
    # Drop the client without logging out, as a killed worker would.
    abandoned.sess.close()
    watcher = session()
    try:
        start = time.monotonic()
        while time.monotonic() - start < minutes * 60:
            held = lockinfo(watcher, adom)
            print(f"  {time.monotonic() - start:4.0f}s  lock still held: {bool(held)}", flush=True)
            if not held:
                print(f"stale lock freed by FortiManager after {time.monotonic() - start:.0f}s")
                return
            time.sleep(30)
            # A watcher session idles out too; refresh it.
            watcher.logout()
            watcher = session()
        print(f"stale lock still held after {minutes} min: {held}")
    finally:
        watcher.logout()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--package", default="default")
    parser.add_argument("--stale-minutes", type=int, default=20)
    parser.add_argument("--only", choices=["areas", "override", "stale"], default=None)
    args = parser.parse_args()
    if args.only in (None, "areas"):
        run_areas(args.adom, args.package)
    if args.only in (None, "override"):
        run_override(args.adom)
    if args.only in (None, "stale"):
        run_stale(args.adom, args.stale_minutes)


if __name__ == "__main__":
    sys.exit(main())
