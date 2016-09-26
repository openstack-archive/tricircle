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
import datetime
import mock
from mock import patch
import pecan
import unittest

import neutronclient.common.exceptions as q_exceptions
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.common import context

from tricircle.common import exceptions as t_exceptions
from tricircle.common import lock_handle
from tricircle.common.scheduler import filter_scheduler
from tricircle.common import xrpcapi
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import helper
from tricircle.nova_apigw.controllers import server


TOP_NETS = []
TOP_SUBNETS = []
TOP_PORTS = []
TOP_SGS = []
BOTTOM1_NETS = []
BOTTOM1_SUBNETS = []
BOTTOM1_PORTS = []
BOTTOM1_SGS = []
BOTTOM2_NETS = []
BOTTOM2_SUBNETS = []
BOTTOM2_PORTS = []
BOTTOM2_SGS = []

BOTTOM_NETS = BOTTOM1_NETS
BOTTOM_SUBNETS = BOTTOM1_SUBNETS
BOTTOM_PORTS = BOTTOM1_PORTS
BOTTOM_SGS = BOTTOM1_SGS
BOTTOM_SERVERS = []

RES_LIST = [TOP_NETS, TOP_SUBNETS, TOP_PORTS, TOP_SGS, BOTTOM_SERVERS,
            BOTTOM1_NETS, BOTTOM1_SUBNETS, BOTTOM1_PORTS, BOTTOM1_SGS,
            BOTTOM2_NETS, BOTTOM2_SUBNETS, BOTTOM2_PORTS, BOTTOM2_SGS]


def _get_ip_suffix():
    # four elements are enough currently
    suffix_list = ['3', '4', '5', '6']
    index = 0
    while True:
        yield suffix_list[index]
        index += 1
        index %= 4

ip_suffix = _get_ip_suffix()


class FakeException(Exception):
    pass


class FakeResponse(object):
    pass


class FakeServerController(server.ServerController):
    def __init__(self, project_id):
        self.clients = {'t_region': FakeClient('t_region')}
        self.project_id = project_id
        self.helper = FakeHelper()
        self.xjob_handler = xrpcapi.XJobAPI()
        self.filter_scheduler = filter_scheduler.FilterScheduler()

    def _get_client(self, pod_name=None):
        if not pod_name:
            return self.clients['t_region']
        else:
            if pod_name not in self.clients:
                self.clients[pod_name] = FakeClient(pod_name)
        return self.clients[pod_name]


class FakeHelper(helper.NetworkHelper):
    def _get_client(self, pod_name=None):
        return FakeClient(pod_name)


