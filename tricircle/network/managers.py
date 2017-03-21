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

from oslo_config import cfg
from oslo_log import log

from neutron.plugins.ml2 import managers

LOG = log.getLogger(__name__)


class TricircleTypeManager(managers.TypeManager):

    def __init__(self):
        self.drivers = {}

        # NOTE(zhiyuan) here we call __init__ of super class's super class,
        # which is NamedExtensionManager's __init__ to bypass initialization
        # process of ml2 type manager
        super(managers.TypeManager, self).__init__(
            'tricircle.network.type_drivers',
            cfg.CONF.tricircle.type_drivers,
            invoke_on_load=True)
        LOG.info('Loaded type driver names: %s', self.names())

        self._register_types()
        self._check_tenant_network_types(
            cfg.CONF.tricircle.tenant_network_types)
        self._check_bridge_network_type(
            cfg.CONF.tricircle.bridge_network_type)

    def _check_bridge_network_type(self, bridge_network_type):
        if not bridge_network_type:
            return
        if bridge_network_type == 'local':
            LOG.error("Local is not a valid bridge network type. "
                      "Service terminated!", bridge_network_type)
            raise SystemExit(1)

        type_set = set(self.tenant_network_types)
        if bridge_network_type not in type_set:
            LOG.error("Bridge network type %s is not registered. "
                      "Service terminated!", bridge_network_type)
            raise SystemExit(1)

    def _register_types(self):
        for ext in self:
            network_type = ext.obj.get_type()
            if network_type not in self.drivers:
                self.drivers[network_type] = ext

    def create_network_segments(self, context, network, tenant_id):
        segments = self._process_provider_create(network)
        session = context.session
        with session.begin(subtransactions=True):
            network_id = network['id']
            if segments:
                for segment_index, segment in enumerate(segments):
                    segment = self.reserve_provider_segment(
                        context, segment)
                    self._add_network_segment(context, network_id, segment,
                                              segment_index)
            else:
                segment = self._allocate_tenant_net_segment(context)
                self._add_network_segment(context, network_id, segment)
