# Copyright 2018 Huazhong University of Science and Technology.
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
import re

from neutron.services.segments.plugin import Plugin
from neutron_lib.api.definitions import availability_zone as az_def
from neutron_lib.api.definitions import provider_net
from neutron_lib.db import api as db_api
from neutron_lib.exceptions import availability_zone as az_exc

import tricircle.common.client as t_client
from tricircle.common import constants
import tricircle.common.context as t_context
from tricircle.common import xrpcapi
from tricircle.db import core
from tricircle.db import models
from tricircle.network.central_plugin import TricirclePlugin
from tricircle.network import helper


LOG = log.getLogger(__name__)


class TricircleSegmentPlugin(Plugin):
    def __init__(self):
        super(TricircleSegmentPlugin, self).__init__()
        self.xjob_handler = xrpcapi.XJobAPI()
        self.clients = {}
        self.central_plugin = TricirclePlugin()
        self.helper = helper.NetworkHelper(self)

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    def get_segment(self, context, sgmt_id, fields=None, tenant_id=None):
        return super(TricircleSegmentPlugin, self).get_segment(
            context, sgmt_id)

    def get_segments(self, context, filters=None, fields=None,
                     sorts=None, limit=None, marker=None,
                     page_reverse=False):
        return super(TricircleSegmentPlugin, self).get_segments(
            context, filters, fields, sorts, limit, marker, page_reverse)

    @staticmethod
    def _validate_availability_zones(context, az_list):
        if not az_list:
            return
        t_ctx = t_context.get_context_from_neutron_context(context)
        with db_api.CONTEXT_WRITER.using(context):
            pods = core.query_resource(t_ctx, models.Pod, [], [])
            az_set = set(az_list)

            known_az_set = set([pod['az_name'] for pod in pods])
            known_az_set = known_az_set | set(
                [pod['region_name'] for pod in pods])

            diff = az_set - known_az_set
            if diff:
                raise az_exc.AvailabilityZoneNotFound(
                    availability_zone=diff.pop())

    def create_segment(self, context, segment):
        """Create a segment."""
        segment_data = segment['segment']
        segment_name = segment_data.get('name')

        # if configed enable_l3_route_network,
        # will create real external network for each segment
        if cfg.CONF.tricircle.enable_l3_route_network:
            match_obj = re.match(constants.SEGMENT_NAME_PATTERN,
                                 segment_name)
            if match_obj:
                match_list = match_obj.groups()
                region_name = match_list[0]
                self._validate_availability_zones(context,
                                                  [region_name])
                # create segment for maintaining the relationship
                # between routed net and real external net
                segment_db = super(TricircleSegmentPlugin, self).\
                    create_segment(context, segment)

                # prepare real external network in central and bottom
                net_data = {
                    'tenant_id': segment_data.get('tenant_id'),
                    'name': segment_name,
                    'shared': False,
                    'admin_state_up': True,
                    az_def.AZ_HINTS: [region_name],
                    provider_net.PHYSICAL_NETWORK:
                        segment_data.get('physical_network'),
                    provider_net.NETWORK_TYPE:
                        segment_data.get('network_type'),
                    'router:external': True
                }
                self.central_plugin.create_network(
                    context, {'network': net_data})

                return segment_db
            else:
                return super(TricircleSegmentPlugin, self).create_segment(
                    context, segment)
        else:
            return super(TricircleSegmentPlugin, self).create_segment(
                context, segment)

    def delete_segment(self, context, uuid, for_net_delete=False):
        segment_dict = self.get_segment(context, uuid)
        segment_name = segment_dict['name']

        # if enable l3 routed network and segment name starts
        # with 'newl3-' need to delete bottom router
        # and bottom external network
        if cfg.CONF.tricircle.enable_l3_route_network and \
                segment_name and \
                segment_name.startswith(constants.PREFIX_OF_SEGMENT_NAME):

            # delete real external network
            net_filter = {'name': [segment_name]}
            nets = self.central_plugin.get_networks(context, net_filter)
            if len(nets):
                self.central_plugin.delete_network(context, nets[0]['id'])

            return super(TricircleSegmentPlugin, self).delete_segment(
                context, uuid)
        else:
            return super(TricircleSegmentPlugin, self).delete_segment(
                context, uuid)
