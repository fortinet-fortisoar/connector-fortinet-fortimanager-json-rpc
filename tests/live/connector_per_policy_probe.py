"""
Per-policy locking through the connector, with per-policy-lock enabled on the appliance.

While a second password session holds a lock on policy A, the connector (minimal locking)
updates:

    OTHER_POLICY  policy B in the same package -> should finish at once and persist
    SAME_POLICY   policy A                     -> should wait, then persist once A is
                                                  released (the holder lets go after
                                                  --hold seconds)

and, with per-policy-lock DISABLED and the holder on the whole package, OTHER_POLICY
again -> the connector takes the package lock, so it waits for the holder (the old
behaviour, and the only safe one with the feature off).

The probe creates two throwaway policies in --package, edits only their comments, deletes
them, and restores per-policy-lock to the value it found.

Usage (workspace mode on):
    python connector_per_policy_probe.py [--adom root] [--package default] [--hold 15]
"""
import argparse
import importlib
import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")
here = os.path.dirname(os.path.abspath(__file__))
tests_directory = os.path.dirname(here)
sys.path[:0] = [here, tests_directory, os.path.dirname(tests_directory)]
import conftest  # noqa: E402,F401

from script_lock_probe import session  # noqa: E402

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations


def ws(adom, verb, package, policy=None):
    url = f"/dvmdb/adom/{adom}/workspace/{verb}/pkg/{package}"
    return url + (f"/firewall/policy/{policy}" if policy is not None else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adom", default="root")
    parser.add_argument("--package", default="default")
    parser.add_argument("--hold", type=int, default=15)
    args = parser.parse_args()
    adom, pkg = args.adom, args.package
    policy_url = f"/pm/config/adom/{adom}/pkg/{pkg}/firewall/policy"
    config = {"address": os.environ["ADDRESS"], "port": os.environ["PORT"], "verify_ssl": False,
              "username": os.environ["USERNAME"], "password": os.environ["PASSWORD"],
              "auth_method": "Username/Password", "verbose_json": True, "minimal_locking": True}

    admin = session()
    original = admin.get("/cli/global/system/global", fields=["per-policy-lock"])[1].get("per-policy-lock")
    ids = []
    try:
        admin.lock_adom(adom)
        for name in ("lockprobe-pp-a", "lockprobe-pp-b"):
            status, r = admin.add(policy_url, data={
                "name": name, "srcintf": ["any"], "dstintf": ["any"], "srcaddr": ["all"],
                "dstaddr": ["all"], "service": ["ALL"], "schedule": ["always"],
                "action": 0, "logtraffic": 0})
            ids.append(r.get("policyid"))
        admin.commit_changes(adom)
        admin.unlock_adom(adom)
        a, b = ids
        print(f"policies A={a} B={b}; per-policy-lock was {original!r}", flush=True)

        def comment(policy):
            return admin.get(f"{policy_url}/{policy}", fields=["comments"])[1].get("comments")

        def arm(label, feature, held_url, target):
            admin.set("/cli/global/system/global", **{"per-policy-lock": feature})
            holder = session()
            try:
                hold_status = holder.execute(held_url)[0]
                release = threading.Timer(args.hold, lambda: holder.execute(held_url.replace("/lock/", "/unlock/")))
                release.start()
                marker = f"{label.lower()}-{int(time.time())}"
                started = time.monotonic()
                r = operations["json_rpc_set"](config, {"url": f"{policy_url}/{target}",
                                                          "data": {"data": {"comments": marker}}})
                took = time.monotonic() - started
                release.join()
                print(f"{label:24} holder={hold_status} status={r.get('status')} took={took:5.1f}s "
                      f"saved={comment(target) == marker}", flush=True)
            finally:
                holder.logout()

        arm("OTHER_POLICY (feature on)", "enable", ws(adom, "lock", pkg, a), b)
        arm("SAME_POLICY (feature on)", "enable", ws(adom, "lock", pkg, a), a)
        arm("OTHER_POLICY (feature off)", "disable", ws(adom, "lock", pkg), b)
    finally:
        admin.set("/cli/global/system/global", **{"per-policy-lock": original})
        admin.lock_adom(adom)
        for policy in ids:
            if policy is not None:
                admin.delete(f"{policy_url}/{policy}")
        admin.commit_changes(adom)
        admin.unlock_adom(adom)
        print("restored per-policy-lock:",
              admin.get("/cli/global/system/global", fields=["per-policy-lock"])[1].get("per-policy-lock"))
        admin.logout()


if __name__ == "__main__":
    main()
