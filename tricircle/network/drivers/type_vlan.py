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

import sys

from oslo_config import cfg
from oslo_log import log

from neutron.plugins.common import utils as plugin_utils
from neutron.plugins.ml2 import driver_api
from neutron.plugins.ml2.drivers import type_vlan

from tricircle.common import constants

LOG = log.getLogger(__name__)


class VLANTypeDriver(type_vlan.VlanTypeDriver):
    def __init__(self):
        super(VLANTypeDriver, self).__init__()

    def _parse_network_vlan_ranges(self):
        try:
            self.network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
                cfg.CONF.tricircle.network_vlan_ranges)
        except Exception:
            LOG.exception('Failed to parse network_vlan_ranges. '
                          'Service terminated!')
            sys.exit(1)
        LOG.info('Network VLAN ranges: %s', self.network_vlan_ranges)

    def get_type(self):
        return constants.NT_VLAN

    def reserve_provider_segment(self, context, segment):
        res = super(VLANTypeDriver,
                    self).reserve_provider_segment(context, segment)
        res[driver_api.NETWORK_TYPE] = constants.NT_VLAN
        return res

    def allocate_tenant_segment(self, context):
        res = super(VLANTypeDriver,
                    self).allocate_tenant_segment(context)
        res[driver_api.NETWORK_TYPE] = constants.NT_VLAN
        return res

    def get_mtu(self, physical):
        pass
