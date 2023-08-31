""" Copyright start
  Copyright (C) 2008 - 2023 Fortinet Inc.
  All rights reserved.
  FORTINET CONFIDENTIAL & FORTINET PROPRIETARY SOURCE CODE
  Copyright end """

from connectors.core.connector import get_logger, ConnectorError
from .freeform_json_rpc import _json_rpc_add, _json_rpc_set, _json_rpc_get, _json_rpc_execute, _json_rpc_delete, _json_rpc_freeform

logger = get_logger('fortinet-fortimanager-json-rpc')


def _check_health(config):
    params = {"url": "/sys/status", "data": {}}
    try:
        response = _json_rpc_get(config, params)
        if response['get_response']:
            return True
    except Exception as e:
        raise ConnectorError(str(e) + " - Unable to get system status")


def json_rpc_add(config, params):
    try:
        response = _json_rpc_add(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


def json_rpc_set(config, params):
    try:
        response = _json_rpc_set(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


def json_rpc_get(config, params):
    try:
        response = _json_rpc_get(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


def json_rpc_execute(config, params):
    try:
        response = _json_rpc_execute(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


def json_rpc_delete(config, params):
    try:
        response = _json_rpc_delete(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


def json_rpc_freeform(config, params):
    try:
        response = _json_rpc_freeform(config, params)
        return response
    except Exception as e:
        raise ConnectorError(str(e))


operations = {
    'json_rpc_add': json_rpc_add,
    'json_rpc_set': json_rpc_set,
    'json_rpc_get': json_rpc_get,
    'json_rpc_execute': json_rpc_execute,
    'json_rpc_delete': json_rpc_delete,
    'json_rpc_freeform': json_rpc_freeform
}
