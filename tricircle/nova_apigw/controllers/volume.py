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
import tricircle.common.context as t_context
from tricircle.common import exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common import utils
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
            return utils.format_nova_error(
                400, _('volumeAttachment is not set'))
        body = kw['volumeAttachment']
        if 'volumeId' not in body:
            return utils.format_nova_error(
                400, _('Invalid input for field/attribute volumeAttachment'))
        try:
            server_mappings = db_api.get_server_mappings_by_top_id(
                context, self.server_id)
            volume_mappings = db_api.get_volume_mappings_by_top_id(
                context, body['volumeId'])
        except exceptions.ServerMappingsNotFound as e:
            return utils.format_nova_error(404, e.message)
        except exceptions.VolumeMappingsNotFound as e:
            return utils.format_nova_error(404, e.message)
        except Exception as e:
            LOG.exception(_LE('Fail to create volume attachment for given'
                              'server %(server_id)s:'
                              '%(exception)s'),
                          {'server_id': self.server_id,
                           'exception': e})
            return utils.format_nova_error(
                500, _('Fail to create volume attachment'))

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
            return utils.format_nova_error(
                400, _('Server and volume not in the same pod'))

        device = None
        if 'device' in body:
            device = body['device']
            # this regular expression is copied from nova/block_device.py
            match = re.match('(^/dev/x{0,1}[a-z]{0,1}d{0,1})([a-z]+)[0-9]*$',
                             device)
            if not match:
                return utils.format_nova_error(
                    400, _('The supplied device path (%s) is '
                           'invalid.') % device)

        try:
            api = self._get_client(server_pod_name).get_native_client(
                'server_volume', context)
            resp, body = api.client.post(
                "/servers/%s/os-volume_attachments" % self.server_id, body=kw)
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Fail to create volume attachment for given server '
                        '%(server_id)s: %(exception)s') % {
                'server_id': self.server_id,
                'exception': e}
            if hasattr(e, 'code'):
                code = e.code
            LOG.error(message)
            return utils.format_nova_error(code, message)

    @expose(generic=True, template='json')
    def get_one(self, _id):
        """Get the volume attachment identified by the attachment ID.

        :param _id: the ID of volume attachment
        :returns: the volume attachment
        """
        context = t_context.extract_context_from_environ()

        try:
            server_mappings = db_api.get_server_mappings_by_top_id(
                context, self.server_id)
        except exceptions.ServerMappingsNotFound as e:
            return utils.format_nova_error(404, e.message)
        except Exception as e:
            LOG.exception(_LE('Fail to get volume attachment'
                              '%(attachment_id)s from server %(server_id)s:'
                              '%(exception)s'),
                          {'attachment_id': _id,
                           'server_id': self.server_id,
                           'exception': e})
            return utils.format_nova_error(
                500, _('Fail to get volume attachment'))

        server_pod_name = server_mappings[0][0]['pod_name']

        try:
            api = self._get_client(server_pod_name).get_native_client(
                'server_volume', context)
            resp, body = api.client.get(
                "/servers/%s/os-volume_attachments/%s" %
                (self.server_id, _id,))
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Fail to get volume attachment %(attachment_id)s'
                        'from server %(server_id)s: %(exception)s') % {
                'attachment_id': _id,
                'server_id': self.server_id,
                'exception': e}
            if hasattr(e, 'code'):
                code = e.code
            LOG.error(message)
            return utils.format_nova_error(code, message)

    @expose(generic=True, template='json')
    def get_all(self):
        """GET a list of all volume attachments for a server.

        :returns: a list of volume attachments
        """
        context = t_context.extract_context_from_environ()

        try:
            server_mappings = db_api.get_server_mappings_by_top_id(
                context, self.server_id)
        except exceptions.ServerMappingsNotFound as e:
            return utils.format_nova_error(404, e.message)
        except Exception as e:
            LOG.exception(_LE('Fail to get volume attachments of server'
                              '%(server_id)s: %(exception)s'),
                          {'server_id': self.server_id,
                           'exception': e})
            return utils.format_nova_error(
                500, _('Fail to get volume attachments'))

        server_pod_name = server_mappings[0][0]['pod_name']

        try:
            api = self._get_client(server_pod_name).get_native_client(
                'server_volume', context)
            resp, body = api.client.get(
                "/servers/%s/os-volume_attachments" % self.server_id)
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Fail to get volume attachments of server'
                        '%(server_id)s: %(exception)s') % {
                'server_id': self.server_id,
                'exception': e}
            if hasattr(e, 'code'):
                code = e.code
            LOG.error(message)
            return utils.format_nova_error(code, message)

    @expose(generic=True, template='json')
    def delete(self, _id):
        """Detach a volume identified by the attachment ID from the given server ID.

        :param _id: the ID of volume attachment
        """
        context = t_context.extract_context_from_environ()

        try:
            server_mappings = db_api.get_server_mappings_by_top_id(
                context, self.server_id)
        except exceptions.ServerMappingsNotFound as e:
            return utils.format_nova_error(404, e.message)
        except Exception as e:
            LOG.exception(_LE('Fail to delete volume attachment'
                              '%(attachment_id)s from server %(server_id)s:'
                              '%(exception)s'),
                          {'attachment_id': _id,
                           'server_id': self.server_id,
                           'exception': e})
            return utils.format_nova_error(
                500, _('Fail to delete volume attachment'))

        server_pod_name = server_mappings[0][0]['pod_name']

        try:
            api = self._get_client(server_pod_name).get_native_client(
                'server_volume', context)
            resp, body = api.client.delete(
                "/servers/%s/os-volume_attachments/%s" %
                (self.server_id, _id,))
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Fail to delete volume attachments %(attachment_id)s'
                        'from server %(server_id)s: %(exception)s') % {
                'attachment_id': _id,
                'server_id': self.server_id,
                'exception': e}
            if hasattr(e, 'code'):
                code = e.code
            LOG.error(message)
            return utils.format_nova_error(code, message)
