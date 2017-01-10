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

from sqlalchemy import orm

from neutron_lib import constants

from neutron.db.models import l3 as l3_models
from neutron.db import models_v2
from neutron.extensions import l3
from neutron.services.l3_router import l3_router_plugin


class TricircleL3Plugin(l3_router_plugin.L3RouterPlugin):
    # Override the original implementation to allow associating a floating ip
    # to a port whose network is not attached to the router. Tricircle will
    # configures extra routes to guarantee packets can reach the port.
    def get_router_for_floatingip(self, context, internal_port,
                                  internal_subnet, external_network_id):
        """Find a router to handle the floating-ip association.

        :param internal_port: The port for the fixed-ip.
        :param internal_subnet: The subnet for the fixed-ip.
        :param external_network_id: The external network for floating-ip.

        :raises: ExternalGatewayForFloatingIPNotFound if no suitable router
        is found.
        """
        router_port = l3_models.RouterPort
        gw_port = orm.aliased(models_v2.Port, name="gw_port")
        router_port_qry = context.session.query(
            router_port.router_id
        ).join(gw_port, gw_port.device_id == router_port.router_id).filter(
            gw_port.network_id == external_network_id,
            gw_port.device_owner == constants.DEVICE_OWNER_ROUTER_GW
        ).distinct()

        first_router_id = None
        for router in router_port_qry:
            if not first_router_id:
                first_router_id = router.router_id
        if first_router_id:
            return first_router_id

        raise l3.ExternalGatewayForFloatingIPNotFound(
            subnet_id=internal_subnet['id'],
            external_network_id=external_network_id,
            port_id=internal_port['id'])
