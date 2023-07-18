""" Copyright start
  Copyright (C) 2008 - 2022 Fortinet Inc.
  All rights reserved.
  FORTINET CONFIDENTIAL & FORTINET PROPRIETARY SOURCE CODE
  Copyright end """

import json
import ipaddress
import requests
from .constants import *
from connectors.core.connector import get_logger, ConnectorError

logger = get_logger('fortinet-fortimanager')


def add_bulk_address(config, ip_list, adom=None):
    failed_to_add_ips = []
    if adom:
        endpoint = ADD_ADDRESS.format(adom=adom)
    else:
        endpoint = GLOBAL_ADD_ADDRESS
    try:
        payload = build_payload(endpoint, method='add', faz_call=False)
        for ip in ip_list:
            if '-' in ip:
                start_ip = ip.split('-')[0].strip()
                end_ip = ip.split('-')[1].strip()
                ips_payload = [{'name': ip, 'start-ip': "{0}".format(start_ip), "end-ip": "{0}".format(end_ip)}]
            else:
                ip_obj = vars(ipaddress.ip_network(ip, False))
                ip_addr = str(ip_obj.get('network_address'))
                ip_netmask = str(ip_obj.get('netmask'))
                ips_payload = [{'name': ip, 'subnet': [ip_addr, ip_netmask]}]
            data = {"data": ips_payload}
            payload['params'][0].update(data)
            try:
                response = _api_request(config, body=payload)
                logger.debug('IP {} added successfully.. '.format(ip_list))
            except Exception as e:
                logger.error('{}'.format(e))
                failed_to_add_ips.append(ip)
                # check 500 status code or not already IP address exists in Addresses
                continue
        return failed_to_add_ips
    except Exception as err:
        logger.exception(err)
        raise ConnectorError(err)


def delete_addresses(config, ip_list, adom=None):
    referenced_ips = []
    try:
        for ip in ip_list:
            if adom:
                endpoint = DELETE_ADDRESS.format(adom=adom, address=ip)
            else:
                endpoint = GLOBAL_DELETE_ADDRESS.format(address=ip)
            payload = build_payload(endpoint, method='delete', faz_call=False)
            try:
                response = _api_request(config, body=payload)
                logger.debug('IP {} deleted successfully.. '.format(ip))
            except Exception as e:
                referenced_ips.append(ip)
                logger.debug('Not able to delete {} IP address entry.'.format(ip))
                logger.error('{}'.format(str(e)))
                continue
        return referenced_ips
    except Exception as err:
        logger.exception(err)
        raise ConnectorError(err)


def check_ip_exists(config, params, param_name, ip_address_list, blocked_ips, adom_name=None, service_call=False,
                    method='add'):
    new_ips = []
    remove_ips = []
    for ip in ip_address_list:
        if method == 'add':
            if ip not in blocked_ips:
                blocked_ips.append(ip)
                new_ips.append(ip)
        if method == 'remove':
            if ip in blocked_ips:
                blocked_ips.remove(ip)
                remove_ips.append(ip)
    if not service_call:
        if new_ips:
            failed_to_add_ips = add_bulk_address(config, new_ips, adom_name)
            logger.debug('failed_to_add_ips: {}'.format(failed_to_add_ips))
        if remove_ips:
            already_exists_ips = delete_addresses(config, remove_ips, adom_name)
            logger.debug('already_exists_ips: {}'.format(already_exists_ips))
    params.update({param_name: list(set(blocked_ips))})


def login(server_url, username, password, verify_ssl):
    try:
        method = "exec"
        payload = build_payload(LOGIN_API, method=method, faz_call=False)
        payload['params'][0].update({"data": {
            "passwd": password,
            "user": username
        }})
        header = {
            'content-Type': 'application/json'
        }
        response = requests.request(method='POST', url=server_url, data=json.dumps(payload), headers=header,
                                    verify=verify_ssl)
        result = validate_response(response)
        return result.get('session')
    except Exception as e:
        logger.exception(e)
        raise ConnectorError(e)


def logout(server_url, verify_ssl, session):
    try:
        method = "exec"
        payload = build_payload(LOGOUT_API, method=method, session=session, faz_call=False)
        header = {
            'content-Type': 'application/json'
        }
        response = requests.request(method='POST', url=server_url, data=json.dumps(payload), headers=header,
                                    verify=verify_ssl)
        result = validate_response(response)
        return result
    except Exception as e:
        logger.exception(e)
        raise ConnectorError(e)


def validate_response(response):
    if response.ok:
        result = response.json()
        if isinstance(result.get('result'), list) and result.get('result')[0].get('status').get('code') != 0:
            logger.exception(result)
            raise Exception(result)
        elif 'error' in result:
            logger.exception(result)
            raise Exception(result)
        return result
    else:
        logger.exception('Fail To request API {0} response is : {1}'.
                         format(str(response.url), str(response.content)))
        raise ConnectorError(
            'Fail To request API {0} response is : {1}'.format(str(response.url), str(response.content)))


