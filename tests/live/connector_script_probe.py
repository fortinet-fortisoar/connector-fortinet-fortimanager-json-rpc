"""
Does /dvmdb/adom/<adom>/script/execute through the CONNECTOR save its change?

script_lock_probe shows a device- or ADOM-database script needs the workspace lock held
while its queued task runs (unlocked, the task fails "No permission for the resource"
while the RPC returns 0). The connector releases its lock when the session closes, and
script/execute is not in HOLD_LOCK_UNTIL_TASK_URLS -- so whether the change lands may
depend on whether the caller tracked the task. This runs each combination through
operations["json_rpc_execute"] and reads the result back:

    target   device_database (sets system global alias) | adom_database (adds an address)
    locking  ADOM | minimal
    track    track_task False | True

Usage (workspace mode on):
    python connector_script_probe.py --device <managed-fgt> [--adom root] [--package default]
"""
import argparse
import importlib
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
tests_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, tests_directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(tests_directory))
import conftest  # noqa: E402,F401

from script_lock_probe import TARGETS, locked, session  # noqa: E402

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations
NAME = "lockprobe-cscript"
ADDR = "lockprobe-cscripted"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--package", default="default")
    parser.add_argument("--device", required=True)
    parser.add_argument("--target", choices=["device_database", "adom_database"], default=None)
    parser.add_argument("--mode", choices=["ADOM", "MINIMAL"], default=None)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    adom = args.adom
    script_url = f"/pm/config/adom/{adom}/obj/fmg/script"
    addr_url = f"/pm/config/adom/{adom}/obj/firewall/address/{ADDR}"
    alias_url = f"/pm/config/device/{args.device}/global/system/global"

    def read(url, field=None):
        fmg = session()
        try:
            status, body = fmg.get(url)
            return (body or {}).get(field) if field else status == 0
        finally:
            fmg.logout()

    original_alias = read(alias_url, "alias")
    base = {"address": os.environ["ADDRESS"], "port": os.environ["PORT"], "verify_ssl": False,
            "username": os.environ["USERNAME"], "password": os.environ["PASSWORD"],
            "auth_method": "Username/Password", "verbose_json": True}
    try:
        for target in [t for t in ("device_database", "adom_database") if args.target in (None, t)]:
            for mode, config in [m for m in (("ADOM", base), ("MINIMAL", dict(base, minimal_locking=True)))
                                 if args.mode in (None, m[0])]:
                for track in [t for t in (False, True) for _ in range(args.repeat)]:
                    marker = f"lockprobe-{mode.lower()}-{int(track)}"
                    if target == "device_database":
                        content = f"config system global\nset alias {marker}\nend"
                        data = {"adom": adom, "script": NAME,
                                "scope": [{"name": args.device, "vdom": "root"}]}
                    else:
                        content = (f'config firewall address\nedit "{ADDR}"\n'
                                   f'set comment {marker}\nset subnet 198.51.100.79 255.255.255.255\nnext\nend')
                        data = {"adom": adom, "package": args.package, "script": NAME}
                    locked(adom, lambda f: (f.delete(f"{script_url}/{NAME}"), f.delete(addr_url),
                                            f.add(script_url, data={"name": NAME, "type": 1,
                                                                    "target": TARGETS[target],
                                                                    "content": content})))
                    started = time.monotonic()
                    response = operations["json_rpc_execute"](config, {
                        "url": f"/dvmdb/adom/{adom}/script/execute", "data": data,
                        "track_task": track})
                    took = time.monotonic() - started
                    # Read back at once and again 20s later: a value that is there and
                    # then gone was reverted after the call, not never written.
                    def now_saved():
                        if target == "device_database":
                            return read(alias_url, "alias") == marker
                        return read(addr_url, "comment") == marker
                    saved_now = now_saved()
                    time.sleep(20)
                    saved = f"{saved_now}->{now_saved()}"
                    task = response.get("task_response") or {}
                    print(f"{target:16} {mode:8} track={track!s:5} status={response.get('status')} "
                          f"task={task.get('state')} saved={saved} ({took:.1f}s)", flush=True)
    finally:
        locked(adom, lambda f: (f.delete(f"{script_url}/{NAME}"), f.delete(addr_url),
                                f.set(alias_url, data={"alias": original_alias or ""})))
        print("restored alias:", read(alias_url, "alias"), "(was", repr(original_alias), ")")


if __name__ == "__main__":
    main()
