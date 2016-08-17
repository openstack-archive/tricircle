# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import copy
import mock
from mock import patch
import netaddr
import unittest

from sqlalchemy.orm import attributes
from sqlalchemy.orm import exc
from sqlalchemy.sql import elements

import neutron_lib.constants as q_constants

import neutron.conf.common as q_config
from neutron.db import db_base_plugin_common
from neutron.db import db_base_plugin_v2
from neutron.db import ipam_pluggable_backend
from neutron.db import l3_db
from neutron.db import models_v2
from neutron.extensions import availability_zone as az_ext
from neutron.ipam import driver
from neutron.ipam import requests
import neutron.ipam.utils as ipam_utils
from neutron import manager
import neutronclient.common.exceptions as q_exceptions

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from tricircle.common import client
from tricircle.common import constants
from tricircle.common import context
from tricircle.common import exceptions
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network.drivers import type_local
from tricircle.network.drivers import type_shared_vlan
from tricircle.network import helper
from tricircle.network import managers
from tricircle.network import plugin
from tricircle.tests.unit.network import test_security_groups
from tricircle.xjob import xmanager


TOP_NETS = []
TOP_SUBNETS = []
TOP_PORTS = []
TOP_ROUTERS = []
TOP_ROUTERPORT = []
TOP_SUBNETPOOLS = []
TOP_SUBNETPOOLPREFIXES = []
TOP_IPALLOCATIONS = []
TOP_VLANALLOCATIONS = []
TOP_SEGMENTS = []
TOP_EXTNETS = []
TOP_FLOATINGIPS = []
TOP_SGS = []
TOP_SG_RULES = []
BOTTOM1_NETS = []
BOTTOM1_SUBNETS = []
BOTTOM1_PORTS = []
BOTTOM1_ROUTERS = []
BOTTOM1_SGS = []
BOTTOM1_FIPS = []
BOTTOM2_NETS = []
BOTTOM2_SUBNETS = []
BOTTOM2_PORTS = []
BOTTOM2_ROUTERS = []
BOTTOM2_SGS = []
BOTTOM2_FIPS = []
RES_LIST = [TOP_NETS, TOP_SUBNETS, TOP_PORTS, TOP_ROUTERS, TOP_ROUTERPORT,
            TOP_SUBNETPOOLS, TOP_SUBNETPOOLPREFIXES, TOP_IPALLOCATIONS,
            TOP_VLANALLOCATIONS, TOP_SEGMENTS, TOP_EXTNETS, TOP_FLOATINGIPS,
            TOP_SGS, TOP_SG_RULES,
            BOTTOM1_NETS, BOTTOM1_SUBNETS, BOTTOM1_PORTS, BOTTOM1_ROUTERS,
            BOTTOM1_SGS, BOTTOM1_FIPS,
            BOTTOM2_NETS, BOTTOM2_SUBNETS, BOTTOM2_PORTS, BOTTOM2_ROUTERS,
            BOTTOM2_SGS, BOTTOM2_FIPS]
RES_MAP = {'networks': TOP_NETS,
           'subnets': TOP_SUBNETS,
           'ports': TOP_PORTS,
           'routers': TOP_ROUTERS,
           'routerports': TOP_ROUTERPORT,
           'ipallocations': TOP_IPALLOCATIONS,
           'subnetpools': TOP_SUBNETPOOLS,
           'subnetpoolprefixes': TOP_SUBNETPOOLPREFIXES,
           'ml2_vlan_allocations': TOP_VLANALLOCATIONS,
           'networksegments': TOP_SEGMENTS,
           'externalnetworks': TOP_EXTNETS,
           'floatingips': TOP_FLOATINGIPS,
           'securitygroups': TOP_SGS,
           'securitygrouprules': TOP_SG_RULES}
SUBNET_INFOS = {}
TEST_TENANT_ID = 'test_tenant_id'


def _fill_external_gateway_info(router):
    if router.gw_port:
        ext_gw_info = {
            'network_id': router.gw_port['network_id'],
            'external_fixed_ips': [
                {'subnet_id': ip["subnet_id"],
                 'ip_address': ip["ip_address"]}
                for ip in router.gw_port['fixed_ips']]}
    else:
        ext_gw_info = None
    router['external_gateway_info'] = ext_gw_info
    return router


def _transform_az(network):
    az_hints_key = 'availability_zone_hints'
    if az_hints_key in network:
        ret = DotDict(network)
        az_str = network[az_hints_key]
        ret[az_hints_key] = jsonutils.loads(az_str) if az_str else []
        return ret
    return network


class FakeIpamSubnet(driver.Subnet):
    def __init__(self, subnet):
        self._subnet = subnet

    def allocate(self, address_request):
        pass

    def deallocate(self, address):
        pass

    def get_details(self):
        return requests.SpecificSubnetRequest(self._subnet['tenant_id'],
                                              self._subnet['id'],
                                              self._subnet['cidr'],
                                              self._subnet['gateway'],
                                              self._subnet['pools'])


class FakePool(driver.Pool):
    def allocate_subnet(self, subnet_request):
        if isinstance(subnet_request, requests.SpecificSubnetRequest):
            subnet_info = {'id': subnet_request.subnet_id,
                           'tenant_id': subnet_request.tenant_id,
                           'cidr': subnet_request.subnet_cidr,
                           'gateway': subnet_request.gateway_ip,
                           'pools': subnet_request.allocation_pools}
            SUBNET_INFOS[subnet_info['id']] = subnet_info
            return FakeIpamSubnet(subnet_info)
        prefix = self._subnetpool.prefixes[0]
        subnet = next(prefix.subnet(subnet_request.prefixlen))
        gateway = subnet.network + 1
        pools = ipam_utils.generate_pools(subnet.cidr,
                                          gateway)
        subnet_info = {'id': subnet_request.subnet_id,
                       'tenant_id': subnet_request.tenant_id,
                       'cidr': subnet.cidr,
                       'gateway': gateway,
                       'pools': pools}
        SUBNET_INFOS[subnet_info['id']] = subnet_info
        return FakeIpamSubnet(subnet_info)

    def get_subnet(self, subnet_id):
        return FakeIpamSubnet(SUBNET_INFOS[subnet_id])

    def get_allocator(self, subnet_ids):
        return driver.SubnetGroup()

    def update_subnet(self, subnet_request):
        return FakeIpamSubnet()

    def remove_subnet(self, subnet_id):
        pass


class DotDict(dict):
    def __init__(self, normal_dict=None):
        if normal_dict:
            for key, value in normal_dict.iteritems():
                self[key] = value

    def __getattr__(self, item):
        return self.get(item)


class DotList(list):
    def all(self):
        return self


class FakeNeutronClient(object):

    _res_map = {'top': {'port': TOP_PORTS},
                'pod_1': {'port': BOTTOM1_PORTS},
                'pod_2': {'port': BOTTOM2_PORTS}}

    def __init__(self, pod_name):
        self.pod_name = pod_name
        self.ports_path = ''

    def _get(self, params=None):
        port_list = self._res_map[self.pod_name]['port']

        if not params:
            return {'ports': port_list}
        if 'marker' in params:
            sorted_list = sorted(port_list, key=lambda x: x['id'])
            for i, port in enumerate(sorted_list):
                if port['id'] == params['marker']:
                    return {'ports': sorted_list[i + 1:]}
        if 'filters' in params:
            return_list = []
            for port in port_list:
                is_selected = True
                for key, value in params['filters'].iteritems():
                    if key not in port or not port[key] or (
                            port[key] not in value):
                        is_selected = False
                        break
                if is_selected:
                    return_list.append(port)
            return {'ports': return_list}
        return {'ports': port_list}

    def get(self, path, params=None):
        if self.pod_name in ['pod_1', 'pod_2', 'top']:
            res_list = self._get(params)['ports']
            return_list = []
            for res in res_list:
                if self.pod_name != 'top':
                    res = copy.copy(res)
                return_list.append(res)
            return {'ports': return_list}
        else:
            raise Exception()


