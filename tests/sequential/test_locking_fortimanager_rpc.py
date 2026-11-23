"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

"""
Sequential locking tests against a live FortiManager.

These tests verify the workspace locking behavior across several scenarios:
  - ADOM and pkg/dev scope locks are released after each operation
  - URLs in NO_LOCK_URLS skip workspace lock acquisition entirely
  - The retry loop resolves contention when a lock is held by another session
  - Concurrent writes to the same ADOM both succeed via retry logic
  - Concurrent writes to different packages with minimal_locking=True complete
    without contention

Requirements:
  - A live FortiManager reachable via the .env credentials, in workspace mode
  - The "default" policy package must exist in the "root" ADOM
  - A managed device named via MANAGED_DEVICE_NAME must exist if device-scope
    tests are run (these skip automatically if the env var is not set)
  - A second package: SECOND_PKG_NAME, or the suite creates "lock-test-pkg2"
    through the connector and deletes it afterwards

Every URL written here is a real object path, verified on a live 7.6.8 appliance:
policies under /pm/config/adom/<adom>/pkg/<pkg>/firewall/policy, and device-DB objects
under /pm/config/device/<dev>/vdom/<vdom>/... (that URL carries no ADOM, so the payload
names it -- unlocked, workspace mode refuses the write -10147). Address objects are not
package objects: /pm/config/adom/<adom>/pkg/<pkg>/firewall/address answers -3.

Tests that depend on workspace mode being enabled will skip automatically
when workspace is disabled.
"""

import importlib
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

current_directory = os.path.dirname(__file__)
parent_directory = os.path.abspath(os.path.join(current_directory, os.pardir))
grandparent_directory = os.path.abspath(os.path.join(parent_directory, os.pardir))
sys.path.insert(0, str(grandparent_directory))

env_path = os.path.join(parent_directory, ".env")
load_dotenv(dotenv_path=env_path)

operations_module = importlib.import_module("fortinet-fortimanager-json-rpc.operations")
generic_module = importlib.import_module("fortinet-fortimanager-json-rpc.generic_json_rpc")
operations = operations_module.operations
ConnectorError = operations_module.ConnectorError
get_config = generic_module.get_config
NO_LOCK_URLS = generic_module.NO_LOCK_URLS

