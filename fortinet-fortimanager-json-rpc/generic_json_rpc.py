"""
Copyright start
MIT License
Copyright (c) 2025 Fortinet Inc
Copyright end
"""

import json
import random
import re
import time
from typing import Union

from connectors.core.connector import get_logger, ConnectorError
from pyFMG.fortimgr import FortiManager

logger = get_logger('fortinet-fortimanager-json-rpc')

# Set the maximum number of retries to acquire a lock on an ADOM
MAX_RETRY_LIMIT = 1500


def get_config(config: dict) -> tuple:
    auth_method = config.get("auth_method")
    server_url = clean_server_url(config.get('address', ''), config.get('port'))
    username = config.get("username", None)
    password = config.get("password", None)
    api_key = config.get("api_key", None)
    verify_ssl = config.get("verify_ssl", True)
    if auth_method == "API Key":
        return server_url, None, None, api_key, verify_ssl
    else:
        return server_url, username, password, None, verify_ssl


def clean_server_url(server_url: str, port: Union[str, None]) -> str:
    server_host = server_url.strip('/').replace("http://", "").replace("https://", "")

    # Append port if specified and not the default port
    if port and port not in ["443", 443]:
        server_host = f"{server_host}:{port}"

    return server_host


def parse_data(data: Union[list, bool, str, dict]):
    if isinstance(data, str):
        try:
            return json.loads(data) if data else {}
        except json.JSONDecodeError as e:
            raise ConnectorError(f"Could not parse JSON: {e}")
    if isinstance(data, list):
        return {"data": data}
    if not isinstance(data, dict):
        raise ConnectorError(f"Unexpected data type: {type(data)}. Please pass a string, list, or dict.")
    return data


def parse_task_timeout(task_timeout, default=120):
    """
    Function to parse task_timeout from params.

    :param task_timeout: task_timeout from params
    :param default: Default timeout value if parsing fails.
    :return: Parsed integer timeout value.
    """
    task_timeout = task_timeout or default
    try:
        task_timeout = int(task_timeout)
    except ValueError:
        task_timeout = default
    return task_timeout


def parse_adom_from_input(url: str, data: Union[list, dict]) -> str:
    match = re.search(r'/adom/([^/]+)/', url)
    if match:
        return match.group(1)

    # If the adom is not found in the URL, check the data
    def extract_adom(nested_data):
        if isinstance(nested_data, dict):
            if 'url' in nested_data:
                nested_match = re.search(r'/adom/([^/]+)/', nested_data['url'])
                if nested_match:
                    return nested_match.group(1)
            if 'adom' in nested_data:
                return nested_data['adom']
            for key, value in nested_data.items():
                result = extract_adom(value)
                if result:
                    return result
        elif isinstance(nested_data, list):
            for item in nested_data:
                result = extract_adom(item)
                if result:
                    return result
        return None

    adom = extract_adom(data)
    return adom if adom else "global"


def parse_track_task_params(params):
    """
    Parse all track task related parameters with their defaults.

    Args:
        params (dict): Parameters from the request

    Returns:
        dict: Dictionary containing all track task parameters with their values
    """
    track_task_params = {
        'timeout': parse_task_timeout(params.get('task_timeout', 21600)),
        'timeout_only': False,  # Always set to False as per requirements
        'zero_percent_timeout': parse_task_timeout(params.get('zero_percent_timeout', 30)),
        'task_stale_timeout': parse_task_timeout(params.get('task_stale_timeout', 120)),
        'delete_task_on_timeout': params.get('delete_task_on_timeout', True)
    }
    return track_task_params


