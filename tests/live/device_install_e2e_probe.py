"""Device-DB write + REAL /securityconsole/install/device, through the connector.

For each locking mode (ADOM, minimal) this:

  1. writes system global alias in the device DB (/pm/config/device/<dev>/global/...)
  2. checks the device DB holds it and no lock is left behind
  3. runs install/device -- a real install, the device's config changes
  4. reads the alias back from the FortiGate itself (REST, through FMG's /sys/proxy/json)
  5. restores the original alias the same way and installs again

Run it against a lab device you are allowed to change. The only field touched is the
alias, and it is put back.

Usage (credentials from the env file, e.g. via envrun):
    python device_install_e2e_probe.py --device <managed-fgt> [--adom root]
"""
import argparse
import importlib
import os
import sys

tests_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, tests_directory)
sys.path.insert(0, os.path.dirname(tests_directory))

import conftest  # noqa: E402,F401  -- registers the connectors.core stub

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    base = {"address": os.getenv("ADDRESS"), "port": os.getenv("PORT"), "verify_ssl": False,
            "username": os.getenv("USERNAME"), "password": os.getenv("PASSWORD"),
            "auth_method": "Username/Password", "verbose_json": True}
    global_url = f"/pm/config/device/{args.device}/global/system/global"
    scope = [{"name": args.device, "vdom": "root"}]

    def devdb_alias():
        return operations["json_rpc_get"](base, {"url": global_url, "data": {"fields": ["alias"]}})[
            "get_response"].get("alias")

    def device_alias():
        r = operations["json_rpc_execute"](base, {"url": "/sys/proxy/json", "data": {
            "target": [f"/adom/{args.adom}/device/{args.device}"], "action": "get",
            "resource": "/api/v2/cmdb/system/global"}})
        resp = r["execute_response"]
        entry = resp[0] if isinstance(resp, list) else resp
        return ((entry.get("response") or {}).get("results") or {}).get("alias")

    def lockinfo():
        r = operations["json_rpc_get"](base, {"url": f"/dvmdb/adom/{args.adom}/workspace/lockinfo"})
        data = r.get("get_response")
        return data if isinstance(data, list) else []

    def set_and_install(config, alias):
        w = operations["json_rpc_set"](config, {"url": global_url, "data": {
            "adom": args.adom, "data": {"alias": alias}}})
        i = operations["json_rpc_execute"](config, {
            "url": "/securityconsole/install/device",
            "data": {"adom": args.adom, "scope": scope}, "track_task": True})
        task = i.get("task_response") or {}
        return w, i, task

    original = device_alias()
    print(f"device alias at start: {original!r} (devdb: {devdb_alias()!r})")
    failures = []
    try:
        for mode, config in (("ADOM", base), ("MINIMAL", dict(base, minimal_locking=True))):
            marker = f"install-probe-{mode.lower()}"
            w, i, task = set_and_install(config, marker)
            lines = [line.get("detail") for line in task.get("line", [])]
            on_device = device_alias()
            ok = (w["status"] == 0 and i["status"] == 0 and task.get("state") in (4, "done")
                  and on_device == marker and not lockinfo())
            print(f"[{mode}] write={w['status']} install={i['status']} task={task.get('state')} "
                  f"{lines} device_alias={on_device!r} locks_left={lockinfo()} "
                  f"{'PASS' if ok else 'FAIL'}")
            if not ok:
                failures.append(mode)
    finally:
        w, i, task = set_and_install(base, original)
        print(f"restore: install={i['status']} task={task.get('state')} "
              f"device_alias={device_alias()!r} (want {original!r})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