# Optional env var — device-scope tests skip when this is absent
MANAGED_DEVICE_NAME = os.getenv("MANAGED_DEVICE_NAME", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _log_level(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture(params=["Username/Password", "API Key"])
def auth_config(request):
    base = {
        "address": os.getenv("ADDRESS"),
        "verify_ssl": os.getenv("VERIFY_SSL", "False").lower() in ("true", "1", "t"),
        "port": os.getenv("PORT"),
        "debug_connection": False,
        "verbose_json": True,
    }
    if request.param == "Username/Password":
        base.update({
            "username": os.getenv("USERNAME"),
            "password": os.getenv("PASSWORD"),
            "auth_method": "Username/Password",
        })
    else:
        if not os.getenv("API_KEY"):
            pytest.skip("API_KEY not set")
        base.update({
            "api_key": os.getenv("API_KEY"),
            "auth_method": "API Key",
        })
    return base


@pytest.fixture
def minimal_lock_config(auth_config):
    """auth_config with minimal_locking=True."""
    config = auth_config.copy()
    config["minimal_locking"] = True
    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_lockinfo(auth_config, adom="root"):
    """Return the raw lockinfo data list for an ADOM, or None if workspace is off."""
    params = {"url": f"/dvmdb/adom/{adom}/workspace/lockinfo"}
    response = operations["json_rpc_get"](auth_config, params)
    data = response.get("get_response")
    if isinstance(data, dict) and data.get("status", {}).get("code") in (-9, -6):
        return None  # workspace not enabled or invalid ADOM
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []


def _workspace_enabled(auth_config, adom="root"):
    """Return True when workspace mode is active for the ADOM."""
    return _get_lockinfo(auth_config, adom) is not None


def _make_address(name, octet=200):
    return {"name": name, "subnet": [f"172.23.{octet}.1", "255.255.255.255"], "type": "ipmask"}


def _add_address(auth_config, name, url="/pm/config/adom/root/obj/firewall/address/", octet=200):
    return operations["json_rpc_add"](auth_config, {"url": url, "data": [_make_address(name, octet)]})


def _delete_address(auth_config, name, base="/pm/config/adom/root/obj/firewall/address"):
    try:
        operations["json_rpc_delete"](auth_config, {"url": f"{base}/{name}", "data": {}})
    except Exception:
        pass


def _make_policy(name):
    # A deny policy cannot keep the default logtraffic "utm" (-9998), so disable it.
    return {"name": name, "srcintf": ["any"], "dstintf": ["any"], "srcaddr": ["all"],
            "dstaddr": ["all"], "service": ["ALL"], "schedule": ["always"],
            "action": 0, "logtraffic": 0}


def _add_policy(config, name, pkg="default"):
    """Add a policy to a package. Returns (response, policyid or None)."""
    response = operations["json_rpc_add"](config, {
        "url": f"/pm/config/adom/root/pkg/{pkg}/firewall/policy",
        "data": {"data": [_make_policy(name)]}})
    add_response = response.get("add_response")
    policy_id = add_response.get("policyid") if isinstance(add_response, dict) else None
    return response, policy_id


def _delete_policy(config, policy_id, pkg="default"):
    if policy_id is None:
        return
    try:
        operations["json_rpc_delete"](config, {
            "url": f"/pm/config/adom/root/pkg/{pkg}/firewall/policy/{policy_id}", "data": {}})
    except Exception:
        pass


def _device_address_url(device):
    return f"/pm/config/device/{device}/vdom/root/firewall/address"


def _add_device_address(config, device, name, octet=230):
    return operations["json_rpc_add"](config, {
        "url": _device_address_url(device),
        "data": {"adom": "root", "data": [_make_address(name, octet)]}})


def _delete_device_address(config, device, name):
    try:
        operations["json_rpc_delete"](config, {
            "url": f"{_device_address_url(device)}/{name}", "data": {"adom": "root"}})
    except Exception:
        pass


@pytest.fixture(scope="module")
def second_package():
    """SECOND_PKG_NAME, or a package created (and removed) through the connector.

    Creating it is itself a regression check: /pm/pkg/adom/root used to resolve no
    ADOM (the parser wanted a trailing "/"), so the create went out unlocked and was
    refused -10147 in workspace mode.
    """
    existing = os.getenv("SECOND_PKG_NAME", "")
    if existing:
        yield existing
        return
    config = {"address": os.getenv("ADDRESS"), "port": os.getenv("PORT"),
              "verify_ssl": os.getenv("VERIFY_SSL", "False").lower() in ("true", "1", "t"),
              "username": os.getenv("USERNAME"), "password": os.getenv("PASSWORD"),
              "auth_method": "Username/Password", "verbose_json": True}
    name = "lock-test-pkg2"
    response = operations["json_rpc_add"](config, {
        "url": "/pm/pkg/adom/root", "data": {"data": [{"name": name, "type": "pkg"}]}})
    status = response.get("add_response", {}).get("status", {}).get("code")
    # -2 = object already exists (left by an interrupted run); usable all the same.
    assert response.get("status") == 0 or status == -2, f"Could not create {name}: {response}"
    yield name
    operations["json_rpc_delete"](config, {"url": f"/pm/pkg/adom/root/{name}", "data": {}})


def _open_fmg(auth_config):
    """Return an open pyFMG FortiManager context (caller must close it)."""
    from pyFMG.fortimgr import FortiManager as FMGDirect
    server_host, username, password, api_key, verify_ssl = get_config(auth_config)
    fmg = FMGDirect(server_host, username, password, apikey=api_key,
                    verify_ssl=verify_ssl, disable_request_warnings=True)
    fmg.login()
    return fmg



def _open_other_session():
    """A pyFMG session that is genuinely another FMG session: always a password login.

    Every request made with one API key shares a single FMG session (one lock_sid), so
    a holder opened with the same key as the connector is not "another session" -- the
    connector would write straight through its lock. Contention tests use this instead.
    """
    from pyFMG.fortimgr import FortiManager as FMGDirect
    server_host = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}"
    for prefix in ("https://", "http://"):
        server_host = server_host.replace(prefix, "")
    fmg = FMGDirect(server_host, os.getenv("USERNAME"), os.getenv("PASSWORD"),
                    verify_ssl=False, disable_request_warnings=True)
    fmg.login()
    return fmg


class TestSharedApiKeyIsOneSession:
    """Appliance behaviour the connector must design around (live-verified on 7.6.8).

    Two clients using the same API key are the same FMG session: the second lock call
    succeeds instead of -20055, and either one's unlock drops the lock. If this test
    starts failing, FMG began isolating API-key callers and the caveat can go.
    """

    def test_same_key_second_lock_is_not_refused(self, auth_config):
        if auth_config["auth_method"] != "API Key":
            pytest.skip("API-key behaviour only")
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")
        a, b = _open_fmg(auth_config), _open_fmg(auth_config)
        try:
            assert a.lock_adom("root")[0] == 0
            assert b.lock_adom("root")[0] == 0, "FMG now refuses a second same-key lock"
            assert b.unlock_adom("root")[0] == 0
            _, info = a.get("/dvmdb/adom/root/workspace/lockinfo")
            assert not (info if isinstance(info, list) else []), "B's unlock left A's lock"
        finally:
            a.unlock_adom("root")

# ---------------------------------------------------------------------------
# 1. Lock released after ADOM-level write
# ---------------------------------------------------------------------------

class TestAdomLockRelease:
    """Verifies that workspace locks are released once an operation completes."""

    ADDR_NAME = "test-lock-release-adom"

    def test_adom_lockinfo_clean_after_write(self, auth_config):
        """After a write op the ADOM should not remain locked."""
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")

        try:
            resp = _add_address(auth_config, self.ADDR_NAME)
            assert resp.get("status") == 0, f"Add failed: {resp}"

            lock_data = _get_lockinfo(auth_config)
            assert lock_data is not None
            # No entries means no active lock
            assert len(lock_data) == 0, (
                f"Expected empty lockinfo after write but got: {lock_data}"
            )
        finally:
            _delete_address(auth_config, self.ADDR_NAME)

    def test_dirty_flag_cleared_after_write(self, auth_config):
        """After a committed write the dirty flag must be 0."""
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")

        try:
            resp = _add_address(auth_config, self.ADDR_NAME + "-dirty")
            assert resp.get("status") == 0

            params = {"url": "/dvmdb/adom/root/workspace/dirty"}
            dirty_resp = operations["json_rpc_get"](auth_config, params)
            dirty_value = dirty_resp.get("get_response", {}).get("dirty", -1)
            assert dirty_value == 0, (
                f"Expected dirty=0 after committed write but got dirty={dirty_value}"
            )
        finally:
            _delete_address(auth_config, self.ADDR_NAME + "-dirty")


# ---------------------------------------------------------------------------
# 2. Minimal lock released after pkg-scoped write
# ---------------------------------------------------------------------------

class TestMinimalLockRelease:
    """Verifies that minimal (pkg/dev) scope locks are released after each op."""

    def test_pkg_lockinfo_clean_after_minimal_write(self, minimal_lock_config):
        """After a pkg-scoped minimal-lock write, lockinfo should show no lock."""
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        policy_id = None
        try:
            resp, policy_id = _add_policy(minimal_lock_config, "test-lock-release-pkg")
            assert resp.get("status") == 0, f"Add failed: {resp}"

            lock_data = _get_lockinfo(minimal_lock_config)
            assert lock_data is not None
            assert len(lock_data) == 0, (
                f"Expected empty lockinfo after minimal-lock pkg write but got: {lock_data}"
            )
        finally:
            _delete_policy(minimal_lock_config, policy_id)

    def test_obj_url_falls_back_to_adom_lock(self, minimal_lock_config):
        """
        With minimal_locking=True, a URL targeting the ADOM object database
        (/pm/config/adom/{adom}/obj/...) has no package component and must fall
        back to ADOM-level locking. Verify the write succeeds and the lock is clean.
        """
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        name = "test-lock-minimal-obj-fallback"
        try:
            resp = _add_address(minimal_lock_config, name)
            assert resp.get("status") == 0, f"Fallback write failed: {resp}"

            lock_data = _get_lockinfo(minimal_lock_config)
            assert len(lock_data) == 0, (
                f"ADOM lock not released after minimal-lock obj-db write: {lock_data}"
            )
        finally:
            _delete_address(minimal_lock_config, name)

    @pytest.mark.skipif(not MANAGED_DEVICE_NAME, reason="MANAGED_DEVICE_NAME env var not set")
    def test_dev_lockinfo_clean_after_minimal_dev_write(self, minimal_lock_config):
        """After a device-scoped minimal-lock write, lockinfo shows no lock."""
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        name = "test-lock-release-dev"
        try:
            resp = _add_device_address(minimal_lock_config, MANAGED_DEVICE_NAME, name)
            assert resp.get("status") == 0, f"Device-scope write failed: {resp}"

            lock_data = _get_lockinfo(minimal_lock_config)
            assert len(lock_data) == 0, (
                f"Device lock not released after minimal-lock write: {lock_data}"
            )
        finally:
            _delete_device_address(minimal_lock_config, MANAGED_DEVICE_NAME, name)


# ---------------------------------------------------------------------------
# 3. NO_LOCK_URLS bypass workspace lock
# ---------------------------------------------------------------------------

class TestNoLockUrlsBypass:
    """
    Every URL in NO_LOCK_URLS is called through the connector while a second session
    holds the root ADOM lock, with an adom in the payload -- the condition under which
    the connector used to lock. An exempt URL answers in seconds; one that took the lock
    would sit in the retry loop until the holder lets go. A real write runs under the
    same hold as a control and must still be waiting, so the test can tell the two apart.
    """

    # Never called: it starts a real firmware upgrade. Its membership rests on the
    # two-arm upgrade measurement recorded beside NO_LOCK_URLS.
    NEVER_CALLED = {"/um/image/upgrade/ext"}
    FAST_SECONDS = 60
    CONTROL_WINDOW = 20

    @staticmethod
    def _payload(url):
        device = MANAGED_DEVICE_NAME
        scope = [{"name": device, "vdom": "root"}]
        return {
            "/securityconsole/install/preview": {"adom": "root", "scope": scope},
            "/securityconsole/preview/result": {"adom": "root", "scope": scope},
            "/sys/proxy/json": {"target": [f"/adom/root/device/{device}"], "action": "get",
                                "resource": "/api/v2/monitor/system/status"},
        }.get(url, {"adom": "root"})

    @pytest.fixture
    def adom_held(self, auth_config):
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")
        holder = _open_other_session()
        status, _ = holder.lock_adom("root")
        if status != 0:
            holder.logout()
            pytest.skip(f"Could not pre-acquire ADOM lock (status={status})")
        yield holder
        holder.unlock_adom("root")
        holder.logout()

    @pytest.mark.skipif(not MANAGED_DEVICE_NAME, reason="MANAGED_DEVICE_NAME env var not set")
    @pytest.mark.parametrize("url", sorted(NO_LOCK_URLS))
    def test_no_lock_url_answers_while_adom_locked(self, auth_config, adom_held, url):
        if url in self.NEVER_CALLED:
            pytest.skip(f"{url} is never called live: it starts a real upgrade")
        start = time.time()
        response = operations["json_rpc_execute"](auth_config, {"url": url, "data": self._payload(url)})
        elapsed = time.time() - start
        assert elapsed < self.FAST_SECONDS, f"{url} took {elapsed:.1f}s -- it waited on the lock"
        if url == "/securityconsole/install/preview":
            # Exempt from the connector's lock, but the preview install it runs cannot
            # while another session holds the ADOM. It must fail fast and visibly.
            prepare = response.get("special_case_prepare") or {}
            assert response.get("status") != 0, response
            assert "no write permission" in str(prepare.get("error")), prepare
        else:
            assert response.get("status") == 0, f"{url}: {response}"

    def test_control_write_waits_while_adom_locked(self, auth_config, adom_held):
        name = "test-no-lock-control"
        done = threading.Event()

        def write():
            _add_address(auth_config, name, octet=240)
            done.set()

        threading.Thread(target=write, daemon=True).start()
        try:
            assert not done.wait(self.CONTROL_WINDOW), (
                "a real write finished while another session held the ADOM -- the "
                "no-lock test above cannot tell exempt URLs from locked ones")
        finally:
            adom_held.unlock_adom("root")
            assert done.wait(120), "control write never finished after the lock was released"
            _delete_address(auth_config, name)

    def test_every_no_lock_url_has_a_live_case(self):
        """A new NO_LOCK_URLS entry must come with a payload above, or be named as never called."""
        generic = {"/securityconsole/install/preview", "/securityconsole/preview/result",
                   "/sys/proxy/json"}
        adom_only = {url for url in NO_LOCK_URLS if url.startswith("/um/")}
        assert set(NO_LOCK_URLS) <= generic | adom_only | self.NEVER_CALLED


# ---------------------------------------------------------------------------
# 4. Lock contention — retry resolves correctly
# ---------------------------------------------------------------------------

class TestLockContention:
    """
    Verifies that the retry loop in lock_adom and lock_minimal_scope resolves
    correctly when a competing session releases the lock after a short delay.
    """

    ADDR_NAME = "test-lock-contention-adom"
    HOLD_SECONDS = 3  # how long the competing session holds the lock

    def test_write_retries_and_succeeds_after_external_lock_released(self, auth_config):
        """
        A competing session holds the ADOM lock for HOLD_SECONDS, then releases it.
        The write operation should retry and succeed once the lock becomes available.
        The total elapsed time must be between HOLD_SECONDS and a generous upper bound.
        """
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")

        # Acquire the ADOM lock from a competing session
        pre_lock_fmg = _open_other_session()
        lock_status, _ = pre_lock_fmg.lock_adom("root")
        if lock_status == -9:
            pre_lock_fmg.logout()
            pytest.skip("Workspace mode not enabled (lock returned -9)")
        if lock_status != 0:
            pre_lock_fmg.logout()
            pytest.skip(f"Could not pre-acquire ADOM lock (status={lock_status})")

        result_holder = {}
        errors = []

        def _do_write():
            try:
                resp = _add_address(auth_config, self.ADDR_NAME)
                result_holder["response"] = resp
            except Exception as exc:
                errors.append(exc)

        # Submit the write in a background thread; it will block on lock acquisition
        start = time.time()
        write_thread = ThreadPoolExecutor(max_workers=1).submit(_do_write)

        # Hold the lock for HOLD_SECONDS, then release
        time.sleep(self.HOLD_SECONDS)
        pre_lock_fmg.unlock_adom("root")
        pre_lock_fmg.logout()

        # Give the write thread enough time to retry and complete
        max_wait = self.HOLD_SECONDS + 30
        write_thread.result(timeout=max_wait)
        elapsed = time.time() - start

        if errors:
            raise errors[0]

        resp = result_holder.get("response", {})
        assert resp.get("status") == 0, f"Write after lock release failed: {resp}"
        assert elapsed >= self.HOLD_SECONDS, (
            f"Write completed in {elapsed:.1f}s — faster than the lock hold time "
            f"({self.HOLD_SECONDS}s), suggesting the lock was not actually contested."
        )
        _delete_address(auth_config, self.ADDR_NAME)

    def test_pkg_write_retries_and_succeeds_after_external_pkg_lock_released(self, minimal_lock_config):
        """
        Same as the ADOM contention test but for a pkg-scoped minimal lock.
        A competing session holds the pkg lock, then releases it after HOLD_SECONDS.
        """
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        pkg = "default"
        pre_lock_fmg = _open_other_session()
        lock_status, _ = pre_lock_fmg.execute(
            url=f"/dvmdb/adom/root/workspace/lock/pkg/{pkg}"
        )
        if lock_status == -9:
            pre_lock_fmg.logout()
            pytest.skip("Workspace mode not enabled")
        if lock_status == -6:
            pre_lock_fmg.logout()
            pytest.skip(f"Policy package '{pkg}' not found")
        if lock_status != 0:
            pre_lock_fmg.logout()
            pytest.skip(f"Could not pre-acquire pkg lock (status={lock_status})")

        name = "test-lock-contention-pkg"
        result_holder = {}
        errors = []

        def _do_write():
            try:
                resp, policy_id = _add_policy(minimal_lock_config, name, pkg=pkg)
                result_holder["response"] = resp
                result_holder["policy_id"] = policy_id
            except Exception as exc:
                errors.append(exc)

        start = time.time()
        write_thread = ThreadPoolExecutor(max_workers=1).submit(_do_write)

        time.sleep(self.HOLD_SECONDS)
        pre_lock_fmg.execute(url=f"/dvmdb/adom/root/workspace/unlock/pkg/{pkg}")
        pre_lock_fmg.logout()

        write_thread.result(timeout=self.HOLD_SECONDS + 30)
        elapsed = time.time() - start

        if errors:
            raise errors[0]

        resp = result_holder.get("response", {})
        _delete_policy(minimal_lock_config, result_holder.get("policy_id"), pkg=pkg)
        assert resp.get("status") == 0, f"Pkg write after lock release failed: {resp}"
        assert elapsed >= self.HOLD_SECONDS


# ---------------------------------------------------------------------------
# 5. Concurrent writes — both succeed
# ---------------------------------------------------------------------------

class TestConcurrentWrites:
    """
    Concurrent writes to the same locking scope must both eventually succeed.
    One will acquire the lock first; the other retries until the first releases it.
    """

    def _run_concurrent(self, config, pairs):
        """
        Submit multiple (add_url, addr_name, octet) write operations simultaneously.
        Returns list of (addr_name, response) tuples; cleans up on finish.
        """
        def _write(add_url, addr_name, octet):
            resp = _add_address(config, addr_name, url=add_url, octet=octet)
            return addr_name, resp

        results = []
        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            futures = {pool.submit(_write, *p): p for p in pairs}
            for fut in as_completed(futures):
                results.append(fut.result())
        return results

    def test_concurrent_adom_writes_both_succeed(self, auth_config):
        """
        Two simultaneous writes to the ADOM object database both succeed.
        ADOM-level locking serialises them via the retry loop.
        """
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")

        obj_url = "/pm/config/adom/root/obj/firewall/address/"
        pairs = [
            (obj_url, "test-concurrent-adom-1", 201),
            (obj_url, "test-concurrent-adom-2", 202),
        ]
        results = self._run_concurrent(auth_config, pairs)
        for name, resp in results:
            assert resp.get("status") == 0, f"Concurrent write '{name}' failed: {resp}"
        for _, name, _ in pairs:
            _delete_address(auth_config, name)

    def _run_concurrent_policies(self, config, writes):
        """Add policies (name, pkg) in parallel; returns [(name, pkg, response, policy_id)]."""
        with ThreadPoolExecutor(max_workers=len(writes)) as pool:
            futures = {pool.submit(_add_policy, config, name, pkg): (name, pkg)
                       for name, pkg in writes}
            results = []
            for future in as_completed(futures):
                name, pkg = futures[future]
                response, policy_id = future.result()
                results.append((name, pkg, response, policy_id))
        return results

    def test_concurrent_pkg_writes_same_pkg_both_succeed(self, minimal_lock_config):
        """
        Two simultaneous writes to the same policy package with minimal_locking=True
        both succeed. The pkg lock serialises them.
        """
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        results = self._run_concurrent_policies(minimal_lock_config, [
            ("test-concurrent-pkg-same-1", "default"),
            ("test-concurrent-pkg-same-2", "default"),
        ])
        for _, pkg, _, policy_id in results:
            _delete_policy(minimal_lock_config, policy_id, pkg=pkg)
        for name, _, response, _ in results:
            assert response.get("status") == 0, f"Concurrent pkg write '{name}' failed: {response}"

    def test_concurrent_pkg_writes_different_pkgs_no_contention(self, minimal_lock_config,
                                                                second_package):
        """
        Two simultaneous writes to DIFFERENT policy packages with minimal_locking=True
        both succeed, each under its own pkg lock.
        """
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")

        start = time.time()
        results = self._run_concurrent_policies(minimal_lock_config, [
            ("test-concurrent-pkg-diff-1", "default"),
            ("test-concurrent-pkg-diff-2", second_package),
        ])
        elapsed = time.time() - start
        for _, pkg, _, policy_id in results:
            _delete_policy(minimal_lock_config, policy_id, pkg=pkg)
        for name, _, response, _ in results:
            assert response.get("status") == 0, f"Concurrent cross-pkg write '{name}' failed: {response}"
        logger.info(f"Two-package concurrent writes elapsed: {elapsed:.2f}s")


# ---------------------------------------------------------------------------
# 6. Minimal locking really is minimal
# ---------------------------------------------------------------------------

class TestMinimalScopeIsNarrow:
    """
    "lockinfo is clean afterwards" passes whether the connector took a package lock or
    the whole ADOM. These tests tell the two apart: a second session holds a lock on a
    DIFFERENT package, which blocks any ADOM lock outright (measured: lock_adom ->
    -20055). A write that took the ADOM would sit in the retry loop; a write that took
    only its own package or device lock completes in seconds.
    """

    FAST_SECONDS = 30

    @pytest.fixture
    def other_package_held(self, minimal_lock_config, second_package):
        if not _workspace_enabled(minimal_lock_config):
            pytest.skip("Workspace mode not enabled")
        holder = _open_other_session()
        status, _ = holder.execute(url=f"/dvmdb/adom/root/workspace/lock/pkg/{second_package}")
        if status != 0:
            holder.logout()
            pytest.skip(f"Could not hold pkg/{second_package} (status={status})")
        # The premise: with that package held, the ADOM itself cannot be locked.
        probe = _open_other_session()
        try:
            adom_status, _ = probe.lock_adom("root")
            if adom_status == 0:
                probe.unlock_adom("root")
            assert adom_status != 0, "ADOM lock was granted while a package was held"
        finally:
            probe.logout()
        yield second_package
        holder.execute(url=f"/dvmdb/adom/root/workspace/unlock/pkg/{second_package}")
        holder.logout()

    def test_pkg_write_does_not_lock_the_adom(self, minimal_lock_config, other_package_held):
        start = time.time()
        response, policy_id = _add_policy(minimal_lock_config, "test-minimal-narrow-pkg")
        elapsed = time.time() - start
        _delete_policy(minimal_lock_config, policy_id)
        assert response.get("status") == 0, response
        assert elapsed < self.FAST_SECONDS, f"pkg write took {elapsed:.1f}s -- it waited on the ADOM"


# ---------------------------------------------------------------------------
# 7. Real installs: the write reaches the FortiGate
# ---------------------------------------------------------------------------

# Opt-in: a package install pushes the whole package and can delete objects on the
# device (a first install purges factory defaults). Name a package that mirrors the
# device -- for example one imported from it -- to run that test.
INSTALL_PACKAGE = os.getenv("LIVE_INSTALL_PACKAGE", "")


def _device_global_alias(config, device):
    """system global alias read from the FortiGate itself, through FMG's REST proxy."""
    response = operations["json_rpc_execute"](config, {"url": "/sys/proxy/json", "data": {
        "target": [f"/adom/root/device/{device}"], "action": "get",
        "resource": "/api/v2/cmdb/system/global"}})["execute_response"]
    entry = response[0] if isinstance(response, list) else response
    return ((entry.get("response") or {}).get("results") or {}).get("alias")


def _install(config, url, data):
    response = operations["json_rpc_execute"](config, {"url": url, "data": data, "track_task": True})
    return response, response.get("task_response") or {}


@pytest.mark.skipif(not MANAGED_DEVICE_NAME, reason="MANAGED_DEVICE_NAME env var not set")
class TestRealInstall:
    """
    "status 0" is not evidence that a change was installed: the install task can end
    "no changes on device" while every RPC succeeds. These tests read the FortiGate's
    own config afterwards. They change the device's system global alias and put it back.
    """

    @pytest.fixture
    def device_alias_restored(self, auth_config):
        if not _workspace_enabled(auth_config):
            pytest.skip("Workspace mode not enabled")
        original = _device_global_alias(auth_config, MANAGED_DEVICE_NAME)
        yield original
        operations["json_rpc_set"](auth_config, {
            "url": f"/pm/config/device/{MANAGED_DEVICE_NAME}/global/system/global",
            "data": {"adom": "root", "data": {"alias": original}}})
        _install(auth_config, "/securityconsole/install/device", {
            "adom": "root", "scope": [{"name": MANAGED_DEVICE_NAME, "vdom": "root"}]})
        assert _device_global_alias(auth_config, MANAGED_DEVICE_NAME) == original

    @pytest.mark.parametrize("minimal", [False, True], ids=["adom-lock", "minimal-lock"])
    def test_device_db_write_reaches_the_device(self, auth_config, device_alias_restored, minimal):
        # With minimal locking a device-DB write used to take dev/<device>; FMG then left
        # the device "nomod" and the install skipped the change (5 of 6 live runs).
        config = dict(auth_config, minimal_locking=minimal)
        marker = f"lock-test-{'min' if minimal else 'adom'}"
        write = operations["json_rpc_set"](config, {
            "url": f"/pm/config/device/{MANAGED_DEVICE_NAME}/global/system/global",
            "data": {"adom": "root", "data": {"alias": marker}}})
        assert write.get("status") == 0, write
        response, task = _install(config, "/securityconsole/install/device", {
            "adom": "root", "scope": [{"name": MANAGED_DEVICE_NAME, "vdom": "root"}]})
        assert response.get("status") == 0, response
        assert task.get("state") in (4, "done"), task
        assert _device_global_alias(config, MANAGED_DEVICE_NAME) == marker
        assert not _get_lockinfo(config), "a lock was left behind after the install"

    @pytest.mark.skipif(not INSTALL_PACKAGE, reason="LIVE_INSTALL_PACKAGE not set (opt-in)")
    @pytest.mark.parametrize("minimal", [False, True], ids=["adom-lock", "minimal-lock"])
    def test_package_install_reaches_the_device(self, auth_config, device_alias_restored, minimal):
        config = dict(auth_config, minimal_locking=minimal)
        marker = f"lock-test-pkg-{'min' if minimal else 'adom'}"
        operations["json_rpc_set"](config, {
            "url": f"/pm/config/device/{MANAGED_DEVICE_NAME}/global/system/global",
            "data": {"adom": "root", "data": {"alias": marker}}})
        response, task = _install(config, "/securityconsole/install/package", {
            "adom": "root", "pkg": INSTALL_PACKAGE,
            "scope": [{"name": MANAGED_DEVICE_NAME, "vdom": "root"}]})
        assert response.get("status") == 0, response
        assert task.get("state") in (4, "done"), task
        # A package install also installs pending device settings.
        assert _device_global_alias(config, MANAGED_DEVICE_NAME) == marker
        assert not _get_lockinfo(config), "a lock was left behind after the install"