def _api_request(config, body=None, parameters=None, method='POST', health_call=False):
    try:
        server_url, username, password, verify_ssl = _get_config(config)
        url = server_url + '/jsonrpc'
        session = login(url, username, password, verify_ssl)
        if not session:
            logger.debug('Fail to get session with given username and password.')
            raise ConnectorError(INVALID_URL_OR_CREDENTIALS)
        elif health_call:
            logout(url, verify_ssl, session)
            return True
        body['session'] = session
        logger.debug("body: {}".format(body))
        header = {
            'content-Type': 'application/json'
        }
        api_response = requests.request(method=method, url=url, data=json.dumps(body), headers=header,
                                        params=parameters, verify=verify_ssl)
        logout(url, verify_ssl, session)
        return validate_response(api_response)
    except requests.exceptions.SSLError:
        raise ConnectorError(SSL_VALIDATION_ERROR)
    except requests.exceptions.ConnectTimeout:
        raise ConnectorError(CONNECTION_TIMEOUT)
    except requests.exceptions.ReadTimeout:
        raise ConnectorError(REQUEST_READ_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise ConnectorError(INVALID_URL_OR_CREDENTIALS)
    except Exception as Err:
        logger.exception(Err)
        raise ConnectorError(Err)


def _get_list_from_str_or_list(params, parameter, typecast=False, raise_exc=True):
    try:
        parameter_list = params.get(parameter, [] if not raise_exc else None)
        if parameter_list:
            if isinstance(parameter_list, str):
                parameter_list = list(map(lambda x: x.strip(' '), parameter_list.split(",")))
                return parameter_list
            elif isinstance(parameter_list, list):
                if typecast:
                    parameter_list = list(map(str, parameter_list))
                return parameter_list
            elif typecast:
                return str(parameter_list)
        if raise_exc:
            raise ConnectorError(
                "{0} are not in format or empty: {1}".format(parameter, parameter_list))
        else:
            return parameter_list if parameter_list else []
    except Exception as Err:
        raise ConnectorError(Err)


def build_payload(endpoint, method='get', session=None, faz_call=True):
    try:
        payload = {
            "id": ID,
            "method": method,
            "params": [
                {
                    "url": endpoint
                }
            ]
        }
        if session:
            payload['session'] = session
        if faz_call:
            payload['jsonrpc'] = JSON_RPC
            payload['params'][0]['apiver'] = API_VERSION
        return payload
    except Exception as e:
        raise ConnectorError(e)


def build_param_payload(params):
    try:
        query_param = {}
        is_remove_keys = False
        remove_params = ['range_limit', 'range_offset', 'name', 'attribute', 'order', 'sortings']
        if 'range_offset' in list(params.keys()) or 'range_limit' in list(params.keys()):
            query_param['range'] = [params.get('range_offset', 0) if params.get('range_offset', 0) else 0,
                                    params.get('range_limit', 50) if params.get('range_limit', 50) else 50]
            is_remove_keys = True
        if 'filter' in list(params.keys()) and params.get('name'):
            # if filter specified append the name filter
            params.get('filter').append(['name', '==', params.get('name')]) if isinstance(params.get('filter'),
                                                                                          list) else params.update(
                {'filter': [["name", "==", params.get('name')]]})
            is_remove_keys = True
        if 'sortings' in list(params.keys()) and params.get('sortings'):
            query_param['sortings'] = [{params.get('attribute'): PARAM_MAPPING.get(params.get('order'))}]
            is_remove_keys = True
        if is_remove_keys:
            remove_keys(params, remove_params)
        for k, v in params.items():
            if (k in DICT_PARAM) and v:
                for dict_key in DICT_PARAM[k]:
                    dict_value = params.get(dict_key)
                    if dict_value:
                        query_param.get(k).update(
                            {dict_key: PARAM_MAPPING.get(dict_value) if isinstance(dict_value, str)
                                                                        and dict_value in PARAM_MAPPING else dict_value}) if k in query_param else query_param.update(
                            {k: {dict_key: PARAM_MAPPING.get(dict_value) if isinstance(dict_value,
                                                                                       str) and dict_value in PARAM_MAPPING else dict_value}})
            elif v and k not in sum(list(DICT_PARAM.values()), []):
                if isinstance(v, str) and v in PARAM_MAPPING:
                    query_param[k] = PARAM_MAPPING.get(v)
                elif k in POLICY_PARAM + ADDRESS_GROUP_PARAM + list(
                        map(lambda x: 'add_' + x, POLICY_PARAM + ADDRESS_GROUP_PARAM)) + list(
                    map(lambda x: 'remove_' + x, POLICY_PARAM + ADDRESS_GROUP_PARAM)) + CUSTOM_SERVICE_PARAM:
                    new_key = k.replace('remove_', '').replace('add_', '')
                    if new_key in query_param:
                        query_param[new_key] = query_param[new_key] + _get_list_from_str_or_list(params, k)
                    else:
                        query_param[new_key] = _get_list_from_str_or_list(params, k)
                elif k == 'additional_args':
                    query_param.update(v)
                else:
                    query_param[k] = str(v) if not isinstance(v, list) else v
        logger.debug("query_param:{}".format(query_param))
        return query_param
    except Exception as e:
        raise ConnectorError(e)


def _get_adom(config, params, func_call='adom'):
    try:
        adom = params.get('adom') if params.get('adom') else config.get('adom')
        if func_call == 'adom' and not adom:
            adom = 'root'
        elif func_call != 'adom':
            adom = None
        return str(adom) if not isinstance(adom, str) else adom
    except Exception as e:
        raise ConnectorError(e)


def remove_keys(params, remove_key_list):
    remove_key_lst = set(
        remove_key_list + list(map(lambda x: 'remove_' + x, POLICY_PARAM + ADDRESS_GROUP_PARAM))).intersection(
        list(params.keys()))
    for key in remove_key_lst:
        params.pop(key, None)
