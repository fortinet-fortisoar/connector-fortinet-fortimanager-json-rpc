"""
Copyright start
MIT License
Copyright (c) 2024 Fortinet Inc
Copyright end
"""

import importlib
import logging
import os
import sys

import pytest
from dotenv import load_dotenv

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables from .env file in the parent directory
current_directory = os.path.dirname(__file__)
parent_directory = os.path.abspath(os.path.join(current_directory, os.pardir))
grandparent_directory = os.path.abspath(os.path.join(parent_directory, os.pardir))

# Add the grandparent directory to the system path
sys.path.insert(0, str(grandparent_directory))

env_path = os.path.join(parent_directory, '.env')
load_dotenv(dotenv_path=env_path)

# Import the module dynamically
module_name = "fortinet-fortimanager-json-rpc.operations"
my_package = importlib.import_module(module_name)

# Import the operations dictionary from the module
operations = my_package.operations


def get_auth_config(auth_method):
    base_config = {
        "address": os.getenv("ADDRESS"),
        "verify_ssl": os.getenv("VERIFY_SSL", "False").lower() in ("true", "1", "t"),
        "port": os.getenv("PORT"),
        "debug_connection": os.getenv("DEBUG_CONNECTION", "False").lower() in ("true", "1", "t"),
        "verbose_json": os.getenv("VERBOSE_JSON", "True").lower() in ("true", "1", "t"),
    }

    if auth_method == "Username/Password":
        base_config.update({
            "username": os.getenv("USERNAME"),
            "password": os.getenv("PASSWORD"),
            "auth_method": "Username/Password"
        })
    else:
        base_config.update({
            "api_key": os.getenv("API_KEY"),
            "auth_method": "API Key"
        })

    return base_config


# Add this to ensure the logs are captured and displayed in pytest output
@pytest.fixture(autouse=True)
def _log_level(caplog):
    caplog.set_level(logging.INFO)


concurrent_input_sets = [
    {
        "name": "host-172-23-200-121",
        "subnet": ["172.23.200.121", "255.255.255.255"],
        "type": "ipmask"
    },
    {
        "name": "host-172-23-200-122",
        "subnet": ["172.23.200.122", "255.255.255.255"],
        "type": "ipmask"
    },
    {
        "name": "host-172-23-200-123",
        "subnet": ["172.23.200.123", "255.255.255.255"],
        "type": "ipmask"
    },
    {
        "name": "host-172-23-200-124",
        "subnet": ["172.23.200.124", "255.255.255.255"],
        "type": "ipmask"
    }
]


@pytest.mark.parametrize("input_set", concurrent_input_sets)
class TestRPCOperations:

    @pytest.mark.user_pass
    def test_rpc_add_concurrent_user_pass(self, input_set):
        self._run_test("Username/Password", input_set)

    @pytest.mark.api_key
    def test_rpc_add_concurrent_api_key(self, input_set):
        self._run_test("API Key", input_set)

    def _run_test(self, auth_method, input_set):
        config = get_auth_config(auth_method)
        params_add = {
            "url": "/pm/config/adom/root/obj/firewall/address/",
            "data": [input_set]
        }
        params_delete = {
            "url": f"/pm/config/adom/root/obj/firewall/address/{input_set['name']}"
        }

        logger.info(f"Running test with {auth_method} authentication for {input_set['name']}")
        print(f"Running test with {auth_method} authentication for {input_set['name']}")

        try:
            for attempt in range(3):

                add_response = operations['json_rpc_add'](config, params_add)
                print(f"Attempt {attempt +1}: {add_response}")
                if add_response.get("status", None) == 0:
                    break
            assert add_response.get("status",
                                    None) == 0, f"Add operation failed with status {add_response.get('status')}"
            assert "add_response" in add_response, "Response missing 'add_response' key"
            assert add_response.get("add_response", {}).get("name", None) == input_set[
                "name"], f"Expected name '{input_set['name']}' in response"

            logger.info(f"Successfully added object {input_set['name']} using {auth_method} authentication")
            print(f"Successfully added object {input_set['name']} using {auth_method} authentication")
        except my_package.ConnectorError as e:
            logger.error(f"ConnectorError occurred during add operation: {str(e)}")
            pytest.fail(f"Add operation failed due to ConnectorError: {str(e)}")

        finally:
            try:
                for attempt in range(3):
                    delete_response = operations['json_rpc_delete'](config, params_delete)
                    print(f"Attempt {attempt +1}: {delete_response}")
                    if delete_response.get("status", None) == 0:
                        break
                print(delete_response)
                assert delete_response.get("status",
                                           None) == 0, f"Delete operation failed with status {delete_response.get('status')}"
                logger.info(f"Successfully deleted object {input_set['name']} using {auth_method} authentication")
                print(f"Successfully deleted object {input_set['name']} using {auth_method} authentication")
            except my_package.ConnectorError as e:
                logger.error(f"ConnectorError occurred during delete operation: {str(e)}")
                print(f"Delete operation failed due to ConnectorError: {str(e)}")
