"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

# One FMG API key is one FMG session (live-verified on 7.6.8): workers sharing a key
# share workspace-lock ownership, so the connector serialises them with a file lock.

import fcntl
import multiprocessing
import os
import sys
import time

import pytest

current_directory = os.path.dirname(__file__)
sys.path.insert(0, current_directory)

from test_unit_locking_orchestration import (  # noqa: E402
    BASE_CONFIG, OBJ_URL, FakeFMG, generic_json_rpc, run_action)

KEY_CONFIG = {"address": "fortimanager.example.com", "auth_method": "API Key",
              "api_key": "<api-key>"}
HOST = "fortimanager.example.com"


@pytest.fixture(autouse=True)
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(generic_json_rpc.API_KEY_LOCK_DIR_ENV, str(tmp_path))
    return tmp_path


def is_locked(path):
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False


class ExitRecordingFMG(FakeFMG):
    """Records whether the key's file lock was still held when the session closed."""

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.locked_at_exit = None
        self.locked_during_call = None

    def add(self, url=None, **kwargs):
        self.locked_during_call = os.path.exists(self.path) and is_locked(self.path)
        return super().add(url=url, **kwargs)

    def __exit__(self, *exc):
        self.locked_at_exit = os.path.exists(self.path) and is_locked(self.path)
        return False


def test_path_is_per_host_key_and_adom_and_hides_the_key():
    p = generic_json_rpc.api_key_lock_path
    assert p(HOST, "k1", "root") == p(HOST, "k1", "root")
    assert len({p(HOST, "k1", "root"), p(HOST, "k2", "root"),
                p(HOST, "k1", "other"), p("other.example.com", "k1", "root")}) == 4
    assert "k1" not in p(HOST, "k1", "root")


def test_api_key_write_holds_file_lock_until_after_session_closes():
    path = generic_json_rpc.api_key_lock_path(HOST, "<api-key>", "root")
    fmg = ExitRecordingFMG(path)
    response = run_action(fmg, "add", {"url": OBJ_URL, "data": {"data": {}}}, KEY_CONFIG)
    assert response["status"] == 0
    assert fmg.locked_during_call is True
    assert fmg.locked_at_exit is True, "pyFMG unlocks on __exit__; file lock must outlive it"
    assert not is_locked(path)


def test_password_auth_takes_no_file_lock(lock_dir):
    fmg = FakeFMG()
    run_action(fmg, "add", {"url": OBJ_URL, "data": {"data": {}}}, BASE_CONFIG)
    assert list(lock_dir.iterdir()) == []


def test_api_key_read_takes_no_file_lock(lock_dir):
    fmg = FakeFMG()
    run_action(fmg, "get", {"url": OBJ_URL, "data": {}}, KEY_CONFIG)
    assert list(lock_dir.iterdir()) == []


def test_no_file_lock_without_workspace_mode(lock_dir):
    fmg = FakeFMG(uses_workspace=False)
    run_action(fmg, "add", {"url": OBJ_URL, "data": {"data": {}}}, KEY_CONFIG)
    assert list(lock_dir.iterdir()) == []


def test_file_lock_released_when_the_call_raises():
    path = generic_json_rpc.api_key_lock_path(HOST, "<api-key>", "root")
    fmg = FakeFMG(action_error=RuntimeError("boom"))
    with pytest.raises(Exception):
        run_action(fmg, "add", {"url": OBJ_URL, "data": {"data": {}}}, KEY_CONFIG)
    assert not is_locked(path)


def _hold(path_dir, ready, seconds):
    os.environ[generic_json_rpc.API_KEY_LOCK_DIR_ENV] = path_dir
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root"):
        ready.set()
        time.sleep(seconds)


def _hold_forever_then_get_killed(path_dir, ready):
    _hold(path_dir, ready, 3600)


def test_second_process_waits_for_the_first(lock_dir):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(lock_dir), ready, 1.5))
    holder.start()
    assert ready.wait(10)
    started = time.monotonic()
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root", timeout=30):
        waited = time.monotonic() - started
    holder.join(10)
    assert waited >= 1.0, f"second worker did not wait ({waited:.2f}s)"


def test_times_out_with_a_clear_error(lock_dir):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(lock_dir), ready, 5))
    holder.start()
    try:
        assert ready.wait(10)
        with pytest.raises(generic_json_rpc.ConnectorError, match="same API key"):
            with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root", timeout=0.5):
                pass
    finally:
        holder.terminate(); holder.join(10)