class FakeClient(object):

    _res_map = {'top': RES_MAP,
                'pod_1': {'network': BOTTOM1_NETS,
                          'subnet': BOTTOM1_SUBNETS,
                          'port': BOTTOM1_PORTS,
                          'router': BOTTOM1_ROUTERS,
                          'security_group': BOTTOM1_SGS,
                          'floatingip': BOTTOM1_FIPS},
                'pod_2': {'network': BOTTOM2_NETS,
                          'subnet': BOTTOM2_SUBNETS,
                          'port': BOTTOM2_PORTS,
                          'router': BOTTOM2_ROUTERS,
                          'security_group': BOTTOM2_SGS,
                          'floatingip': BOTTOM2_FIPS}}

    def __init__(self, pod_name):
        if not pod_name:
            self.pod_name = 'top'
        else:
            self.pod_name = pod_name
        self.client = FakeNeutronClient(self.pod_name)

    def get_native_client(self, resource, ctx):
        return self.client

    def _get_connection(self):
        # only for mock purpose
        pass

    def _allocate_ip(self, port_body):
        subnet_list = self._res_map[self.pod_name]['subnet']
        for subnet in subnet_list:
            if subnet['network_id'] == port_body['port']['network_id']:
                cidr = subnet['cidr']
                ip = cidr[:cidr.rindex('.')] + '.5'
                return {'subnet_id': subnet['id'],
                        'ip_address': ip}

    def create_resources(self, _type, ctx, body):
        if _type == 'port':
            res_list = self._res_map[self.pod_name][_type]
            subnet_ips_map = {}
            for res in res_list:
                fixed_ips = res.get('fixed_ips', [])
                for fixed_ip in fixed_ips:
                    if fixed_ip['subnet_id'] not in subnet_ips_map:
                        subnet_ips_map[fixed_ip['subnet_id']] = set()
                    subnet_ips_map[fixed_ip['subnet_id']].add(
                        fixed_ip['ip_address'])
            fixed_ips = body[_type].get('fixed_ips', [])
            for fixed_ip in fixed_ips:
                for subnet in self._res_map[self.pod_name]['subnet']:
                    ip_range = netaddr.IPNetwork(subnet['cidr'])
                    ip = netaddr.IPAddress(fixed_ip['ip_address'])
                    if ip in ip_range:
                        fixed_ip['subnet_id'] = subnet['id']
                        break
                if fixed_ip['ip_address'] in subnet_ips_map.get(
                        fixed_ip['subnet_id'], set()):
                    raise q_exceptions.IpAddressInUseClient()
            if 'device_id' not in body[_type]:
                body[_type]['device_id'] = ''
            if 'fixed_ips' not in body[_type]:
                body[_type]['fixed_ips'] = [self._allocate_ip(body)]
        if _type == 'subnet':
            if 'gateway_ip' not in body[_type]:
                cidr = body[_type]['cidr']
                body[_type]['gateway_ip'] = cidr[:cidr.rindex('.')] + '.1'
        if 'id' not in body[_type]:
            body[_type]['id'] = uuidutils.generate_uuid()
        res_list = self._res_map[self.pod_name][_type]
        res = dict(body[_type])
        res_list.append(res)
        return res

    def list_resources(self, _type, ctx, filters=None):
        if self.pod_name == 'top':
            res_list = self._res_map[self.pod_name][_type + 's']
        else:
            res_list = self._res_map[self.pod_name][_type]
        ret_list = []
        for res in res_list:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if _filter['value'] != res[_filter['key']]:
                    is_selected = False
                    break
            if is_selected:
                ret_list.append(res)
        return ret_list

    def delete_resources(self, _type, ctx, _id):
        index = -1
        if self.pod_name == 'top':
            res_list = self._res_map[self.pod_name][_type + 's']
        else:
            res_list = self._res_map[self.pod_name][_type]
        for i, res in enumerate(res_list):
            if res['id'] == _id:
                index = i
        if index != -1:
            del res_list[index]

    def list_networks(self, ctx, filters=None):
        networks = self.list_resources('network', ctx, filters)
        if self.pod_name != 'top':
            return networks
        ret_list = []
        for network in networks:
            ret_list.append(_transform_az(network))
        return ret_list

    def get_networks(self, ctx, net_id):
        return self.list_networks(ctx, [{'key': 'id',
                                         'comparator': 'eq',
                                         'value': net_id}])[0]

    def delete_networks(self, ctx, net_id):
        self.delete_resources('network', ctx, net_id)

    def list_subnets(self, ctx, filters=None):
        return self.list_resources('subnet', ctx, filters)

    def get_subnets(self, ctx, subnet_id):
        return self.list_resources('subnet', ctx, [{'key': 'id',
                                                    'comparator': 'eq',
                                                    'value': subnet_id}])[0]

    def delete_subnets(self, ctx, subnet_id):
        self.delete_resources('subnet', ctx, subnet_id)

    def update_subnets(self, ctx, subnet_id, body):
        pass

    def create_ports(self, ctx, body):
        return self.create_resources('port', ctx, body)

    def list_ports(self, ctx, filters=None):
        filter_dict = {}
        filters = filters or []
        for query_filter in filters:
            key = query_filter['key']
            value = query_filter['value']
            filter_dict[key] = value
        return self.client.get('', {'filters': filter_dict})['ports']

    def get_ports(self, ctx, port_id):
        return self.client.get(
            '', params={'filters': {'id': [port_id]}})['ports'][0]

    def delete_ports(self, ctx, port_id):
        self.delete_resources('port', ctx, port_id)
        index = -1
        for i, allocation in enumerate(TOP_IPALLOCATIONS):
            if allocation['port_id'] == port_id:
                index = i
                break
        if index != -1:
            del TOP_IPALLOCATIONS[index]

    def add_gateway_routers(self, ctx, *args, **kwargs):
        # only for mock purpose
        pass

    def add_interface_routers(self, ctx, *args, **kwargs):
        self._get_connection()

        router_id, body = args
        if 'port_id' in body:
            for port in self._res_map[self.pod_name]['port']:
                if port['id'] == body['port_id']:
                    port['device_id'] = router_id
                    port['device_owner'] = 'network:router_interface'
        else:
            subnet_id = body['subnet_id']
            subnet = self.get_subnets(ctx, subnet_id)
            self.create_ports(ctx, {'port': {
                'tenant_id': subnet['tenant_id'],
                'admin_state_up': True,
                'id': uuidutils.generate_uuid(),
                'name': '',
                'network_id': subnet['network_id'],
                'fixed_ips': [
                    {'subnet_id': subnet_id,
                     'ip_address': subnet['gateway_ip']}
                ],
                'mac_address': '',
                'device_id': router_id,
                'device_owner': 'network:router_interface'
            }})

    def remove_interface_routers(self, ctx, *args, **kwargs):
        # only for mock purpose
        pass

    def get_routers(self, ctx, router_id):
        router = self.list_resources('router', ctx, [{'key': 'id',
                                                      'comparator': 'eq',
                                                      'value': router_id}])[0]
        return _fill_external_gateway_info(router)

    def delete_routers(self, ctx, router_id):
        self.delete_resources('router', ctx, router_id)

    def action_routers(self, ctx, action, *args, **kwargs):
        # divide into three functions for test purpose
        if action == 'add_interface':
            return self.add_interface_routers(ctx, *args, **kwargs)
        elif action == 'add_gateway':
            return self.add_gateway_routers(ctx, *args, **kwargs)
        elif action == 'remove_interface':
            return self.remove_interface_routers(ctx, *args, **kwargs)

    def create_floatingips(self, ctx, body):
        fip = self.create_resources('floatingip', ctx, body)
        for key in ['fixed_port_id']:
            if key not in fip:
                fip[key] = None
        return fip

    def list_floatingips(self, ctx, filters=None):
        fips = self.list_resources('floatingip', ctx, filters)
        for fip in fips:
            if 'port_id' not in fip:
                fip['port_id'] = None
        return fips

    def update_floatingips(self, ctx, _id, body):
        pass

    def delete_floatingips(self, ctx, _id):
        pass

    def create_security_group_rules(self, ctx, body):
        sg_id = body['security_group_rule']['security_group_id']
        res_list = self._res_map[self.pod_name]['security_group']
        for sg in res_list:
            if sg['id'] == sg_id:
                target_sg = sg
        new_rule = copy.copy(body['security_group_rule'])
        match_found = False
        for rule in target_sg['security_group_rules']:
            old_rule = copy.copy(rule)
            if new_rule == old_rule:
                match_found = True
                break
        if match_found:
            raise q_exceptions.Conflict()
        target_sg['security_group_rules'].append(body['security_group_rule'])

    def delete_security_group_rules(self, ctx, rule_id):
        res_list = self._res_map[self.pod_name]['security_group']
        for sg in res_list:
            for rule in sg['security_group_rules']:
                if rule['id'] == rule_id:
                    sg['security_group_rules'].remove(rule)
                    return

    def get_security_groups(self, ctx, sg_id):
        res_list = self._res_map[self.pod_name]['security_group']
        for sg in res_list:
            if sg['id'] == sg_id:
                # need to do a deep copy because we will traverse the security
                # group's 'security_group_rules' field and make change to the
                # group
                ret_sg = copy.deepcopy(sg)
                return ret_sg


