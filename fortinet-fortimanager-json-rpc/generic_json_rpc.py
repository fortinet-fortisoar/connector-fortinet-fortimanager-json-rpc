""" Copyright start
  Copyright (C) 2008 - 2023 Fortinet Inc.
  All rights reserved.
  FORTINET CONFIDENTIAL & FORTINET PROPRIETARY SOURCE CODE
  Copyright end """

import json
import re
from typing import Union
from connectors.core.connector import get_logger, ConnectorError
from pyFMG.fortimgr import FortiManager

logger = get_logger('fortinet-fortimanager-json-rpc')


def get_config(config: dict) -> tuple:
    server_url = clean_server_url(config.get('address', ''), config.get('port'))
    return server_url, config.get("username"), config.get("password"), config.get("verify_ssl", None)


def clean_server_url(server_url: str, port: Union[str, None]) -> str:
    server_host = server_url.strip('/').replace("http://", "").replace("https://", "")

    # Append port if specified and not the default port
    if port and port not in ["443", 443]:
        server_host = f"{server_host}:{port}"

    return server_host


def parse_data(data: Union[list, bool, str, dict]):
    if isinstance(data, str):
        try:
            if data == "":
                return {}
            return json.loads(data)
        except json.JSONDecodeError as e:
            raise ConnectorError(f"Could not parse json: {e}")
    if isinstance(data, list):
        return {"data": data}
    if not isinstance(data, dict):
        raise ConnectorError(f"Unexpected data type: {type(data)}. Please pass a string, list, or dict.")
    return data


def parse_adom_item_regex(url: str) -> str:
    match = re.search(r'/adom/([^/]+)/', url)
    if match:
        return match.group(1)  # Return the matched group after 'adom'
    else:
        return "global"


def perform_rpc_action(action: str, config: dict, params: dict) -> dict:
    server_host, username, password, verify_ssl = get_config(config)
    try:
        with FortiManager(server_host, username, password, verify_ssl=verify_ssl,
                          debug=config.get("debug_connection", False),
                          verbose=config.get("verbose_json", True), disable_request_warnings=True) as fmg:
            action_func = getattr(fmg, action)
            data = parse_data(params.get("data", {}))
            url = params.get("url")
            adom = parse_adom_item_regex(url)
            response = {}

            # Lock the ADOM if the action is not a get or execute and the lock context uses the workspace
            if action not in ["get"] and fmg._lock_ctx.uses_workspace:
                fmg.lock_adom(adom)
                # Run the action
                status, action_response = action_func(url=url, **data)
                fmg.commit_changes(adom)
            else:
                status, action_response = action_func(url=url, **data)
            response[f"{action}_response"] = action_response
            # If the action is execute and track_task is set to True, track the task
            if action == 'execute' and params.get("track_task", False):
                task = action_response.get('task') or action_response.get('taskid')
                status, task_response = fmg.track_task(task)
                response["task_response"] = task_response
                if fmg._lock_ctx.uses_workspace:
                    fmg.commit_changes(adom)

            response["status"] = status
            logger.debug(response)
            return response
    except Exception as e:
        raise ConnectorError(e)
