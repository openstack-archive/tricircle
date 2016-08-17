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

import urlparse

from pecan import expose
from pecan import request
from pecan import response
from pecan import rest

from oslo_log import log as logging
from oslo_serialization import jsonutils

from tricircle.common import az_ag
from tricircle.common import constants as cons
import tricircle.common.context as t_context
from tricircle.common import httpclient as hclient
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common.scheduler import filter_scheduler
from tricircle.common import utils

import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models

LOG = logging.getLogger(__name__)


class VolumeController(rest.RestController):

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.filter_scheduler = filter_scheduler.FilterScheduler()

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if 'volume' not in kw:
            return utils.format_cinder_error(
                400, _("Missing required element 'volume' in request body."))

        az = kw['volume'].get('availability_zone', '')
        pod, pod_az = self.filter_scheduler.select_destination(
            context, az, self.tenant_id, pod_group='')

        if not pod:
            LOG.error(_LE("Pod not configured or scheduling failure"))
            return utils.format_cinder_error(
                500, _('Pod not configured or scheduling failure'))

        t_pod = db_api.get_top_pod(context)
        if not t_pod:
            LOG.error(_LE("Top Pod not configured"))
            return utils.format_cinder_error(500, _('Top Pod not configured'))

        # TODO(joehuang): get release from pod configuration,
        # to convert the content
        # b_release = pod['release']
        # t_release = t_pod['release']
        t_release = cons.R_MITAKA
        b_release = cons.R_MITAKA

        s_ctx = hclient.get_pod_service_ctx(
            context,
            request.url,
            pod['pod_name'],
            s_type=cons.ST_CINDER)

        if s_ctx['b_url'] == '':
            LOG.error(_LE("Bottom Pod endpoint incorrect %s") %
                      pod['pod_name'])
            return utils.format_cinder_error(
                500, _('Bottom Pod endpoint incorrect'))

        b_headers = hclient.convert_header(t_release,
                                           b_release,
                                           request.headers)

        t_vol = kw['volume']

        # add or remove key-value in the request for diff. version
        b_vol_req = hclient.convert_object(t_release, b_release, t_vol,
                                           res_type=cons.RT_VOLUME)

        # convert az to the configured one
        # remove the AZ parameter to bottom request for default one
        b_vol_req['availability_zone'] = pod['pod_az_name']
        if b_vol_req['availability_zone'] == '':
            b_vol_req.pop("availability_zone", None)

        b_body = jsonutils.dumps({'volume': b_vol_req})

        resp = hclient.forward_req(
            context,
            'POST',
            b_headers,
            s_ctx['b_url'],
            b_body)
        b_status = resp.status_code
        b_ret_body = jsonutils.loads(resp.content)

        # build routing and convert response from the bottom pod
        # for different version.
        response.status = b_status
        if b_status == 202:
            if b_ret_body.get('volume') is not None:
                b_vol_ret = b_ret_body['volume']

                try:
                    with context.session.begin():
                        core.create_resource(
                            context, models.ResourceRouting,
                            {'top_id': b_vol_ret['id'],
                             'bottom_id': b_vol_ret['id'],
                             'pod_id': pod['pod_id'],
                             'project_id': self.tenant_id,
                             'resource_type': cons.RT_VOLUME})
                except Exception as e:
                    LOG.exception(_LE('Failed to create volume '
                                      'resource routing'
                                      'top_id: %(top_id)s ,'
                                      'bottom_id: %(bottom_id)s ,'
                                      'pod_id: %(pod_id)s ,'
                                      '%(exception)s '),
                                  {'top_id': b_vol_ret['id'],
                                   'bottom_id': b_vol_ret['id'],
                                   'pod_id': pod['pod_id'],
                                   'exception': e})
                    return utils.format_cinder_error(
                        500, _('Failed to create volume resource routing'))

                ret_vol = hclient.convert_object(b_release, t_release,
                                                 b_vol_ret,
                                                 res_type=cons.RT_VOLUME)

                ret_vol['availability_zone'] = pod['az_name']

                return {'volume': ret_vol}

        return b_ret_body

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if _id == 'detail':
            return {'volumes': self._get_all(context)}

        # TODO(joehuang): get the release of top and bottom
        t_release = cons.R_MITAKA
        b_release = cons.R_MITAKA

        b_headers = hclient.convert_header(t_release,
                                           b_release,
                                           request.headers)

        s_ctx = hclient.get_res_routing_ref(context, _id, request.url,
                                            cons.ST_CINDER)
        if not s_ctx:
            return utils.format_cinder_error(
                404, _('Volume %s could not be found.') % _id)

        if s_ctx['b_url'] == '':
            return utils.format_cinder_error(
                404, _('Bottom Pod endpoint incorrect'))

        resp = hclient.forward_req(context, 'GET',
                                   b_headers,
                                   s_ctx['b_url'],
                                   request.body)

        b_ret_body = jsonutils.loads(resp.content)

        b_status = resp.status_code
        response.status = b_status
        if b_status == 200:
            if b_ret_body.get('volume') is not None:
                b_vol_ret = b_ret_body['volume']
                ret_vol = hclient.convert_object(b_release, t_release,
                                                 b_vol_ret,
                                                 res_type=cons.RT_VOLUME)

                pod = utils.get_pod_by_top_id(context, _id)
                if pod:
                    ret_vol['availability_zone'] = pod['az_name']

                return {'volume': ret_vol}

        # resource not find but routing exist, remove the routing
        if b_status == 404:
            filters = [{'key': 'top_id', 'comparator': 'eq', 'value': _id},
                       {'key': 'resource_type',
                        'comparator': 'eq',
                        'value': cons.RT_VOLUME}]
            with context.session.begin():
                core.delete_resources(context,
                                      models.ResourceRouting,
                                      filters)
        return b_ret_body

    @expose(generic=True, template='json')
    def get_all(self):

        # TODO(joehuang): here should return link instead,
        # now combined with 'detail'

        context = t_context.extract_context_from_environ()
        return {'volumes': self._get_all(context)}

    def _get_all(self, context):

        # TODO(joehuang): query optimization for pagination, sort, etc
        ret = []
        pods = az_ag.list_pods_by_tenant(context, self.tenant_id)
        for pod in pods:
            if pod['pod_name'] == '':
                continue

            query = urlparse.urlsplit(request.url).query
            query_filters = urlparse.parse_qsl(query)
            skip_pod = False
            for k, v in query_filters:
                if k == 'availability_zone' and v != pod['az_name']:
                    skip_pod = True
                    break
            if skip_pod:
                continue

            s_ctx = hclient.get_pod_service_ctx(
                context,
                request.url,
                pod['pod_name'],
                s_type=cons.ST_CINDER)
            if s_ctx['b_url'] == '':
                LOG.error(_LE("bottom pod endpoint incorrect %s")
                          % pod['pod_name'])
                continue

            # TODO(joehuang): get the release of top and bottom
            t_release = cons.R_MITAKA
            b_release = cons.R_MITAKA
            b_headers = hclient.convert_header(t_release,
                                               b_release,
                                               request.headers)

            resp = hclient.forward_req(context, 'GET',
                                       b_headers,
                                       s_ctx['b_url'],
                                       request.body)

            if resp.status_code == 200:

                routings = db_api.get_bottom_mappings_by_tenant_pod(
                    context, self.tenant_id,
                    pod['pod_id'], cons.RT_VOLUME
                )

                b_ret_body = jsonutils.loads(resp.content)
                if b_ret_body.get('volumes'):
                    for vol in b_ret_body['volumes']:

                        if not routings.get(vol['id']):
                            b_ret_body['volumes'].remove(vol)
                            continue

                        vol['availability_zone'] = pod['az_name']

                    ret.extend(b_ret_body['volumes'])
        return ret

    @expose(generic=True, template='json')
    def put(self, _id, **kw):
        context = t_context.extract_context_from_environ()

        # TODO(joehuang): Implement API multi-version compatibility
        # currently _convert_header and _convert_object are both dummy
        # functions and API versions are hard coded. After multi-version
        # compatibility is implemented, API versions will be retrieved from
        # top and bottom API server, also, _convert_header and _convert_object
        # will do the real job to convert the request header and body
        # according to the API versions.
        t_release = cons.R_MITAKA
        b_release = cons.R_MITAKA

        s_ctx = hclient.get_res_routing_ref(context, _id, request.url,
                                            cons.ST_CINDER)
        if not s_ctx:
            return utils.format_cinder_error(
                404, _('Volume %s could not be found.') % _id)

        if s_ctx['b_url'] == '':
            return utils.format_cinder_error(
                404, _('Bottom Pod endpoint incorrect'))

        b_headers = hclient.convert_header(t_release,
                                           b_release,
                                           request.headers)

        t_vol = kw['volume']

        # add or remove key-value in the request for diff. version
        b_vol_req = hclient.convert_object(t_release, b_release, t_vol,
                                           res_type=cons.RT_VOLUME)

        b_body = jsonutils.dumps({'volume': b_vol_req})

        resp = hclient.forward_req(context, 'PUT',
                                   b_headers,
                                   s_ctx['b_url'],
                                   b_body)

        b_status = resp.status_code
        b_ret_body = jsonutils.loads(resp.content)
        response.status = b_status

        if b_status == 200:
            if b_ret_body.get('volume') is not None:
                b_vol_ret = b_ret_body['volume']
                ret_vol = hclient.convert_object(b_release, t_release,
                                                 b_vol_ret,
                                                 res_type=cons.RT_VOLUME)

                pod = utils.get_pod_by_top_id(context, _id)
                if pod:
                    ret_vol['availability_zone'] = pod['az_name']

                return {'volume': ret_vol}

        # resource not found but routing exist, remove the routing
        if b_status == 404:
            filters = [{'key': 'top_id', 'comparator': 'eq', 'value': _id},
                       {'key': 'resource_type',
                        'comparator': 'eq',
                        'value': cons.RT_VOLUME}]
            with context.session.begin():
                core.delete_resources(context,
                                      models.ResourceRouting,
                                      filters)
        return b_ret_body

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()

        # TODO(joehuang): get the release of top and bottom
        t_release = cons.R_MITAKA
        b_release = cons.R_MITAKA

        s_ctx = hclient.get_res_routing_ref(context, _id, request.url,
                                            cons.ST_CINDER)
        if not s_ctx:
            return utils.format_cinder_error(
                404, _('Volume %s could not be found.') % _id)

        if s_ctx['b_url'] == '':
            return utils.format_cinder_error(
                404, _('Bottom Pod endpoint incorrect'))

        b_headers = hclient.convert_header(t_release,
                                           b_release,
                                           request.headers)

        resp = hclient.forward_req(context, 'DELETE',
                                   b_headers,
                                   s_ctx['b_url'],
                                   request.body)

        response.status = resp.status_code

        # don't remove the resource routing for delete is async. operation
        # remove the routing when query is executed but not find
        # No content in the resp actually
        return response