class FakeNeutronContext(object):
    def __init__(self):
        self._session = None
        self.is_admin = True
        self.is_advsvc = False
        self.tenant_id = TEST_TENANT_ID
        self.project_id = TEST_TENANT_ID

    @property
    def session(self):
        if not self._session:
            self._session = FakeSession()
        return self._session

    def elevated(self):
        return self


def delete_model(res_list, model_obj, key=None):
    if not res_list:
        return
    if not key:
        key = 'id'
    if key not in res_list[0]:
        return
    index = -1
    for i, res in enumerate(res_list):
        if res[key] == model_obj[key]:
            index = i
            break
    if index != -1:
        del res_list[index]
        return


def link_models(model_obj, model_dict, foreign_table, foreign_key, table, key,
                link_prop):
    if model_obj.__tablename__ == foreign_table:
        for instance in RES_MAP[table]:
            if instance[key] == model_dict[foreign_key]:
                if link_prop not in instance:
                    instance[link_prop] = []
                instance[link_prop].append(model_dict)


def unlink_models(res_list, model_dict, foreign_key, key, link_prop,
                  link_ele_foreign_key, link_ele_key):
    if foreign_key not in model_dict:
        return
    for instance in res_list:
        if instance[key] == model_dict[foreign_key]:
            if link_prop not in instance:
                return
            index = -1
            for i, res in enumerate(instance[link_prop]):
                if res[link_ele_foreign_key] == model_dict[link_ele_key]:
                    index = i
                    break
            if index != -1:
                del instance[link_prop][index]
                return


def update_floatingip(self, context, _id, floatingip):
    for fip in TOP_FLOATINGIPS:
        if fip['id'] != _id:
            continue
        update_dict = floatingip['floatingip']
        if not floatingip['floatingip']['port_id']:
            update_dict['fixed_port_id'] = None
            update_dict['fixed_ip_address'] = None
            update_dict['router_id'] = None
            fip.update(update_dict)
            return
        for port in TOP_PORTS:
            if port['id'] != floatingip['floatingip']['port_id']:
                continue
            update_dict['fixed_port_id'] = port['id']
            update_dict[
                'fixed_ip_address'] = port['fixed_ips'][0]['ip_address']
            for router_port in TOP_ROUTERPORT:
                for _port in TOP_PORTS:
                    if _port['id'] != router_port['port_id']:
                        continue
                    if _port['network_id'] == port['network_id']:
                        update_dict['router_id'] = router_port['router_id']

        fip.update(update_dict)


