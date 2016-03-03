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

from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.db import core
from tricircle.db import models
from tricircle.network import exceptions


class TricircleSecurityGroupTestMixin(object):

    @staticmethod
    def _build_test_rule(_id, sg_id, project_id, ip_prefix, remote_group=None):
        return {'security_group_id': sg_id,
                'id': _id,
                'tenant_id': project_id,
                'remote_group_id': remote_group,
                'direction': 'ingress',
                'remote_ip_prefix': ip_prefix,
                'protocol': None,
                'port_range_max': None,
                'port_range_min': None,
                'ethertype': 'IPv4'}

    def _test_create_security_group_rule(self, plugin, q_ctx, t_ctx, pod_id,
                                         top_sgs, bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_sg = {'id': t_sg_id, 'name': 'test', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        b_sg = {'id': b_sg_id, 'name': t_sg_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        top_sgs.append(t_sg)
        bottom1_sgs.append(b_sg)
        route = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        rule = {
            'security_group_rule': self._build_test_rule(
                t_rule_id, t_sg_id, project_id, '10.0.0.0/24')}
        plugin.create_security_group_rule(q_ctx, rule)

        self.assertEqual(1, len(bottom1_sgs[0]['security_group_rules']))
        b_rule = bottom1_sgs[0]['security_group_rules'][0]
        self.assertEqual(b_sg_id, b_rule['security_group_id'])
        rule['security_group_rule'].pop('security_group_id', None)
        b_rule.pop('security_group_id', None)
        self.assertEqual(rule['security_group_rule'], b_rule)

    def _test_delete_security_group_rule(self, plugin, q_ctx, t_ctx, pod_id,
                                         top_sgs, top_rules, bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg_id, project_id, '10.0.1.0/24')
        t_rule2 = self._build_test_rule(
            t_rule2_id, t_sg_id, project_id, '10.0.2.0/24')
        b_rule1 = self._build_test_rule(
            t_rule1_id, b_sg_id, project_id, '10.0.1.0/24')
        b_rule2 = self._build_test_rule(
            t_rule2_id, b_sg_id, project_id, '10.0.2.0/24')
        t_sg = {'id': t_sg_id, 'name': 'test', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1, t_rule2]}
        b_sg = {'id': b_sg_id, 'name': t_sg_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [b_rule1, b_rule2]}
        top_sgs.append(t_sg)
        top_rules.append(t_rule1)
        top_rules.append(t_rule2)
        bottom1_sgs.append(b_sg)
        route = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        plugin.delete_security_group_rule(q_ctx, t_rule1_id)

        self.assertEqual(1, len(bottom1_sgs[0]['security_group_rules']))
        b_rule = bottom1_sgs[0]['security_group_rules'][0]
        self.assertEqual(b_sg_id, b_rule['security_group_id'])
        t_rule2.pop('security_group_id', None)
        b_rule.pop('security_group_id', None)
        self.assertEqual(t_rule2, b_rule)

    def _test_handle_remote_group_invalid_input(self, plugin, q_ctx, t_ctx,
                                                pod_id, top_sgs, top_rules,
                                                bottom1_sgs):
        t_sg1_id = uuidutils.generate_uuid()
        t_sg2_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg1_id, project_id, None, t_sg1_id)
        t_rule2 = self._build_test_rule(
            t_rule2_id, t_sg1_id, project_id, None, t_sg2_id)
        t_sg = {'id': t_sg1_id, 'name': 'test', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        b_sg = {'id': b_sg_id, 'name': t_sg1_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        top_sgs.append(t_sg)
        top_rules.append(t_rule1)
        bottom1_sgs.append(b_sg)
        route = {
            'top_id': t_sg1_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        self.assertRaises(exceptions.RemoteGroupNotSupported,
                          plugin.create_security_group_rule, q_ctx,
                          {'security_group_rule': t_rule2})
        self.assertRaises(exceptions.RemoteGroupNotSupported,
                          plugin.delete_security_group_rule, q_ctx, t_rule1_id)

    def _test_handle_default_sg_invalid_input(self, plugin, q_ctx, t_ctx,
                                              pod_id, top_sgs, top_rules,
                                              bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg_id, project_id, '10.0.0.0/24')
        t_rule2 = self._build_test_rule(
            t_rule2_id, t_sg_id, project_id, '10.0.1.0/24')
        t_sg = {'id': t_sg_id, 'name': 'default', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1]}
        b_sg = {'id': b_sg_id, 'name': t_sg_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        top_sgs.append(t_sg)
        top_rules.append(t_rule1)
        bottom1_sgs.append(b_sg)
        route1 = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route1)

        self.assertRaises(exceptions.DefaultGroupUpdateNotSupported,
                          plugin.create_security_group_rule, q_ctx,
                          {'security_group_rule': t_rule2})
        self.assertRaises(exceptions.DefaultGroupUpdateNotSupported,
                          plugin.delete_security_group_rule, q_ctx, t_rule1_id)

    def _test_create_security_group_rule_exception(
            self, plugin, q_ctx, t_ctx, pod_id, top_sgs, bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_sg = {'id': t_sg_id, 'name': 'test', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        b_sg = {'id': b_sg_id, 'name': t_sg_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': []}
        top_sgs.append(t_sg)
        bottom1_sgs.append(b_sg)
        route = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        rule = {
            'security_group_rule': self._build_test_rule(
                t_rule_id, t_sg_id, project_id, '10.0.0.0/24')}
        self.assertRaises(exceptions.BottomPodOperationFailure,
                          plugin.create_security_group_rule, q_ctx, rule)

    def _test_delete_security_group_rule_exception(self, plugin, q_ctx, t_ctx,
                                                   pod_id, top_sgs, top_rules,
                                                   bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule = self._build_test_rule(
            t_rule_id, t_sg_id, project_id, '10.0.1.0/24')
        b_rule = self._build_test_rule(
            t_rule_id, b_sg_id, project_id, '10.0.1.0/24')
        t_sg = {'id': t_sg_id, 'name': 'test', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule]}
        b_sg = {'id': b_sg_id, 'name': t_sg_id, 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [b_rule]}
        top_sgs.append(t_sg)
        top_rules.append(t_rule)
        bottom1_sgs.append(b_sg)
        route = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        self.assertRaises(exceptions.BottomPodOperationFailure,
                          plugin.delete_security_group_rule, q_ctx, t_rule_id)
