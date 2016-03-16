# Copyright (c) 2015 Huawei Tech. Co., Ltd.
# All Rights Reserved.
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

import pecan
from pecan import expose
from pecan import rest
import re

from oslo_log import log as logging

import tricircle.common.client as t_client
from tricircle.common import constants
import tricircle.common.context as t_context
from tricircle.common.i18n import _LE
import tricircle.db.api as db_api

LOG = logging.getLogger(__name__)


class VolumeController(rest.RestController):

    def __init__(self, project_id, server_id):
        self.project_id = project_id
        self.server_id = server_id
        self.clients = {'top': t_client.Client()}

    def _get_client(self, pod_name='top'):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if 'volumeAttachment' not in kw:
            pecan.abort(400, 'Request body not found')
            return
        body = kw['volumeAttachment']
        if 'volumeId' not in body:
            pecan.abort(400, 'Volume not set')
            return

        server_mappings = db_api.get_bottom_mappings_by_top_id(
            context, self.server_id, constants.RT_SERVER)
        if not server_mappings:
            pecan.abort(404, 'Server not found')
            return
        volume_mappings = db_api.get_bottom_mappings_by_top_id(
            context, body['volumeId'], constants.RT_VOLUME)
        if not volume_mappings:
            pecan.abort(404, 'Volume not found')
            return

        server_pod_name = server_mappings[0][0]['pod_name']
        volume_pod_name = volume_mappings[0][0]['pod_name']
        if server_pod_name != volume_pod_name:
            LOG.error(_LE('Server %(server)s is in pod %(server_pod)s and '
                          'volume %(volume)s is in pod %(volume_pod)s, which '
                          'are not the same.'),
                      {'server': self.server_id,
                       'server_pod': server_pod_name,
                       'volume': body['volumeId'],
                       'volume_pod': volume_pod_name})
            pecan.abort(400, 'Server and volume not in the same pod')
            return

        device = None
        if 'device' in body:
            device = body['device']
            # this regular expression is copied from nova/block_device.py
            match = re.match('(^/dev/x{0,1}[a-z]{0,1}d{0,1})([a-z]+)[0-9]*$',
                             device)
            if not match:
                pecan.abort(400, 'Invalid device path')
                return

        client = self._get_client(server_pod_name)
        volume = client.action_server_volumes(
            context, 'create_server_volume',
            server_mappings[0][1], volume_mappings[0][1], device)
        return {'volumeAttachment': volume.to_dict()}
