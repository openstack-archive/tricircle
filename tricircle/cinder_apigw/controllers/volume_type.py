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
from oslo_utils import uuidutils

import tricircle.common.context as t_context
from tricircle.common import exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common import utils
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models

LOG = logging.getLogger(__name__)


class VolumeTypeController(rest.RestController):

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    def _metadata_refs(self, metadata_dict, meta_class):
        metadata_refs = []

        if metadata_dict:
            for k, v in metadata_dict.items():
                metadata_ref = meta_class()
                metadata_ref['key'] = k
                metadata_ref['value'] = v
                metadata_refs.append(metadata_ref)
        return metadata_refs

    @expose(generic=True, template='json')
    def post(self, **kw):
        """Creates volume types."""
        context = t_context.extract_context_from_environ()

        if not context.is_admin:
            return utils.format_cinder_error(
                403, _("Policy doesn't allow volume_extension:types_manage "
                       "to be performed."))

        if 'volume_type' not in kw:
            return utils.format_cinder_error(
                400, _("Missing required element 'volume_type' in "
                       "request body."))

        projects = []

        if self.tenant_id is not None:
            projects = [self.tenant_id]

        vol_type = kw['volume_type']
        name = vol_type.get('name', None)
        description = vol_type.get('description')
        specs = vol_type.get('extra_specs', {})
        is_public = vol_type.pop('os-volume-type-access:is_public', True)

        if name is None or len(name.strip()) == 0:
            return utils.format_cinder_error(
                400, _("Volume type name can not be empty."))

        try:
            utils.check_string_length(name, 'Type name',
                                      min_len=1, max_len=255)
        except exceptions.InvalidInput as e:
            return utils.format_cinder_error(
                400, e.message)

        if description is not None:
            try:
                utils.check_string_length(description, 'Type description',
                                          min_len=0, max_len=255)
            except exceptions.InvalidInput as e:
                return utils.format_cinder_error(400, e.message)

        if not utils.is_valid_boolstr(is_public):
            msg = _("Invalid value '%(is_public)s' for is_public. "
                    "Accepted values: True or False.") % {
                'is_public': is_public}
            return utils.format_cinder_error(400, msg)

        vol_type['extra_specs'] = specs
        vol_type['is_public'] = is_public
        vol_type['id'] = uuidutils.generate_uuid()

        session = core.get_session()
        with session.begin():
            try:
                db_api.volume_type_get_by_name(context, vol_type['name'],
                                               session)
                return utils.format_cinder_error(
                    409, _("Volume Type %(id)s already exists.") % {
                        'id': vol_type['id']})
            except exceptions.VolumeTypeNotFoundByName:
                pass
            try:
                extra_specs = vol_type['extra_specs']
                vol_type['extra_specs'] = \
                    self._metadata_refs(vol_type.get('extra_specs'),
                                        models.VolumeTypeExtraSpecs)
                volume_type_ref = models.VolumeTypes()
                volume_type_ref.update(vol_type)
                session.add(volume_type_ref)
                for project in set(projects):
                    access_ref = models.VolumeTypeProjects()
                    access_ref.update({"volume_type_id": volume_type_ref.id,
                                       "project_id": project})
                    access_ref.save(session=session)
            except Exception as e:
                LOG.exception(_LE('Fail to create volume type: %(name)s,'
                                  '%(exception)s'),
                              {'name': vol_type['name'],
                               'exception': e})
                return utils.format_cinder_error(
                    500, _('Fail to create volume type'))

            vol_type['extra_specs'] = extra_specs
            return {'volume_type': vol_type}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        """Retrieves single volume type by id.

        :param _id: id of volume type to be retrieved
        :returns: retrieved volume type
        """
        context = t_context.extract_context_from_environ()
        try:
            result = db_api.volume_type_get(context, _id)
        except exceptions.VolumeTypeNotFound as e:
            return utils.format_cinder_error(404, e.message)
        except Exception as e:
            LOG.exception(_LE('Volume type not found: %(id)s,'
                              '%(exception)s'),
                          {'id': _id,
                           'exception': e})
            return utils.format_cinder_error(
                404, _("Volume type %(id)s could not be found.") % {
                    'id': _id})
        return {'volume_type': result}

    @expose(generic=True, template='json')
    def get_all(self):
        """Get all non-deleted volume_types."""
        filters = {}
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            # Only admin has query access to all volume types
            filters['is_public'] = True
        try:
            list_result = db_api.volume_type_get_all(context,
                                                     list_result=True,
                                                     filters=filters)
        except Exception as e:
            LOG.exception(_LE('Fail to retrieve volume types: %(exception)s'),
                          {'exception': e})
            return utils.format_cinder_error(500, e)

        return {'volume_types': list_result}

    @expose(generic=True, template='json')
    def put(self, _id, **kw):
        """Update volume type by id.

        :param _id: id of volume type to be updated
        :param kw: dictionary of values to be updated
        :returns: updated volume type
        """
        context = t_context.extract_context_from_environ()

        if not context.is_admin:
            return utils.format_cinder_error(
                403, _("Policy doesn't allow volume_extension:types_manage "
                       "to be performed."))

        if 'volume_type' not in kw:
            return utils.format_cinder_error(
                400, _("Missing required element 'volume_type' in "
                       "request body."))

        values = kw['volume_type']
        name = values.get('name')
        description = values.get('description')
        is_public = values.get('os-volume-type-access:is_public')

        # Name and description can not be both None.
        # If name specified, name can not be empty.
        if name and len(name.strip()) == 0:
            return utils.format_cinder_error(
                400, _("Volume type name can not be empty."))

        if name is None and description is None and is_public is None:
            msg = _("Specify volume type name, description, is_public or "
                    "a combination thereof.")
            return utils.format_cinder_error(400, msg)

        if is_public is not None and not utils.is_valid_boolstr(is_public):
            msg = _("Invalid value '%(is_public)s' for is_public. Accepted "
                    "values: True or False.") % {'is_public': is_public}
            return utils.format_cinder_error(400, msg)

        if name:
            try:
                utils.check_string_length(name, 'Type name',
                                          min_len=1, max_len=255)
            except exceptions.InvalidInput as e:
                return utils.format_cinder_error(400, e.message)

        if description is not None:
            try:
                utils.check_string_length(description, 'Type description',
                                          min_len=0, max_len=255)
            except exceptions.InvalidInput as e:
                return utils.format_cinder_error(400, e.message)

        try:
            type_updated = \
                db_api.volume_type_update(context, _id,
                                          dict(name=name,
                                               description=description,
                                               is_public=is_public))
        except exceptions.VolumeTypeNotFound as e:
            return utils.format_cinder_error(404, e.message)
        except exceptions.VolumeTypeExists as e:
            return utils.format_cinder_error(409, e.message)
        except exceptions.VolumeTypeUpdateFailed as e:
            return utils.format_cinder_error(500, e.message)
        except Exception as e:
            LOG.exception(_LE('Fail to update volume type: %(name)s,'
                              '%(exception)s'),
                          {'name': values['name'],
                           'exception': e})
            return utils.format_cinder_error(
                500, _("Fail to update volume type."))
        return {'volume_type': type_updated}

    @expose(generic=True, template='json')
    def delete(self, _id):
        """Marks volume types as deleted.

        :param _id: id of volume type to be deleted
        """
        context = t_context.extract_context_from_environ()

        if not context.is_admin:
            return utils.format_cinder_error(
                403, _("Policy doesn't allow volume_extension:types_manage "
                       "to be performed."))

        session = core.get_session()
        with session.begin():
            try:
                db_api.volume_type_get(context, _id, session)
            except exceptions.VolumeTypeNotFound as e:
                return utils.format_cinder_error(404, e.message)
            try:
                db_api.volume_type_delete(context, _id, session)
            except Exception as e:
                LOG.exception(_LE('Fail to update volume type: %(id)s,'
                                  '%(exception)s'),
                              {'id': _id,
                               'exception': e})
                return utils.format_cinder_error(
                    500, _('Fail to delete volume type.'))

        pecan.response.status = 202
        return pecan.response
