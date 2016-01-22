# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from mock import patch
import unittest

from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.xjob import xmanager


BOTTOM1_NETWORK = []
BOTTOM2_NETWORK = []
BOTTOM1_SUBNET = []
BOTTOM2_SUBNET = []
BOTTOM1_PORT = []
BOTTOM2_PORT = []
BOTTOM1_ROUTER = []
BOTTOM2_ROUTER = []
RES_LIST = [BOTTOM1_SUBNET, BOTTOM2_SUBNET, BOTTOM1_PORT, BOTTOM2_PORT]
RES_MAP = {'pod_1': {'network': BOTTOM1_NETWORK,
                     'subnet': BOTTOM1_SUBNET,
                     'port': BOTTOM1_PORT,
                     'router': BOTTOM1_ROUTER},
           'pod_2': {'network': BOTTOM2_NETWORK,
                     'subnet': BOTTOM2_SUBNET,
                     'port': BOTTOM2_PORT,
                     'router': BOTTOM2_ROUTER}}


class FakeXManager(xmanager.XManager):
    def __init__(self):
        self.clients = {'pod_1': FakeClient('pod_1'),
                        'pod_2': FakeClient('pod_2')}

    def _get_client(self, pod_name=None):
        return self.clients[pod_name]


class FakeClient(object):
    def __init__(self, pod_name=None):
        if pod_name:
            self.pod_name = pod_name
        else:
            self.pod_name = 'top'

    def list_resources(self, resource, cxt, filters=None):
        res_list = []
        filters = filters or []
        for res in RES_MAP[self.pod_name][resource]:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if res[_filter['key']] != _filter['value']:
                    is_selected = False
                    break
            if is_selected:
                res_list.append(res)
        return res_list

    def list_ports(self, cxt, filters=None):
        return self.list_resources('port', cxt, filters)

    def get_subnets(self, cxt, subnet_id):
        return self.list_resources(
            'subnet', cxt,
            [{'key': 'id', 'comparator': 'eq', 'value': subnet_id}])[0]

    def update_routers(self, cxt, *args, **kwargs):
        pass


class XManagerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()
        self.xmanager = FakeXManager()

    @patch.object(FakeClient, 'update_routers')
    def test_configure_extra_routes(self, mock_update):
        top_router_id = 'router_id'
        for i in xrange(1, 3):
            pod_dict = {'pod_id': 'pod_id_%d' % i,
                        'pod_name': 'pod_%d' % i,
                        'az_name': 'az_name_%d' % i}
            db_api.create_pod(self.context, pod_dict)

            network = {'id': 'network_%d_id' % i}
            bridge_network = {'id': 'bridge_network_%d_id' % i}
            router = {'id': 'router_%d_id' % i}
            subnet = {
                'id': 'subnet_%d_id' % i,
                'network_id': network['id'],
                'cidr': '10.0.%d.0/24' % i,
                'gateway_ip': '10.0.%d.1' % i,
            }
            bridge_subnet = {
                'id': 'bridge_subnet_%d_id' % i,
                'network_id': bridge_network['id'],
                'cidr': '100.0.1.0/24',
                'gateway_ip': '100.0.1.%d' % i,
            }
            port = {
                'network_id': network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_interface',
                'fixed_ips': [{'subnet_id': subnet['id'],
                               'ip_address': subnet['gateway_ip']}]
            }
            bridge_port = {
                'network_id': bridge_network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_interface',
                'fixed_ips': [{'subnet_id': bridge_subnet['id'],
                               'ip_address': bridge_subnet['gateway_ip']}]
            }
            pod_name = 'pod_%d' % i
            RES_MAP[pod_name]['network'].append(network)
            RES_MAP[pod_name]['network'].append(bridge_network)
            RES_MAP[pod_name]['subnet'].append(subnet)
            RES_MAP[pod_name]['subnet'].append(bridge_subnet)
            RES_MAP[pod_name]['port'].append(port)
            RES_MAP[pod_name]['port'].append(bridge_port)
            RES_MAP[pod_name]['router'].append(router)

            route = {'top_id': top_router_id, 'bottom_id': router['id'],
                     'pod_id': pod_dict['pod_id'], 'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context, models.ResourceRouting,
                                     route)
        BOTTOM1_NETWORK.append({'id': 'network_3_id'})
        BOTTOM1_SUBNET.append({'id': 'subnet_3_id',
                               'network_id': 'network_3_id',
                               'cidr': '10.0.3.0/24',
                               'gateway_ip': '10.0.3.1'})
        BOTTOM1_PORT.append({'network_id': 'network_3_id',
                             'device_id': 'router_1_id',
                             'device_owner': 'network:router_interface',
                             'fixed_ips': [{'subnet_id': 'subnet_3_id',
                                            'ip_address': '10.0.3.1'}]})

        self.xmanager.configure_extra_routes(self.context,
                                             {'router': top_router_id})
        calls = [mock.call(self.context, 'router_1_id',
                           {'router': {
                               'routes': [{'nexthop': '100.0.1.2',
                                           'destination': '10.0.2.0/24'}]}}),
                 mock.call(self.context, 'router_2_id',
                           {'router': {
                               'routes': [{'nexthop': '100.0.1.1',
                                           'destination': '10.0.1.0/24'},
                                          {'nexthop': '100.0.1.1',
                                           'destination': '10.0.3.0/24'}]}})]
        mock_update.assert_has_calls(calls)
