"""
Does a device-database SCRIPT run under a device lock reach the FortiGate on install?

A device-database *write* under a dev/<device> lock reports success but leaves the device
"nomod", so the next install/device skips it -- which is why those URLs take the ADOM lock
(see ADOM_ONLY_URL_PREFIXES). With minimal locking, /dvmdb/adom/<adom>/script/execute with
a device scope resolves to a dev/<device> lock too. This checks whether the same trap
applies to scripts. Per locking mode, through the connector:

  1. run a device-database script setting system global alias to a marker
  2. run install/device for that device
  3. read the alias from the FortiGate itself (REST through /sys/proxy/json)

then restore the original alias the same way. The only field touched is the alias.

Usage (workspace mode on):
    python devdb_script_install_probe.py --device <managed-fgt> [--adom root] [--rounds 2]
"""
import argparse
import importlib
import os
import sys
import warnings

warnings.filterwarnings("ignore")
here = os.path.dirname(os.path.abspath(__file__))
tests_directory = os.path.dirname(here)
sys.path[:0] = [here, tests_directory, os.path.dirname(tests_directory)]
import conftest  # noqa: E402,F401

from script_lock_probe import TARGETS, locked  # noqa: E402

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations
NAME = "lockprobe-devscript"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--device", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    adom, device = args.adom, args.device
    script_url = f"/pm/config/adom/{adom}/obj/fmg/script"
    base = {"address": os.environ["ADDRESS"], "port": os.environ["PORT"], "verify_ssl": False,
            "username": os.environ["USERNAME"], "password": os.environ["PASSWORD"],
            "auth_method": "Username/Password", "verbose_json": True}

    def device_alias():
        r = operations["json_rpc_execute"](base, {"url": "/sys/proxy/json", "data": {
            "target": [f"/adom/{adom}/device/{device}"], "action": "get",
            "resource": "/api/v2/cmdb/system/global"}})
        entry = r["execute_response"]
        entry = entry[0] if isinstance(entry, list) else entry
        return ((entry.get("response") or {}).get("results") or {}).get("alias")

    def db_status():
        r = operations["json_rpc_get"](base, {"url": f"/dvmdb/adom/{adom}/device/{device}",
                                              "data": {"fields": ["db_status"]}})
        return (r.get("get_response") or {}).get("db_status")

    def script_then_install(config, alias):
        locked(adom, lambda f: (f.delete(f"{script_url}/{NAME}"), f.add(script_url, data={
            "name": NAME, "type": 1, "target": TARGETS["device_database"],
            "content": f"config system global\nset alias {alias}\nend"})))
        s = operations["json_rpc_execute"](config, {
            "url": f"/dvmdb/adom/{adom}/script/execute",
            "data": {"adom": adom, "script": NAME, "scope": [{"name": device, "vdom": "root"}]}})
        status_after_script = db_status()
        i = operations["json_rpc_execute"](config, {
            "url": "/securityconsole/install/device",
            "data": {"adom": adom, "scope": [{"name": device, "vdom": "root"}]}, "track_task": True})
        lines = [line.get("detail") for line in (i.get("task_response") or {}).get("line", [])]
        return s, status_after_script, i, lines

    original = device_alias()
    print(f"device alias at start: {original!r}", flush=True)
    try:
        for rnd in range(args.rounds):
            for mode, config in (("ADOM", base), ("MINIMAL", dict(base, minimal_locking=True))):
                marker = f"lockprobe-ds-{mode.lower()}-{rnd}"
                s, mod, i, lines = script_then_install(config, marker)
                on_device = device_alias()
                print(f"[{mode} r{rnd}] script={s.get('status')} task={(s.get('task_response') or {}).get('state')} "
                      f"db_status_after_script={mod!r} install={i.get('status')} {lines[-1:]} "
                      f"device_alias={on_device!r} {'REACHED' if on_device == marker else 'MISSED'}",
                      flush=True)
    finally:
        s, mod, i, lines = script_then_install(base, original or "")
        print(f"restore: install={i.get('status')} device_alias={device_alias()!r} (want {original!r})")
        locked(adom, lambda f: f.delete(f"{script_url}/{NAME}"))


if __name__ == "__main__":
    main()
