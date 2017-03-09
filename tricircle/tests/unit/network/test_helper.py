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

from mock import patch
import six
import unittest

import neutronclient.common.exceptions as q_cli_exceptions
from oslo_utils import uuidutils

from tricircle.network import helper


class FakeClient(object):
    def __init__(self, region_name=None):
        pass

    def create_ports(self, context, body):
        for port in body['ports']:
            index = int(port['name'].split('-')[-1])
            if index in (1, 3, 6, 7, 8, 14, 19):
                raise q_cli_exceptions.MacAddressInUseClient(
                    message='fa:16:3e:d4:01:%02x' % index)
            port['id'] = port['name'].split('_')[-1]
        return body['ports']


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.helper = helper.NetworkHelper()

    def test_get_create_subnet_body(self):
        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        b_net_id = uuidutils.generate_uuid()
        project_id = uuidutils.generate_uuid()

        t_subnet = {
            'network_id': t_net_id,
            'id': t_subnet_id,
            'ip_version': 4,
            'cidr': '10.0.1.0/24',
            'gateway_ip': '10.0.1.1',
            'allocation_pools': [{'start': '10.0.1.10', 'end': '10.0.1.254'}],
            'enable_dhcp': True,
            'tenant_id': project_id
        }
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.10')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.11', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.10', body['subnet']['gateway_ip'])

        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.254')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.10', 'end': '10.0.1.253'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.254', body['subnet']['gateway_ip'])

        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.8')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.10', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.8', body['subnet']['gateway_ip'])

        t_subnet['allocation_pools'] = [
            {'start': '10.0.1.2', 'end': '10.0.1.10'},
            {'start': '10.0.1.20', 'end': '10.0.1.254'}]
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.5')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.4'},
                              {'start': '10.0.1.6', 'end': '10.0.1.10'},
                              {'start': '10.0.1.20', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.5', body['subnet']['gateway_ip'])

        t_subnet['gateway_ip'] = '10.0.1.11'
        t_subnet['allocation_pools'] = [
            {'start': '10.0.1.2', 'end': '10.0.1.10'},
            {'start': '10.0.1.12', 'end': '10.0.1.254'}]
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.5')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.2', 'end': '10.0.1.4'},
                              {'start': '10.0.1.6', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.5', body['subnet']['gateway_ip'])

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    def test_prepare_shadow_ports(self):
        port_bodys = [{
            'id': 'port-id-%d' % i,
            'fixed_ips': [{'ip_address': '10.0.1.%d' % i}],
            'mac_address': 'fa:16:3e:d4:01:%02x' % i,
            'binding:host_id': 'host1'
        } for i in range(1, 20)]
        agents = [{'type': 'Open vSwitch agent',
                   'tunnel_ip': '192.168.1.101'} for _ in range(1, 20)]
        # we just want to test the logic, so we pass None for context, a
        # malformed dict for target_pod
        ret_port_ids = self.helper.prepare_shadow_ports(
            None, 'project_id', {'region_name': 'pod1'}, 'net-id-1',
            port_bodys, agents, 5)
        req_port_ids = [port['id'] for port in port_bodys]
        six.assertCountEqual(self, ret_port_ids, req_port_ids)
