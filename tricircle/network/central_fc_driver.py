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

from networking_sfc.services.flowclassifier.drivers import base as fc_driver

from neutronclient.common import exceptions as client_exceptions

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
from tricircle.common import xrpcapi
import tricircle.db.api as db_api


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

    @log_helpers.log_method_call
    def create_flow_classifier_precommit(self, context):
        pass
