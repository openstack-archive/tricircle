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

from tricircle.common import az_ag
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exc
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common import policy
from tricircle.common import utils

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
        pod_name = pod.get('pod_name', '').strip()
        pod_az_name = pod.get('pod_az_name', '').strip()
        dc_name = pod.get('dc_name', '').strip()
        az_name = pod.get('az_name', '').strip()
        _uuid = uuidutils.generate_uuid()

        if az_name == '' and pod_name == '':
            return Response(_('Valid pod_name is required for top region'),
                            422)

        if az_name != '' and pod_name == '':
            return Response(_('Valid pod_name is required for pod'), 422)

        if pod.get('az_name') is None:
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
                # if not top region,
                # then add corresponding ag and az for the pod
                if az_name != '':
                    ag_name = utils.get_ag_name(pod_name)
                    aggregate = az_ag.create_ag_az(context,
                                                   ag_name=ag_name,
                                                   az_name=az_name)
                    if aggregate is None:
                        return Response(_('Ag creation failure'), 400)

                new_pod = core.create_resource(
                    context, models.Pod,
                    {'pod_id': _uuid,
                     'pod_name': pod_name,
                     'pod_az_name': pod_az_name,
                     'dc_name': dc_name,
                     'az_name': az_name})
        except db_exc.DBDuplicateEntry as e1:
            LOG.exception(_LE('Record already exists on %(pod_name)s: '
                              '%(exception)s'),
                          {'pod_name': pod_name,
                          'exception': e1})
            return Response(_('Record already exists'), 409)
        except Exception as e2:
            LOG.exception(_LE('Failed to create pod: %(pod_name)s,'
                              'pod_az_name: %(pod_az_name)s,'
                              'dc_name: %(dc_name)s,'
                              'az_name: %(az_name)s'
                              '%(exception)s '),
                          {'pod_name': pod_name,
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
        except t_exc.ResourceNotFound:
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
            LOG.exception(_LE('Failed to list all pods: %(exception)s '),
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
                pod = core.get_resource(context, models.Pod, _id)
                if pod is not None:
                    ag_name = utils.get_ag_name(pod['pod_name'])
                    ag = az_ag.get_ag_by_name(context, ag_name)
                    if ag is not None:
                        az_ag.delete_ag(context, ag['id'])
                core.delete_resource(context, models.Pod, _id)
                pecan.response.status = 200
                return {}
        except t_exc.ResourceNotFound:
            return Response(_('Pod not found'), 404)
        except Exception as e:
            LOG.exception(_LE('Failed to delete pod: %(pod_id)s,'
                              '%(exception)s'),
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
                    if pod['az_name'] == '' and pod['pod_name'] != '':
                        return pod['pod_name']
        except Exception as e:
            LOG.exception(_LE('Failed to get top region: %(exception)s '),
                          {'exception': e})

            return top_region_name

        return top_region_name


class BindingsController(rest.RestController):

    def __init__(self):
        pass

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_BINDINGS_CREATE):
            pecan.abort(401, _('Unauthorized to create bindings'))
            return

        if 'pod_binding' not in kw:
            pecan.abort(400, _('Request body not found'))
            return

        pod_b = kw['pod_binding']
        tenant_id = pod_b.get('tenant_id', '').strip()
        pod_id = pod_b.get('pod_id', '').strip()

        if tenant_id == '' or pod_id == '':
            return Response(
                _('Tenant_id and pod_id can not be empty'),
                422)

        # the az_pod_map_id should be exist for in the pod map table
        try:
            with context.session.begin():
                pod = core.get_resource(context, models.Pod,
                                        pod_id)
                if pod.get('az_name') == '':
                    return Response(_('Top region can not be bound'), 422)
        except t_exc.ResourceNotFound:
            return Response(_('pod_id not found in pod'), 422)
        except Exception as e:
            LOG.exception(_LE('Failed to get_resource for pod_id: '
                              '%(pod_id)s ,'
                              '%(exception)s '),
                          {'pod_id': pod_id,
                          'exception': e})
            pecan.abort(500, _('Failed to create pod binding'))
            return

        try:
            pod_binding = db_api.create_pod_binding(
                context, tenant_id, pod_id)
        except db_exc.DBDuplicateEntry:
            return Response(_('Pod binding already exists'), 409)
        except db_exc.DBConstraintError:
            return Response(_('pod_id not exists in pod'), 422)
        except db_exc.DBReferenceError:
            return Response(_('DB reference not exists in pod'), 422)
        except Exception as e:
            LOG.exception(_LE('Failed to create pod binding: %(exception)s '),
                          {'exception': e})
            pecan.abort(500, _('Failed to create pod binding'))
            return

        return {'pod_binding': pod_binding}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_BINDINGS_SHOW):
            pecan.abort(401, _('Unauthorized to show bindings'))
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

        if not policy.enforce(context, policy.ADMIN_API_BINDINGS_LIST):
            pecan.abort(401, _('Unauthorized to list bindings'))
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

        if not policy.enforce(context, policy.ADMIN_API_BINDINGS_DELETE):
            pecan.abort(401, _('Unauthorized to delete bindings'))
            return

        try:
            with context.session.begin():
                core.delete_resource(context, models.PodBinding, _id)
                pecan.response.status = 200
                return {}
        except t_exc.ResourceNotFound:
            pecan.abort(404, _('Pod binding not found'))
            return
