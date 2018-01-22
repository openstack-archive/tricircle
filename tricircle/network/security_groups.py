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

from oslo_log import log

from neutron.db import securitygroups_db

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
from tricircle.common import context
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common import xrpcapi
from tricircle.db import core
from tricircle.db import models
import tricircle.network.exceptions as n_exceptions
from tricircle.network import utils as nt_utils

LOG = log.getLogger(__name__)


class TricircleSecurityGroupMixin(securitygroups_db.SecurityGroupDbMixin):

    def __init__(self):
        super(TricircleSecurityGroupMixin, self).__init__()
        self.xjob_handler = xrpcapi.XJobAPI()
        self.clients = {}

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key] and str(rule1[key]) != str(rule2[key]):
                return False
        return True

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

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

    def get_security_group(self, context, sg_id, fields=None, tenant_id=None):
        dict_param = {'resource_id': sg_id, 'resource_type': t_constants.RT_SG}
        security_group_list = None
        try:
            security_group_list = nt_utils.check_resource_not_in_deleting(
                context, dict_param)
        except t_exceptions.ResourceNotFound:
            raise

        if security_group_list:
            return security_group_list
        else:
            return super(TricircleSecurityGroupMixin, self).\
                get_security_group(context, sg_id)

    def delete_security_group(self, context, sg_id):
        LOG.debug("lyman--enter delete security group")
        t_ctx = t_context.get_context_from_neutron_context(context)
        # check the sg whether in security group
        super(TricircleSecurityGroupMixin, self).\
            get_security_group(context, sg_id)
        # check the sg whether in deleting
        dict_para = {'resource_id': sg_id, 'resource_type': t_constants.RT_SG}

        nt_utils.check_resource_not_in_deleting(context, dict_para)
        try:
            with t_ctx.session.begin():
                core.create_resource(
                    t_ctx, models.DeletingResources, dict_para)
            for pod, bottom_security_group_id in (
                    self.helper.get_real_shadow_resource_iterator(
                        t_ctx, t_constants.RT_SG, sg_id)):
                self._get_client(pod['region_name']). \
                    delete_security_groups(t_ctx, bottom_security_group_id)
                with t_ctx.session.begin():
                    core.delete_resources(
                        t_ctx, models.ResourceRouting,
                        filters=[{'key': 'top_id', 'comparator': 'eq',
                                  'value': sg_id},
                                 {'key': 'pod_id', 'comparator': 'eq',
                                  'value': pod['pod_id']}])

            with t_ctx.session.begin():
                super(TricircleSecurityGroupMixin, self). \
                    delete_security_group(context, sg_id)
        except Exception:
            raise
        finally:
            with t_ctx.session.begin():
                core.delete_resources(
                    t_ctx, models.DeletingResources,
                    filters=[{
                        'key': 'resource_id', 'comparator': 'eq',
                        'value': sg_id}])