class FakeClient(object):

    _res_map = {'top': {'network': TOP_NETS,
                        'subnet': TOP_SUBNETS,
                        'port': TOP_PORTS,
                        'security_group': TOP_SGS},
                'bottom': {'network': BOTTOM_NETS,
                           'subnet': BOTTOM_SUBNETS,
                           'port': BOTTOM_PORTS,
                           'security_group': BOTTOM_SGS,
                           'server': BOTTOM_SERVERS},
                'bottom2': {'network': BOTTOM2_NETS,
                            'subnet': BOTTOM2_SUBNETS,
                            'port': BOTTOM2_PORTS,
                            'security_group': BOTTOM2_SGS}}

    def __init__(self, pod_name):
        if not pod_name:
            pod_name = 't_region'
        self.pod_name = pod_name

    def _get_res_list(self, _type):
        if self.pod_name == 'b_region_2':
            pod = 'bottom2'
        elif self.pod_name == 't_region':
            pod = 'top'
        else:
            pod = 'bottom'
        return self._res_map[pod][_type]

    def _check_port_ip_conflict(self, subnet_id, ip):
        port_list = self._get_res_list('port')
        for port in port_list:
            if 'fixed_ips' in port:
                if port['fixed_ips'][0]['ip_address'] == ip and (
                    port['fixed_ips'][0]['subnet_id'] == subnet_id
                ):
                    raise FakeException()

    def create_resources(self, _type, ctx, body):
        if 'id' not in body[_type]:
            body[_type]['id'] = uuidutils.generate_uuid()
        if _type == 'port' and 'fixed_ips' not in body[_type]:
            net_id = body['port']['network_id']
            subnets = self._get_res_list('subnet')
            fixed_ip_list = []
            for subnet in subnets:
                if subnet['network_id'] == net_id:
                    cidr = subnet['cidr']
                    ip_prefix = cidr[:cidr.rindex('.') + 1]
                    mac_prefix = 'fa:16:3e:96:41:0'
                    if body['port'].get('device_owner') == 'network:dhcp':
                        ip = ip_prefix + '2'
                        body['port']['mac_address'] = mac_prefix + '2'
                    else:
                        suffix = ip_suffix.next()
                        ip = ip_prefix + suffix
                        body['port']['mac_address'] = mac_prefix + suffix
                    fixed_ip_list.append({'ip_address': ip,
                                          'subnet_id': subnet['id']})
            body['port']['fixed_ips'] = fixed_ip_list
        if _type == 'port' and 'fixed_ips' in body[_type]:
            ip_dict = body[_type]['fixed_ips'][0]
            self._check_port_ip_conflict(ip_dict['subnet_id'],
                                         ip_dict['ip_address'])
        if _type == 'security_group':
            body[_type]['security_group_rules'] = [
                {'remote_group_id': None,
                 'direction': 'egress',
                 'remote_ip_prefix': None,
                 'protocol': None,
                 'port_range_max': None,
                 'port_range_min': None,
                 'ethertype': 'IPv4',
                 'id': uuidutils.generate_uuid()},
                {'remote_group_id': None,
                 'direction': 'egress',
                 'remote_ip_prefix': None,
                 'protocol': None,
                 'port_range_max': None,
                 'port_range_min': None,
                 'ethertype': 'IPv6',
                 'id': uuidutils.generate_uuid()},
            ]
        res_list = self._get_res_list(_type)
        res = dict(body[_type])
        res_list.append(res)
        return res

    def list_resources(self, _type, ctx, filters):
        res_list = self._get_res_list(_type)
        ret_list = []
        for res in res_list:
            match = True
            for filter in filters:
                if filter['key'] not in res:
                    match = False
                    break
                if res[filter['key']] != filter['value']:
                    match = False
                    break
            if match:
                ret_list.append(res)
        return ret_list

    def create_ports(self, ctx, body):
        return self.create_resources('port', ctx, body)

    def list_ports(self, ctx, filters):
        return self.list_resources('port', ctx, filters)

    def list_security_groups(self, ctx, filters):
        return self.list_resources('security_group', ctx, filters)

    def delete_ports(self, ctx, port_id):
        port_list = self._get_res_list('port')
        for i, port in enumerate(port_list):
            if port['id'] == port_id:
                break
        port_list.pop(i)

    def get_networks(self, ctx, network_id):
        return self.list_resources(
            'network', ctx,
            [{'key': 'id', 'comparator': 'eq', 'value': network_id}])[0]

    def list_subnets(self, ctx, filters):
        return self.list_resources('subnet', ctx, filters)

    def get_subnets(self, ctx, subnet_id):
        return self.list_resources(
            'subnet', ctx,
            [{'key': 'id', 'comparator': 'eq', 'value': subnet_id}])[0]

    def update_subnets(self, ctx, subnet_id, body):
        subnet = self.get_subnets(ctx, subnet_id)
        for key, value in body['subnet'].iteritems():
            subnet[key] = value

    def get_ports(self, ctx, port_id):
        return self.list_resources(
            'port', ctx,
            [{'key': 'id', 'comparator': 'eq', 'value': port_id}])[0]

    def create_servers(self, ctx, **body):
        body['id'] = uuidutils.generate_uuid()
        BOTTOM_SERVERS.append(body)
        return body

    def list_servers(self, ctx, filters):
        ret_servers = []
        for b_server in self.list_resources('server', ctx, filters):
            ret_server = copy.deepcopy(b_server)
            for nic in ret_server['nics']:
                ports = self.list_ports(
                    ctx, [{'key': 'id', 'comparator': 'eq',
                           'value': nic['port-id']}])
                nets = self.list_resources(
                    'network', ctx, [{'key': 'id', 'comparator': 'eq',
                                      'value': ports[0]['network_id']}])
                ret_server['addresses'] = {
                    nets[0]['name']: [
                        {'OS-EXT-IPS-MAC:mac_addr': ports[0]['mac_address'],
                         'version': 4,
                         'addr': ports[0]['fixed_ips'][0]['ip_address'],
                         'OS-EXT-IPS:type': 'fixed'}]}
            ret_servers.append(ret_server)
        return ret_servers

    def get_servers(self, ctx, server_id):
        return self.list_servers(
            ctx, [{'key': 'id', 'comparator': 'eq', 'value': server_id}])[0]

    def get_security_groups(self, ctx, sg_id):
        sg = self.list_resources(
            'security_group', ctx,
            [{'key': 'id', 'comparator': 'eq', 'value': sg_id}])[0]
        # need to do a deep copy because we will traverse the security group's
        # 'security_group_rules' field and make change to the group
        ret_sg = copy.deepcopy(sg)
        return ret_sg

    def create_security_group_rules(self, ctx, body):
        for _rule in body['security_group_rules']:
            sg_id = _rule['security_group_id']
            sg = self.list_resources(
                'security_group', ctx,
                [{'key': 'id', 'comparator': 'eq', 'value': sg_id}])[0]
            new_rule = copy.copy(_rule)
            match_found = False
            for rule in sg['security_group_rules']:
                old_rule = copy.copy(rule)
                if new_rule == old_rule:
                    match_found = True
                    break
            if match_found:
                raise q_exceptions.Conflict()
            sg['security_group_rules'].append(new_rule)

    def delete_security_group_rules(self, ctx, rule_id):
        res_list = self._get_res_list('security_group')
        for sg in res_list:
            for rule in sg['security_group_rules']:
                if rule['id'] == rule_id:
                    sg['security_group_rules'].remove(rule)
                    return

    def delete_servers(self, ctx, _id):
        pass


class ServerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_project'
        self.controller = FakeServerController(self.project_id)

    def _prepare_pod(self, bottom_pod_num=1):
        t_pod = {'pod_id': 't_pod_uuid', 'pod_name': 't_region',
                 'az_name': ''}
        api.create_pod(self.context, t_pod)
        if bottom_pod_num == 1:
            b_pod = {'pod_id': 'b_pod_uuid', 'pod_name': 'b_region',
                     'az_name': 'b_az'}
            api.create_pod(self.context, b_pod)
            return t_pod, b_pod
        b_pods = []
        for i in xrange(1, bottom_pod_num + 1):
            b_pod = {'pod_id': 'b_pod_%d_uuid' % i,
                     'pod_name': 'b_region_%d' % i,
                     'az_name': 'b_az_%d' % i}
            api.create_pod(self.context, b_pod)
            b_pods.append(b_pod)
        return t_pod, b_pods

    def _validate_error_code(self, res, code):
        self.assertEqual(code, res[res.keys()[0]]['code'])

    def test_get_or_create_route(self):
        t_pod, b_pod = self._prepare_pod()
        route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertTrue(is_own)
        self.assertEqual('test_top_id', route['top_id'])
        self.assertIsNone(route['bottom_id'])
        self.assertEqual('port', route['resource_type'])
        self.assertEqual(self.project_id, route['project_id'])

    def test_get_or_create_route_conflict(self):
        t_pod, b_pod = self._prepare_pod()
        self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        route, status = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertEqual(lock_handle.NONE_DONE, status)
        self.assertIsNone(route)

    def test_get_or_create_route_conflict_expire(self):
        t_pod, b_pod = self._prepare_pod()
        route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        # manually set update time to expire the routing entry
        with self.context.session.begin():
            update_time = route['created_at'] - datetime.timedelta(0, 60)
            core.update_resource(self.context, models.ResourceRouting,
                                 route['id'], {'updated_at': update_time})
        new_route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertTrue(is_own)
        self.assertEqual('test_top_id', new_route['top_id'])
        self.assertIsNone(new_route['bottom_id'])
        self.assertEqual('port', new_route['resource_type'])
        self.assertEqual(self.project_id, new_route['project_id'])

    def test_get_or_create_route_conflict_expire_has_bottom_res(self):
        t_pod, b_pod = self._prepare_pod()
        route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        # manually set update time to expire the routing entry
        with self.context.session.begin():
            update_time = route['created_at'] - datetime.timedelta(0, 60)
            core.update_resource(self.context, models.ResourceRouting,
                                 route['id'], {'updated_at': update_time})
        # insert a fake bottom port
        BOTTOM_PORTS.append({'id': 'test_bottom_id', 'name': 'test_top_id'})
        new_route, status = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertEqual(lock_handle.RES_DONE, status)
        self.assertEqual('test_top_id', new_route['top_id'])
        self.assertEqual('test_bottom_id', new_route['bottom_id'])
        self.assertEqual('port', new_route['resource_type'])
        self.assertEqual(self.project_id, new_route['project_id'])

    def test_prepare_neutron_element(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id'}
        body = {'network': {'name': 'top_net_id'}}
        is_new, bottom_port_id = self.controller.helper.prepare_bottom_element(
            self.context, self.project_id, b_pod, net, 'network', body)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_net_id', 'network')
        self.assertEqual(bottom_port_id, mappings[0][1])

    @patch.object(FakeClient, 'create_resources')
    def test_prepare_neutron_element_create_res_exception(self, mock_method):
        mock_method.side_effect = FakeException()
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id'}
        body = {'network': {'name': 'top_net_id'}}
        self.assertRaises(FakeException,
                          self.controller.helper.prepare_bottom_element,
                          self.context, self.project_id, b_pod, net,
                          'network', body)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_net_id', 'network')
        self.assertEqual(0, len(mappings))

    def _check_routes(self, b_pod):
        for res in (TOP_NETS, TOP_SUBNETS, BOTTOM_NETS, BOTTOM_SUBNETS):
            self.assertEqual(1, len(res))
        enable_dhcp = TOP_SUBNETS[0]['enable_dhcp']
        self.assertEqual(enable_dhcp, BOTTOM_SUBNETS[0]['enable_dhcp'])
        # top vm port, top interface port, top dhcp port
        t_port_num = 3 if enable_dhcp else 2
        # bottom vm port, bottom dhcp port
        b_port_num = 2 if enable_dhcp else 1
        self.assertEqual(t_port_num, len(TOP_PORTS))
        self.assertEqual(b_port_num, len(BOTTOM_PORTS))

        with self.context.session.begin():
            routes = core.query_resource(self.context,
                                         models.ResourceRouting, [], [])
        # bottom network, bottom subnet, bottom port, no top dhcp and bottom
        # dhcp if dhcp disabled
        entry_num = 6 if enable_dhcp else 4
        self.assertEqual(entry_num, len(routes))
        actual = [[], [], [], []]
        actual[3].append(constants.interface_port_name % (
            b_pod['pod_id'], TOP_SUBNETS[0]['id']))
        if entry_num > 4:
            actual.extend([[], []])
            actual[5].append(constants.dhcp_port_name % TOP_SUBNETS[0]['id'])

        for region in ('t_region', 'b_region'):
            actual[0].append(self.controller._get_client(
                region).list_resources('network', self.context, [])[0]['id'])
            actual[1].append(self.controller._get_client(
                region).list_resources('subnet', self.context, [])[0]['id'])
            ports = self.controller._get_client(
                region).list_resources('port', self.context, [])

            for port in ports:
                if port.get('device_id'):
                    dhcp_port_id = port['id']
                elif port.get('device_owner'):
                    gateway_port_id = port['id']
                else:
                    vm_port_id = port['id']

            actual[2].append(vm_port_id)
            if region == 't_region':
                actual[3].append(gateway_port_id)
            if entry_num > 4:
                actual[4].append(dhcp_port_id)
                if region == 't_region':
                    actual[5].append(dhcp_port_id)

        expect = [[route['top_id'], route['bottom_id']] for route in routes]
        self.assertItemsEqual(expect, actual)

    def test_handle_network(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id', 'name': 'net'}
        subnet = {'id': 'top_subnet_id',
                  'network_id': 'top_net_id',
                  'ip_version': 4,
                  'cidr': '10.0.0.0/24',
                  'gateway_ip': '10.0.0.1',
                  'allocation_pools': [{'start': '10.0.0.2',
                                        'end': '10.0.0.254'}],
                  'enable_dhcp': True}
        TOP_NETS.append(net)
        TOP_SUBNETS.append(subnet)
        self.controller._handle_network(self.context, b_pod, net, [subnet])
        self._check_routes(b_pod)

    def test_handle_network_dhcp_disable(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id', 'name': 'net'}
        subnet = {'id': 'top_subnet_id',
                  'network_id': 'top_net_id',
                  'ip_version': 4,
                  'cidr': '10.0.0.0/24',
                  'gateway_ip': '10.0.0.1',
                  'allocation_pools': [{'start': '10.0.0.2',
                                        'end': '10.0.0.254'}],
                  'enable_dhcp': False}
        TOP_NETS.append(net)
        TOP_SUBNETS.append(subnet)
        self.controller._handle_network(self.context, b_pod, net, [subnet])
        self._check_routes(b_pod)

    def test_handle_port(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id', 'name': 'net'}
        subnet = {'id': 'top_subnet_id',
                  'network_id': 'top_net_id',
                  'ip_version': 4,
                  'cidr': '10.0.0.0/24',
                  'gateway_ip': '10.0.0.1',
                  'allocation_pools': [{'start': '10.0.0.2',
                                        'end': '10.0.0.254'}],
                  'enable_dhcp': True}
        port = {
            'id': 'top_port_id',
            'network_id': 'top_net_id',
            'mac_address': 'fa:16:3e:96:41:07',
            'fixed_ips': [{'subnet_id': 'top_subnet_id',
                          'ip_address': '10.0.0.7'}]
        }
        TOP_NETS.append(net)
        TOP_SUBNETS.append(subnet)
        TOP_PORTS.append(port)
        self.controller._handle_port(self.context, b_pod, port)
        self._check_routes(b_pod)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_with_network_az(self, mock_ctx, mock_create):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'
        t_net = {'id': top_net_id, 'name': 'net'}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': [{'start': '10.0.0.2',
                                          'end': '10.0.0.254'}],
                    'enable_dhcp': True}
        t_sg = {'id': top_sg_id, 'name': 'default', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': top_sg_id,
                     'direction': 'ingress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_SGS.append(t_sg)

        server_name = 'test_server'
        image_id = 'image_id'
        flavor_id = 1
        body = {
            'server': {
                'name': server_name,
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod['az_name'],
                'networks': [{'uuid': top_net_id}]
            }
        }
        mock_create.return_value = {'id': 'bottom_server_id'}
        mock_ctx.return_value = self.context

        # update top net for test purpose, correct az
        TOP_NETS[0]['availability_zone_hints'] = ['b_az']
        self.controller.post(**body)

        # update top net for test purpose, wrong az
        TOP_NETS[0]['availability_zone_hints'] = ['fake_az']
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_ctx, mock_create):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'

        t_net = {'id': top_net_id, 'name': 'net'}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': [{'start': '10.0.0.2',
                                          'end': '10.0.0.254'}],
                    'enable_dhcp': True}
        t_sg = {'id': top_sg_id, 'name': 'default', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': top_sg_id,
                     'direction': 'ingress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_SGS.append(t_sg)

        server_name = 'test_server'
        image_id = 'image_id'
        flavor_id = 1
        body = {
            'server': {
                'name': server_name,
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod['az_name'],
                'networks': [{'uuid': top_net_id}]
            }
        }
        mock_create.return_value = {'id': 'bottom_server_id'}
        mock_ctx.return_value = self.context

        server_dict = self.controller.post(**body)['server']

        for port in BOTTOM_PORTS:
            if 'device_id' not in port:
                bottom_port_id = port['id']
        for sg in BOTTOM_SGS:
            if sg['name'] == top_sg_id:
                bottom_sg = sg

        mock_create.assert_called_with(self.context, name=server_name,
                                       image=image_id, flavor=flavor_id,
                                       nics=[{'port-id': bottom_port_id}],
                                       security_groups=[bottom_sg['id']])
        # make sure remote group is extended to ip addresses
        for rule in bottom_sg['security_group_rules']:
            if rule['ethertype'] == 'IPv4' and rule['direction'] == 'ingress':
                self.assertIsNone(rule['remote_group_id'])
                self.assertEqual('10.0.0.0/24', rule['remote_ip_prefix'])

        with self.context.session.begin():
            routes = core.query_resource(self.context, models.ResourceRouting,
                                         [{'key': 'resource_type',
                                           'comparator': 'eq',
                                           'value': 'server'}], [])
            self.assertEqual(1, len(routes))
            self.assertEqual(server_dict['id'], routes[0]['top_id'])
            self.assertEqual(server_dict['id'], routes[0]['bottom_id'])
            self.assertEqual(b_pod['pod_id'], routes[0]['pod_id'])
            self.assertEqual(self.project_id, routes[0]['project_id'])

            # make sure security group mapping is built
            routes = core.query_resource(self.context, models.ResourceRouting,
                                         [{'key': 'resource_type',
                                           'comparator': 'eq',
                                           'value': 'security_group'}], [])
            self.assertEqual(1, len(routes))
            self.assertEqual(top_sg_id, routes[0]['top_id'])
            self.assertEqual(bottom_sg['id'], routes[0]['bottom_id'])
            self.assertEqual(b_pod['pod_id'], routes[0]['pod_id'])
            self.assertEqual(self.project_id, routes[0]['project_id'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_exception_retry(self, mock_ctx, mock_server):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'

        t_net = {'id': top_net_id, 'name': 'net'}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': [{'start': '10.0.0.2',
                                          'end': '10.0.0.254'}],
                    'enable_dhcp': True}
        t_sg = {'id': top_sg_id, 'name': 'test_sg', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': None,
                     'direction': 'ingress',
                     'remote_ip_prefix': '10.0.1.0/24',
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_SGS.append(t_sg)

        server_name = 'test_server'
        image_id = 'image_id'
        flavor_id = 1
        body = {
            'server': {
                'name': server_name,
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod['az_name'],
                'networks': [{'uuid': top_net_id}],
                'security_groups': [{'name': 'test_sg'}]
            }
        }
        mock_server.return_value = {'id': 'bottom_server_id'}
        mock_ctx.return_value = self.context

        create_security_group_rules = FakeClient.create_security_group_rules
        FakeClient.create_security_group_rules = mock.Mock()
        FakeClient.create_security_group_rules.side_effect = \
            q_exceptions.ConnectionFailed

        self.assertRaises(q_exceptions.ConnectionFailed, self.controller.post,
                          **body)
        with self.context.session.begin():
            routes = core.query_resource(
                self.context, models.ResourceRouting,
                [{'key': 'top_sg_id', 'comparator': 'eq',
                  'value': t_sg['id']},
                 {'key': 'pod_id', 'comparator': 'eq',
                  'value': 'b_pod_uuid'}], [])
            self.assertIsNone(routes[0]['bottom_id'])

        # test we can redo after exception
        FakeClient.create_security_group_rules = create_security_group_rules
        self.controller.post(**body)

        for port in BOTTOM_PORTS:
            if 'device_id' not in port:
                bottom_port_id = port['id']
        for sg in BOTTOM_SGS:
            if sg['name'] == top_sg_id:
                bottom_sg = sg

        mock_server.assert_called_with(self.context, name=server_name,
                                       image=image_id, flavor=flavor_id,
                                       nics=[{'port-id': bottom_port_id}],
                                       security_groups=[bottom_sg['id']])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_across_pods(self, mock_ctx, mock_create):
        t_pod, b_pods = self._prepare_pod(2)
        b_pod1, b_pod2 = b_pods
        top_net1_id = 'top_net1_id'
        top_subnet1_id = 'top_subnet1_id'
        top_net2_id = 'top_net2_id'
        top_subnet2_id = 'top_subnet2_id'
        top_sg_id = 'top_sg_id'

        t_net1 = {'id': top_net1_id, 'name': 'net1'}
        t_subnet1 = {'id': top_subnet1_id,
                     'tenant_id': self.project_id,
                     'network_id': top_net1_id,
                     'ip_version': 4,
                     'cidr': '10.0.1.0/24',
                     'gateway_ip': '10.0.1.1',
                     'allocation_pools': [{'start': '10.0.1.2',
                                           'end': '10.0.1.254'}],
                     'enable_dhcp': True}
        t_net2 = {'id': top_net2_id, 'name': 'net2'}
        t_subnet2 = {'id': top_subnet2_id,
                     'tenant_id': self.project_id,
                     'network_id': top_net2_id,
                     'ip_version': 4,
                     'cidr': '10.0.2.0/24',
                     'gateway_ip': '10.0.2.1',
                     'allocation_pools': [{'start': '10.0.2.2',
                                           'end': '10.0.2.254'}],
                     'enable_dhcp': True}
        t_sg = {'id': top_sg_id, 'name': 'default', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': top_sg_id,
                     'direction': 'ingress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net1)
        TOP_SUBNETS.append(t_subnet1)
        TOP_NETS.append(t_net2)
        TOP_SUBNETS.append(t_subnet2)
        TOP_SGS.append(t_sg)

        image_id = 'image_id'
        flavor_id = 1
        mock_ctx.return_value = self.context

        body = {
            'server': {
                'name': 'test_server1',
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod1['az_name'],
                'networks': [{'uuid': top_net1_id}]
            }
        }
        mock_create.return_value = {'id': 'bottom_server1_id'}
        self.controller.post(**body)['server']

        body = {
            'server': {
                'name': 'test_server2',
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod2['az_name'],
                'networks': [{'uuid': top_net2_id}]
            }
        }
        mock_create.return_value = {'id': 'bottom_server2_id'}
        self.controller.post(**body)['server']

        for port in BOTTOM1_PORTS:
            if 'device_id' not in port:
                bottom_port1_id = port['id']
        for port in BOTTOM2_PORTS:
            if 'device_id' not in port:
                bottom_port2_id = port['id']
        for sg in BOTTOM1_SGS:
            if sg['name'] == top_sg_id:
                bottom_sg1 = sg
        for sg in BOTTOM2_SGS:
            if sg['name'] == top_sg_id:
                bottom_sg2 = sg

        calls = [mock.call(self.context, name='test_server1', image=image_id,
                           flavor=flavor_id,
                           nics=[{'port-id': bottom_port1_id}],
                           security_groups=[bottom_sg1['id']]),
                 mock.call(self.context, name='test_server2', image=image_id,
                           flavor=flavor_id,
                           nics=[{'port-id': bottom_port2_id}],
                           security_groups=[bottom_sg2['id']])]
        mock_create.assert_has_calls(calls)

        # make sure remote group is extended to ip addresses
        expected_ips = ['10.0.1.0/24', '10.0.2.0/24']
        ips = []
        for rule in bottom_sg1['security_group_rules']:
            if rule['ethertype'] == 'IPv4' and rule['direction'] == 'ingress':
                self.assertIsNone(rule['remote_group_id'])
                ips.append(rule['remote_ip_prefix'])
        self.assertEqual(expected_ips, ips)
        ips = []
        for rule in bottom_sg2['security_group_rules']:
            if rule['ethertype'] == 'IPv4' and rule['direction'] == 'ingress':
                self.assertIsNone(rule['remote_group_id'])
                ips.append(rule['remote_ip_prefix'])
        self.assertEqual(expected_ips, ips)

    @patch.object(xrpcapi.XJobAPI, 'delete_server_port')
    @patch.object(FakeClient, 'delete_servers')
    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_delete(self, mock_ctx, mock_delete, mock_delete_port):
        t_pod, b_pod = self._prepare_pod()
        mock_ctx.return_value = self.context
        t_server_id = 't_server_id'
        b_server_id = 'b_server_id'

        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})

        port_id = uuidutils.generate_uuid()
        server_port = {
            'id': port_id,
            'device_id': t_server_id
        }
        TOP_PORTS.append(server_port)

        mock_delete.return_value = ()
        res = self.controller.delete(t_server_id)
        mock_delete_port.assert_called_once_with(self.context, port_id)
        mock_delete.assert_called_once_with(self.context, b_server_id)
        self.assertEqual(204, res.status)

    @patch.object(FakeClient, 'delete_servers')
    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_delete_error(self, mock_ctx, mock_delete):
        t_pod, b_pod = self._prepare_pod()
        mock_ctx.return_value = self.context

        # pass invalid id
        res = self.controller.delete('fake_id')
        self.assertEqual('Server not found', res['Error']['message'])
        self.assertEqual(404, res['Error']['code'])

        t_server_id = 't_server_id'
        b_server_id = 'b_server_id'

        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})
        mock_delete.return_value = None
        # pass stale server id
        res = self.controller.delete(t_server_id)
        self.assertEqual('Server not found', res['Error']['message'])
        self.assertEqual(404, res['Error']['code'])
        routes = core.query_resource(
            self.context, models.ResourceRouting,
            [{'key': 'top_id', 'comparator': 'eq', 'value': t_server_id}], [])
        # check the stale mapping is deleted
        self.assertEqual(0, len(routes))

        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})

        # exception occurs when deleting server
        mock_delete.side_effect = t_exceptions.PodNotFound('pod2')
        res = self.controller.delete(t_server_id)
        self.assertEqual('Pod pod2 could not be found.',
                         res['Error']['message'])
        self.assertEqual(404, res['Error']['code'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(xrpcapi.XJobAPI, 'setup_bottom_router')
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_l3_involved(self, mock_ctx, mock_create, mock_setup):
        t_pod, b_pod = self._prepare_pod(1)

        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_port_id = 'top_port_id'
        top_sg_id = 'top_sg_id'
        top_router_id = 'top_router_id'

        t_net = {'id': top_net_id, 'name': 'net'}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': [{'start': '10.0.0.2',
                                          'end': '10.0.0.254'}],
                    'enable_dhcp': True}
        t_port = {'id': top_port_id,
                  'network_id': top_net_id,
                  'device_id': top_router_id,
                  'device_owner': 'network:router_interface',
                  'fixed_ips': [{'subnet_id': top_subnet_id,
                                 'ip_address': '10.0.0.1'}],
                  'mac_address': 'fa:16:3e:96:41:03'}
        t_sg = {'id': top_sg_id, 'name': 'default', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': top_sg_id,
                     'direction': 'ingress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_PORTS.append(t_port)
        TOP_SGS.append(t_sg)

        server_name = 'test_server'
        image_id = 'image_id'
        flavor_id = 1
        body = {
            'server': {
                'name': server_name,
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod['az_name'],
                'networks': [{'port': top_port_id}]
            }
        }
        mock_create.return_value = {'id': 'bottom_server_id'}
        mock_ctx.return_value = self.context

        self.controller.post(**body)['server']
        mock_setup.assert_called_with(self.context, top_net_id, top_router_id,
                                      b_pod['pod_id'])

    @patch.object(pecan, 'response', new=FakeResponse)
    def test_process_injected_file_quota(self):
        ctx = self.context.elevated()

        def _update_default_quota(num1, len1, len2):
            self.default_quota = dict(
                injected_files=num1, injected_file_path_bytes=len1,
                injected_file_content_bytes=len2)
            for k, v in self.default_quota.items():
                api.quota_class_create(ctx, 'default', k, v)

        injected_files = [
            {
                "path": "/etc/banner.txt",
                "contents": "foo foo",
            },

            {
                "path": "/etc/canner.txt",
                "contents": "goo goo",
            },
        ]

        t_server_dict = {'injected_files': injected_files}

        max_path = 0
        max_content = 0
        for path, content in injected_files:
            max_path = max(max_path, len(path))
            max_content = max(max_content, len(content))

        _update_default_quota(len(injected_files) - 1,
                              max_path + 1,
                              max_content + 1)
        self.assertRaises(t_exceptions.OnsetFileLimitExceeded,
                          self.controller._check_injected_file_quota,
                          ctx, injected_files)

        res = self.controller._process_injected_file_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        _update_default_quota(len(injected_files),
                              max_path + 1,
                              max_content + 1)
        self.controller._check_injected_file_quota(ctx, injected_files)

        _update_default_quota(len(injected_files) + 1,
                              max_path - 1,
                              max_content + 1)
        self.assertRaises(t_exceptions.OnsetFilePathLimitExceeded,
                          self.controller._check_injected_file_quota,
                          ctx, injected_files)

        res = self.controller._process_injected_file_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        _update_default_quota(len(injected_files) + 1,
                              max_path,
                              max_content + 1)
        self.controller._check_injected_file_quota(ctx, injected_files)

        _update_default_quota(len(injected_files) + 1,
                              max_path + 1,
                              max_content - 1)
        self.assertRaises(t_exceptions.OnsetFileContentLimitExceeded,
                          self.controller._check_injected_file_quota,
                          ctx, injected_files)

        res = self.controller._process_injected_file_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        _update_default_quota(len(injected_files) + 1,
                              max_path + 1,
                              max_content)
        self.controller._check_injected_file_quota(ctx, injected_files)

    @patch.object(pecan, 'response', new=FakeResponse)
    def test_process_metadata_quota(self):
        ctx = self.context.elevated()

        def _update_default_quota(num):
            self.default_quota = dict(metadata_items=num)
            for k, v in self.default_quota.items():
                api.quota_class_create(ctx, 'default', k, v)

        meta_data_items = {
            'A': '1',
            'B': '2',
            'C': '3',
        }

        t_server_dict = {'metadata': meta_data_items}

        self.controller._check_metadata_properties_quota(ctx)
        self.controller._check_metadata_properties_quota(ctx, {})

        self.assertRaises(t_exceptions.InvalidMetadata,
                          self.controller._check_metadata_properties_quota,
                          ctx, [1, ])

        meta_data_items['A'] = None
        self.assertRaises(t_exceptions.InvalidMetadata,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)
        res = self.controller._process_metadata_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        meta_data_items['A'] = '1'
        _update_default_quota(len(meta_data_items))
        self.controller._check_metadata_properties_quota(ctx, meta_data_items)

        _update_default_quota(len(meta_data_items) + 1)
        self.controller._check_metadata_properties_quota(ctx, meta_data_items)

        meta_data_items['C'] = '3'
        _update_default_quota(len(meta_data_items) - 1)
        self.assertRaises(t_exceptions.MetadataLimitExceeded,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)

        res = self.controller._process_metadata_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        _update_default_quota(len(meta_data_items) + 1)

        string_exceed_MAX_METADATA_LEGNGTH = (server.MAX_METADATA_VALUE_LENGTH
                                              + 1) * '3'

        meta_data_items['C'] = string_exceed_MAX_METADATA_LEGNGTH
        self.assertRaises(t_exceptions.InvalidMetadataSize,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)

        res = self.controller._process_metadata_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

        meta_data_items['C'] = '3'
        meta_data_items[string_exceed_MAX_METADATA_LEGNGTH] = '4'
        self.assertRaises(t_exceptions.InvalidMetadataSize,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)

        res = self.controller._process_metadata_quota(ctx, t_server_dict)
        self._validate_error_code(res, 400)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get(self, mock_ctx):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'

        t_net = {'id': top_net_id, 'name': 'net'}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': [{'start': '10.0.0.2',
                                          'end': '10.0.0.254'}],
                    'enable_dhcp': True}
        t_sg = {'id': top_sg_id, 'name': 'default', 'description': '',
                'tenant_id': self.project_id,
                'security_group_rules': [
                    {'remote_group_id': top_sg_id,
                     'direction': 'ingress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                    {'remote_group_id': None,
                     'direction': 'egress',
                     'remote_ip_prefix': None,
                     'protocol': None,
                     'port_range_max': None,
                     'port_range_min': None,
                     'ethertype': 'IPv4'},
                ]}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_SGS.append(t_sg)

        server_name = 'test_server'
        image_id = 'image_id'
        flavor_id = 1
        body = {
            'server': {
                'name': server_name,
                'imageRef': image_id,
                'flavorRef': flavor_id,
                'availability_zone': b_pod['az_name'],
                'networks': [{'uuid': top_net_id}]
            }
        }
        mock_ctx.return_value = self.context

        server_dict = self.controller.post(**body)['server']
        ret_server = self.controller.get_one(server_dict['id'])['server']
        self.assertEqual(server_name, ret_server['name'])
        self.assertEqual(image_id, ret_server['image'])
        self.assertEqual(flavor_id, ret_server['flavor'])
        self.assertEqual(t_net['name'], ret_server['addresses'].keys()[0])

        ret_server = self.controller.get_one('detail')['servers'][0]
        self.assertEqual(server_name, ret_server['name'])
        self.assertEqual(image_id, ret_server['image'])
        self.assertEqual(flavor_id, ret_server['flavor'])
        self.assertEqual(t_net['name'], ret_server['addresses'].keys()[0])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
