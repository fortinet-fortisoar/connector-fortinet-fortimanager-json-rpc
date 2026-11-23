"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

# The connector modules import `connectors.core.connector`, which only exists
# inside a FortiSOAR appliance. Register a minimal stub so the unit tests can be
# collected and run in a plain virtualenv (CI, laptop) with no FortiSOAR install.

import logging
import sys
import types

if "connectors" not in sys.modules:
    connectors = types.ModuleType("connectors")
    core = types.ModuleType("connectors.core")
    connector = types.ModuleType("connectors.core.connector")

    class ConnectorError(Exception):
        pass

    def get_logger(name):
        return logging.getLogger(name)

    class Connector:
        def execute(self, config, operation, params, **kwargs):
            raise NotImplementedError

    connector.ConnectorError = ConnectorError
    connector.get_logger = get_logger
    connector.Connector = Connector

    core.connector = connector
    connectors.core = core

    sys.modules["connectors"] = connectors
    sys.modules["connectors.core"] = core
    sys.modules["connectors.core.connector"] = connector


# ---------------------------------------------------------------------------
# Live progress: one line per test start/finish, plus a heartbeat while a test runs.
# ---------------------------------------------------------------------------
# Output goes to PYTEST_PROGRESS_FILE (or stderr), flushed as it happens, so a long live
# run can be followed with `tail -f` and a stuck test is obvious within a minute instead
# of after the run. PYTEST_HEARTBEAT sets the heartbeat interval in seconds (default 60).
import os
import threading as _threading
import time as _time

_progress = {"test": None, "started": None, "run_started": _time.monotonic()}


def _progress_write(line):
    stamp = _time.strftime("%H:%M:%S")
    text = f"[{stamp} +{_time.monotonic() - _progress['run_started']:.0f}s] {line}\n"
    path = os.getenv("PYTEST_PROGRESS_FILE")
    if path:
        with open(path, "a") as handle:
            handle.write(text)
    else:
        sys.__stderr__.write(text)
        sys.__stderr__.flush()


def _heartbeat():
    interval = float(os.getenv("PYTEST_HEARTBEAT", "60"))
    while True:
        _time.sleep(interval)
        test, started = _progress["test"], _progress["started"]
        if test and started:
            _progress_write(f"... still running {test} ({_time.monotonic() - started:.0f}s)")


def pytest_sessionstart(session):
    _threading.Thread(target=_heartbeat, daemon=True).start()


def _is_live(nodeid):
    # Unit tests run in milliseconds; only live suites get progress lines.
    return not nodeid.startswith("unit/")


def pytest_runtest_logstart(nodeid, location):
    if not _is_live(nodeid):
        return
    _progress["test"], _progress["started"] = nodeid, _time.monotonic()
    _progress_write(f"START {nodeid}")


def pytest_runtest_logreport(report):
    if not _is_live(report.nodeid):
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        took = _time.monotonic() - (_progress["started"] or _time.monotonic())
        _progress_write(f"{report.outcome.upper():7} {report.nodeid} ({took:.1f}s)")


def pytest_runtest_logfinish(nodeid, location):
    _progress["test"] = None
