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
from pecan import Response
from pecan import rest

from oslo_utils import uuidutils

import oslo_db.exception as db_exc

import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exc
from tricircle.common.i18n import _
from tricircle.db import core
from tricircle.db import models


class PodsController(rest.RestController):

    def __init__(self):
        pass

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to create pods'))
            return

        if 'pod_map' not in kw:
            pecan.abort(400, _('Request body pod_map not found'))
            return

        pod_map = kw['pod_map']

        # if az_name is null, and there is already one in db
        az_name = pod_map.get('az_name', '').strip()
        dc_name = pod_map.get('dc_name', '').strip()
        pod_name = pod_map.get('pod_name', '').strip()
        pod_az_name = pod_map.get('pod_az_name', '').strip()
        _uuid = uuidutils.generate_uuid()

        if az_name == '' and pod_name == '':
            return Response(_('Valid pod_name is required for top region'),
                            422)

        if az_name != '' and pod_name == '':
            return Response(_('Valid pod_name is required for pod'), 422)

        if pod_map.get('az_name') is None:
            if self._get_top_region(context) != '':
                return Response(_('Top region already exists'), 409)

        # if az_name is not null, then the pod region name should not
        # be same as that the top region
        if az_name != '':
            if self._get_top_region(context) == pod_name and pod_name != '':
                return Response(
                    _('Pod region name duplicated with the top region name'),
                    409)

        # to create the top region, make the pod_az_name to null value
        if az_name == '':
            pod_az_name = ''

        try:
            with context.session.begin():
                pod_map = core.create_resource(context, models.PodMap,
                                               {'id': _uuid,
                                                'az_name': az_name,
                                                'dc_name': dc_name,
                                                'pod_name': pod_name,
                                                'pod_az_name': pod_az_name})
        except db_exc.DBDuplicateEntry:
            return Response(_('Pod map already exists'), 409)
        except Exception:
            return Response(_('Fail to create pod map'), 500)

        return {'pod_map': pod_map}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to show pods'))
            return

        try:
            with context.session.begin():
                pod_map = core.get_resource(context, models.PodMap, _id)
                return {'pod_map': pod_map}
        except t_exc.ResourceNotFound:
            pecan.abort(404, _('AZ pod map not found'))
            return

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to list pods'))
            return

        try:
            with context.session.begin():
                pod_maps = core.query_resource(context, models.PodMap, [], [])
        except Exception:
            pecan.abort(500, _('Fail to list pod maps'))
            return

        return {'pod_maps': pod_maps}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to delete pods'))
            return

        try:
            with context.session.begin():
                core.delete_resource(context, models.PodMap, _id)
                pecan.response.status = 200
        except t_exc.ResourceNotFound:
            pecan.abort(404, _('Pod map not found'))
            return

    def _get_top_region(self, ctx):
        top_region_name = ''
        try:
            with ctx.session.begin():
                pod_maps = core.query_resource(ctx,
                                               models.PodMap, [], [])
                for pod in pod_maps:
                    if pod['az_name'] == '' and pod['pod_name'] != '':
                        return pod['pod_name']
        except Exception:
            return top_region_name

        return top_region_name


class BindingsController(rest.RestController):

    def __init__(self):
        pass

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to create bindings'))
            return

        if 'pod_binding' not in kw:
            pecan.abort(400, _('Request body not found'))
            return

        pod_b = kw['pod_binding']
        tenant_id = pod_b.get('tenant_id', '').strip()
        az_pod_map_id = pod_b.get('az_pod_map_id', '').strip()
        _uuid = uuidutils.generate_uuid()

        if tenant_id == '' or az_pod_map_id == '':
            return Response(
                _('Tenant_id and az_pod_map_id can not be empty'),
                422)

        # the az_pod_map_id should be exist for in the pod map table
        try:
            with context.session.begin():
                pod_map = core.get_resource(context, models.PodMap,
                                            az_pod_map_id)
                if pod_map.get('az_name') == '':
                    return Response(_('Top region can not be bound'), 422)
        except t_exc.ResourceNotFound:
            return Response(_('Az_pod_map_id not found in pod map'), 422)
        except Exception:
            pecan.abort(500, _('Fail to create pod binding'))
            return

        try:
            with context.session.begin():
                pod_binding = core.create_resource(context, models.PodBinding,
                                                   {'id': _uuid,
                                                    'tenant_id': tenant_id,
                                                    'az_pod_map_id':
                                                        az_pod_map_id})
        except db_exc.DBDuplicateEntry:
            return Response(_('Pod binding already exists'), 409)
        except db_exc.DBConstraintError:
            return Response(_('Az_pod_map_id not exists in pod mapping'), 422)
        except db_exc.DBReferenceError:
            return Response(_('DB reference not exists in pod mapping'), 422)
        except Exception:
            pecan.abort(500, _('Fail to create pod binding'))
            return

        return {'pod_binding': pod_binding}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to show bindings'))
            return

        try:
            with context.session.begin():
                pod_binding = core.get_resource(context,
                                                models.PodBinding,
                                                _id)
                return {'pod_binding': pod_binding}
        except t_exc.ResourceNotFound:
            pecan.abort(404, _('Tenant pod binding not found'))
            return

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to list bindings'))
            return

        try:
            with context.session.begin():
                pod_bindings = core.query_resource(context,
                                                   models.PodBinding,
                                                   [], [])
        except Exception:
            pecan.abort(500, _('Fail to list tenant pod bindings'))
            return

        return {'pod_bindings': pod_bindings}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()

        if not t_context.is_admin_context(context):
            pecan.abort(400, _('Admin role required to delete bindings'))
            return

        try:
            with context.session.begin():
                core.delete_resource(context, models.PodBinding, _id)
                pecan.response.status = 200
        except t_exc.ResourceNotFound:
            pecan.abort(404, _('Pod binding not found'))
            return
