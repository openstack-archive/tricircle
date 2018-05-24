# Copyright 2017 Hunan University.
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


from neutron.services.qos import qos_plugin
from neutron_lib.api.definitions import portbindings
from neutron_lib.objects import registry as obj_reg
from oslo_log import log

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.db.api as db_api

LOG = log.getLogger(__name__)


class TricircleQosPlugin(qos_plugin.QoSPlugin):

    def __init__(self):
        super(TricircleQosPlugin, self).__init__()
        self.clients = {'top': t_client.Client()}

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    def _get_ports_with_policy(self, context, policy):
        networks_ids = policy.get_bound_networks()

        ports_with_net_policy = obj_reg.load_class('Port').get_objects(
            context, network_id=networks_ids)

        # Filter only these ports which don't have overwritten policy
        ports_with_net_policy = [
            port for port in ports_with_net_policy if
            port.qos_policy_id is None
        ]

        ports_ids = policy.get_bound_ports()
        ports_with_policy = obj_reg.load_class('Port').get_objects(
            context, id=ports_ids)
        t_ports = list(set(ports_with_policy + ports_with_net_policy))

        t_ctx = t_context.get_context_from_neutron_context(context)
        for t_port in t_ports:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, t_port.id, t_constants.RT_PORT)
            if mappings:
                b_pod, b_port_id = mappings[0]
                b_region_name = b_pod['region_name']
                b_client = self._get_client(region_name=b_region_name)
                b_port = b_client.get_ports(t_ctx, b_port_id)
                new_binding = obj_reg.new_instance(
                    'PortBinding',
                    port_id=t_port.id,
                    vif_type=b_port.get('binding:vif_type',
                                        portbindings.VIF_TYPE_UNBOUND),
                    vnic_type=b_port.get('binding:vnic_type',
                                         portbindings.VNIC_NORMAL)
                )
                t_port.binding = new_binding
            else:
                new_binding = obj_reg.new_instance(
                    'PortBinding',
                    port_id=t_port.id,
                    vif_type=portbindings.VIF_TYPE_UNBOUND,
                    vnic_type=portbindings.VNIC_NORMAL
                )
                t_port.binding = new_binding

        return t_ports
