"""
info.json and operations.py must agree.

FortiSOAR builds each action's input form from info.json and dispatches to the function
of the same name in operations.py. A mismatch is invisible to every test that calls
operations[...] directly and only fails once the connector is installed: an action in
info.json with no function errors when run, and a function with no info.json entry
cannot be used from a playbook at all.
"""
import importlib
import json
import os
import sys

import pytest

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
sys.path.insert(0, repo_root)

operations = importlib.import_module("fortinet-fortimanager-json-rpc.operations").operations
with open(os.path.join(repo_root, "fortinet-fortimanager-json-rpc", "info.json")) as handle:
    INFO = json.load(handle)
OPS = {op["operation"]: op for op in INFO["operations"]}


def params(op_name):
    # "label" entries are form section headings, not inputs.
    return {p["name"]: p for p in OPS[op_name].get("parameters", []) if p.get("type") != "label"}


def test_every_info_json_operation_has_a_function():
    assert sorted(set(OPS) - set(operations)) == []


# FortiSOAR calls the health check itself; it is not a playbook action.
NOT_ACTIONS = {"check_health"}


def test_every_function_is_exposed_in_info_json():
    assert sorted(set(operations) - set(OPS) - NOT_ACTIONS) == []


def test_every_input_has_a_name_title_and_type():
    for name, op in OPS.items():
        for p in op.get("parameters", []):
            if p.get("type") == "label":
                continue
            assert p.get("name") and p.get("title") and p.get("type"), (name, p)


@pytest.mark.parametrize("op_name", ["json_rpc_update", "json_rpc_clone", "json_rpc_replace"])
def test_url_and_data_actions(op_name):
    p = params(op_name)
    assert set(p) == {"url", "data"}
    assert p["url"]["required"] and p["data"]["required"]
    assert p["data"]["type"] == "json"


def test_move_inputs_match_what_the_code_reads():
    # perform_rpc_action reads params["option"] and params["target"] for a move.
    p = params("json_rpc_move")
    assert set(p) == {"url", "option", "target"}
    assert p["option"]["type"] == "select"
    assert sorted(p["option"]["options"]) == ["after", "before"]
    assert p["option"]["value"] in p["option"]["options"]
    # A text field: FMG needs the target as a string (an int is -3 "Object does not exist").
    assert p["target"]["type"] == "text"
    assert all(p[k]["required"] for k in p)


def test_replace_warns_that_unsent_fields_are_reset():
    op = OPS["json_rpc_replace"]
    text = (op["description"] + params("json_rpc_replace")["data"]["description"]).lower()
    assert "reset" in text