def lock_adom(fmg, adom, url, data):
    for attempt in range(MAX_RETRY_LIMIT):
        status, _ = fmg.lock_adom(adom)
        # If the lock was acquired, break the loop
        if status == 0:
            logger.debug(f"Acquired lock for ADOM: {adom} using URL: {url} with PAYLOAD: {data}.")
            return True
        # status == -9 means that the command for the url is invalid. This happens when an adom is attempted to be
        # locked when workspaces isn't enabled. This is a workaround for a pyFMG bug where uses_workspace is True when
        # it should be False. That happens because pyFMG checks a 0 or 1 int, but verbose mode returns a string.
        if status == -9:
            logger.debug(f"Workspaces not enabled. Locking ADOM: {adom} not required.")
            return True
        # status == -6 when URL is invalid. This could occur when a nonexistent adom is attempted to be locked.
        if status == -6:
            logger.error(f"URL is invalid. ADOM: {adom} does not exist.")
            return False
        if attempt < MAX_RETRY_LIMIT - 1:
            # Sleep for a random amount of time between 1 and 10 seconds
            sleep_time = random.randint(1, 10)
            logger.debug(
                f"Failed to acquire lock for ADOM: {adom} using URL: {url} with PAYLOAD: {data}. Sleeping {sleep_time} seconds and retrying...")
            time.sleep(sleep_time)
        else:
            logger.error(
                f"Max retry limit reached. Could not acquire lock for ADOM: {adom} using URL: {url} with PAYLOAD: {data}.")
            return False
    return False


def handle_special_cases(fmg, url, data, action_response, task_response=None):
    special_cases = {
        "/securityconsole/install/preview": {
            "extra_url": "/securityconsole/preview/result",
            "action": "execute"
        },
        # Add more special cases here as needed
    }

    if url in special_cases:
        case = special_cases[url]
        action_func = getattr(fmg, case["action"])
        status, extra_response = action_func(url=case["extra_url"], **data)
        return extra_response
    return None


def perform_rpc_action(action: str, config: dict, params: dict) -> dict:
    server_host, username, password, api_key, verify_ssl = get_config(config)
    try:
        with FortiManager(server_host, username, password, apikey=api_key, verify_ssl=verify_ssl,
                          debug=config.get("debug_connection", False),
                          verbose=config.get("verbose_json", True), disable_request_warnings=True) as fmg:
            action_func = getattr(fmg, action)
            data = parse_data(params.get("data", {}))
            url = params.get("url")
            # To handle locking ADOM's when freeform action is used, I will pick the first url found and lock that adom.
            if action == "free_form":
                # make sure data is a list before accessing the first instance
                if not isinstance(data.get("data", None), list):
                    raise ConnectorError("Payload must be a list")
                url = data["data"][0].get("url", url)
            adom = parse_adom_from_input(url, data)
            response = {}

            # Lock the ADOM if the action is not a get or execute and the lock context uses the workspace
            if action not in ["get"] and fmg._lock_ctx.uses_workspace:
                if not lock_adom(fmg, adom, url, data):
                    raise ConnectorError(f"Failed to lock ADOM: {adom}")

                if action == "free_form":
                    method = params.get("method")
                    status, action_response = action_func(method, **data)
                else:
                    status, action_response = action_func(url=url, **data)
            else:
                if action == "free_form":
                    method = params.get("method")
                    status, action_response = action_func(method, **data)
                else:
                    status, action_response = action_func(url=url, **data)

            if fmg._lock_ctx.uses_workspace and action != "get":
                fmg.commit_changes(adom)
                # Consider unlocking the adom here, but not sure if it's safe to do so if there is a task to track
                # Not unlocking here could potentially cause delays in other workers that need to lock the same adom

            response[f"{action}_response"] = action_response
            # If the action is execute and track_task is set to True, track the task
            # Also need to make sure that the response is a dict because some exec actions like sys/proxy/info can return a list
            if action == 'execute' and params.get("track_task", False) and isinstance(action_response, dict):
                task = action_response.get('task') or action_response.get('taskid')
                # handle case where no task id is found and there is an attempt to track task
                if not task:
                    response["task_response"] = None
                    response["error"] = "No task id found in execute_response and track_task is set to True."
                else:
                    track_task_params = parse_track_task_params(params)
                    status, task_response = fmg.track_task(task, **track_task_params)
                    response["task_response"] = task_response

                    # Handle special cases. Putting this here because the task needs to be tracked first for exec actions
                    special_case_result = handle_special_cases(fmg, url, data, action_response, task_response)
                    if special_case_result:
                        response["special_case_response"] = special_case_result

                # I'm not sure if we need to commit changes here after the task is tracked, but leaving it here for now
                if fmg._lock_ctx.uses_workspace:
                    fmg.commit_changes(adom)
                    fmg.unlock_adom(adom)

            response["status"] = status
            logger.debug(response)
            return response
    except Exception as e:
        raise ConnectorError(e)
