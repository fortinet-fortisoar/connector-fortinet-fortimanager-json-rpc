"""
Requests that span ADOMs, and the global ADOM, through the connector.

Needs ADOMs enabled and a second scratch ADOM (created here if missing, with --setup).

    FREEFORM_2_ADOMS   one json_rpc_freeform batch adding an address in ADOM A and one
                       in ADOM B. The connector resolves the ADOM from the first URL only,
                       so it locks A; does the write to B land?
    GLOBAL_WRITE       an address in the global ADOM (/pm/config/global/obj/...). The
                       connector treats "global" as unlockable and runs unlocked; does
                       FortiManager accept that in workspace mode, and does a lock exist?

Each runs under ADOM locking and minimal locking, password auth. Objects are named
lockprobe-* and removed afterwards.

Usage:
    python multi_adom_probe.py --adom-b lockprobe_b [--setup] [--teardown]
"""
import argparse
import importlib
import os
import sys
import warnings

warnings.filterwarnings("ignore")
tests_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, tests_directory)
sys.path.insert(0, os.path.dirname(tests_directory))
import conftest  # noqa: E402,F401

from pyFMG.fortimgr import FortiManager  # noqa: E402

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations


def session():
    host = os.environ["ADDRESS"].split("://")[-1].rstrip("/") + ":" + os.environ["PORT"]
    fmg = FortiManager(host, os.environ["USERNAME"], os.environ["PASSWORD"],
                       verify_ssl=False, disable_request_warnings=True, timeout=120)
    fmg.login()
    return fmg


def addr(name, octet):
    return {"name": name, "type": "ipmask", "subnet": [f"198.51.100.{octet}", "255.255.255.255"]}


def addr_url(adom):
    return "/pm/config/global/obj/firewall/address" if adom == "global" else \
        f"/pm/config/adom/{adom}/obj/firewall/address"


def exists(adom, name):
    fmg = session()
    try:
        return fmg.get(f"{addr_url(adom)}/{name}")[0] == 0
    finally:
        fmg.logout()


def remove(adom, name):
    fmg = session()
    try:
        if adom != "global":
            fmg.lock_adom(adom)
        else:
            fmg.lock_adom("global")
        fmg.delete(f"{addr_url(adom)}/{name}")
        fmg.commit_changes(adom)
        fmg.unlock_adom(adom)
    finally:
        fmg.logout()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom-a", default="root")
    parser.add_argument("--adom-b", default="lockprobe_b")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args()
    a, b = args.adom_a, args.adom_b

    if args.setup:
        fmg = session()
        try:
            if fmg.get(f"/dvmdb/adom/{b}")[0] != 0:
                print("create adom", b, fmg.add("/dvmdb/adom", data={
                    "name": b, "restricted_prds": "fos", "os_ver": "7.0", "mr": 6}))
        finally:
            fmg.logout()

    base = {"address": os.environ["ADDRESS"], "port": os.environ["PORT"], "verify_ssl": False,
            "username": os.environ["USERNAME"], "password": os.environ["PASSWORD"],
            "auth_method": "Username/Password", "verbose_json": True}
    for mode, config in (("ADOM", base), ("MINIMAL", dict(base, minimal_locking=True))):
        na, nb = f"lockprobe-ff-a-{mode.lower()}", f"lockprobe-ff-b-{mode.lower()}"
        try:
            r = operations["json_rpc_freeform"](config, {"method": "add", "data": [
                {"url": addr_url(a), "data": [addr(na, 81)]},
                {"url": addr_url(b), "data": [addr(nb, 82)]}]})
            codes = [x.get("status", {}).get("code") for x in r.get("free_form_response", [])] \
                if isinstance(r.get("free_form_response"), list) else r.get("free_form_response")
            print(f"FREEFORM_2_ADOMS [{mode}] status={r.get('status')} per-url={codes} "
                  f"saved A={exists(a, na)} B={exists(b, nb)}")
        except Exception as error:
            print(f"FREEFORM_2_ADOMS [{mode}] raised: {str(error)[:300]}")
        finally:
            remove(a, na)
            remove(b, nb)

        ng = f"lockprobe-global-{mode.lower()}"
        try:
            r = operations["json_rpc_add"](config, {"url": addr_url("global"), "data": {"data": [addr(ng, 83)]}})
            print(f"GLOBAL_WRITE [{mode}] status={r.get('status')} {str(r.get('add_response'))[:160]} "
                  f"saved={exists('global', ng)}")
        except Exception as error:
            print(f"GLOBAL_WRITE [{mode}] raised: {str(error)[:300]}")
        finally:
            remove("global", ng)

    # Is there a global lock at all, and does an unlocked global write pass while one is held?
    holder, other = session(), session()
    try:
        held = holder.lock_adom("global")
        print("global lock by holder:", held[0], str(held[1])[:120])
        r = other.add(addr_url("global"), data=[addr("lockprobe-global-contended", 84)])
        print("unlocked global write while holder has global lock:", r[0], str(r[1])[:120])
    finally:
        holder.unlock_adom("global")
        holder.logout()
        other.logout()
        remove("global", "lockprobe-global-contended")

    if args.teardown:
        fmg = session()
        try:
            print("delete adom", b, fmg.delete(f"/dvmdb/adom/{b}")[0])
        finally:
            fmg.logout()


if __name__ == "__main__":
    main()
