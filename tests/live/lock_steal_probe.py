"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

"""
Can a lock be taken away from the connector mid-flight, and does it notice?

The worry: the connector acquires a scope, an administrator intervenes, and the
connector carries on writing into a workspace it no longer owns -- reporting success for
changes that never landed. Silent data loss is the bad outcome; a loud failure is fine.

Two arms, because "stolen" turns out to mean two different things:

    API_STEAL      a second session, Super_User, tries to unlock the holder's scope --
                   with and without a force flag
    SESSION_KILL   the holder's admin session is killed outright (the only mechanism
                   that was ever observed to clear an abandoned lock, section I.3)

Each arm writes a marker *before* the steal attempt and another *after*, then re-reads
the device from a third session. That is what separates "the connector was stopped" from
"the connector kept going and the write vanished": the before-marker proves the arm was
set up correctly, and which marker survives says what the steal actually did.

The session kill needs CLI access; pass --ssh-password to enable that arm, otherwise
only API_STEAL runs.

Usage
-----
    python lock_steal_probe.py --adom <scratch-adom> --device <model-device> \
        --address <fmg> --username <user> --password <pw> --ssh-password <pw>
"""

import argparse
import os
import contextlib
import shutil
import tempfile
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")

current_directory = os.path.dirname(os.path.abspath(__file__))
tests_directory = os.path.abspath(os.path.join(current_directory, os.pardir))
repo_root = os.path.abspath(os.path.join(tests_directory, os.pardir))
sys.path.insert(0, current_directory)
sys.path.insert(0, repo_root)

from lock_matrix_probe import connect  # noqa: E402

API_STEAL = "API_STEAL"
SESSION_KILL = "SESSION_KILL"

NO_PERMISSION = -11


def lock_url(adom, device, verb):
    return f"/dvmdb/adom/{adom}/workspace/{verb}/dev/{device}"


def held_by(fmg, adom, device):
    """The lock_sid currently holding the scope, or None when it is free."""
    status, info = fmg.get(url=lock_url(adom, device, "lockinfo"))
    if isinstance(info, list) and info:
        return info[0].get("lock_sid")
    return None


def write_marker(fmg, adom, device, marker):
    return fmg.set(url=f"/dvmdb/adom/{adom}/device/{device}", data={"desc": marker})[0]


def read_marker(fmg, adom, device):
    status, response = fmg.get(url=f"/dvmdb/adom/{adom}/device/{device}")
    return response.get("desc") if isinstance(response, dict) else None


@contextlib.contextmanager
def askpass_env(password: str):
    """Env for plain ssh that takes `password` from an SSH_ASKPASS helper (no external binary).

    The helper prints $SSH_PW, so the password only lives in the child's env and
    never in argv. The 0700 temp dir holding the helper is removed on exit.
    """
    tmp = tempfile.mkdtemp(prefix="askpass-")
    try:
        helper = os.path.join(tmp, "askpass")
        fd = os.open(helper, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%s\\n' \"$SSH_PW\"\n")
        yield {**os.environ, "SSH_ASKPASS": helper, "SSH_ASKPASS_REQUIRE": "force",
               "DISPLAY": os.environ.get("DISPLAY") or ":0", "SSH_PW": password}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ssh_command(address, password, command):
    with askpass_env(password) as env:
        result = subprocess.run(
            ["ssh",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no",
             "-o", "IdentitiesOnly=yes", f"admin@{address}", command],
            capture_output=True, text=True, timeout=60, env=env)
    return result.stdout


def run_api_steal(connect_args, adom, device):
    """A second Super_User session tries to release the holder's lock."""
    holder = connect(*connect_args)
    holder.login()
    thief = connect(*connect_args)
    thief.login()
    findings = {}
    try:
        findings["locked"] = holder.execute(url=lock_url(adom, device, "lock"))[0]
        findings["sid_before"] = held_by(holder, adom, device)
        findings["before_write"] = write_marker(holder, adom, device, "steal-probe-before")

        findings["plain_unlock_status"] = thief.execute(url=lock_url(adom, device, "unlock"))[0]
        findings["sid_after_plain"] = held_by(holder, adom, device)
        findings["force_unlock_status"] = thief.execute(
            url=lock_url(adom, device, "unlock"), data={"force": 1})[0]
        findings["sid_after_force"] = held_by(holder, adom, device)

        findings["after_write"] = write_marker(holder, adom, device, "steal-probe-after")
    finally:
        holder.execute(url=lock_url(adom, device, "unlock"))
        for session in (holder, thief):
            try:
                session.logout()
            except Exception:             # noqa: BLE001 - cleanup must not mask results
                pass
    return findings


def run_session_kill(connect_args, adom, device, address, ssh_password):
    """The holder's admin session is killed while it holds the lock."""
    holder = connect(*connect_args)
    holder.login()
    findings = {}
    try:
        findings["locked"] = holder.execute(url=lock_url(adom, device, "lock"))[0]
        sid = held_by(holder, adom, device)
        findings["sid_before"] = sid
        findings["before_write"] = write_marker(holder, adom, device, "kill-probe-before")

        ssh_command(address, ssh_password, f"diagnose system admin-session kill {sid}")

        # The victim keeps using its handle exactly as the connector would.
        try:
            findings["after_write"] = write_marker(holder, adom, device, "kill-probe-after")
        except Exception as failure:      # noqa: BLE001 - the failure IS the measurement
            findings["after_write"] = f"raised {type(failure).__name__}"
    finally:
        try:
            holder.execute(url=lock_url(adom, device, "unlock"))
            holder.logout()
        except Exception:                 # noqa: BLE001 - the session is expected to be dead
            pass

    verifier = connect(*connect_args)
    verifier.login()
    try:
        findings["sid_after"] = held_by(verifier, adom, device)
        findings["surviving_marker"] = read_marker(verifier, adom, device)
    finally:
        verifier.logout()
    return findings


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adom", required=True)
    parser.add_argument("--device", required=True, help="a model device in that ADOM")
    parser.add_argument("--address", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--ssh-password", default="",
                        help="enables the SESSION_KILL arm; needs ssh on PATH (password fed via SSH_ASKPASS)")
    args = parser.parse_args()

    connect_args = (args.address, args.username, args.password, args.api_key)

    print(f"-> {API_STEAL}")
    findings = run_api_steal(connect_args, args.adom, args.device)
    for key, value in findings.items():
        print(f"   {key:22} {value}")
    stolen = findings["sid_after_force"] != findings["sid_before"]
    print(f"   VERDICT                {'lock was taken away' if stolen else 'lock survived both unlock attempts'}")
    if findings["plain_unlock_status"] == 0 and not stolen:
        print("   NOTE                   the thief's unlock reported status 0 and did nothing")
    print()

    if not args.ssh_password:
        print(f"{SESSION_KILL} skipped (no --ssh-password).")
        return 0

    print(f"-> {SESSION_KILL}")
    findings = run_session_kill(connect_args, args.adom, args.device,
                                args.address or os.getenv("ADDRESS", ""), args.ssh_password)
    for key, value in findings.items():
        print(f"   {key:22} {value}")
    silent = findings["after_write"] == 0
    print(f"   VERDICT                "
          f"{'SILENT -- write reported success' if silent else 'victim was refused, not ignored'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
