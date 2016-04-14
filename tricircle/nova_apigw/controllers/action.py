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
import tricircle.db.api as db_api

LOG = logging.getLogger(__name__)


class ActionController(rest.RestController):

    def __init__(self, project_id, server_id):
        self.project_id = project_id
        self.server_id = server_id
        self.clients = {constants.TOP: t_client.Client()}
        self.handle_map = {
            'os-start': self._handle_start,
            'os-stop': self._handle_stop
        }

    def _get_client(self, pod_name=constants.TOP):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    def _handle_start(self, context, pod_name, body):
        client = self._get_client(pod_name)
        return client.action_servers(context, 'start', self.server_id)

    def _handle_stop(self, context, pod_name, body):
        client = self._get_client(pod_name)
        return client.action_servers(context, 'stop', self.server_id)

    @staticmethod
    def _format_error(code, message):
        pecan.response.status = code
        # format error message in this form so nova client can
        # correctly parse it
        return {'Error': {'message': message, 'code': code}}

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        action_handle = None
        action_type = None
        for _type in self.handle_map:
            if _type in kw:
                action_handle = self.handle_map[_type]
                action_type = _type
        if not action_handle:
            return self._format_error(400, _('Server action not supported'))

        server_mappings = db_api.get_bottom_mappings_by_top_id(
            context, self.server_id, constants.RT_SERVER)
        if not server_mappings:
            return self._format_error(404, _('Server not found'))

        pod_name = server_mappings[0][0]['pod_name']
        try:
            resp, body = action_handle(context, pod_name, kw)
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Action %(action)s on server %(server_id)s fails') % {
                'action': action_type,
                'server_id': self.server_id}
            if hasattr(e, 'code'):
                code = e.code
            ex_message = str(e)
            if ex_message:
                message = ex_message
            LOG.error(message)
            return self._format_error(code, message)
