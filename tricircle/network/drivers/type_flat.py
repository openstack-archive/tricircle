# Copyright 2017 Huawei Technologies Co., Ltd.
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

from neutron.common import exceptions
from neutron.plugins.ml2 import driver_api
from neutron.plugins.ml2.drivers import type_flat

from tricircle.common import constants

LOG = log.getLogger(__name__)


class FlatTypeDriver(type_flat.FlatTypeDriver):
    def __init__(self):
        super(type_flat.FlatTypeDriver, self).__init__()
        self._parse_networks(cfg.CONF.tricircle.flat_networks)

    def get_type(self):
        return constants.NT_FLAT

    def initialize(self):
        LOG.info("FlatTypeDriver initialization complete")

    def reserve_provider_segment(self, context, segment):
        try:
            res = super(FlatTypeDriver,
                        self).reserve_provider_segment(context, segment)
        except exceptions.FlatNetworkInUse:
            # to support multiple regions sharing the same physical network
            # for external network, we ignore this exception and let local
            # Neutron judge whether the physical network is valid
            res = segment
            res[driver_api.MTU] = None
        res[driver_api.NETWORK_TYPE] = self.get_type()
        return res

    def get_mtu(self, physical_network=None):
        pass
