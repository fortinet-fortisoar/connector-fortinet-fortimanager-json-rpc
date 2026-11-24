"""Which payload does /securityconsole/preview/result actually accept?

The connector follows /securityconsole/install/preview with a preview/result call.
It used to forward the preview's own payload (adom, scope, flags...) verbatim. This
probe runs one tracked preview, then asks for its result with three payload shapes:

    FORWARDED   the preview payload unchanged (the old connector behaviour)
    DEVICE      {adom, device} -- the documented shape
    ADOM_ONLY   {adom}

and prints the status and the size of the returned diff for each.

Usage:
    python preview_result_probe.py [--adom root] [--device <fgt>]
"""
import argparse
import json
import os
import sys

current_directory = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_directory)

from lock_matrix_probe import connect  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--device", default=os.getenv("LIVE_FGT_DEVICE_NAME", ""))
    parser.add_argument("--package", default=os.getenv("FGT_ASSIGNED_POL_PKG", "default"))
    args = parser.parse_args()

    preview = {"adom": args.adom, "scope": [{"name": args.device, "vdom": "root"}]}
    arms = {
        "FORWARDED": dict(preview),
        "DEVICE": {"adom": args.adom, "device": args.device},
        "ADOM_ONLY": {"adom": args.adom},
    }

    # Credentials explicitly: connect() prefers API_KEY, which lock_matrix_probe loads from
    # tests/.env even when another env file targets a different appliance.
    with connect(username=os.getenv("USERNAME"), password=os.getenv("PASSWORD")) as fmg:
        for name, payload in arms.items():
            status, resp = fmg.execute(url="/securityconsole/install/preview", **preview)
            task = resp.get("task") if isinstance(resp, dict) else None
            print(f"[{name}] preview status={status} task={task}")
            if task:
                t_status, t_resp = fmg.track_task(task, timeout=180)
                state = t_resp.get("state") if isinstance(t_resp, dict) else t_resp
                print(f"[{name}] task status={t_status} state={state}")
            r_status, r_resp = fmg.execute(url="/securityconsole/preview/result", **payload)
            body = json.dumps(r_resp, default=str)
            print(f"[{name}] result status={r_status} bytes={len(body)} head={body[:300]}")


if __name__ == "__main__":
    main()
