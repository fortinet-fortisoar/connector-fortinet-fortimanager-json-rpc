"""Does every NO_LOCK_URLS entry still work through the connector while the ADOM is held?

A URL belongs in NO_LOCK_URLS when the appliance answers it without a workspace lock.
The sharpest test is contention: a second session holds the ADOM lock, and each URL is
called through json_rpc_execute with an adom in the payload (the trigger that used to
make the connector lock). An exempt URL answers in seconds; a URL that wrongly took the
lock would sit in the 1-10s retry loop until the holder lets go.

A CONTROL call to a non-exempt execute URL runs under the same hold and must still be
waiting when the window closes -- otherwise the probe cannot tell the two apart.

/um/image/upgrade/ext is listed but never called: it starts a real firmware upgrade.
Its membership rests on the two-arm upgrade measurement in generic_json_rpc.py.

Usage (credentials from the env file, e.g. via envrun):
    python no_lock_urls_contended_probe.py --device <managed-fgt> [--adom root]
"""
import argparse
import importlib
import os
import sys
import threading
import time

tests_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, tests_directory)
sys.path.insert(0, os.path.dirname(tests_directory))
sys.path.insert(0, os.path.join(tests_directory, "live"))

import conftest  # noqa: E402,F401  -- registers the connectors.core stub
from lock_matrix_probe import connect  # noqa: E402

generic = importlib.import_module("fortinet-fortimanager-json-rpc.generic_json_rpc")
operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations

NEVER_CALLED = {"/um/image/upgrade/ext": "starts a real firmware upgrade"}
FAST_SECONDS = 60       # an exempt call, preview task included, finishes well inside this
CONTROL_WINDOW = 20     # how long the control must stay blocked


def payloads(adom, device):
    scope = [{"name": device, "vdom": "root"}]
    return {
        "/securityconsole/install/preview": {"adom": adom, "scope": scope},
        "/sys/proxy/json": {"target": [f"/adom/{adom}/device/{device}"], "action": "get",
                            "resource": "/api/v2/monitor/system/status"},
        "/um/image/list": {"adom": adom},
        "/um/image/list/ext": {"adom": adom},
        "/um/image/version/list": {"adom": adom},
        "/um/image/version/list/ext": {"adom": adom},
        "/um/device/list": {"adom": adom},
        "/um/image/upgrade/status": {"adom": adom},
        "/securityconsole/preview/result": {"adom": adom, "scope": scope},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    config = {"address": os.getenv("ADDRESS"), "port": os.getenv("PORT"), "verify_ssl": False,
              "username": os.getenv("USERNAME"), "password": os.getenv("PASSWORD"),
              "auth_method": "Username/Password", "verbose_json": True}
    calls = payloads(args.adom, args.device)
    unknown = set(generic.NO_LOCK_URLS) - set(calls) - set(NEVER_CALLED)
    if unknown:
        print(f"FAIL: NO_LOCK_URLS entries with no probe payload: {sorted(unknown)}")
        sys.exit(1)

    failures = []
    holder = connect(username=config["username"], password=config["password"])
    holder.login()
    try:
        status, _ = holder.lock_adom(args.adom)
        if status != 0:
            print(f"cannot hold ADOM {args.adom} (status {status}); is workspace mode on?")
            sys.exit(2)
        for url, data in sorted(calls.items()):
            started = time.time()
            response = None
            try:
                response = operations["json_rpc_execute"](config, {"url": url, "data": data})
                status = response.get("status")
            except Exception as error:  # noqa: BLE001
                status = f"raised {error}"
            elapsed = time.time() - started
            if url == "/securityconsole/install/preview":
                # Exempt from the connector's lock, but its preview install cannot run
                # while another session holds the ADOM ("no write permission"). Correct
                # behaviour is to answer fast and fail visibly, not wait or report 0.
                prepare = (response or {}).get("special_case_prepare") or {}
                ok = status not in (0, None) and "no write permission" in str(
                    prepare.get("error")) and elapsed < FAST_SECONDS
            else:
                ok = status == 0 and elapsed < FAST_SECONDS
            print(f"{'PASS' if ok else 'FAIL'} {url}: status={status} {elapsed:.1f}s")
            if not ok:
                failures.append(url)
        for url, why in NEVER_CALLED.items():
            print(f"SKIP {url}: {why}")

        # Control: a real write must wait on the held lock. (/securityconsole/package/
        # status, the obvious read-shaped control, is -6 "Invalid url" on 7.6.8.)
        done = threading.Event()
        control_url = f"/pm/config/adom/{args.adom}/obj/firewall/address"

        def control():
            operations["json_rpc_add"](config, {"url": control_url, "data": {"data": [
                {"name": "no-lock-probe-control", "type": "ipmask",
                 "subnet": ["198.51.100.251", "255.255.255.255"]}]}})
            done.set()

        threading.Thread(target=control, daemon=True).start()
        blocked = not done.wait(CONTROL_WINDOW)
        print(f"{'PASS' if blocked else 'FAIL'} control address add "
              f"{'still waiting' if blocked else 'finished'} after {CONTROL_WINDOW}s under the hold")
        if not blocked:
            failures.append("control")
    finally:
        holder.unlock_adom(args.adom)
        holder.logout()
    if blocked:
        print("control finished after release:", done.wait(120))
    operations["json_rpc_delete"](config, {"url": f"/pm/config/adom/{args.adom}/obj/firewall/"
                                                  "address/no-lock-probe-control", "data": {}})
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
