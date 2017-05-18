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

import oslo_db.exception as db_exc
from oslo_log import log as logging
from oslo_utils import uuidutils

import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common import policy

from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.db import models

LOG = logging.getLogger(__name__)


class PodsController(rest.RestController):

    def __init__(self):
        pass

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_PODS_CREATE):
            pecan.abort(401, _('Unauthorized to create pods'))
            return

        if 'pod' not in kw:
            pecan.abort(400, _('Request body pod not found'))
            return

        pod = kw['pod']

        # if az_name is null, and there is already one in db
        region_name = pod.get('region_name', '').strip()
        pod_az_name = pod.get('pod_az_name', '').strip()
        dc_name = pod.get('dc_name', '').strip()
        az_name = pod.get('az_name', '').strip()
        _uuid = uuidutils.generate_uuid()
        top_region_name = self._get_top_region(context)

        if az_name == '':
            if region_name == '':
                return Response(
                    _('Valid region_name is required for top region'),
                    422)

            if top_region_name != '':
                return Response(_('Top region already exists'), 409)
            # to create the top region, make the pod_az_name to null value
            pod_az_name = ''

        if az_name != '':
            if region_name == '':
                return Response(
                    _('Valid region_name is required for pod'), 422)
            # region_name != ''
            # then the pod region name should not be same as the top region
            if top_region_name == region_name:
                return Response(
                    _('Pod region name duplicated with the top region name'),
                    409)

        try:
            with context.session.begin():
                new_pod = core.create_resource(
                    context, models.Pod,
                    {'pod_id': _uuid,
                     'region_name': region_name,
                     'pod_az_name': pod_az_name,
                     'dc_name': dc_name,
                     'az_name': az_name})
        except db_exc.DBDuplicateEntry as e1:
            LOG.exception('Record already exists on %(region_name)s: '
                          '%(exception)s',
                          {'region_name': region_name,
                           'exception': e1})
            return Response(_('Record already exists'), 409)
        except Exception as e2:
            LOG.exception('Failed to create pod: %(region_name)s,'
                          'pod_az_name: %(pod_az_name)s,'
                          'dc_name: %(dc_name)s,'
                          'az_name: %(az_name)s'
                          '%(exception)s ',
                          {'region_name': region_name,
                           'pod_az_name': pod_az_name,
                           'dc_name': dc_name,
                           'az_name': az_name,
                           'exception': e2})
            return Response(_('Failed to create pod'), 500)

        return {'pod': new_pod}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_PODS_SHOW):
            pecan.abort(401, _('Unauthorized to show pods'))
            return

        try:
            return {'pod': db_api.get_pod(context, _id)}
        except t_exceptions.ResourceNotFound:
            pecan.abort(404, _('Pod not found'))
            return

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_PODS_LIST):
            pecan.abort(401, _('Unauthorized to list pods'))
            return

        try:
            return {'pods': db_api.list_pods(context)}
        except Exception as e:
            LOG.exception('Failed to list all pods: %(exception)s ',
                          {'exception': e})

            pecan.abort(500, _('Failed to list pods'))
            return

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_PODS_DELETE):
            pecan.abort(401, _('Unauthorized to delete pods'))
            return

        try:
            with context.session.begin():
                core.delete_resource(context, models.Pod, _id)
                pecan.response.status = 200
                return {}
        except t_exceptions.ResourceNotFound:
            return Response(_('Pod not found'), 404)
        except Exception as e:
            LOG.exception('Failed to delete pod: %(pod_id)s,'
                          '%(exception)s',
                          {'pod_id': _id,
                           'exception': e})

            return Response(_('Failed to delete pod'), 500)

    def _get_top_region(self, ctx):
        top_region_name = ''
        try:
            with ctx.session.begin():
                pods = core.query_resource(ctx,
                                           models.Pod, [], [])
                for pod in pods:
                    if pod['az_name'] == '' and pod['region_name'] != '':
                        return pod['region_name']
        except Exception as e:
            LOG.exception('Failed to get top region: %(exception)s ',
                          {'exception': e})

            return top_region_name

        return top_region_name
