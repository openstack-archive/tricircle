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

import oslo_db.exception as db_exc

import tricircle.common.context as t_context
from tricircle.common.i18n import _
from tricircle.common import utils
from tricircle.db import core
from tricircle.db import models


class FlavorManageController(rest.RestController):
    # NOTE(zhiyuan) according to nova API reference, flavor creating and
    # deleting should use '/flavors/os-flavor-manage' path, but '/flavors/'
    # also supports this two operations to keep compatible with nova client

    def __init__(self, project_id):
        self.project_id = project_id

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            return utils.format_nova_error(
                403, _("Policy doesn't allow os_compute_api:os-flavor-manage "
                       "to be performed."))

        required_fields = ['name', 'ram', 'vcpus', 'disk']
        if 'flavor' not in kw:
            utils.format_nova_error(400, _('flavor is not set'))
        if not utils.validate_required_fields_set(kw['flavor'],
                                                  required_fields):
            utils.format_nova_error(
                400, _('Invalid input for field/attribute flavor.'))

        flavor_dict = {
            'name': kw['flavor']['name'],
            'flavorid': kw['flavor'].get('id'),
            'memory_mb': kw['flavor']['ram'],
            'vcpus': kw['flavor']['vcpus'],
            'root_gb': kw['flavor']['disk'],
            'ephemeral_gb': kw['flavor'].get('OS-FLV-EXT-DATA:ephemeral', 0),
            'swap': kw['flavor'].get('swap', 0),
            'rxtx_factor': kw['flavor'].get('rxtx_factor', 1.0),
            'is_public': kw['flavor'].get('os-flavor-access:is_public', True),
        }

        try:
            with context.session.begin():
                flavor = core.create_resource(
                    context, models.InstanceTypes, flavor_dict)
        except db_exc.DBDuplicateEntry as e:
            if 'flavorid' in e.columns:
                return utils.format_nova_error(
                    409, _('Flavor with ID %s already '
                           'exists.') % flavor_dict['flavorid'])
            else:
                return utils.format_nova_error(
                    409, _('Flavor with name %s already '
                           'exists.') % flavor_dict['name'])
        except Exception:
            return utils.format_nova_error(500, _('Failed to create flavor'))

        return {'flavor': flavor}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                flavors = core.query_resource(context, models.InstanceTypes,
                                              [{'key': 'flavorid',
                                                'comparator': 'eq',
                                                'value': _id}], [])
                if not flavors:
                    return utils.format_nova_error(
                        404, _('Flavor %s could not be found') % _id)
                core.delete_resource(context, models.InstanceTypes,
                                     flavors[0]['id'])
        except Exception:
            return utils.format_nova_error(500, _('Failed to delete flavor'))
        pecan.response.status = 202
        return


class FlavorController(rest.RestController):

    def __init__(self, project_id):
        self.project_id = project_id

    @pecan.expose()
    def _lookup(self, action, *remainder):
        if action == 'os-flavor-manage':
            return FlavorManageController(self.project_id), remainder

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            return utils.format_nova_error(
                403, _("Policy doesn't allow os_compute_api:os-flavor-manage "
                       "to be performed."))

        required_fields = ['name', 'ram', 'vcpus', 'disk']
        if 'flavor' not in kw:
            utils.format_nova_error(400, _('flavor is not set'))
        if not utils.validate_required_fields_set(kw['flavor'],
                                                  required_fields):
            utils.format_nova_error(
                400, _('Invalid input for field/attribute flavor.'))

        flavor_dict = {
            'name': kw['flavor']['name'],
            'flavorid': kw['flavor'].get('id'),
            'memory_mb': kw['flavor']['ram'],
            'vcpus': kw['flavor']['vcpus'],
            'root_gb': kw['flavor']['disk'],
            'ephemeral_gb': kw['flavor'].get('OS-FLV-EXT-DATA:ephemeral', 0),
            'swap': kw['flavor'].get('swap', 0),
            'rxtx_factor': kw['flavor'].get('rxtx_factor', 1.0),
            'is_public': kw['flavor'].get('os-flavor-access:is_public', True),
        }

        try:
            with context.session.begin():
                flavor = core.create_resource(
                    context, models.InstanceTypes, flavor_dict)
        except db_exc.DBDuplicateEntry as e:
            if 'flavorid' in e.columns:
                return utils.format_nova_error(
                    409, _('Flavor with ID %s already '
                           'exists.') % flavor_dict['flavorid'])
            else:
                return utils.format_nova_error(
                    409, _('Flavor with name %s already '
                           'exists.') % flavor_dict['name'])
        except Exception:
            utils.format_nova_error(500, _('Failed to create flavor'))

        flavor['id'] = flavor['flavorid']
        del flavor['flavorid']
        return {'flavor': flavor}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        # NOTE(zhiyuan) this function handles two kinds of requests
        # GET /flavors/flavor_id
        # GET /flavors/detail
        context = t_context.extract_context_from_environ()
        if _id == 'detail':
            with context.session.begin():
                flavors = core.query_resource(context, models.InstanceTypes,
                                              [], [])
                for flavor in flavors:
                    flavor['id'] = flavor['flavorid']
                    del flavor['flavorid']
                return {'flavors': flavors}
        else:
            with context.session.begin():
                flavors = core.query_resource(context, models.InstanceTypes,
                                              [{'key': 'flavorid',
                                                'comparator': 'eq',
                                                'value': _id}], [])
                if not flavors:
                    return utils.format_nova_error(
                        404, _('Flavor %s could not be found') % _id)
                flavor = flavors[0]
                flavor['id'] = flavor['flavorid']
                del flavor['flavorid']
                return {'flavor': flavor}

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()
        with context.session.begin():
            flavors = core.query_resource(context, models.InstanceTypes,
                                          [], [])
            return {'flavors': [dict(
                [('id', flavor['flavorid']),
                 ('name', flavor['name'])]) for flavor in flavors]}

    @expose(generic=True, template='json')
    def delete(self, _id):
        # TODO(zhiyuan) handle foreign key constraint
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                flavors = core.query_resource(context, models.InstanceTypes,
                                              [{'key': 'flavorid',
                                                'comparator': 'eq',
                                                'value': _id}], [])
                if not flavors:
                    return utils.format_nova_error(
                        404, _('Flavor %s could not be found') % _id)
                core.delete_resource(context,
                                     models.InstanceTypes, flavors[0]['id'])
        except Exception:
            return utils.format_nova_error(500, _('Failed to delete flavor'))
        pecan.response.status = 202
        return
