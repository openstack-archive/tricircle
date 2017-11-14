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

from tricircle.common import context
from tricircle.common import xrpcapi
import tricircle.network.exceptions as n_exceptions


class TricircleSecurityGroupMixin(securitygroups_db.SecurityGroupDbMixin):

    def __init__(self):
        super(TricircleSecurityGroupMixin, self).__init__()
        self.xjob_handler = xrpcapi.XJobAPI()

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key] and str(rule1[key]) != str(rule2[key]):
                return False
        return True

    def create_security_group_rule(self, q_context, security_group_rule):
        rule = security_group_rule['security_group_rule']
        if rule['remote_group_id']:
            raise n_exceptions.RemoteGroupNotSupported()
        sg_id = rule['security_group_id']
        sg = self.get_security_group(q_context, sg_id)
        if not sg:
            raise n_exceptions.SecurityGroupNotFound(sg_id=sg_id)

        new_rule = super(TricircleSecurityGroupMixin,
                         self).create_security_group_rule(q_context,
                                                          security_group_rule)

        t_context = context.get_context_from_neutron_context(q_context)

        try:
            self.xjob_handler.configure_security_group_rules(
                t_context, rule['project_id'])
        except Exception:
            raise n_exceptions.BottomPodOperationFailure(
                resource='security group rule', region_name='')
        return new_rule

    def delete_security_group_rule(self, q_context, _id):
        rule = self.get_security_group_rule(q_context, _id)
        if not rule:
            raise n_exceptions.SecurityGroupRuleNotFound(rule_id=_id)

        if rule['remote_group_id']:
            raise n_exceptions.RemoteGroupNotSupported()
        sg_id = rule['security_group_id']
        sg = self.get_security_group(q_context, sg_id)

        if not sg:
            raise n_exceptions.SecurityGroupNotFound(sg_id=sg_id)

        super(TricircleSecurityGroupMixin,
              self).delete_security_group_rule(q_context, _id)
        t_context = context.get_context_from_neutron_context(q_context)

        try:
            self.xjob_handler.configure_security_group_rules(
                t_context, rule['project_id'])
        except Exception:
            raise n_exceptions.BottomPodOperationFailure(
                resource='security group rule', region_name='')
