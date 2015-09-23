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

import neutron.common.rpc as neutron_rpc
import neutron.common.topics as neutron_topics
import neutron.context as neutron_context
from oslo_config import cfg
import oslo_messaging


class NetworkingRpcApi(object):
    def __init__(self):
        if not neutron_rpc.TRANSPORT:
            neutron_rpc.init(cfg.CONF)
        target = oslo_messaging.Target(topic=neutron_topics.PLUGIN,
                                       version='1.0')
        self.client = neutron_rpc.get_client(target)

    # adapt tricircle context to neutron context
    def _make_neutron_context(self, context):
        return neutron_context.ContextBase(context.user, context.tenant,
                                           auth_token=context.auth_token,
                                           is_admin=context.is_admin,
                                           request_id=context.request_id,
                                           user_name=context.user_name,
                                           tenant_name=context.tenant_name)

    def update_port_up(self, context, port_id):
        call_context = self.client.prepare()
        return call_context.call(self._make_neutron_context(context),
                                 'update_port_up', port_id=port_id)

    def update_port_down(self, context, port_id):
        call_context = self.client.prepare()
        return call_context.call(self._make_neutron_context(context),
                                 'update_port_down', port_id=port_id)
