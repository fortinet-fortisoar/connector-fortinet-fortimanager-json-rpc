"""
Does CLI script execution respect workspace locks, and does it need one?

lock_matrix_probe classifies /dvmdb/adom/<adom>/script/execute as NOT_NEEDED because the
task finishes "done" with and without a lock. That says nothing about whether the
script's change was SAVED, or whether an unlocked script writes straight through a lock
another session holds. This probe checks both, per target:

    adom_database    script creates a firewall address in the ADOM via a package
    device_database  script sets system global alias in the device DB

Arms, each followed by reading the object back:

    UNLOCKED         no lock anywhere
    OWN_LOCK         this session holds the ADOM lock across the task
    OTHER_HOLDS      another session holds the ADOM lock; this session runs unlocked

If OTHER_HOLDS still saves the change, scripts bypass workspace locking entirely and the
connector's lock buys nothing; if UNLOCKED runs "done" but saves nothing, the lock is
required and the matrix verdict is wrong.

Usage (workspace mode on):
    python script_lock_probe.py --device <managed-fgt> [--adom root] [--package default]
"""
import argparse
import os
import time
import warnings

warnings.filterwarnings("ignore")

from pyFMG.fortimgr import FortiManager  # noqa: E402

NAME = "lockprobe-script"
# FMG enum values (same as lock_matrix_probe): the string forms are not accepted for every target.
TARGETS = {"device_database": 0, "adom_database": 2}
ADDR = "lockprobe-scripted"


def session():
    host = os.environ["ADDRESS"].split("://")[-1].rstrip("/") + ":" + os.environ["PORT"]
    fmg = FortiManager(host, os.environ["USERNAME"], os.environ["PASSWORD"],
                       verify_ssl=False, disable_request_warnings=True, timeout=120)
    fmg.login()
    return fmg


def locked(adom, fn):
    fmg = session()
    try:
        fmg.lock_adom(adom)
        out = fn(fmg)
        fmg.commit_changes(adom)
        fmg.unlock_adom(adom)
        return out
    finally:
        fmg.logout()


def run_task(fmg, adom, data):
    status, response = fmg.execute(f"/dvmdb/adom/{adom}/script/execute", data=data)
    task = response.get("task") if isinstance(response, dict) else None
    if status != 0 or not task:
        return status, None, response
    track, task_response = fmg.track_task(task, timeout=180)
    lines = [l.get("detail") for l in task_response.get("line", [])] if isinstance(task_response, dict) else []
    return status, task_response.get("state") if isinstance(task_response, dict) else None, lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--package", default="default")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()
    adom = args.adom
    script_url = f"/pm/config/adom/{adom}/obj/fmg/script"
    addr_url = f"/pm/config/adom/{adom}/obj/firewall/address/{ADDR}"
    alias_url = f"/pm/config/device/{args.device}/global/system/global"

    def read_alias():
        fmg = session()
        try:
            return (fmg.get(alias_url, fields=["alias"])[1] or {}).get("alias")
        finally:
            fmg.logout()

    def addr_exists():
        fmg = session()
        try:
            return fmg.get(addr_url)[0] == 0
        finally:
            fmg.logout()

    original_alias = read_alias()
    targets = {
        "adom_database": dict(
            content=f'config firewall address\nedit "{ADDR}"\nset subnet 198.51.100.78 255.255.255.255\nnext\nend',
            data={"adom": adom, "package": args.package, "script": NAME},
            saved=addr_exists,
            reset=lambda: locked(adom, lambda f: f.delete(addr_url))),
        "device_database": dict(
            content=None,
            data={"adom": adom, "script": NAME, "scope": [{"name": args.device, "vdom": "root"}]},
            saved=None, reset=None),
    }
    try:
        for target, spec in targets.items():
            for arm in ("UNLOCKED", "OWN_LOCK", "OTHER_HOLDS"):
                marker = f"lockprobe-{arm.lower()}"
                content = spec["content"] or f"config system global\nset alias {marker}\nend"
                created = locked(adom, lambda f: (f.delete(f"{script_url}/{NAME}"), f.add(script_url, data={
                    "name": NAME, "type": 1, "target": TARGETS[target], "content": content}))[1])
                if created[0] != 0:
                    print(f"{target:16} {arm:12} could not create the script: {created}")
                    continue
                if spec["reset"]:
                    spec["reset"]()
                holder = None
                fmg = session()
                try:
                    if arm == "OWN_LOCK":
                        fmg.lock_adom(adom)
                    if arm == "OTHER_HOLDS":
                        holder = session()
                        holder.lock_adom(adom)
                    status, state, detail = run_task(fmg, adom, spec["data"])
                    if arm == "OWN_LOCK":
                        fmg.commit_changes(adom)
                        fmg.unlock_adom(adom)
                finally:
                    if holder:
                        holder.unlock_adom(adom)
                        holder.logout()
                    fmg.logout()
                saved = spec["saved"]() if spec["saved"] else read_alias() == marker
                print(f"{target:16} {arm:12} rpc={status} task={state} saved={saved} {str(detail)[:120]}")
    finally:
        locked(adom, lambda f: (f.delete(f"{script_url}/{NAME}"), f.delete(addr_url),
                                f.set(alias_url, data={"alias": original_alias or ""})))
        print("restored alias:", read_alias(), "(was", repr(original_alias), ")")


if __name__ == "__main__":
    main()
