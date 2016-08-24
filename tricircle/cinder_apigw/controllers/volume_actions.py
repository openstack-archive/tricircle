# Copyright 2016 OpenStack Foundation.
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
from tricircle.common.i18n import _LE
from tricircle.common import utils
import tricircle.db.api as db_api

LOG = logging.getLogger(__name__)


class VolumeActionController(rest.RestController):

    def __init__(self, project_id, volume_id):
        self.project_id = project_id
        self.volume_id = volume_id
        self.clients = {constants.TOP: t_client.Client()}
        self.handle_map = {
            'os-attach': self._attach,
            'os-extend': self._extend,
            'os-reset_status': self._reset_status,
            'os-set_image_metadata': self._set_image_metadata,
            'os-unset_image_metadata': self._unset_image_metadata,
            'os-show_image_metadata': self._show_image_metadata,
            'os-force_detach': self._force_detach
        }

    def _get_client(self, pod_name=constants.TOP):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    def _action(self, context, pod_name, action, info=None, **kwargs):
        """Perform a volume "action".

        :param pod_name: the bottom pod name.
        :param action: volume action name.
        :param info: action parameters body.
        """
        body = {action: info}
        url = '/volumes/%s/action' % self.volume_id
        api = self._get_client(pod_name).get_native_client('volume', context)
        return api.client.post(url, body=body)

    def _attach(self, context, pod_name, kw):
        """Add attachment metadata.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        try:
            mountpoint = None
            if 'mountpoint' in kw['os-attach']:
                mountpoint = kw['os-attach']['mountpoint']
            body = {'mountpoint': mountpoint}
            instance_uuid = None
            if 'instance_uuid' in kw['os-attach']:
                instance_uuid = kw['os-attach']['instance_uuid']
            host_name = None
            if 'host_name' in kw['os-attach']:
                host_name = kw['os-attach']['host_name']
        except (KeyError, ValueError, TypeError):
            msg = _('The server could not comply with the request since '
                    'it is either malformed or otherwise incorrect.')
            return utils.format_cinder_error(400, msg)

        if instance_uuid is not None:
            body.update({'instance_uuid': instance_uuid})
        if host_name is not None:
            body.update({'host_name': host_name})
        return self._action(context, pod_name, 'os-attach', body)

    def _extend(self, context, pod_name, kw):
        """Extend the size of the specified volume.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        try:
            new_size = int(kw['os-extend']['new_size'])
        except (KeyError, ValueError, TypeError):
            msg = _("New volume size must be specified as an integer.")
            return utils.format_cinder_error(400, msg)
        return self._action(context, pod_name, 'os-extend',
                            {'new_size': new_size})

    def _force_detach(self, context, pod_name, kw):
        """Forces a volume to detach

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        body = kw['os-force_detach']
        return self._action(context, pod_name, 'os-force_detach', body)

    def _reset_status(self, context, pod_name, kw):
        """Update the provided volume with the provided state.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        try:
            status = None
            if 'status' in kw['os-reset_status']:
                status = kw['os-reset_status']['status']
            attach_status = None
            if 'attach_status' in kw['os-reset_status']:
                attach_status = kw['os-reset_status']['attach_status']
            migration_status = None
            if 'migration_status' in kw['os-reset_status']:
                migration_status = kw['os-reset_status']['migration_status']
        except (TypeError, KeyError, ValueError):
            msg = _('The server has either erred or is incapable of '
                    'performing the requested operation.')
            return utils.format_cinder_error(500, msg)

        body = {'status': status} if status else {}
        if attach_status:
            body.update({'attach_status': attach_status})
        if migration_status:
            body.update({'migration_status': migration_status})
        return self._action(context, pod_name, 'os-reset_status', body)

    def _set_image_metadata(self, context, pod_name, kw):
        """Set a volume's image metadata.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        try:
            metadata = kw['os-set_image_metadata']['metadata']
        except (KeyError, TypeError):
            msg = _("Malformed request body.")
            return utils.format_cinder_error(400, msg)
        return self._action(context, pod_name, 'os-set_image_metadata',
                            {'metadata': metadata})

    def _unset_image_metadata(self, context, pod_name, kw):
        """Unset specified keys from volume's image metadata.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        try:
            key = kw['os-unset_image_metadata']['key']
        except (KeyError, TypeError):
            msg = _("Malformed request body.")
            return utils.format_cinder_error(400, msg)
        return self._action(
            context, pod_name, 'os-unset_image_metadata', {'key': key})

    def _show_image_metadata(self, context, pod_name, kw):
        """Show a volume's image metadata.

        :param pod_name: the bottom pod name.
        :param kw: request body.
        """
        return self._action(context, pod_name, 'os-show_image_metadata')

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
            return utils.format_cinder_error(
                400, _('Volume action not supported'))

        volume_mappings = db_api.get_bottom_mappings_by_top_id(
            context, self.volume_id, constants.RT_VOLUME)
        if not volume_mappings:
            return utils.format_cinder_error(
                404, _('Volume %(volume_id)s could not be found.') % {
                    'volume_id': self.volume_id
                })

        pod_name = volume_mappings[0][0]['pod_name']

        if action_type == 'os-attach':
            instance_uuid = kw['os-attach'].get('instance_uuid')
            if instance_uuid is not None:
                server_mappings = db_api.get_bottom_mappings_by_top_id(
                    context, instance_uuid, constants.RT_SERVER)
                if not server_mappings:
                    return utils.format_cinder_error(
                        404, _('Server not found'))
                server_pod_name = server_mappings[0][0]['pod_name']
                if server_pod_name != pod_name:
                    LOG.error(_LE('Server %(server)s is in pod %(server_pod)s'
                                  'and volume %(volume)s is in pod'
                                  '%(volume_pod)s, which '
                                  'are not the same.'),
                              {'server': instance_uuid,
                               'server_pod': server_pod_name,
                               'volume': self.volume_id,
                               'volume_pod': pod_name})
                    return utils.format_cinder_error(
                        400, _('Server and volume not in the same pod'))

        try:
            resp, body = action_handle(context, pod_name, kw)
            pecan.response.status = resp.status_code
            if not body:
                return pecan.response
            else:
                return body
        except Exception as e:
            code = 500
            message = _('Action %(action)s on volume %(volume_id)s fails') % {
                'action': action_type,
                'volume_id': self.volume_id}
            if hasattr(e, 'code'):
                code = e.code
            ex_message = str(e)
            if ex_message:
                message = ex_message
            LOG.error(message)
            return utils.format_cinder_error(code, message)
