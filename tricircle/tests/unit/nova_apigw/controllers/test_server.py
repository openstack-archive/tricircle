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

from tricircle.common import context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common import lock_handle
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
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

RES_LIST = [TOP_NETS, TOP_SUBNETS, TOP_PORTS, TOP_SGS,
            BOTTOM1_NETS, BOTTOM1_SUBNETS, BOTTOM1_PORTS, BOTTOM1_SGS,
            BOTTOM2_NETS, BOTTOM2_SUBNETS, BOTTOM2_PORTS, BOTTOM2_SGS]


class FakeException(Exception):
    pass


class FakeServerController(server.ServerController):
    def __init__(self, project_id):
        self.clients = {'t_region': FakeClient('t_region')}
        self.project_id = project_id

    def _get_client(self, pod_name=None):
        if not pod_name:
            return self.clients['t_region']
        else:
            if pod_name not in self.clients:
                self.clients[pod_name] = FakeClient(pod_name)
        return self.clients[pod_name]


class FakeClient(object):

    _res_map = {'top': {'network': TOP_NETS,
                        'subnet': TOP_SUBNETS,
                        'port': TOP_PORTS,
                        'security_group': TOP_SGS},
                'bottom': {'network': BOTTOM_NETS,
                           'subnet': BOTTOM_SUBNETS,
                           'port': BOTTOM_PORTS,
                           'security_group': BOTTOM_SGS},
                'bottom2': {'network': BOTTOM2_NETS,
                            'subnet': BOTTOM2_SUBNETS,
                            'port': BOTTOM2_PORTS,
                            'security_group': BOTTOM2_SGS}}

    def __init__(self, pod_name):
        self.pod_name = pod_name
        self.ip_suffix_gen = self._get_ip_suffix()

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

    @staticmethod
    def _get_ip_suffix():
        # three elements should be enough
        suffix_list = ['3', '4', '5']
        index = 0
        while True:
            yield suffix_list[index]
            index += 1
            index %= 3

    def create_ports(self, ctx, body):
        if 'fixed_ips' in body['port']:
            return self.create_resources('port', ctx, body)
        net_id = body['port']['network_id']
        subnets = self._get_res_list('subnet')
        fixed_ip_list = []
        for subnet in subnets:
            if subnet['network_id'] == net_id:
                cidr = subnet['cidr']
                ip_prefix = cidr[:cidr.rindex('.') + 1]
                mac_prefix = 'fa:16:3e:96:41:0'
                if 'device_owner' in body['port']:
                    ip = ip_prefix + '2'
                    body['port']['mac_address'] = mac_prefix + '2'
                else:
                    suffix = self.ip_suffix_gen.next()
                    ip = ip_prefix + suffix
                    body['port']['mac_address'] = mac_prefix + suffix
                fixed_ip_list.append({'ip_address': ip,
                                      'subnet_id': subnet['id']})
        body['port']['fixed_ips'] = fixed_ip_list
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

    def create_servers(self, ctx, body):
        # do nothing here since it will be mocked
        pass

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
        port = {'id': 'top_port_id'}
        body = {'port': {'name': 'top_port_id'}}
        _, bottom_port_id = self.controller._prepare_neutron_element(
            self.context, b_pod, port, 'port', body)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_port_id', 'port')
        self.assertEqual(bottom_port_id, mappings[0][1])

    @patch.object(FakeClient, 'create_resources')
    def test_prepare_neutron_element_create_res_exception(self, mock_method):
        mock_method.side_effect = FakeException()
        t_pod, b_pod = self._prepare_pod()
        port = {'id': 'top_port_id'}
        body = {'port': {'name': 'top_port_id'}}
        self.assertRaises(FakeException,
                          self.controller._prepare_neutron_element,
                          self.context, b_pod, port, 'port', body)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_port_id', 'port')
        self.assertEqual(0, len(mappings))

    def _check_routes(self):
        for res in (TOP_NETS, TOP_SUBNETS, BOTTOM_NETS, BOTTOM_SUBNETS):
            self.assertEqual(1, len(res))
        self.assertEqual(2, len(TOP_PORTS))
        self.assertEqual(2, len(BOTTOM_PORTS))

        with self.context.session.begin():
            routes = core.query_resource(self.context,
                                         models.ResourceRouting, [], [])
        self.assertEqual(4, len(routes))
        actual = [[], [], [], []]
        for region in ('t_region', 'b_region'):
            actual[0].append(self.controller._get_client(
                region).list_resources('network', self.context, [])[0]['id'])
            actual[1].append(self.controller._get_client(
                region).list_resources('subnet', self.context, [])[0]['id'])
            t_ports = self.controller._get_client(
                region).list_resources('port', self.context, [])
            if 'device_id' in t_ports[0]:
                actual[2].append(t_ports[0]['id'])
                actual[3].append(t_ports[1]['id'])
            else:
                actual[2].append(t_ports[1]['id'])
                actual[3].append(t_ports[0]['id'])
        expect = [[route['top_id'], route['bottom_id']] for route in routes]
        self.assertItemsEqual(expect, actual)

    def test_handle_network(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id'}
        subnet = {'id': 'top_subnet_id',
                  'network_id': 'top_net_id',
                  'ip_version': 4,
                  'cidr': '10.0.0.0/24',
                  'gateway_ip': '10.0.0.1',
                  'allocation_pools': {'start': '10.0.0.2',
                                       'end': '10.0.0.254'},
                  'enable_dhcp': True}
        TOP_NETS.append(net)
        TOP_SUBNETS.append(subnet)
        self.controller._handle_network(self.context, b_pod, net, [subnet])
        self._check_routes()

    def test_handle_port(self):
        t_pod, b_pod = self._prepare_pod()
        net = {'id': 'top_net_id'}
        subnet = {'id': 'top_subnet_id',
                  'network_id': 'top_net_id',
                  'ip_version': 4,
                  'cidr': '10.0.0.0/24',
                  'gateway_ip': '10.0.0.1',
                  'allocation_pools': {'start': '10.0.0.2',
                                       'end': '10.0.0.254'},
                  'enable_dhcp': True}
        port = {
            'id': 'top_port_id',
            'network_id': 'top_net_id',
            'mac_address': 'fa:16:3e:96:41:03',
            'fixed_ips': [{'subnet_id': 'top_subnet_id',
                          'ip_address': '10.0.0.3'}]
        }
        TOP_NETS.append(net)
        TOP_SUBNETS.append(subnet)
        TOP_PORTS.append(port)
        self.controller._handle_port(self.context, b_pod, port)
        self._check_routes()

    def _test_handle_network_dhcp_port(self, dhcp_ip):
        t_pod, b_pod = self._prepare_pod()

        top_net_id = 'top_net_id'
        bottom_net_id = 'bottom_net_id'
        top_subnet_id = 'top_subnet_id'
        bottom_subnet_id = 'bottom_subnet_id'
        t_net = {'id': top_net_id}
        b_net = {'id': bottom_net_id}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
                    'enable_dhcp': True}
        b_subnet = {'id': bottom_subnet_id,
                    'network_id': bottom_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
                    'enable_dhcp': True}
        b_dhcp_port = {'id': 'bottom_dhcp_port_id',
                       'network_id': bottom_net_id,
                       'fixed_ips': [
                           {'subnet_id': bottom_subnet_id,
                            'ip_address': dhcp_ip}
                       ],
                       'mac_address': 'fa:16:3e:96:41:0a',
                       'binding:profile': {},
                       'device_id': 'reserved_dhcp_port',
                       'device_owner': 'network:dhcp'}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        BOTTOM_NETS.append(b_net)
        BOTTOM_SUBNETS.append(b_subnet)
        BOTTOM_PORTS.append(b_dhcp_port)
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': top_net_id, 'bottom_id': bottom_net_id,
                 'pod_id': b_pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': 'network'})
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': top_subnet_id, 'bottom_id': bottom_subnet_id,
                 'pod_id': b_pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': 'subnet'})
        self.controller._handle_network(self.context,
                                        b_pod, t_net, [t_subnet])
        self._check_routes()

    def test_handle_network_dhcp_port_same_ip(self):
        self._test_handle_network_dhcp_port('10.0.0.2')

    def test_handle_network_dhcp_port_exist_diff_ip(self):
        self._test_handle_network_dhcp_port('10.0.0.4')

    @patch.object(pecan, 'abort')
    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_with_network_az(self, mock_ctx, mock_create, mock_abort):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'
        t_net = {'id': top_net_id}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
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
        self.controller.post(**body)

        # update top net for test purpose, correct az and wrong az
        TOP_NETS[0]['availability_zone_hints'] = ['b_az', 'fake_az']
        self.controller.post(**body)

        msg = 'Network and server not in the same availability zone'
        # abort two times
        calls = [mock.call(400, msg), mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_ctx, mock_create):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'

        t_net = {'id': top_net_id}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
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

    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post_exception_retry(self, mock_ctx, mock_server):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        top_sg_id = 'top_sg_id'

        t_net = {'id': top_net_id}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
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

        t_net1 = {'id': top_net1_id}
        t_subnet1 = {'id': top_subnet1_id,
                     'tenant_id': self.project_id,
                     'network_id': top_net1_id,
                     'ip_version': 4,
                     'cidr': '10.0.1.0/24',
                     'gateway_ip': '10.0.1.1',
                     'allocation_pools': {'start': '10.0.1.2',
                                          'end': '10.0.1.254'},
                     'enable_dhcp': True}
        t_net2 = {'id': top_net2_id}
        t_subnet2 = {'id': top_subnet2_id,
                     'tenant_id': self.project_id,
                     'network_id': top_net2_id,
                     'ip_version': 4,
                     'cidr': '10.0.2.0/24',
                     'gateway_ip': '10.0.2.1',
                     'allocation_pools': {'start': '10.0.2.2',
                                          'end': '10.0.2.254'},
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

    @patch.object(pecan, 'abort')
    def test_process_injected_file_quota(self, mock_abort):
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

        self.controller._process_injected_file_quota(ctx, t_server_dict)
        msg = _('Quota exceeded %s') % \
            t_exceptions.OnsetFileLimitExceeded.message
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

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

        self.controller._process_injected_file_quota(ctx, t_server_dict)
        msg = _('Quota exceeded %s') % \
            t_exceptions.OnsetFilePathLimitExceeded.message
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

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

        self.controller._process_injected_file_quota(ctx, t_server_dict)
        msg = _('Quota exceeded %s') % \
            t_exceptions.OnsetFileContentLimitExceeded.message
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

        _update_default_quota(len(injected_files) + 1,
                              max_path + 1,
                              max_content)
        self.controller._check_injected_file_quota(ctx, injected_files)

    @patch.object(pecan, 'abort')
    def test_process_metadata_quota(self, mock_abort):
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
        self.controller._process_metadata_quota(ctx, t_server_dict)
        msg = _('Invalid metadata')
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

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

        self.controller._process_metadata_quota(ctx, t_server_dict)
        msg = _('Quota exceeded in metadata')
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

        _update_default_quota(len(meta_data_items) + 1)

        string_exceed_MAX_METADATA_LEGNGTH = (server.MAX_METADATA_VALUE_LENGTH
                                              + 1) * '3'

        meta_data_items['C'] = string_exceed_MAX_METADATA_LEGNGTH
        self.assertRaises(t_exceptions.InvalidMetadataSize,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)

        self.controller._process_metadata_quota(ctx, t_server_dict)
        msg = _('Invalid metadata size')
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

        meta_data_items['C'] = '3'
        meta_data_items[string_exceed_MAX_METADATA_LEGNGTH] = '4'
        self.assertRaises(t_exceptions.InvalidMetadataSize,
                          self.controller._check_metadata_properties_quota,
                          ctx, meta_data_items)

        self.controller._process_metadata_quota(ctx, t_server_dict)
        msg = _('Invalid metadata size')
        calls = [mock.call(400, msg)]
        mock_abort.assert_has_calls(calls)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
