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

import unittest

from oslo_utils import uuidutils

from tricircle.network import helper


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
            'allocation_pools': [{'start': '10.0.1.2', 'end': '10.0.1.254'}],
            'enable_dhcp': True,
            'tenant_id': project_id
        }
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.2')
        self.assertItemsEqual([{'start': '10.0.1.3', 'end': '10.0.1.254'}],
                              body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.2', body['subnet']['gateway_ip'])

        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.254')
        self.assertItemsEqual([{'start': '10.0.1.2', 'end': '10.0.1.253'}],
                              body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.254', body['subnet']['gateway_ip'])

        t_subnet['allocation_pools'] = [
            {'start': '10.0.1.2', 'end': '10.0.1.10'},
            {'start': '10.0.1.20', 'end': '10.0.1.254'}]
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.5')
        self.assertItemsEqual([{'start': '10.0.1.2', 'end': '10.0.1.4'},
                               {'start': '10.0.1.6', 'end': '10.0.1.10'},
                               {'start': '10.0.1.20', 'end': '10.0.1.254'}],
                              body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.5', body['subnet']['gateway_ip'])
