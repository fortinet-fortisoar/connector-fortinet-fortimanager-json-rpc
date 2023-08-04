""" Copyright start
  Copyright (C) 2008 - 2023 Fortinet Inc.
  All rights reserved.
  FORTINET CONFIDENTIAL & FORTINET PROPRIETARY SOURCE CODE
  Copyright end """

import json
from typing import Union

from connectors.core.connector import get_logger, ConnectorError
from pyFMG.fortimgr import FortiManager

logger = get_logger('fortinet-fortimanager')


def _get_config(config):
    server_url = config.get('address', None).strip('/')
    port = config.get('port', None)
    username = config.get("username")
    password = config.get("password")
    verify_ssl = config.get("verify_ssl", None)
    if port:
        server_url = '{0}:{1}'.format(server_url, port)
    if server_url[:7] != 'http://' and server_url[:8] != 'https://':
        server_url = 'https://{}'.format(str(server_url))
    return server_url, username, password, verify_ssl


def create_fmg_session(config: dict):
    try:
        server_url, username, password, verify_ssl = _get_config(config)
        server_url = server_url.replace("https://", "").replace("http://", "").strip("/")
        debug_connection = config.get("debug_connection", False)
        verbose_json = config.get("verbose_json", True)
        fmg = FortiManager(server_url, username, password, verify_ssl=verify_ssl, debug=debug_connection,
                           verbose=verbose_json)
        return fmg
    except Exception as e:
        raise ConnectorError(e)


def parse_data(data: Union[list, bool, str]):
    if type(data) == str:
        try:
            data = json.loads(data)
        except Exception as e:
            raise ConnectorError(f"Could not parse json: {e}")
    elif type(data) == list:
        data = {"data": data}
    elif type(data) == dict:
        pass
    else:
        raise ConnectorError(f"You passed an unexpected type of {type(data)}. Please pass a string, list, or dict")
    return data


def _json_rpc_add(config: dict, params: dict) -> dict:
    try:
        fmg_session = create_fmg_session(config)
        fmg_session.login()
        add_call = getattr(fmg_session, 'add')
        url = params.get("url")
        data = parse_data(params.get("data", {}))
        status, add_response = add_call(url=url, **data)
        logger.debug(add_response)
        return {"status": status, "add_response": add_response}
    except Exception as e:
        raise ConnectorError(e)
    finally:
        fmg_session.logout()


def _json_rpc_set(config: dict, params: dict) -> dict:
    try:
        fmg_session = create_fmg_session(config)
        fmg_session.login()
        set_call = getattr(fmg_session, 'set')
        url = params.get("url")
        data = parse_data(params.get("data", {}))
        status, set_response = set_call(url=url, **data)
        logger.debug(set_response)
        return {"status": status, "set_response": set_response}
    except Exception as e:
        raise ConnectorError(e)
    finally:
        fmg_session.logout()


def _json_rpc_get(config: dict, params: dict) -> dict:
    try:
        fmg_session = create_fmg_session(config)
        fmg_session.login()
        get_call = getattr(fmg_session, 'get')
        url = params.get("url")
        data = parse_data(params.get("data", {}))
        status, get_response = get_call(url=url, **data)
        logger.debug(get_response)
        return {"status": status, "get_response": get_response}
    except Exception as e:
        raise ConnectorError(e)
    finally:
        fmg_session.logout()


def _json_rpc_execute(config: dict, params: dict) -> dict:
    try:
        fmg_session = create_fmg_session(config)
        fmg_session.login()
        execute_call = getattr(fmg_session, 'execute')
        url = params.get("url")
        data = parse_data(params.get("data", {}))
        track_task = params.get("track_task", False)
        status, execute_response = execute_call(url=url, **data)
        if track_task:
            task = execute_response.get('task') or execute_response.get('taskid')
            status, task_response = fmg_session.track_task(task)
            logger.debug(task_response)
        else:
            task_response = None
        logger.debug(execute_response)
        return {"status": status, "execute_response": execute_response, "task_response": task_response}
    except Exception as e:
        raise ConnectorError(e)
    finally:
        fmg_session.logout()


def _json_rpc_delete(config: dict, params: dict) -> dict:
    try:
        fmg_session = create_fmg_session(config)
        fmg_session.login()
        delete_call = getattr(fmg_session, 'delete')
        url = params.get("url")
        data = parse_data(params.get("data", {}))
        status, delete_response = delete_call(url=url, **data)
        logger.debug(delete_response)
        return {"status": status, "delete_response": delete_response}
    except Exception as e:
        raise ConnectorError(e)
    finally:
        fmg_session.logout()
