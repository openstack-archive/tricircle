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
from oslo_log import log

from networking_sfc.db import sfc_db
from networking_sfc.services.flowclassifier.drivers import base as fc_driver

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


class TricircleFcDriver(fc_driver.FlowClassifierDriverBase):

    def __init__(self):
        self.xjob_handler = xrpcapi.XJobAPI()
        self.clients = {}

    def initialize(self):
        pass

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    @log_helpers.log_method_call
    def create_flow_classifier(self, context):
        pass

    @log_helpers.log_method_call
    def update_flow_classifier(self, context):
        pass

    @log_helpers.log_method_call
    def delete_flow_classifier(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        flowclassifier_id = context.current['id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, flowclassifier_id, t_constants.RT_FLOW_CLASSIFIER)
        for b_pod, b_classifier_id in mappings:
            b_region_name = b_pod['region_name']
            b_client = self._get_client(b_region_name)
            try:
                b_client.delete_flow_classifiers(t_ctx, b_classifier_id)
            except client_exceptions.NotFound:
                LOG.debug(('flow classifier: %(classifier_id)s not found, '
                           'region name: %(name)s'),
                          {'classifier_id': flowclassifier_id,
                           'name': b_region_name})
            db_api.delete_mappings_by_bottom_id(t_ctx, b_classifier_id)

    def delete_flow_classifier_precommit(self, context):
        t_ctx = t_context.get_context_from_neutron_context(
            context._plugin_context)
        flowclassifier_id = context.current['id']
        db_api.create_recycle_resource(
            t_ctx, flowclassifier_id, t_constants.RT_FLOW_CLASSIFIER,
            t_ctx.project_id)

    def _get_chain_id_by_flowclassifier_id(
            self, context, fc_plugin, flowclassifier_id):
        chain_classifier_assoc = model_query.query_with_hooks(
            context, sfc_db.ChainClassifierAssoc).filter_by(
            flowclassifier_id=flowclassifier_id).first()
        if chain_classifier_assoc:
            return chain_classifier_assoc['portchain_id']
        return None

    def _get_net_id_by_portchain_id(self, context, portchain_id):
        sfc_plugin = directory.get_plugin('sfc')
        port_chain = sfc_plugin.get_port_chain(context, portchain_id)
        if not port_chain:
            raise n_exceptions.PortChainNotFound(portchain_id=portchain_id)
        port_pairs = sfc_plugin.get_port_pairs(
            context, {'portpairgroup_id': port_chain['port_pair_groups']})
        if not port_pairs:
            raise n_exceptions.PortPairsNotFoundForPortPairGroup(
                portpairgroup_id=port_chain['port_pair_groups'])
        core_plugin = directory.get_plugin()
        port = super(central_plugin.TricirclePlugin, core_plugin
                     ).get_port(context, port_pairs[0]['ingress'])
        if not port:
            raise n_exceptions.PortNotFound(port_id=port_pairs[0]['ingress'])
        return port['network_id']

    def update_flow_classifier_precommit(self, context):
        plugin_context = context._plugin_context
        t_ctx = t_context.get_context_from_neutron_context(plugin_context)
        flowclassifier = context.current
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, flowclassifier['id'], t_constants.RT_FLOW_CLASSIFIER)
        if mappings:
            portchain_id = self._get_chain_id_by_flowclassifier_id(
                plugin_context, context._plugin, flowclassifier['id'])
            if not portchain_id:
                raise n_exceptions.PortChainNotFoundForFlowClassifier(
                    flowclassifier_id=flowclassifier['id'])
            net_id = self._get_net_id_by_portchain_id(plugin_context,
                                                      portchain_id)
            if not net_id:
                raise n_exceptions.NetNotFoundForPortChain(
                    portchain_id=portchain_id)
            self.xjob_handler.sync_service_function_chain(
                t_ctx, flowclassifier['project_id'], portchain_id,
                net_id, t_constants.POD_NOT_SPECIFIED)

    @log_helpers.log_method_call
    def create_flow_classifier_precommit(self, context):
        pass
