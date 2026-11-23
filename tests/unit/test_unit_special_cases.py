"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

# Follow-up calls (SPECIAL_CASES): a URL whose result is only available from a second
# call made after the first call's task finishes. Today that is install/preview, whose
# diff lives at /securityconsole/preview/result.

import os
import sys

current_directory = os.path.dirname(__file__)
sys.path.insert(0, current_directory)

from test_unit_locking_orchestration import (  # noqa: E402
    BASE_CONFIG, FakeFMG, generic_json_rpc, run_action)

PREVIEW = "/securityconsole/install/preview"
RESULT = "/securityconsole/preview/result"
PREVIEW_DATA = {"adom": "root", "flags": ["none"],
                "scope": [{"name": "fgt1", "vdom": "root"}]}


class FollowUpFakeFMG(FakeFMG):
    """FakeFMG that records execute payloads and answers preview/result separately."""

    def __init__(self, result=(0, {"message": "diff"}), result_error=None,
                 task=(0, {"state": 4}), **kwargs):
        super().__init__(exec_result=(0, {"task": 42}), **kwargs)
        self.result = result
        self.result_error = result_error
        self.task = task
        self.payloads = {}

    def execute(self, url=None, **kwargs):
        self.payloads[url] = kwargs
        if url == RESULT:
            self.calls.append(("execute", url))
            if self.result_error:
                raise self.result_error
            return self.result
        return super().execute(url=url, **kwargs)

    def track_task(self, task, **kwargs):
        self.calls.append(("track_task", task))
        return self.task


def preview(fmg, **extra):
    return run_action(fmg, "execute", dict({"url": PREVIEW, "data": PREVIEW_DATA}, **extra),
                      BASE_CONFIG)


def test_preview_tracks_and_fetches_result_without_track_task():
    fmg = FollowUpFakeFMG()
    response = preview(fmg)
    names = [name for name, _ in fmg.calls]
    assert names.index("track_task") < fmg.calls.index(("execute", RESULT))
    assert response["special_case_response"] == {"message": "diff"}
    assert response["special_case_status"] == 0
    assert response["status"] == 0


def test_result_payload_is_adom_and_scope_only():
    # preview/result answers "no devices" to every device-keyed shape (live 7.6.8);
    # it selects by the preview's own scope. Flags and the like are dropped.
    fmg = FollowUpFakeFMG()
    preview(fmg)
    assert fmg.payloads[RESULT] == {"adom": "root",
                                    "scope": [{"name": "fgt1", "vdom": "root"}]}


def test_bare_device_name_becomes_a_scope():
    assert generic_json_rpc._preview_result_payload({"adom": "a", "device": "d"}) == {
        "adom": "a", "scope": [{"name": "d", "vdom": "root"}]}


def test_scope_wins_over_device():
    assert generic_json_rpc._preview_result_payload(
        {"adom": "a", "device": "d", "scope": [{"name": "s"}]}) == {
        "adom": "a", "scope": [{"name": "s"}]}


def test_trailing_slash_still_matches():
    fmg = FollowUpFakeFMG()
    response = run_action(fmg, "execute", {"url": PREVIEW + "/", "data": PREVIEW_DATA},
                          BASE_CONFIG)
    assert "special_case_response" in response


def test_failed_task_skips_the_follow_up():
    fmg = FollowUpFakeFMG(task=(0, {"state": 5}))
    response = preview(fmg, track_task=True)
    assert ("execute", RESULT) not in fmg.calls
    assert "special_case_skipped" in response


def test_follow_up_error_status_is_surfaced():
    fmg = FollowUpFakeFMG(result=(-6, {"message": "Invalid url"}))
    response = preview(fmg)
    assert response["special_case_status"] == -6
    assert response["status"] == -6


def test_follow_up_exception_keeps_main_response():
    fmg = FollowUpFakeFMG(result_error=RuntimeError("boom"))
    response = preview(fmg)
    assert response["execute_response"] == {"task": 42}
    assert response["special_case_error"] == "boom"
    assert response["status"] == -1


def test_empty_result_is_still_reported():
    fmg = FollowUpFakeFMG(result=(0, {}))
    response = preview(fmg)
    assert response["special_case_response"] == {}


def test_other_urls_have_no_special_case():
    fmg = FollowUpFakeFMG()
    response = run_action(fmg, "execute", {"url": "/um/image/upgrade/ext",
                                           "data": {"adom": "root"}}, BASE_CONFIG)
    assert "special_case_response" not in response
    assert ("execute", RESULT) not in fmg.calls


