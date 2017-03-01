# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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
"""
Client side of the job daemon RPC API.
"""

from oslo_config import cfg
import oslo_messaging as messaging

from tricircle.common import constants
from tricircle.common import rpc
from tricircle.common import serializer as t_serializer
from tricircle.common import topics
import tricircle.db.api as db_api


CONF = cfg.CONF

rpcapi_cap_opt = cfg.StrOpt('xjobapi',
                            default='1.0',
                            help='Set a version cap for messages sent to the'
                                 'xjob api in any service')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


class XJobAPI(object):

    """Client side of the xjob rpc API.

    API version history:
        * 1.0 - Initial version.
    """

    VERSION_ALIASES = {
        'mitaka': '1.0',
    }

    def __init__(self):
        super(XJobAPI, self).__init__()

        rpc.init(CONF)
        target = messaging.Target(topic=topics.TOPIC_XJOB, version='1.0')
        upgrade_level = CONF.upgrade_levels.xjobapi
        version_cap = 1.0
        if upgrade_level == 'auto':
            version_cap = self._determine_version_cap(target)
        else:
            version_cap = self.VERSION_ALIASES.get(upgrade_level,
                                                   upgrade_level)
        serializer = t_serializer.TricircleSerializer()
        self.client = rpc.get_client(target,
                                     version_cap=version_cap,
                                     serializer=serializer)

    # to do the version compatibility for future purpose
    def _determine_version_cap(self, target):
        version_cap = 1.0
        return version_cap

    def invoke_method(self, ctxt, project_id, method, _type, id):
        db_api.new_job(ctxt, project_id, _type, id)
        self.client.prepare(exchange='openstack').cast(
            ctxt, method, payload={_type: id})

    def setup_bottom_router(self, ctxt, project_id, net_id, router_id, pod_id):
        self.invoke_method(
            ctxt, project_id, constants.job_handles[constants.JT_ROUTER_SETUP],
            constants.JT_ROUTER_SETUP,
            '%s#%s#%s' % (pod_id, router_id, net_id))

    def configure_route(self, ctxt, project_id, router_id):
        # NOTE(zhiyuan) this RPC is called by plugin in Neutron server, whose
        # control exchange is "neutron", however, we starts xjob without
        # specifying its control exchange, so the default value "openstack" is
        # used, thus we need to pass exchange as "openstack" here.
        self.invoke_method(
            ctxt, project_id,
            constants.job_handles[constants.JT_CONFIGURE_ROUTE],
            constants.JT_CONFIGURE_ROUTE, router_id)

    def delete_server_port(self, ctxt, project_id, port_id, pod_id):
        self.invoke_method(
            ctxt, project_id, constants.job_handles[constants.JT_PORT_DELETE],
            constants.JT_PORT_DELETE,
            '%s#%s' % (pod_id, port_id))

    def configure_security_group_rules(self, ctxt, project_id):
        self.invoke_method(
            ctxt, project_id,
            constants.job_handles[constants.JT_SEG_RULE_SETUP],
            constants.JT_SEG_RULE_SETUP, project_id)

    def update_network(self, ctxt, project_id, network_id, pod_id):
        self.invoke_method(
            ctxt, project_id,
            constants.job_handles[constants.JT_NETWORK_UPDATE],
            constants.JT_NETWORK_UPDATE,
            '%s#%s' % (pod_id, network_id))

    def update_subnet(self, ctxt, project_id, subnet_id, pod_id):
        self.invoke_method(
            ctxt, project_id,
            constants.job_handles[constants.JT_SUBNET_UPDATE],
            constants.JT_SUBNET_UPDATE,
            '%s#%s' % (pod_id, subnet_id))

    def setup_shadow_ports(self, ctxt, project_id, pod_id, net_id):
        self.invoke_method(
            ctxt, project_id,
            constants.job_handles[constants.JT_SHADOW_PORT_SETUP],
            constants.JT_SHADOW_PORT_SETUP, '%s#%s' % (pod_id, net_id))

    def sync_trunk(self, t_ctx, project_id, trunk_id, pod_id):
        self.invoke_method(
            t_ctx, project_id, constants.job_handles[constants.JT_TRUNK_SYNC],
            constants.JT_TRUNK_SYNC, '%s#%s' % (pod_id, trunk_id))
