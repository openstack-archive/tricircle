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

import datetime
from mock import patch
import unittest

from oslo_utils import uuidutils

from tricircle.common import context
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
from tricircle.nova_apigw.controllers import server


TOP_NETS = []
TOP_SUBNETS = []
TOP_PORTS = []
BOTTOM_NETS = []
BOTTOM_SUBNETS = []
BOTTOM_PORTS = []
RES_LIST = [TOP_NETS, TOP_SUBNETS, TOP_PORTS,
            BOTTOM_NETS, BOTTOM_SUBNETS, BOTTOM_PORTS]


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
                        'port': TOP_PORTS},
                'bottom': {'network': BOTTOM_NETS,
                           'subnet': BOTTOM_SUBNETS,
                           'port': BOTTOM_PORTS}}

    def __init__(self, pod_name):
        self.pod_name = pod_name

    def _get_res_list(self, _type):
        pod = 'top' if self.pod_name == 't_region' else 'bottom'
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
                    ip = ip_prefix + '3'
                    body['port']['mac_address'] = mac_prefix + '3'
                fixed_ip_list.append({'ip_address': ip,
                                      'subnet_id': subnet['id']})
        body['port']['fixed_ips'] = fixed_ip_list
        return self.create_resources('port', ctx, body)

    def list_ports(self, ctx, filters):
        return self.list_resources('port', ctx, filters)

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


class ServerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_project'
        self.controller = FakeServerController(self.project_id)

    def _prepare_pod(self):
        t_pod = {'pod_id': 't_pod_uuid', 'pod_name': 't_region',
                 'az_name': ''}
        b_pod = {'pod_id': 'b_pod_uuid', 'pod_name': 'b_region',
                 'az_name': 'b_az'}
        api.create_pod(self.context, t_pod)
        api.create_pod(self.context, b_pod)
        return t_pod, b_pod

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
        route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertFalse(is_own)
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
        new_route, is_own = self.controller._get_or_create_route(
            self.context, b_pod, 'test_top_id', 'port')
        self.assertFalse(is_own)
        self.assertEqual('test_top_id', new_route['top_id'])
        self.assertEqual('test_bottom_id', new_route['bottom_id'])
        self.assertEqual('port', new_route['resource_type'])
        self.assertEqual(self.project_id, new_route['project_id'])

    def test_prepare_neutron_element(self):
        t_pod, b_pod = self._prepare_pod()
        port = {'id': 'top_port_id'}
        body = {'port': {'name': 'top_port_id'}}
        bottom_port_id = self.controller._prepare_neutron_element(
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

    @patch.object(FakeClient, 'create_servers')
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_ctx, mock_create):
        t_pod, b_pod = self._prepare_pod()
        top_net_id = 'top_net_id'
        top_subnet_id = 'top_subnet_id'
        t_net = {'id': top_net_id}
        t_subnet = {'id': top_subnet_id,
                    'network_id': top_net_id,
                    'ip_version': 4,
                    'cidr': '10.0.0.0/24',
                    'gateway_ip': '10.0.0.1',
                    'allocation_pools': {'start': '10.0.0.2',
                                         'end': '10.0.0.254'},
                    'enable_dhcp': True}
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)

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

        bottom_port_id = ''
        for port in BOTTOM_PORTS:
            if 'device_id' not in port:
                bottom_port_id = port['id']
        mock_create.assert_called_with(self.context, name=server_name,
                                       image=image_id, flavor=flavor_id,
                                       nics=[{'port-id': bottom_port_id}])
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

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