# --- prepare step: the preview-flagged install, in the same session -------------------

def test_preview_install_runs_first_in_the_same_session():
    fmg = FollowUpFakeFMG()
    response = preview(fmg)
    executes = [url for name, url in fmg.calls if name == "execute"]
    assert executes.index("/securityconsole/install/device") < executes.index(PREVIEW) \
        < executes.index(RESULT)
    assert fmg.payloads["/securityconsole/install/device"] == {
        "adom": "root", "scope": PREVIEW_DATA["scope"], "flags": ["preview"]}
    assert response["special_case_prepare"]["status"] == 0


def test_package_in_payload_previews_a_package_install():
    fmg = FollowUpFakeFMG()
    run_action(fmg, "execute", {"url": PREVIEW, "data": dict(PREVIEW_DATA, pkg="default")},
               BASE_CONFIG)
    assert fmg.payloads["/securityconsole/install/package"]["pkg"] == "default"
    assert "/securityconsole/install/device" not in fmg.payloads


def test_failed_preview_install_fails_the_call():
    class PrepareFails(FollowUpFakeFMG):
        def execute(self, url=None, **kwargs):
            if url == "/securityconsole/install/device":
                self.calls.append(("execute", url))
                return -11, {"status": {"code": -11}}
            return super().execute(url=url, **kwargs)

    response = preview(PrepareFails())
    assert response["special_case_prepare"]["status"] == -11
    assert response["status"] == -11


def test_prepare_exception_is_reported_not_raised():
    class PrepareRaises(FollowUpFakeFMG):
        def execute(self, url=None, **kwargs):
            if url == "/securityconsole/install/device":
                raise RuntimeError("boom")
            return super().execute(url=url, **kwargs)

    response = preview(PrepareRaises())
    assert response["special_case_prepare"]["error"] == "boom"
    assert response["status"] == -1


def test_failed_preview_task_fails_the_call_without_track_task():
    # Live 7.6.8: install/preview task ended state 5 "Internal error" and the call
    # still returned status 0 because the caller had not asked for tracking.
    class PreviewTaskFails(FollowUpFakeFMG):
        def __init__(self):
            super().__init__()
            self.tracked = 0

        def track_task(self, task, **kwargs):
            self.calls.append(("track_task", task))
            self.tracked += 1
            return (0, {"state": 4}) if self.tracked == 1 else (0, {"state": 5})

    response = preview(PreviewTaskFails())
    assert "special_case_skipped" in response
    assert response["status"] == -1


def test_package_preview_holds_the_package_lock_across_its_task():
    # Live 7.6.8, workspace mode: unlocked package preview fails "no write permission".
    fmg = FollowUpFakeFMG()
    run_action(fmg, "execute", {"url": PREVIEW, "data": dict(PREVIEW_DATA, pkg="Pkg1")},
               BASE_CONFIG)
    calls = fmg.calls
    lock = calls.index(("execute", "/dvmdb/adom/root/workspace/lock/pkg/Pkg1"))
    install = calls.index(("execute", "/securityconsole/install/package"))
    unlock = calls.index(("execute", "/dvmdb/adom/root/workspace/unlock/pkg/Pkg1"))
    tracked = [i for i, call in enumerate(calls) if call[0] == "track_task"][0]
    assert lock < install < tracked < unlock
    assert ("execute", "/dvmdb/adom/root/workspace/commit/pkg/Pkg1") not in calls


def test_device_preview_takes_no_lock():
    fmg = FollowUpFakeFMG()
    preview(fmg)
    assert not any("/workspace/" in str(url) for _, url in fmg.calls)


def test_package_preview_without_workspace_mode_takes_no_lock():
    fmg = FollowUpFakeFMG(uses_workspace=False)
    run_action(fmg, "execute", {"url": PREVIEW, "data": dict(PREVIEW_DATA, pkg="Pkg1")},
               BASE_CONFIG)
    assert not any("/workspace/" in str(url) for _, url in fmg.calls)


def test_preview_install_ending_in_warning_fails_the_call():
    # Live 7.6.8: another session holds dev/<device>; the preview install ends "warning"
    # ("Lock Device ... failed") and the result is "No preview result".
    fmg = FollowUpFakeFMG(task=(0, {"state": "warning",
                                    "line": [{"detail": "Lock Device, fgt1, failed"}]}))
    response = preview(fmg)
    assert response["status"] == -1
    assert "Lock Device" in response["special_case_prepare"]["error"]
