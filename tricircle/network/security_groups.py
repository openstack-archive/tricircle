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

from neutron.db import securitygroups_db
import neutronclient.common.exceptions as q_exceptions

from tricircle.common import constants
from tricircle.common import context
import tricircle.db.api as db_api
import tricircle.network.exceptions as n_exceptions


class TricircleSecurityGroupMixin(securitygroups_db.SecurityGroupDbMixin):

    @staticmethod
    def _safe_create_security_group_rule(t_context, client, body):
        try:
            client.create_security_group_rules(t_context, body)
        except q_exceptions.Conflict:
            return

    @staticmethod
    def _safe_delete_security_group_rule(t_context, client, _id):
        try:
            client.delete_security_group_rules(t_context, _id)
        except q_exceptions.NotFound:
            return

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key]:
                return False
        return True

    def create_security_group_rule(self, q_context, security_group_rule):
        rule = security_group_rule['security_group_rule']
        if rule['remote_group_id']:
            raise n_exceptions.RemoteGroupNotSupported()
        sg_id = rule['security_group_id']
        sg = self.get_security_group(q_context, sg_id)
        if sg['name'] == 'default':
            raise n_exceptions.DefaultGroupUpdateNotSupported()

        new_rule = super(TricircleSecurityGroupMixin,
                         self).create_security_group_rule(q_context,
                                                          security_group_rule)

        t_context = context.get_context_from_neutron_context(q_context)
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_context, sg_id, constants.RT_SG)

        try:
            for pod, b_sg_id in mappings:
                client = self._get_client(pod['pod_name'])
                rule['security_group_id'] = b_sg_id
                self._safe_create_security_group_rule(
                    t_context, client, {'security_group_rule': rule})
        except Exception:
            super(TricircleSecurityGroupMixin,
                  self).delete_security_group_rule(q_context, new_rule['id'])
            raise n_exceptions.BottomPodOperationFailure(
                resource='security group rule', pod_name=pod['pod_name'])
        return new_rule

    def delete_security_group_rule(self, q_context, _id):
        rule = self.get_security_group_rule(q_context, _id)
        if rule['remote_group_id']:
            raise n_exceptions.RemoteGroupNotSupported()
        sg_id = rule['security_group_id']
        sg = self.get_security_group(q_context, sg_id)
        if sg['name'] == 'default':
            raise n_exceptions.DefaultGroupUpdateNotSupported()

        t_context = context.get_context_from_neutron_context(q_context)
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_context, sg_id, constants.RT_SG)

        try:
            for pod, b_sg_id in mappings:
                client = self._get_client(pod['pod_name'])
                rule['security_group_id'] = b_sg_id
                b_sg = client.get_security_groups(t_context, b_sg_id)
                for b_rule in b_sg['security_group_rules']:
                    if not self._compare_rule(b_rule, rule):
                        continue
                    self._safe_delete_security_group_rule(t_context, client,
                                                          b_rule['id'])
                    break
        except Exception:
            raise n_exceptions.BottomPodOperationFailure(
                resource='security group rule', pod_name=pod['pod_name'])

        super(TricircleSecurityGroupMixin,
              self).delete_security_group_rule(q_context, _id)
