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

from oslo_log import log as logging

import tricircle.common.client as t_client
from tricircle.common import constants
import tricircle.common.context as t_context
from tricircle.common.i18n import _
from tricircle.common import utils
import tricircle.db.api as db_api

LOG = logging.getLogger(__name__)


class ServerIpsController(rest.RestController):

    def __init__(self, project_id, server_id):
        self.project_id = project_id
        self.server_id = server_id
        self.clients = {constants.TOP: t_client.Client()}

    def _get_client(self, pod_name=constants.TOP):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    @expose(generic=True, template='json')
    def get_all(self, **kwargs):
        context = t_context.extract_context_from_environ()

        server_mappings = db_api.get_server_mappings_by_top_id(
            context, self.server_id)
        if not server_mappings:
            return utils.format_nova_error(
                404, _('Server %s could not be found') % self.server_id)
        try:
            server_pod_name = server_mappings[0][0]['pod_name']
            api = self._get_client(server_pod_name).get_native_client(
                constants.RT_SERVER, context)
            resp, body = api.client.get('/servers/%s/ips' % self.server_id)
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Fail to lists assigned IP addresses'
                        '%(server_id)s: %(exception)s') % {
                'server_id': self.server_id,
                'exception': e}
            if hasattr(e, 'code'):
                code = e.code
            LOG.error(message)
            return utils.format_nova_error(code, message)
