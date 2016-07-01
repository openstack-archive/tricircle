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
from oslo_log import log as logging
import oslo_messaging as messaging

import rpc
from serializer import TricircleSerializer as Serializer
import topics

from tricircle.common import constants


CONF = cfg.CONF

rpcapi_cap_opt = cfg.StrOpt('xjobapi',
                            default='1.0',
                            help='Set a version cap for messages sent to the'
                                 'xjob api in any service')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')

LOG = logging.getLogger(__name__)


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
        serializer = Serializer()
        self.client = rpc.get_client(target,
                                     version_cap=version_cap,
                                     serializer=serializer)

    # to do the version compatibility for future purpose
    def _determine_version_cap(self, target):
        version_cap = 1.0
        return version_cap

    def test_rpc(self, ctxt, payload):
        return self.client.call(ctxt, 'test_rpc', payload=payload)

    def setup_bottom_router(self, ctxt, net_id, router_id, pod_id):
        combine_id = '%s#%s#%s' % (pod_id, router_id, net_id)
        self.client.prepare(exchange='openstack').cast(
            ctxt, 'setup_bottom_router',
            payload={constants.JT_ROUTER_SETUP: combine_id})

    def configure_extra_routes(self, ctxt, router_id):
        # NOTE(zhiyuan) this RPC is called by plugin in Neutron server, whose
        # control exchange is "neutron", however, we starts xjob without
        # specifying its control exchange, so the default value "openstack" is
        # used, thus we need to pass exchange as "openstack" here.
        self.client.prepare(exchange='openstack').cast(
            ctxt, 'configure_extra_routes',
            payload={constants.JT_ROUTER: router_id})

    def delete_server_port(self, ctxt, port_id):
        self.client.prepare(exchange='openstack').cast(
            ctxt, 'delete_server_port',
            payload={constants.JT_PORT_DELETE: port_id})
