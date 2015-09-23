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


import oslo_log.helpers as log_helpers
from oslo_log import log

from neutron.extensions import portbindings

from neutron.common import exceptions as n_exc
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import agentschedulers_db
from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
from neutron.db import l3_db
from neutron.db import portbindings_db
from neutron.db import securitygroups_db
from neutron.i18n import _LI
from tricircle.common import cascading_networking_api as c_net_api
from tricircle.networking_tricircle import rpc as c_net_rpc

LOG = log.getLogger(__name__)


class TricirclePlugin(db_base_plugin_v2.NeutronDbPluginV2,
                      securitygroups_db.SecurityGroupDbMixin,
                      l3_db.L3_NAT_dbonly_mixin,
                      external_net_db.External_net_db_mixin,
                      portbindings_db.PortBindingMixin,
                      extradhcpopt_db.ExtraDhcpOptMixin,
                      agentschedulers_db.DhcpAgentSchedulerDbMixin):

    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    supported_extension_aliases = ["quotas",
                                   "extra_dhcp_opt",
                                   "binding",
                                   "security-group",
                                   "external-net",
                                   "router"]

    def __init__(self):
        super(TricirclePlugin, self).__init__()
        LOG.info(_LI("Starting TricirclePlugin"))
        self.vif_type = portbindings.VIF_TYPE_OVS
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}

        self._cascading_rpc_api = c_net_api.CascadingNetworkingNotifyAPI()

        self._setup_rpc()

    def _setup_rpc(self):
        self.endpoints = [c_net_rpc.RpcCallbacks()]

    @log_helpers.log_method_call
    def start_rpc_listeners(self):
        self.topic = topics.PLUGIN
        self.conn = n_rpc.create_connection(new=True)
        self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        return self.conn.consume_in_threads()

    def create_network(self, context, network):
        with context.session.begin(subtransactions=True):
            result = super(TricirclePlugin, self).create_network(
                context,
                network)
            self._process_l3_create(context, result, network['network'])
        LOG.debug("New network %s ", network['network']['name'])
        if self._cascading_rpc_api:
            self._cascading_rpc_api.create_network(context, network)
        return result

    def delete_network(self, context, network_id):
        net = super(TricirclePlugin, self).delete_network(
            context,
            network_id)
        if self._cascading_rpc_api:
            self._cascading_rpc_api.delete_network(context, network_id)
        return net

    def update_network(self, context, network_id, network):
        with context.session.begin(subtransactions=True):
            net = super(TricirclePlugin, self).update_network(
                context,
                network_id,
                network)
        if self._cascading_rpc_api:
            self._cascading_rpc_api.delete_network(
                context,
                network_id,
                network)
        return net

    def create_port(self, context, port):
        with context.session.begin(subtransactions=True):
            neutron_db = super(TricirclePlugin, self).create_port(
                context, port)
            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         neutron_db)

            neutron_db[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL
        # Call create port to the cascading API
        LOG.debug("New port  %s ", port['port'])
        if self._cascading_rpc_api:
            self._cascading_rpc_api.create_port(context, port)
        return neutron_db

    def delete_port(self, context, port_id, l3_port_check=True):
        with context.session.begin():
            ret_val = super(TricirclePlugin, self).delete_port(
                context, port_id)
        if self._cascading_rpc_api:
            self._cascading_rpc_api.delete_port(context,
                                                port_id,
                                                l3_port_checki=True)

        return ret_val

    def update_port_status(self, context, port_id, port_status):
        with context.session.begin(subtransactions=True):
            try:
                port = super(TricirclePlugin, self).get_port(context, port_id)
                port['status'] = port_status
                neutron_db = super(TricirclePlugin, self).update_port(
                    context, port_id, {'port': port})
            except n_exc.PortNotFound:
                LOG.debug("Port %(port)s update to %(status)s not found",
                          {'port': port_id, 'status': port_status})
                return None
        return neutron_db

    def extend_port_dict_binding(self, port_res, port_db):
        super(TricirclePlugin, self).extend_port_dict_binding(
            port_res, port_db)
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL
