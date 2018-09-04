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

from neutron.objects.qos import rule
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.db import api as db_api


class TricircleQosTestMixin(object):
    def _test_create_policy(self, plugin, q_ctx, t_ctx):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id
            }
        }

        res = plugin.create_policy(q_ctx, t_policy)
        res1 = plugin.get_policy(q_ctx, res['id'])

        self.assertEqual('test_qos', res['name'])
        self.assertEqual(res1['id'], res['id'])
        self.assertEqual(res1['name'], res['name'])
        self.assertEqual(res['description'], res['description'])

    def _test_update_policy(self, plugin, q_ctx, t_ctx,
                            pod_id, bottom_policy):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id
            }
        }

        res = plugin.create_policy(q_ctx, t_policy)

        updated_qos = {
            'policy': {
                'name': 'test_updated_qos'
            }
        }

        updated_res = plugin.update_policy(q_ctx, res['id'], updated_qos)
        self.assertEqual(res['id'], updated_res['id'])
        self.assertEqual('test_updated_qos', updated_res['name'])

        b_policy_id = uuidutils.generate_uuid()
        b_policy = {
            'id': b_policy_id, 'name': b_policy_id, 'description': '',
            'tenant_id': project_id
        }
        bottom_policy.append(b_policy)
        db_api.create_resource_mapping(t_ctx, res['id'], b_policy_id,
                                       pod_id, project_id, constants.RT_QOS)

        updated_qos = {
            'policy': {
                'name': 'test_policy'
            }
        }

        updated_res = plugin.update_policy(q_ctx, res['id'], updated_qos)
        self.assertEqual('test_policy', updated_res['name'])
        self.assertEqual('test_policy', bottom_policy[0]['name'])

    def _test_delete_policy(self, plugin, q_ctx,
                            t_ctx, pod_id, bottom_policy):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id
            }
        }

        res = plugin.create_policy(q_ctx, t_policy)
        b_policy_id = uuidutils.generate_uuid()
        b_policy = {
            'id': b_policy_id, 'name': b_policy_id, 'description': '',
            'tenant_id': project_id
        }
        bottom_policy.append(b_policy)
        db_api.create_resource_mapping(t_ctx, res['id'], b_policy_id,
                                       pod_id, project_id, constants.RT_QOS)

        self.assertEqual(1, len(bottom_policy))
        plugin.delete_policy(q_ctx, res['id'])
        self.assertEqual(0, len(bottom_policy))

    def _test_create_policy_rule(self, plugin, q_ctx,
                                 t_ctx, pod_id, bottom_policy):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id
            }
        }

        res = plugin.create_policy(q_ctx, t_policy)

        rule_data = {
            "bandwidth_limit_rule": {
                "max_kbps": "10000"
            }
        }

        t_rule = plugin.create_policy_rule(
            q_ctx, rule.QosBandwidthLimitRule, res['id'], rule_data)
        res1 = plugin.get_policy(q_ctx, res['id'])

        self.assertEqual(1, len(res1['rules']))
        self.assertEqual(t_rule['id'], res1['rules'][0]['id'])

        b_policy_id = uuidutils.generate_uuid()
        b_policy = {'id': b_policy_id, 'name': b_policy_id, 'description': '',
                    'tenant_id': project_id, 'rules': []}
        bottom_policy.append(b_policy)
        db_api.create_resource_mapping(t_ctx, res['id'], b_policy_id,
                                       pod_id, project_id, constants.RT_QOS)

    def _test_delete_policy_rule(self, plugin, q_ctx,
                                 t_ctx, pod_id, bottom_policy):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id
            }
        }

        res = plugin.create_policy(q_ctx, t_policy)

        b_policy_id = uuidutils.generate_uuid()
        b_policy = {
            'id': b_policy_id, 'name': b_policy_id, 'description': '',
            'tenant_id': project_id, 'rules': []
        }
        bottom_policy.append(b_policy)
        db_api.create_resource_mapping(t_ctx, res['id'], b_policy_id,
                                       pod_id, project_id, constants.RT_QOS)

        rule_data = {
            "bandwidth_limit_rule": {
                "max_kbps": "10000"
            }
        }

        res1 = plugin.create_policy_rule(
            q_ctx, rule.QosBandwidthLimitRule, res['id'], rule_data)

        self.assertEqual(1, len(bottom_policy[0]['rules']))
        b_rule = bottom_policy[0]['rules'][0]
        self.assertEqual(b_policy_id, b_rule['qos_policy_id'])

        plugin.delete_policy_rule(
            q_ctx, rule.QosBandwidthLimitRule, res1['id'], res['id'])
        self.assertEqual(0, len(bottom_policy[0]['rules']))

    @staticmethod
    def _create_policy_in_top(self, plugin, q_ctx, t_ctx,
                              pod_id, bottom_policy):
        project_id = 'test_prject_id'
        t_policy = {
            'policy': {
                'name': 'test_qos',
                'description': 'This policy limits the ports to 10Mbit max.',
                'project_id': project_id,
            }
        }

        return plugin.create_policy(q_ctx, t_policy)

    def _test_update_network_with_qos_policy(self, plugin, client, q_ctx,
                                             t_ctx, pod_id, t_net_id,
                                             bottom_policy):
        res = \
            self._create_policy_in_top(self, plugin, q_ctx, t_ctx,
                                       pod_id, bottom_policy)

        update_body = {
            'network': {
                'qos_policy_id': res['id']}
        }
        top_net = plugin.update_network(q_ctx, t_net_id, update_body)
        self.assertEqual(top_net['qos_policy_id'], res['id'])

        route_res = \
            db_api.get_bottom_mappings_by_top_id(t_ctx, res['id'],
                                                 constants.RT_QOS)
        bottom_net = client.get_networks(q_ctx, t_net_id)
        self.assertEqual(bottom_net['qos_policy_id'], route_res[0][1])

    def _test_update_port_with_qos_policy(self, plugin, client, q_ctx,
                                          t_ctx, pod_id, t_port_id,
                                          b_port_id, bottom_policy):
        res = \
            self._create_policy_in_top(self, plugin, q_ctx, t_ctx,
                                       pod_id, bottom_policy)

        update_body = {
            'port': {
                'qos_policy_id': res['id']}
        }
        top_port = plugin.update_port(q_ctx, t_port_id, update_body)
        self.assertEqual(top_port['qos_policy_id'], res['id'])

        route_res = \
            db_api.get_bottom_mappings_by_top_id(t_ctx, res['id'],
                                                 constants.RT_QOS)
        bottom_port = client.get_ports(q_ctx, b_port_id)
        self.assertEqual(bottom_port['qos_policy_id'], route_res[0][1])
