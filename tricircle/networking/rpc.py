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

import neutron.common.constants as neutron_const
from neutron import manager
from oslo_log import log
import oslo_messaging

LOG = log.getLogger(__name__)


class RpcCallbacks(object):

    target = oslo_messaging.Target(version='1.0')

    def update_port_up(self, context, **kwargs):
        port_id = kwargs.get('port_id')
        plugin = manager.NeutronManager.get_plugin()
        plugin.update_port_status(context, port_id,
                                  neutron_const.PORT_STATUS_ACTIVE)

    def update_port_down(self, context, **kwargs):
        port_id = kwargs.get('port_id')
        plugin = manager.NeutronManager.get_plugin()
        plugin.update_port_status(context, port_id,
                                  neutron_const.PORT_STATUS_DOWN)
