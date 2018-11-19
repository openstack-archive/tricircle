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

from oslo_log import helpers as log_helpers

from networking_sfc.db import sfc_db
from networking_sfc.services.sfc.drivers import base as sfc_driver

from oslo_log import log

from neutron_lib.db import model_query
from neutron_lib.plugins import directory
from neutronclient.common import exceptions as client_exceptions

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.network import central_plugin
import tricircle.network.exceptions as n_exceptions


LOG = log.getLogger(__name__)


class TricircleSfcDriver(sfc_driver.SfcDriverBase):

    def __init__(self):
        self.xjob_handler = xrpcapi.XJobAPI()
        self.clients = {}

    def initialize(self):
        pass

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    def _get_net_id_by_port_id(self, context, port_id):
        core_plugin = directory.get_plugin()
        port = super(central_plugin.TricirclePlugin, core_plugin
                     ).get_port(context, port_id)
        if not port:
            raise n_exceptions.PortNotFound(port_id=port_id)
        return port['network_id']

    def _get_net_id_by_portpairgroups(self, context,
                                      sfc_plugin, port_pair_groups):
        if not port_pair_groups:
            return None
        port_pairs = sfc_plugin.get_port_pairs(
            context, {'portpairgroup_id': port_pair_groups})
        if not port_pairs:
            return None
        return self._get_net_id_by_port_id(context, port_pairs[0]['ingress'])

    @log_helpers.log_method_call
    def create_port_chain(self, context):
        pass

    @log_helpers.log_method_call
    def create_port_chain_precommit(self, context):
        plugin_context = context._plugin_context
        t_ctx = t_context.get_context_from_neutron_context(plugin_context)
        port_chain = context.current
        net_id = self._get_net_id_by_portpairgroups(
            plugin_context, context._plugin, port_chain['port_pair_groups'])
        if net_id:
            self.xjob_handler.sync_service_function_chain(
                t_ctx, port_chain['project_id'], port_chain['id'], net_id,
                t_constants.POD_NOT_SPECIFIED)

    @log_helpers.log_method_call
    def delete_port_chain(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portchain_id = context.current['id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, portchain_id, t_constants.RT_PORT_CHAIN)
        for b_pod, b_porchain_id in mappings:
            b_region_name = b_pod['region_name']
            b_client = self._get_client(region_name=b_region_name)
            try:
                b_client.delete_port_chains(t_ctx, b_porchain_id)
            except client_exceptions.NotFound:
                LOG.debug(('port chain: %(portchain_id)s not found, '
                           'region name: %(name)s'),
                          {'portchain_id': portchain_id,
                           'name': b_region_name})
            db_api.delete_mappings_by_bottom_id(t_ctx, b_porchain_id)

    @log_helpers.log_method_call
    def delete_port_chain_precommit(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portchain_id = context.current['id']
        db_api.create_recycle_resource(
            t_ctx, portchain_id, t_constants.RT_PORT_CHAIN,
            t_ctx.project_id)

    @log_helpers.log_method_call
    def delete_port_pair_group(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portpairgroup_id = context.current['id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, portpairgroup_id, t_constants.RT_PORT_PAIR_GROUP)
        for b_pod, b_portpairgroup_id in mappings:
            b_region_name = b_pod['region_name']
            b_client = self._get_client(b_region_name)

            try:
                b_client.delete_port_pair_groups(t_ctx, b_portpairgroup_id)
            except client_exceptions.NotFound:
                LOG.debug(('port pair group: %(portpairgroup_id)s not found, '
                           'region name: %(name)s'),
                          {'portpairgroup_id': portpairgroup_id,
                           'name': b_region_name})
            db_api.delete_mappings_by_bottom_id(t_ctx, b_portpairgroup_id)

    def delete_port_pair_group_precommit(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portpairgroup_id = context.current['id']
        db_api.create_recycle_resource(
            t_ctx, portpairgroup_id, t_constants.RT_PORT_PAIR_GROUP,
            t_ctx.project_id)

    @log_helpers.log_method_call
    def delete_port_pair(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portpair_id = context.current['id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, portpair_id, t_constants.RT_PORT_PAIR)
        for b_pod, b_portpair_id in mappings:
            b_region_name = b_pod['region_name']
            b_client = self._get_client(b_region_name)
            try:
                b_client.delete_port_pairs(t_ctx, b_portpair_id)
            except client_exceptions.NotFound:
                LOG.debug(('port pair: %(portpair_id)s not found, '
                           'region name: %(name)s'),
                          {'portpair_id': portpair_id, 'name': b_region_name})
            db_api.delete_mappings_by_bottom_id(t_ctx, b_portpair_id)

    def delete_port_pair_precommit(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        portpair_id = context.current['id']
        db_api.create_recycle_resource(
            t_ctx, portpair_id, t_constants.RT_PORT_PAIR,
            t_ctx.project_id)

    def update_port_chain_precommit(self, context):
        plugin_context = context._plugin_context
        t_ctx = t_context.get_context_from_neutron_context(plugin_context)
        port_chain = context.current
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, port_chain['id'], t_constants.RT_PORT_CHAIN)
        if mappings:
            net_id = self._get_net_id_by_portpairgroups(
                plugin_context, context._plugin,
                port_chain['port_pair_groups'])
            if not net_id:
                return
            self.xjob_handler.sync_service_function_chain(
                t_ctx, port_chain['project_id'], port_chain['id'],
                net_id, t_constants.POD_NOT_SPECIFIED)

    def _get_chain_id_by_group_id(self, context, sfc_plugin, portpairgroup_id):
        chain_group_assoc = model_query.query_with_hooks(
            context, sfc_db.ChainGroupAssoc).filter_by(
            portpairgroup_id=portpairgroup_id).first()
        if chain_group_assoc:
            return chain_group_assoc['portchain_id']
        return None

    def update_port_pair_group_precommit(self, context):
        plugin_context = context._plugin_context
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        port_pair_group = context.current
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, port_pair_group['id'], t_constants.RT_PORT_PAIR_GROUP)
        if mappings:
            portchain_id = self._get_chain_id_by_group_id(
                plugin_context, context._plugin, port_pair_group['id'])
            if port_pair_group['port_pairs']:
                net_id = self._get_net_id_by_portpairgroups(
                    plugin_context, context._plugin, [port_pair_group['id']])
            elif context.original['port_pairs']:
                portpair_id = context.original['port_pairs'][0]
                port_pair = context._plugin._get_port_pair(
                    plugin_context, portpair_id)
                net_id = self._get_net_id_by_port_id(
                    plugin_context, port_pair['ingress'])
            else:
                net_id = ''
            if not portchain_id and not net_id:
                return
            self.xjob_handler.sync_service_function_chain(
                t_ctx, port_pair_group['project_id'], portchain_id, net_id,
                t_constants.POD_NOT_SPECIFIED)

    def _get_chain_id_by_pair_id(self, context, sfc_plugin, portpair_id):
        port_pair = sfc_plugin._get_port_pair(context, portpair_id)
        if not port_pair:
            raise n_exceptions.PortPairNotFound(portpair_id=portpair_id)
        return self._get_chain_id_by_group_id(
            context, sfc_plugin, port_pair['portpairgroup_id'])

    def update_port_pair_precommit(self, context):
        plugin_context = context._plugin_context
        t_ctx = t_context.get_context_from_neutron_context(plugin_context)
        port_pair = context.current
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, port_pair['id'], t_constants.RT_PORT_PAIR)
        if mappings:
            portchain_id = self._get_chain_id_by_pair_id(
                plugin_context, context._plugin, port_pair['id'])
            net_id = self._get_net_id_by_port_id(
                plugin_context, port_pair['ingress'])
            if not portchain_id or not net_id:
                return
            self.xjob_handler.sync_service_function_chain(
                t_ctx, port_pair['project_id'], portchain_id,
                net_id, t_constants.POD_NOT_SPECIFIED)

    @log_helpers.log_method_call
    def update_port_chain(self, context):
        pass

    @log_helpers.log_method_call
    def create_port_pair_group(self, context):
        pass

    @log_helpers.log_method_call
    def update_port_pair_group(self, context):
        pass

    @log_helpers.log_method_call
    def create_port_pair(self, context):
        pass

    @log_helpers.log_method_call
    def update_port_pair(self, context):
        pass
