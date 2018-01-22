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

from neutron.extensions import securitygroup as ext_sg
from oslo_utils import uuidutils

from tricircle.common import constants
import tricircle.common.constants as t_constants
import tricircle.common.exceptions as t_exceptions
from tricircle.db import core
from tricircle.db import models
from tricircle.network import exceptions


class TricircleSecurityGroupTestMixin(object):

    @staticmethod
    def _build_test_rule(_id, sg_id, project_id, ip_prefix, remote_group=None):
        return {'security_group_id': sg_id,
                'id': _id,
                'tenant_id': project_id,
                'project_id': project_id,
                'remote_group_id': remote_group,
                'direction': 'ingress',
                'remote_ip_prefix': ip_prefix,
                'protocol': None,
                'port_range_max': None,
                'port_range_min': None,
                'ethertype': 'IPv4'}

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key] and str(rule1[key]) != str(rule2[key]):
                return False
        return True

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

    def _test_update_default_sg(self, plugin, q_ctx, t_ctx,
                                pod_id, top_sgs, top_rules,
                                bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg_id, project_id, '10.0.0.0/24')
        t_sg = {'id': t_sg_id, 'name': 'default', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1]}
        b_sg = {'id': b_sg_id, 'name': 'default', 'description': '',
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

        t_rule2 = {
            'security_group_rule': self._build_test_rule(
                t_rule2_id, t_sg_id, project_id, '10.0.1.0/24')}
        plugin.create_security_group_rule(q_ctx, t_rule2)
        self.assertEqual(len(top_sgs[0]['security_group_rules']),
                         len(bottom1_sgs[0]['security_group_rules']))

        for i in range(len(bottom1_sgs[0]['security_group_rules'])):
            self.assertTrue(self._compare_rule(
                bottom1_sgs[0]['security_group_rules'][i],
                top_sgs[0]['security_group_rules'][i]))

        plugin.delete_security_group_rule(q_ctx, t_rule1_id)
        self.assertEqual(len(bottom1_sgs[0]['security_group_rules']),
                         len(top_sgs[0]['security_group_rules']))

        for i in range(len(bottom1_sgs[0]['security_group_rules'])):
            self.assertTrue(self._compare_rule(
                bottom1_sgs[0]['security_group_rules'][i],
                top_sgs[0]['security_group_rules'][i]))

    def _test_get_security_group(self, plugin, q_ctx, t_ctx,
                                 pod_id, top_sgs, bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg_id, project_id, '10.0.0.0/24')
        t_rule2 = self._build_test_rule(
            t_rule2_id, t_sg_id, project_id, '192.168.56.0/24')
        t_sg = {'id': t_sg_id, 'name': 'top_sg', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1, t_rule2]}
        b_sg = {'id': b_sg_id, 'name': 'bottom_sg', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1, t_rule2]}
        top_sgs.append(t_sg)
        bottom1_sgs.append(b_sg)

        route1 = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route1)

        # test get_sg for normal situation
        res = plugin.get_security_group(q_ctx, t_sg_id)
        self.assertTrue(res['id'] == t_sg_id and res['name'] == 'top_sg')

        # test get_sg when the top_sg is under deleting
        dict_para = {'resource_id': t_sg_id,
                     'resource_type': t_constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.DeletingResources,
                                 dict_para)

        q_ctx.USER_AGENT = t_constants.LOCAL
        self.assertRaises(t_exceptions.ResourceNotFound,
                          plugin.get_security_group,
                          q_ctx, t_sg_id)

        # test get_sg when the request is from user_agent
        q_ctx.USER_AGENT = t_constants.USER_AGENT
        self.assertRaises(t_exceptions.ResourceIsInDeleting,
                          plugin.get_security_group,
                          q_ctx, t_sg_id)

    def _test_delete_security_group(self, plugin, q_ctx, t_ctx,
                                    pod_id, top_sgs, bottom1_sgs):
        t_sg_id = uuidutils.generate_uuid()
        t_rule1_id = uuidutils.generate_uuid()
        t_rule2_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        project_id = 'test_prject_id'
        t_rule1 = self._build_test_rule(
            t_rule1_id, t_sg_id, project_id, '10.0.0.0/24')
        t_rule2 = self._build_test_rule(
            t_rule2_id, t_sg_id, project_id, '192.168.56.0/24')
        t_sg = {'id': t_sg_id, 'name': 'top_sg', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1, t_rule2]}
        b_sg = {'id': b_sg_id, 'name': 'bottom_sg', 'description': '',
                'tenant_id': project_id,
                'security_group_rules': [t_rule1, t_rule2]}
        top_sgs.append(t_sg)
        bottom1_sgs.append(b_sg)

        route1 = {
            'top_id': t_sg_id,
            'pod_id': pod_id,
            'bottom_id': b_sg_id,
            'resource_type': constants.RT_SG}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route1)

        # test delete_sg when sg is not exit
        rand_id = uuidutils.generate_uuid()
        self.assertRaises(ext_sg.SecurityGroupNotFound,
                          plugin.delete_security_group, q_ctx, rand_id)
        # when sg is under deleting from Local
        dict_para = {'resource_id': t_sg_id,
                     'resource_type': t_constants.RT_SG}
        q_ctx.USER_AGENT = t_constants.LOCAL
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.DeletingResources,
                                 dict_para)
        self.assertRaises(t_exceptions.ResourceNotFound,
                          plugin.delete_security_group, q_ctx, t_sg_id)