def test_crashed_holder_never_leaves_the_file_locked(lock_dir):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold_forever_then_get_killed, args=(str(lock_dir), ready))
    holder.start()
    assert ready.wait(10)
    holder.kill(); holder.join(10)
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root", timeout=2):
        pass


def test_different_adoms_do_not_wait_on_each_other(lock_dir):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(lock_dir), ready, 5))
    holder.start()
    try:
        assert ready.wait(10)
        with generic_json_rpc.api_key_workspace_lock(HOST, "k", "other", timeout=0.5):
            pass
    finally:
        holder.terminate(); holder.join(10)


# ---------------------------------------------------------------------------
# Cluster-wide path: Postgres advisory lock in FortiSOAR's own database
# ---------------------------------------------------------------------------

class FakePgConnection:
    """Mimics django.db.connection against Postgres advisory locks (one shared table)."""

    vendor = "postgresql"
    held = {}            # lock_id -> owner, shared like the primary's pg_locks

    def __init__(self, name, busy_polls=0):
        self.name, self.busy_polls, self.statements = name, busy_polls, []

    def ensure_connection(self):
        pass

    def cursor(self):
        conn = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args):
                conn.statements.append(sql.split("(")[0].split()[-1])
                lock_id = args[0]
                if "pg_try_advisory_lock" in sql:
                    if conn.busy_polls:
                        conn.busy_polls -= 1
                        self.result = False
                    elif FakePgConnection.held.get(lock_id, conn.name) == conn.name:
                        FakePgConnection.held[lock_id] = conn.name
                        self.result = True
                    else:
                        self.result = False
                else:
                    self.result = FakePgConnection.held.pop(lock_id, None) == conn.name

            def fetchone(self):
                return (self.result,)

        return Cursor()


@pytest.fixture
def pg(monkeypatch):
    FakePgConnection.held = {}
    conn = FakePgConnection("node-a")
    monkeypatch.setattr(generic_json_rpc, "_fortisoar_db_connection", lambda: conn)
    monkeypatch.setattr(generic_json_rpc.time, "sleep", lambda s: None)
    return conn


def test_lock_id_is_stable_signed_64_bit_and_per_scope():
    i = generic_json_rpc.api_key_lock_id
    assert i(HOST, "k", "root") == i(HOST, "k", "root")
    assert -2 ** 63 <= i(HOST, "k", "root") < 2 ** 63
    assert len({i(HOST, "k", "root"), i(HOST, "k2", "root"), i(HOST, "k", "other")}) == 3


def test_uses_advisory_lock_not_a_file_inside_fortisoar(pg, lock_dir):
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root"):
        assert FakePgConnection.held == {generic_json_rpc.api_key_lock_id(HOST, "k", "root"): "node-a"}
    assert FakePgConnection.held == {}
    assert pg.statements == ["pg_try_advisory_lock", "pg_advisory_unlock"]
    assert list(lock_dir.iterdir()) == []


def test_waits_while_another_node_holds_the_key(pg):
    pg.busy_polls = 3
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root"):
        pass
    assert pg.statements.count("pg_try_advisory_lock") == 4


def test_advisory_wait_times_out_clearly(pg):
    FakePgConnection.held[generic_json_rpc.api_key_lock_id(HOST, "k", "root")] = "node-b"
    with pytest.raises(generic_json_rpc.ConnectorError, match="same API key"):
        with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root", timeout=0):
            pass


def test_advisory_lock_released_when_the_body_raises(pg):
    with pytest.raises(RuntimeError):
        with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root"):
            raise RuntimeError("boom")
    assert FakePgConnection.held == {}


def test_falls_back_to_file_lock_without_django(lock_dir):
    # The unit-test venv has no Django -- exactly a remote agent's situation.
    assert generic_json_rpc._fortisoar_db_connection() is None
    with generic_json_rpc.api_key_workspace_lock(HOST, "k", "root"):
        assert len(list(lock_dir.iterdir())) == 1


def test_api_key_write_goes_through_the_advisory_lock(pg):
    fmg = FakeFMG()
    run_action(fmg, "add", {"url": OBJ_URL, "data": {"data": {}}}, KEY_CONFIG)
    assert pg.statements == ["pg_try_advisory_lock", "pg_advisory_unlock"]
