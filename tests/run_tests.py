"""
Copyright start
MIT License
Copyright (c) 2025 Fortinet Inc
Copyright end
"""

import importlib
import os
import subprocess
import sys
import time

from dotenv import load_dotenv

# Load environment variables from .env file in the parent directory
current_directory = os.path.dirname(__file__)
parent_directory = os.path.abspath(os.path.join(current_directory, os.pardir))

# Add the grandparent directory to the system path
sys.path.insert(0, str(parent_directory))

# Load environment variables from .env file in the parent directory
env_path = os.path.join(current_directory, '.env')
load_dotenv(dotenv_path=env_path)

# Import the module dynamically
module_name = "fortinet-fortimanager-json-rpc.operations"
my_package = importlib.import_module(module_name)

# Import the operations dictionary from the module
operations = my_package.operations

config = {
    "username": os.getenv("USERNAME"),
    "password": os.getenv("PASSWORD"),
    "auth_method": os.getenv("AUTH_METHOD"),
    "address": os.getenv("ADDRESS"),
    "verify_ssl": os.getenv("VERIFY_SSL", "False").lower() in ("true", "1", "t"),
    "port": os.getenv("PORT"),
    "debug_connection": os.getenv("DEBUG_CONNECTION", "False").lower() in ("true", "1", "t"),
    "verbose_json": os.getenv("VERBOSE_JSON", "True").lower() in ("true", "1", "t"),
}


def get_server_value():
    params = {
        "url": "/cli/global/system/global",
        "data": {"fields": ["workspace-mode", "adom-status"]}
    }
    response = operations['json_rpc_get'](config, params)
    # Status should be 0 for success
    assert response.get("status", None) == 0

    assert "get_response" in response, "Response missing 'get_response' key"
    workspace_mode = response['get_response']['workspace-mode']
    print(f"Current workspace mode: {workspace_mode}")
    if workspace_mode in [0, "0", "disabled"]:
        return 0
    else:
        return 1


def update_server_value(new_value):
    params = {
        "url": "/cli/global/system/global",
        "data": {"workspace-mode": new_value}
    }
    print("Setting workspace mode to", new_value)
    response = operations['json_rpc_set'](config, params)
    # Status should be 0 for success
    assert response.get("status", None) == 0

    assert "set_response" in response, "Response missing 'set_response' key"


def execute_tests():
    try:
        # Run concurrent tests for Username/Password
        print("Running concurrent tests with Username/Password authentication...")
        subprocess.run(["pytest", "concurrent", "-n", "4", "-v", "-m", "user_pass"], check=True)
        print("Concurrent tests with Username/Password authentication completed successfully.")

        # Run concurrent tests for API Key
        print("Running concurrent tests with API Key authentication...")
        subprocess.run(["pytest", "concurrent", "-n", "4", "-v", "-m", "api_key"], check=True)
        print("Concurrent tests with API Key authentication completed successfully.")

        # Run sequential tests
        print("Running sequential tests...")
        subprocess.run(["pytest", "sequential", "-v"], check=True)
        print("Sequential tests completed successfully.")

        print("All tests completed successfully!")
        return 0

    except subprocess.CalledProcessError as e:
        print(f"Tests failed with return code {e.returncode}")
        return e.returncode


def run_tests():
    original_value = get_server_value()
    new_value = 1 if original_value == 0 else 0
    execute_tests()
    update_server_value(new_value)
    # sleep for 10 seconds to allow fmg time to update the workspace mode
    time.sleep(10)
    execute_tests()
    update_server_value(original_value)


if __name__ == "__main__":
    exit(run_tests())
