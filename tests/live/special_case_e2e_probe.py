"""End-to-end check of install/preview through the connector operation.

Stages one harmless device-DB change (system global alias), then runs json_rpc_execute
on /securityconsole/install/preview -- ONE call each -- and checks that the staged change
is in the returned preview. The connector runs the preview-flagged install itself, in
the same session, because FMG keeps preview state per session.

    DEVICE      {adom, scope}             -> device install preview, must show the alias
    TRACK       same, with track_task     -> must show the alias
    PACKAGE     {adom, scope, pkg}        -> package install preview, must succeed
    BAD_SCOPE   a device that is not managed -> must fail with a non-zero status

The alias is reverted, the package scope entry removed and the pending install
cancelled at the end. Device-DB writes pass an explicit adom: the URL carries none, and
in workspace mode an unlocked write is refused -10147 "no write permission". Nothing is
installed to the device (flags=["preview"]).

Usage (credentials from the env file, e.g. via envrun):
    python special_case_e2e_probe.py --device <managed-fgt> [--adom root] [--package default]
"""
import argparse
import importlib
import os
import sys

tests_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repo_root = os.path.dirname(tests_directory)
sys.path.insert(0, tests_directory)
sys.path.insert(0, repo_root)

import conftest  # noqa: E402,F401  -- registers the connectors.core stub

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations

MARKER = "preview-probe"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--device", required=True)
    parser.add_argument("--package", default="default")
    args = parser.parse_args()

    config = {
        "address": os.getenv("ADDRESS"), "port": os.getenv("PORT"),
        "verify_ssl": False, "username": os.getenv("USERNAME"),
        "password": os.getenv("PASSWORD"), "auth_method": "Username/Password",
        "verbose_json": True,
    }
    execute, rpc_set, rpc_get = (operations["json_rpc_execute"], operations["json_rpc_set"],
                                 operations["json_rpc_get"])
    global_url = f"/pm/config/device/{args.device}/global/system/global"
    scope = [{"name": args.device, "vdom": "root"}]

    original = rpc_get(config, {"url": global_url, "data": {"fields": ["alias"]}})[
        "get_response"].get("alias", "")
    rpc_set(config, {"url": global_url, "data": {"adom": args.adom, "data": {"alias": MARKER}}})

    arms = [
        ("DEVICE", {"adom": args.adom, "scope": scope}, {}, "diff"),
        ("TRACK", {"adom": args.adom, "scope": scope}, {"track_task": True}, "diff"),
        ("PACKAGE", {"adom": args.adom, "scope": scope, "pkg": args.package}, {}, "ok"),
        ("BAD_SCOPE", {"adom": args.adom, "scope": [{"name": "no-such-fgt", "vdom": "root"}]},
         {}, "fail"),
    ]
    failures = []
    try:
        for name, data, extra, expect in arms:
            scope_url = f"/pm/pkg/adom/{args.adom}/{args.package}/scope member"
            if name == "PACKAGE":
                # A package preview needs the device in the package's install scope.
                operations["json_rpc_add"](config, {"url": scope_url, "data": {"data": scope}})
            try:
                r = execute(config, dict({"url": "/securityconsole/install/preview",
                                          "data": data}, **extra))
            except Exception as error:  # noqa: BLE001
                r = {"status": f"raised {error}"}
            finally:
                if name == "PACKAGE":
                    operations["json_rpc_delete"](config, {"url": scope_url, "data": {"data": scope}})
            text = str(r.get("special_case_response"))
            prepare = r.get("special_case_prepare") or {}
            print(f"[{name}] status={r.get('status')} prepare={prepare.get('url')}:"
                  f"{prepare.get('status')} result_status={r.get('special_case_status')}")
            print(f"[{name}]   {text[:300]}")
            ok = {"diff": r.get("status") == 0 and MARKER in text,
                  "ok": r.get("status") == 0 and "Preview result ===" in text,
                  "fail": r.get("status") != 0}[expect]
            print(f"[{name}]   {'PASS' if ok else 'FAIL'} (expected {expect})")
            if not ok:
                failures.append(name)
    finally:
        rpc_set(config, {"url": global_url, "data": {"adom": args.adom, "data": {"alias": original}}})
        execute(config, {"url": "/securityconsole/package/cancel/install",
                         "data": {"adom": args.adom, "scope": scope}})
        restored = rpc_get(config, {"url": global_url, "data": {"fields": ["alias"]}})[
            "get_response"].get("alias")
        print("alias restored:", restored == original)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