class FakeQuery(object):
    def __init__(self, records, table):
        self.records = records
        self.table = table
        self.index = 0

    def _handle_pagination_by_id(self, record_id):
        for i, record in enumerate(self.records):
            if record['id'] == record_id:
                if i + 1 < len(self.records):
                    return FakeQuery(self.records[i + 1:], self.table)
                else:
                    return FakeQuery([], self.table)
        return FakeQuery([], self.table)

    def _handle_filter(self, keys, values):
        filtered_list = []
        for record in self.records:
            selected = True
            for i, key in enumerate(keys):
                if key not in record or record[key] != values[i]:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def filter(self, *criteria):
        _filter = []
        keys = []
        values = []
        for e in criteria:
            if not hasattr(e, 'right') and isinstance(e, elements.False_):
                # filter is a single False value, set key to a 'INVALID_FIELD'
                # then no records will be returned
                keys.append('INVALID_FIELD')
                values.append(False)
            elif not isinstance(e.right, elements.Null):
                _filter.append(e)
            else:
                if e.left.name == 'network_id' and (
                        e.expression.operator.__name__ == 'isnot'):
                    keys.append('router:external')
                    values.append(True)
        if not _filter:
            if not keys:
                return FakeQuery(self.records, self.table)
            else:
                return self._handle_filter(keys, values)
        if hasattr(_filter[0].right, 'value'):
            keys.extend([e.left.name for e in _filter])
            values.extend([e.right.value for e in _filter])
        else:
            keys.extend([e.expression.left.name for e in _filter])
            values.extend(
                [e.expression.right.element.clauses[0].value for e in _filter])
        if _filter[0].expression.operator.__name__ == 'lt':
            return self._handle_pagination_by_id(values[0])
        else:
            return self._handle_filter(keys, values)

    def filter_by(self, **kwargs):
        filtered_list = []
        for record in self.records:
            selected = True
            for key, value in kwargs.iteritems():
                if key not in record or record[key] != value:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def delete(self, synchronize_session=False):
        for model_obj in self.records:
            unlink_models(RES_MAP['routers'], model_obj, 'router_id',
                          'id', 'attached_ports', 'port_id', 'port_id')
            delete_model(RES_MAP[self.table], model_obj, key='port_id')

    def outerjoin(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

    def join(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

    def order_by(self, func):
        self.records.sort(key=lambda x: x['id'])
        return FakeQuery(self.records, self.table)

    def enable_eagerloads(self, value):
        return FakeQuery(self.records, self.table)

    def limit(self, limit):
        return FakeQuery(self.records[:limit], self.table)

    def next(self):
        if self.index >= len(self.records):
            raise StopIteration
        self.index += 1
        return self.records[self.index - 1]

    def one(self):
        if len(self.records) == 0:
            raise exc.NoResultFound()
        return self.records[0]

    def first(self):
        if len(self.records) == 0:
            return None
        else:
            return self.records[0]

    def update(self, values):
        for record in self.records:
            for key, value in values.iteritems():
                record[key] = value
        return len(self.records)

    def all(self):
        return self.records

    def count(self):
        return len(self.records)

    def __iter__(self):
        return self


class FakeSession(object):
    class WithWrapper(object):
        def __enter__(self):
            pass

        def __exit__(self, type, value, traceback):
            pass

    def __init__(self):
        self.info = {}

    def __getattr__(self, field):
        def dummy_method(*args, **kwargs):
            pass

        return dummy_method

    @property
    def is_active(self):
        return True

    def begin(self, subtransactions=False, nested=True):
        return FakeSession.WithWrapper()

    def begin_nested(self):
        return FakeSession.WithWrapper()

    def query(self, model):
        if isinstance(model, attributes.InstrumentedAttribute):
            model = model.class_
        if model.__tablename__ not in RES_MAP:
            return FakeQuery([], model.__tablename__)
        return FakeQuery(RES_MAP[model.__tablename__],
                         model.__tablename__)

    def add(self, model_obj):
        if model_obj.__tablename__ not in RES_MAP:
            return
        model_dict = DotDict(model_obj._as_dict())
        if 'project_id' in model_dict:
            model_dict['tenant_id'] = model_dict['project_id']

        if model_obj.__tablename__ == 'networks':
            model_dict['subnets'] = []
        if model_obj.__tablename__ == 'ports':
            model_dict['dhcp_opts'] = []
            model_dict['security_groups'] = []

        link_models(model_obj, model_dict,
                    'subnetpoolprefixes', 'subnetpool_id',
                    'subnetpools', 'id', 'prefixes')
        link_models(model_obj, model_dict,
                    'ipallocations', 'port_id',
                    'ports', 'id', 'fixed_ips')
        link_models(model_obj, model_dict,
                    'subnets', 'network_id', 'networks', 'id', 'subnets')
        link_models(model_obj, model_dict,
                    'securitygrouprules', 'security_group_id',
                    'securitygroups', 'id', 'security_group_rules')

        if model_obj.__tablename__ == 'routerports':
            for port in TOP_PORTS:
                if port['id'] == model_dict['port_id']:
                    model_dict['port'] = port
                    port.update(model_dict)
                    break
        if model_obj.__tablename__ == 'externalnetworks':
            for net in TOP_NETS:
                if net['id'] == model_dict['network_id']:
                    net['external'] = True
                    net['router:external'] = True
                    break
        link_models(model_obj, model_dict,
                    'routerports', 'router_id',
                    'routers', 'id', 'attached_ports')

        RES_MAP[model_obj.__tablename__].append(model_dict)

    def _cascade_delete(self, model_dict, foreign_key, table, key):
        if key not in model_dict:
            return
        index = -1
        for i, instance in enumerate(RES_MAP[table]):
            if instance[foreign_key] == model_dict[key]:
                index = i
                break
        if index != -1:
            del RES_MAP[table][index]

    def delete(self, model_obj):
        unlink_models(RES_MAP['routers'], model_obj, 'router_id', 'id',
                      'attached_ports', 'port_id', 'id')
        self._cascade_delete(model_obj, 'port_id', 'ipallocations', 'id')
        for res_list in RES_MAP.values():
            delete_model(res_list, model_obj)


class FakeXManager(xmanager.XManager):
    def __init__(self, fake_plugin):
        self.clients = {constants.TOP: client.Client()}
        self.job_handles = {
            constants.JT_ROUTER: self.configure_extra_routes,
            constants.JT_ROUTER_SETUP: self.setup_bottom_router,
            constants.JT_PORT_DELETE: self.delete_server_port}
        self.helper = FakeHelper(fake_plugin)
        self.xjob_handler = FakeBaseRPCAPI()

    def _get_client(self, pod_name=None):
        return FakeClient(pod_name)


class FakeBaseRPCAPI(object):
    def configure_extra_routes(self, ctxt, router_id):
        pass


class FakeRPCAPI(FakeBaseRPCAPI):
    def __init__(self, fake_plugin):
        self.xmanager = FakeXManager(fake_plugin)

    def setup_bottom_router(self, ctxt, net_id, router_id, pod_id):
        combine_id = '%s#%s#%s' % (pod_id, router_id, net_id)
        self.xmanager.setup_bottom_router(
            ctxt, payload={constants.JT_ROUTER_SETUP: combine_id})


class FakeExtension(object):
    def __init__(self, ext_obj):
        self.obj = ext_obj


class FakeHelper(helper.NetworkHelper):
    def _get_client(self, pod_name=None):
        return FakeClient(pod_name)

    def _prepare_top_element_by_call(self, t_ctx, q_ctx,
                                     project_id, pod, ele, _type, body):
        if not q_ctx:
            q_ctx = FakeNeutronContext()
        return super(FakeHelper, self)._prepare_top_element_by_call(
            t_ctx, q_ctx, project_id, pod, ele, _type, body)

    def _get_top_element(self, t_ctx, q_ctx, _type, _id):
        if not q_ctx:
            q_ctx = FakeNeutronContext()
        return super(FakeHelper, self)._get_top_element(
            t_ctx, q_ctx, _type, _id)


class FakeTypeManager(managers.TricircleTypeManager):
    def _register_types(self):
        local_driver = type_local.LocalTypeDriver()
        self.drivers[constants.NT_LOCAL] = FakeExtension(local_driver)
        vlan_driver = type_shared_vlan.SharedVLANTypeDriver()
        self.drivers[constants.NT_SHARED_VLAN] = FakeExtension(vlan_driver)

    def extend_network_dict_provider(self, cxt, net):
        target_net = None
        for t_net in TOP_NETS:
            if t_net['id'] == net['id']:
                target_net = t_net
        if not target_net:
            return
        for segment in TOP_SEGMENTS:
            if target_net['id'] == segment['network_id']:
                target_net['provider:network_type'] = segment['network_type']
                target_net[
                    'provider:physical_network'] = segment['physical_network']
                target_net[
                    'provider:segmentation_id'] = segment['segmentation_id']
                break


class FakePlugin(plugin.TricirclePlugin):
    def __init__(self):
        self.set_ipam_backend()
        self.helper = FakeHelper(self)
        self.xjob_handler = FakeRPCAPI(self)
        self.type_manager = FakeTypeManager()

    def _get_client(self, pod_name):
        return FakeClient(pod_name)

    def _make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
        network = _transform_az(network)
        if 'project_id' in network:
            network['tenant_id'] = network['project_id']
        return network

    def _make_subnet_dict(self, subnet, fields=None, context=None):
        return subnet

    def _make_port_dict(self, port, fields=None, process_extensions=True):
        if port.get('fixed_ips'):
            if isinstance(port['fixed_ips'][0], dict):
                return port
            else:
                for i, fixed_ip in enumerate(port['fixed_ips']):
                    port['fixed_ips'][i] = {
                        'subnet_id': fixed_ip['subnet_id'],
                        'ip_address': fixed_ip['ip_address']}
        for allocation in TOP_IPALLOCATIONS:
            if allocation['port_id'] == port['id']:
                ret = {}
                for key, value in port.iteritems():
                    if key == 'fixed_ips':
                        ret[key] = [{'subnet_id': allocation['subnet_id'],
                                     'ip_address': allocation['ip_address']}]
                    else:
                        ret[key] = value
                if 'project_id' in ret:
                    ret['tenant_id'] = ret['project_id']
                return ret
        if 'project_id' in port:
            port['tenant_id'] = port['project_id']
        return port

    def _make_security_group_dict(self, security_group, fields=None):
        return security_group


def fake_get_context_from_neutron_context(q_context):
    return context.get_db_context()


def fake_get_client(self, pod_name):
    return FakeClient(pod_name)


def fake_make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
    return network


def fake_make_subnet_dict(self, subnet, fields=None, context=None):
    return subnet


def fake_make_router_dict(self, router, fields=None, process_extensions=True):
    return _fill_external_gateway_info(router)


def fake_generate_ip(subnet):
    suffix = 1
    for allocation in TOP_IPALLOCATIONS:
        if allocation['subnet_id'] == subnet['id']:
            ip = allocation['ip_address']
            current_suffix = int(ip[ip.rindex('.') + 1:])
            if current_suffix >= suffix:
                suffix = current_suffix
    suffix += 1
    cidr = subnet['cidr']
    new_ip = cidr[:cidr.rindex('.') + 1] + ('%d' % suffix)
    return {'ip_address': new_ip, 'subnet_id': subnet['id']}


def fake_allocate_ips_for_port(self, context, port):
    if 'fixed_ips' in port['port'] and (
            port['port'][
                'fixed_ips'] is not q_constants.ATTR_NOT_SPECIFIED):
        return port['port']['fixed_ips']
    for subnet in TOP_SUBNETS:
        if subnet['network_id'] == port['port']['network_id']:
            return [fake_generate_ip(subnet)]


@classmethod
def fake_get_instance(cls, subnet_pool, context):
    return FakePool(subnet_pool, context)


class PluginTest(unittest.TestCase,
                 test_security_groups.TricircleSecurityGroupTestMixin):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        cfg.CONF.register_opts(q_config.core_opts)
        plugin_path = 'tricircle.tests.unit.network.test_plugin.FakePlugin'
        cfg.CONF.set_override('core_plugin', plugin_path)
        self.context = context.Context()
        self.save_method = manager.NeutronManager._get_default_service_plugins
        manager.NeutronManager._get_default_service_plugins = mock.Mock()
        manager.NeutronManager._get_default_service_plugins.return_value = []
        xmanager.IN_TEST = True

        phynet = 'bridge'
        vlan_min = 2000
        vlan_max = 2001
        cfg.CONF.set_override('type_drivers', ['local', 'shared_vlan'],
                              group='tricircle')
        cfg.CONF.set_override('tenant_network_types', ['local', 'shared_vlan'],
                              group='tricircle')
        cfg.CONF.set_override('network_vlan_ranges',
                              ['%s:%d:%d' % (phynet, vlan_min, vlan_max)],
                              group='tricircle')
        cfg.CONF.set_override('bridge_network_type', 'shared_vlan',
                              group='tricircle')
        for vlan in (vlan_min, vlan_max):
            TOP_VLANALLOCATIONS.append(
                DotDict({'physical_network': phynet,
                         'vlan_id': vlan, 'allocated': False}))

    def _basic_pod_route_setup(self):
        pod1 = {'pod_id': 'pod_id_1',
                'pod_name': 'pod_1',
                'az_name': 'az_name_1'}
        pod2 = {'pod_id': 'pod_id_2',
                'pod_name': 'pod_2',
                'az_name': 'az_name_2'}
        pod3 = {'pod_id': 'pod_id_0',
                'pod_name': 'top_pod',
                'az_name': ''}
        for pod in (pod1, pod2, pod3):
            db_api.create_pod(self.context, pod)
        route1 = {
            'top_id': 'top_id_1',
            'pod_id': 'pod_id_1',
            'bottom_id': 'bottom_id_1',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_id_2',
            'pod_id': 'pod_id_2',
            'bottom_id': 'bottom_id_2',
            'resource_type': 'port'}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, route1)
            core.create_resource(self.context, models.ResourceRouting, route2)

    def _basic_port_setup(self):
        TOP_PORTS.extend([{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [models_v2.IPAllocation(
                               port_id='top_id_0', ip_address='10.0.0.1',
                               subnet_id='top_subnet_id',
                               network_id='top_net_id')]},
                          {'id': 'top_id_1', 'name': 'top'},
                          {'id': 'top_id_2', 'name': 'top'},
                          {'id': 'top_id_3', 'name': 'top'}])
        BOTTOM1_PORTS.append({'id': 'bottom_id_1', 'name': 'bottom'})
        BOTTOM2_PORTS.append({'id': 'bottom_id_2', 'name': 'bottom'})

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port')
    def test_get_port(self, mock_plugin_method):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        fake_plugin.get_port(neutron_context, 'top_id_0')
        port1 = fake_plugin.get_port(neutron_context, 'top_id_1')
        port2 = fake_plugin.get_port(neutron_context, 'top_id_2')
        fake_plugin.get_port(neutron_context, 'top_id_3')

        self.assertEqual({'id': 'top_id_1', 'name': 'bottom'}, port1)
        self.assertEqual({'id': 'top_id_2', 'name': 'bottom'}, port2)
        calls = [mock.call(neutron_context, 'top_id_0', None),
                 mock.call(neutron_context, 'top_id_3', None)]
        mock_plugin_method.assert_has_calls(calls)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_pagination(self):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context, limit=1)
        ports2 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports1[-1]['id'])
        ports3 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports2[-1]['id'])
        ports4 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports3[-1]['id'])
        ports = []
        expected_ports = [{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [{'subnet_id': 'top_subnet_id',
                                          'ip_address': '10.0.0.1'}]},
                          {'id': 'top_id_1', 'name': 'bottom'},
                          {'id': 'top_id_2', 'name': 'bottom'},
                          {'id': 'top_id_3', 'name': 'top'}]
        for _ports in (ports1, ports2, ports3, ports4):
            ports.extend(_ports)
        self.assertItemsEqual(expected_ports, ports)

        ports = fake_plugin.get_ports(neutron_context)
        self.assertItemsEqual(expected_ports, ports)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_filters(self):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_0']})
        ports2 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_1']})
        ports3 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_4']})
        self.assertEqual([{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [{'subnet_id': 'top_subnet_id',
                                          'ip_address': '10.0.0.1'}]}], ports1)
        self.assertEqual([{'id': 'top_id_1', 'name': 'bottom'}], ports2)
        self.assertEqual([], ports3)

        TOP_ROUTERS.append({'id': 'router_id'})
        b_routers_list = [BOTTOM1_ROUTERS, BOTTOM2_ROUTERS]
        b_ports_list = [BOTTOM1_PORTS, BOTTOM2_PORTS]
        for i in xrange(1, 3):
            router_id = 'router_%d_id' % i
            b_routers_list[i - 1].append({'id': router_id})
            route = {
                'top_id': 'router_id',
                'pod_id': 'pod_id_%d' % i,
                'bottom_id': router_id,
                'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context,
                                     models.ResourceRouting, route)
            # find port and add device_id
            for port in b_ports_list[i - 1]:
                port_id = 'bottom_id_%d' % i
                if port['id'] == port_id:
                    port['device_id'] = router_id
        ports = fake_plugin.get_ports(neutron_context,
                                      filters={'device_id': ['router_id']})
        expected = [{'id': 'top_id_1', 'name': 'bottom',
                     'device_id': 'router_id'},
                    {'id': 'top_id_2', 'name': 'bottom',
                     'device_id': 'router_id'}]
        self.assertItemsEqual(expected, ports)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'delete_port')
    @patch.object(FakeClient, 'delete_ports')
    def test_delete_port(self, mock_client_method, mock_plugin_method,
                         mock_context_method):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context_method.return_value = tricircle_context

        fake_plugin.delete_port(neutron_context, 'top_id_0')
        fake_plugin.delete_port(neutron_context, 'top_id_1')

        calls = [mock.call(neutron_context, 'top_id_0'),
                 mock.call(neutron_context, 'top_id_1')]
        mock_plugin_method.assert_has_calls(calls)
        mock_client_method.assert_called_once_with(tricircle_context,
                                                   'bottom_id_1')

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'update_network')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'create_network')
    def test_network_az(self, mock_create, mock_update, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        network = {'network': {
            'id': 'net_id', 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'availability_zone_hints': ['az_name_1', 'az_name_2']}}
        mock_create.return_value = {'id': 'net_id', 'name': 'net_az'}
        mock_update.return_value = network['network']
        fake_plugin.create_network(neutron_context, network)
        mock_update.assert_called_once_with(
            neutron_context, 'net_id',
            {'network': {
                'availability_zone_hints': '["az_name_1", "az_name_2"]'}})

        err_network = {'network': {
            'id': 'net_id', 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'availability_zone_hints': ['az_name_1', 'az_name_3']}}
        mock_create.return_value = {'id': 'net_id', 'name': 'net_az'}
        self.assertRaises(az_ext.AvailabilityZoneNotFound,
                          fake_plugin.create_network,
                          neutron_context, err_network)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        network = {'network': {
            'id': 'net_id', 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': ['az_name_1', 'az_name_2']}}
        fake_plugin.create_network(neutron_context, network)

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_element(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        for pod in db_api.list_pods(t_ctx):
            if not pod['az_name']:
                t_pod = pod
            else:
                b_pod = pod

        # test _prepare_top_element
        pool_id = fake_plugin._get_bridge_subnet_pool_id(
            t_ctx, q_ctx, 'project_id', t_pod, True)
        net, subnet = fake_plugin._get_bridge_network_subnet(
            t_ctx, q_ctx, 'project_id', t_pod, pool_id, True)
        port = fake_plugin._get_bridge_interface(t_ctx, q_ctx, 'project_id',
                                                 pod, net['id'], 'b_router_id',
                                                 None, True)

        top_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': 'pod_id_0'}], []):
                top_entry_map[entry['resource_type']] = entry
        self.assertEqual(net['id'], subnet['network_id'])
        self.assertEqual(net['id'], port['network_id'])
        self.assertEqual(subnet['id'], port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(top_entry_map['network']['bottom_id'], net['id'])
        self.assertEqual(top_entry_map['subnet']['bottom_id'], subnet['id'])
        self.assertEqual(top_entry_map['port']['bottom_id'], port['id'])

        # test _prepare_bottom_element
        _, b_port_id, _, _ = fake_plugin._get_bottom_bridge_elements(
            q_ctx, 'project_id', b_pod, net, False, subnet, port)
        b_port = fake_plugin._get_client(b_pod['pod_name']).get_ports(
            t_ctx, b_port_id)

        bottom_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': b_pod['pod_id']}], []):
                bottom_entry_map[entry['resource_type']] = entry
        self.assertEqual(bottom_entry_map['network']['top_id'], net['id'])
        self.assertEqual(bottom_entry_map['network']['bottom_id'],
                         b_port['network_id'])
        self.assertEqual(bottom_entry_map['subnet']['top_id'], subnet['id'])
        self.assertEqual(bottom_entry_map['subnet']['bottom_id'],
                         b_port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(bottom_entry_map['port']['top_id'], port['id'])
        self.assertEqual(bottom_entry_map['port']['bottom_id'], b_port_id)

    @staticmethod
    def _prepare_router_test(tenant_id, ctx, pod_name, index):
        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        b_net_id = uuidutils.generate_uuid()
        b_subnet_id = uuidutils.generate_uuid()

        # no need to specify az, we will setup router in the pod where bottom
        # network is created
        t_net = {
            'id': t_net_id,
            'name': 'top_net_%d' % index,
            'tenant_id': tenant_id
        }
        t_subnet = {
            'id': t_subnet_id,
            'network_id': t_net_id,
            'name': 'top_subnet_%d' % index,
            'ip_version': 4,
            'cidr': '10.0.%d.0/24' % index,
            'allocation_pools': [],
            'enable_dhcp': True,
            'gateway_ip': '10.0.%d.1' % index,
            'ipv6_address_mode': '',
            'ipv6_ra_mode': '',
            'tenant_id': tenant_id
        }
        TOP_NETS.append(DotDict(t_net))
        TOP_SUBNETS.append(DotDict(t_subnet))
        subnet_info = {'id': t_subnet['id'],
                       'tenant_id': t_subnet['tenant_id'],
                       'cidr': t_subnet['cidr'],
                       'gateway': t_subnet['gateway_ip'],
                       'pools': t_subnet['allocation_pools']}
        SUBNET_INFOS[subnet_info['id']] = subnet_info

        b_net = {
            'id': b_net_id,
            'name': t_net_id,
            'tenant_id': tenant_id
        }
        b_subnet = {
            'id': b_subnet_id,
            'network_id': b_net_id,
            'name': b_subnet_id,
            'ip_version': 4,
            'cidr': '10.0.%d.0/24' % index,
            'allocation_pools': [],
            'enable_dhcp': True,
            'gateway_ip': '10.0.%d.1' % index,
            'ipv6_address_mode': '',
            'ipv6_ra_mode': '',
            'tenant_id': tenant_id
        }
        if pod_name == 'pod_1':
            BOTTOM1_NETS.append(DotDict(b_net))
            BOTTOM1_SUBNETS.append(DotDict(b_subnet))
        else:
            BOTTOM2_NETS.append(DotDict(b_net))
            BOTTOM2_SUBNETS.append(DotDict(b_subnet))

        pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_net_id,
                              'bottom_id': b_net_id,
                              'pod_id': pod_id,
                              'project_id': tenant_id,
                              'resource_type': constants.RT_NETWORK})
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_subnet_id,
                              'bottom_id': b_subnet_id,
                              'pod_id': pod_id,
                              'project_id': tenant_id,
                              'resource_type': constants.RT_SUBNET})

        if len(TOP_ROUTERS) == 0:
            t_router_id = uuidutils.generate_uuid()
            t_router = {
                'id': t_router_id,
                'name': 'top_router',
                'distributed': False,
                'tenant_id': tenant_id,
                'attached_ports': DotList()
            }
            TOP_ROUTERS.append(DotDict(t_router))
        else:
            t_router_id = TOP_ROUTERS[0]['id']

        return t_net_id, t_subnet_id, t_router_id, b_net_id, b_subnet_id

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_subnet_clean(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = 'test_tenant_id'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        port_num = len(TOP_PORTS)
        pre_created_port_num = 0
        for port in TOP_PORTS:
            if port.get('name').startswith('dhcp_port_'):
                pre_created_port_num += 1
            elif port.get('name').startswith('interface_'):
                pre_created_port_num += 1
            elif port.get('device_owner') == 'network:router_interface':
                pre_created_port_num += 1

        fake_plugin.remove_router_interface(
            q_ctx, t_router_id, {'port_id': t_port_id})
        fake_plugin.delete_subnet(q_ctx, t_subnet_id)

        # check pre-created ports are all deleted
        self.assertEqual(port_num - pre_created_port_num, len(TOP_PORTS))

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeBaseRPCAPI, 'configure_extra_routes')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface(self, mock_context, mock_rpc):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, 'router')[0]

        mock_rpc.assert_called_once_with(t_ctx, t_router_id)
        for b_net in BOTTOM1_NETS:
            if 'provider:segmentation_id' in b_net:
                self.assertIn(b_net['provider:segmentation_id'], (2000, 2001))
        # only one VLAN allocated, for E-W bridge network
        allocations = [
            allocation['allocated'] for allocation in TOP_VLANALLOCATIONS]
        self.assertItemsEqual([True, False], allocations)
        for segment in TOP_SEGMENTS:
            self.assertIn(segment['segmentation_id'], (2000, 2001))

        bridge_port_name = constants.ew_bridge_port_name % (tenant_id,
                                                            b_router_id)
        _, t_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port_name, 'port')[0]
        _, b_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_id, 'port')[0]

        (t_net_id, t_subnet_id, t_router_id,
         b_another_net_id, b_another_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 2)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        t_ns_bridge_net_id = None
        for net in TOP_NETS:
            if net['name'].startswith('ns_bridge'):
                t_ns_bridge_net_id = net['id']
        # N-S bridge not created since no extenal network created
        self.assertIsNone(t_ns_bridge_net_id)

        device_ids = ['', '', '']
        for port in BOTTOM1_PORTS:
            if port['id'] == b_bridge_port_id:
                device_ids[0] = port['device_id']
            elif port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[1] = port['device_id']
            elif port['network_id'] == b_another_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[2] = port['device_id']

        self.assertEqual(device_ids, [b_router_id, b_router_id, b_router_id])

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeBaseRPCAPI, 'configure_extra_routes')
    @patch.object(FakeClient, 'add_gateway_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_with_external_network(self, mock_context,
                                                 mock_action, mock_rpc):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        e_net_id = uuidutils.generate_uuid()
        e_net = {'id': e_net_id,
                 'name': 'ext-net',
                 'admin_state_up': True,
                 'shared': False,
                 'tenant_id': tenant_id,
                 'router:external': True,
                 'availability_zone_hints': '["pod_2"]'}
        TOP_NETS.append(e_net)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        b_router_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_router_id, 'pod_1', 'router')

        mock_rpc.assert_called_once_with(t_ctx, t_router_id)
        for b_net in BOTTOM1_NETS:
            if 'provider:segmentation_id' in b_net:
                self.assertIn(b_net['provider:segmentation_id'], (2000, 2001))
        # two VLANs allocated, for E-W and N-S bridge network
        allocations = [
            allocation['allocated'] for allocation in TOP_VLANALLOCATIONS]
        self.assertItemsEqual([True, True], allocations)
        for segment in TOP_SEGMENTS:
            self.assertIn(segment['segmentation_id'], (2000, 2001))

        bridge_port_name = constants.ew_bridge_port_name % (tenant_id,
                                                            b_router_id)
        _, t_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port_name, 'port')[0]
        _, b_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_id, 'port')[0]

        (t_net_id, t_subnet_id, t_router_id,
         b_another_net_id, b_another_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 2)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        for net in TOP_NETS:
            if net['name'].startswith('ns_bridge'):
                t_ns_bridge_net_id = net['id']
        for subnet in TOP_SUBNETS:
            if subnet['name'].startswith('ns_bridge'):
                t_ns_bridge_subnet_id = subnet['id']
        b_ns_bridge_net_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_ns_bridge_net_id, 'pod_1', constants.RT_NETWORK)
        b_ns_bridge_subnet_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_ns_bridge_subnet_id, 'pod_1', constants.RT_SUBNET)
        # internal network and external network are in different pods, need
        # to create N-S bridge network and set gateway, add_router_interface
        # is called two times, so add_gateway is also called two times.
        # add_interface is called three times because the second time
        # add_router_interface is called, bottom router is already attached
        # to E-W bridge network, only need to attach internal network to
        # bottom router
        calls = [mock.call(t_ctx, b_router_id,
                           {'network_id': b_ns_bridge_net_id,
                            'external_fixed_ips': [
                                {'subnet_id': b_ns_bridge_subnet_id,
                                 'ip_address': '100.128.0.2'}]}),
                 mock.call(t_ctx, b_router_id,
                           {'network_id': b_ns_bridge_net_id,
                            'external_fixed_ips': [
                                {'subnet_id': b_ns_bridge_subnet_id,
                                 'ip_address': '100.128.0.2'}]})]
        mock_action.assert_has_calls(calls)

        device_ids = ['', '', '']
        for port in BOTTOM1_PORTS:
            if port['id'] == b_bridge_port_id:
                device_ids[0] = port['device_id']
            elif port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[1] = port['device_id']
            elif port['network_id'] == b_another_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[2] = port['device_id']
        self.assertEqual(device_ids, [b_router_id, b_router_id, b_router_id])

        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_2', 2)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        b_router_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_router_id, 'pod_2', 'router')
        bridge_port_name = constants.ew_bridge_port_name % (tenant_id,
                                                            b_router_id)
        _, t_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port_name, 'port')[0]
        _, b_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_id, 'port')[0]
        # internal network and external network are in the same pod, no need
        # to create N-S bridge network when attaching router interface(N-S
        # bridge network is created when setting router external gateway), so
        # add_gateway is not called.
        device_ids = ['', '']
        for port in BOTTOM2_PORTS:
            if port['id'] == b_bridge_port_id:
                device_ids[0] = port['device_id']
            elif port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[1] = port['device_id']
        self.assertEqual(device_ids, [b_router_id, b_router_id])

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            entry_num = len(entries)

        mock_action.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        self.assertEqual(0, len(TOP_ROUTERS[0]['attached_ports']))

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # two new entries, for top and bottom bridge ports
            self.assertEqual(entry_num + 2, len(entries))
        # top and bottom interface is deleted, only bridge port left
        self.assertEqual(1, len(TOP_PORTS))
        self.assertEqual(1, len(BOTTOM1_PORTS))

        mock_action.side_effect = None
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id})
        # bottom dhcp port and bridge port
        self.assertEqual(2, len(BOTTOM1_PORTS))
        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # three more entries, for top and bottom dhcp ports, top interface
            self.assertEqual(entry_num + 2 + 3, len(entries))

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, '_get_connection')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception_port_left(self, mock_context,
                                               mock_connect):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        mock_connect.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        # top interface is removed
        self.assertEqual(0, len(TOP_ROUTERS[0]['attached_ports']))

        mock_connect.side_effect = None
        # test that we can success when bottom pod comes back
        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        # bottom dhcp port, bottom interface and bridge port
        self.assertEqual(3, len(BOTTOM1_PORTS))

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeBaseRPCAPI, 'configure_extra_routes')
    @patch.object(FakeClient, 'remove_interface_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_interface(self, mock_context, mock_remove, mock_rpc):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        for port in BOTTOM1_PORTS:
            if port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                b_interface_id = port['id']

        fake_plugin.remove_router_interface(
            q_ctx, t_router_id, {'port_id': t_port_id})

        mock_remove.assert_called_with(
            t_ctx, b_router_id, {'port_id': b_interface_id})
        mock_rpc.assert_called_with(t_ctx, t_router_id)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_external_network_no_az_pod(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        # create external network without specifying az pod name
        body = {
            'network': {
                'name': 'ext-net',
                'admin_state_up': True,
                'shared': True,
                'tenant_id': TEST_TENANT_ID,
                'router:external': True,
            }
        }

        top_net = fake_plugin.create_network(q_ctx, body)
        for net in BOTTOM1_NETS:
            if net.get('router:external'):
                bottom_net = net
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, top_net['id'], constants.RT_NETWORK)
        self.assertEqual(mappings[0][1], bottom_net['id'])

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_external_network(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        # create external network specifying az name
        body = {
            'network': {
                'router:external': True,
                'tenant_id': TEST_TENANT_ID,
                'availability_zone_hints': ['az_name_1']
            }
        }
        self.assertRaises(exceptions.PodNotFound,
                          fake_plugin.create_network, q_ctx, body)
        body = {
            'network': {
                'name': 'ext-net',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': TEST_TENANT_ID,
                'router:external': True,
                'availability_zone_hints': ['pod_1']
            }
        }
        top_net = fake_plugin.create_network(q_ctx, body)
        for net in BOTTOM1_NETS:
            if net.get('router:external'):
                bottom_net = net
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, top_net['id'], constants.RT_NETWORK)
        self.assertEqual(mappings[0][1], bottom_net['id'])

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_set_gateway(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        t_net_body = {
            'name': 'ext_net',
            'availability_zone_hints': ['pod_1'],
            'tenant_id': tenant_id,
            'router:external': True,
            'admin_state_up': True,
            'shared': False,
        }
        fake_plugin.create_network(q_ctx, {'network': t_net_body})
        t_net_id = TOP_NETS[0]['id']

        t_subnet_body = {
            'network_id': t_net_id,  # only one network created
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        fake_plugin.create_subnet(q_ctx, {'subnet': t_subnet_body})
        t_subnet_id = TOP_SUBNETS[0]['id']

        t_router_id = uuidutils.generate_uuid()
        t_router = {
            'id': t_router_id,
            'name': 'router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': DotList()
        }

        TOP_ROUTERS.append(DotDict(t_router))
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': TOP_NETS[0]['id'],
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': TOP_SUBNETS[0]['id'],
                                        'ip_address': '100.64.0.5'}]}}})

        b_router_id = BOTTOM1_ROUTERS[0]['id']
        b_net_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_net_id, 'pod_1', constants.RT_NETWORK)
        b_subnet_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_subnet_id, 'pod_1', constants.RT_SUBNET)

        for subnet in TOP_SUBNETS:
            if subnet['name'].startswith('ns_bridge_subnet'):
                t_ns_bridge_subnet_id = subnet['id']
        b_ns_bridge_subnet_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, t_ns_bridge_subnet_id, 'pod_1', constants.RT_SUBNET)
        body = {'network_id': b_net_id,
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': b_subnet_id,
                                        'ip_address': '100.64.0.5'}]}
        calls = [mock.call(t_ctx, 'add_gateway', b_router_id, body),
                 mock.call(t_ctx, 'add_interface', b_router_id,
                           {'subnet_id': b_ns_bridge_subnet_id})]
        mock_action.assert_has_calls(calls)

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_unset_gateway(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        t_net_body = {
            'name': 'ext_net',
            'availability_zone_hints': ['pod_1'],
            'tenant_id': tenant_id,
            'router:external': True,
            'admin_state_up': True,
            'shared': False,
        }
        fake_plugin.create_network(q_ctx, {'network': t_net_body})
        t_net_id = TOP_NETS[0]['id']

        t_subnet_body = {
            'network_id': t_net_id,  # only one network created
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        fake_plugin.create_subnet(q_ctx, {'subnet': t_subnet_body})
        t_subnet_id = TOP_SUBNETS[0]['id']

        t_router_id = uuidutils.generate_uuid()
        t_router = {
            'id': t_router_id,
            'name': 'router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': DotList()
        }

        TOP_ROUTERS.append(DotDict(t_router))
        # first add router gateway
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': t_net_id,
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': t_subnet_id,
                                        'ip_address': '100.64.0.5'}]}}})
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        # then remove router gateway
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {}}})
        mock_action.assert_called_with(t_ctx, 'remove_gateway', b_router_id)

    def _prepare_associate_floatingip_test(self, t_ctx, q_ctx, fake_plugin):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        net_body = {
            'name': 'ext_net',
            'admin_state_up': True,
            'shared': False,
            'tenant_id': tenant_id,
            'router:external': True,
            'availability_zone_hints': ['pod_2']
        }
        e_net = fake_plugin.create_network(q_ctx, {'network': net_body})
        subnet_body = {
            'network_id': e_net['id'],
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [{'start': '100.64.0.2',
                                  'end': '100.64.0.254'}],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        e_subnet = fake_plugin.create_subnet(q_ctx, {'subnet': subnet_body})
        # set external gateway
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': e_net['id'],
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': e_subnet['id'],
                                        'ip_address': '100.64.0.5'}]}}})
        # create floating ip
        fip_body = {'floating_network_id': e_net['id'],
                    'tenant_id': tenant_id}
        fip = fake_plugin.create_floatingip(q_ctx, {'floatingip': fip_body})
        # add router interface
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id})
        # create internal port
        t_port_id = uuidutils.generate_uuid()
        b_port_id = uuidutils.generate_uuid()
        t_port = {
            'id': t_port_id,
            'network_id': t_net_id,
            'mac_address': 'fa:16:3e:96:41:03',
            'fixed_ips': [{'subnet_id': t_subnet_id,
                          'ip_address': '10.0.0.4'}]
        }
        b_port = {
            'id': b_port_id,
            'name': t_port_id,
            'network_id': db_api.get_bottom_id_by_top_id_pod_name(
                t_ctx, t_net_id, 'pod_1', constants.RT_NETWORK),
            'mac_address': 'fa:16:3e:96:41:03',
            'fixed_ips': [
                {'subnet_id': db_api.get_bottom_id_by_top_id_pod_name(
                    t_ctx, t_subnet_id, 'pod_1', constants.RT_SUBNET),
                 'ip_address': '10.0.0.4'}]
        }
        TOP_PORTS.append(t_port)
        BOTTOM1_PORTS.append(b_port)
        route = {'top_id': t_port_id,
                 'pod_id': 'pod_id_1',
                 'bottom_id': b_port_id,
                 'resource_type': constants.RT_PORT}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        return t_port_id, b_port_id, fip, e_net

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'create_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_associate_floatingip(self, mock_context, mock_create):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)

        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        b_ext_net_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, e_net['id'], 'pod_2', constants.RT_NETWORK)
        for port in BOTTOM2_PORTS:
            if port['name'] == 'ns_bridge_port':
                ns_bridge_port = port
        for net in TOP_NETS:
            if net['name'].startswith('ns_bridge'):
                b_bridge_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                    t_ctx, net['id'], 'pod_1', constants.RT_NETWORK)
        calls = [mock.call(t_ctx,
                           {'floatingip': {
                               'floating_network_id': b_ext_net_id,
                               'floating_ip_address': fip[
                                   'floating_ip_address'],
                               'port_id': ns_bridge_port['id']}}),
                 mock.call(t_ctx,
                           {'floatingip': {
                               'floating_network_id': b_bridge_net_id,
                               'floating_ip_address': '100.128.0.3',
                               'port_id': b_port_id}})]
        mock_create.assert_has_calls(calls)

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakePlugin, '_rollback_floatingip_data')
    @patch.object(FakeRPCAPI, 'setup_bottom_router')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_associate_floatingip_port_exception(
            self, mock_context, mock_setup, mock_rollback):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)

        # associate floating ip and exception occurs
        # actually we will not get this exception when calling
        # setup_bottom_router, we set this exception for test purpose
        mock_setup.side_effect = q_exceptions.ConnectionFailed
        fip_body = {'port_id': t_port_id}
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.update_floatingip, q_ctx, fip['id'],
                          {'floatingip': fip_body})
        data = {'fixed_port_id': None,
                'fixed_ip_address': None,
                'router_id': None}
        mock_rollback.assert_called_once_with(q_ctx, fip['id'], data)

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'delete_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_disassociate_floatingip(self, mock_context, mock_delete):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)

        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        bridge_port_name = constants.ns_bridge_port_name % (
            e_net['tenant_id'], None, b_port_id)
        t_pod = db_api.get_top_pod(t_ctx)
        mapping = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, bridge_port_name, t_pod['pod_name'], constants.RT_PORT)
        # check routing for bridge port in top pod exists
        self.assertIsNotNone(mapping)

        # disassociate floating ip
        fip_body = {'port_id': None}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        fip_id1 = BOTTOM1_FIPS[0]['id']
        fip_id2 = BOTTOM2_FIPS[0]['id']

        calls = [mock.call(t_ctx, fip_id1),
                 mock.call(t_ctx, fip_id2)]
        mock_delete.assert_has_calls(calls)
        mapping = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, bridge_port_name, t_pod['pod_name'], constants.RT_PORT)
        # check routing for bridge port in top pod is deleted
        self.assertIsNone(mapping)

        # check the association information is cleared
        self.assertIsNone(TOP_FLOATINGIPS[0]['fixed_port_id'])
        self.assertIsNone(TOP_FLOATINGIPS[0]['fixed_ip_address'])
        self.assertIsNone(TOP_FLOATINGIPS[0]['router_id'])

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'delete_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_floatingip(self, mock_context, mock_delete):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)
        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        bridge_port_name = constants.ns_bridge_port_name % (
            e_net['tenant_id'], None, b_port_id)
        t_pod = db_api.get_top_pod(t_ctx)
        mapping = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, bridge_port_name, t_pod['pod_name'], constants.RT_PORT)
        # check routing for bridge port in top pod exists
        self.assertIsNotNone(mapping)

        fake_plugin.delete_floatingip(q_ctx, fip['id'])

        fip_id1 = BOTTOM1_FIPS[0]['id']
        fip_id2 = BOTTOM2_FIPS[0]['id']

        calls = [mock.call(t_ctx, fip_id1),
                 mock.call(t_ctx, fip_id2)]
        mock_delete.assert_has_calls(calls)
        mapping = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, bridge_port_name, t_pod['pod_name'], constants.RT_PORT)
        # check routing for bridge port in top pod is deleted
        self.assertIsNone(mapping)

    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_router(self, mock_context):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        t_ctx.project_id = 'test_tenant_id'
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)
        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})
        # disassociate floating ip
        fip_body = {'port_id': None}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        t_router_id = TOP_ROUTERS[0]['id']
        for port in TOP_PORTS:
            if port['id'] == t_port_id:
                t_subnet_id = port['fixed_ips'][0]['subnet_id']
        fake_plugin.remove_router_interface(q_ctx, t_router_id,
                                            {'subnet_id': t_subnet_id})
        fake_plugin.update_router(q_ctx, t_router_id,
                                  {'router': {'external_gateway_info': {}}})

        top_res_sets = [TOP_NETS, TOP_SUBNETS, TOP_PORTS]
        top_res_nums = [len(top_res_set) for top_res_set in top_res_sets]
        top_pre_created_res_nums = [0, 0, 0]
        for i, top_res_set in enumerate(top_res_sets):
            for top_res in top_res_set:
                if top_res.get('name', '').find('bridge') != -1:
                    top_pre_created_res_nums[i] += 1
        fake_plugin.delete_router(q_ctx, t_router_id)

        # check pre-created networks, subnets and ports are all deleted
        for i, top_res_set in enumerate(top_res_sets):
            self.assertEqual(top_res_nums[i] - top_pre_created_res_nums[i],
                             len(top_res_set))

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_security_group_rule(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_create_security_group_rule(fake_plugin, q_ctx, t_ctx,
                                              'pod_id_1', TOP_SGS, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_security_group_rule(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_delete_security_group_rule(fake_plugin, q_ctx, t_ctx,
                                              'pod_id_1', TOP_SGS,
                                              TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_handle_remote_group_invalid_input(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_handle_remote_group_invalid_input(fake_plugin, q_ctx, t_ctx,
                                                     'pod_id_1', TOP_SGS,
                                                     TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_handle_default_sg_invalid_input(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_handle_default_sg_invalid_input(fake_plugin, q_ctx, t_ctx,
                                                   'pod_id_1', TOP_SGS,
                                                   TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(FakeClient, 'create_security_group_rules')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_security_group_rule_exception(self, mock_context,
                                                  mock_create):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        mock_create.side_effect = q_exceptions.ConnectionFailed

        self._test_create_security_group_rule_exception(
            fake_plugin, q_ctx, t_ctx, 'pod_id_1', TOP_SGS, BOTTOM1_SGS)

    @patch.object(FakeClient, 'delete_security_group_rules')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_security_group_rule_exception(self, mock_context,
                                                  mock_delete):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        mock_delete.side_effect = q_exceptions.ConnectionFailed

        self._test_delete_security_group_rule_exception(
            fake_plugin, q_ctx, t_ctx, 'pod_id_1', TOP_SGS, TOP_SG_RULES,
            BOTTOM1_SGS)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
        cfg.CONF.unregister_opts(q_config.core_opts)
        xmanager.IN_TEST = False
