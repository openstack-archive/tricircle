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

import uuid

import oslo_log.log as logging
import pecan
from pecan import request
from pecan import rest

from tricircle.common import cascading_site_api
from tricircle.common import utils
import tricircle.context as t_context
from tricircle.db import client
from tricircle.db import exception
from tricircle.db import models

LOG = logging.getLogger(__name__)


def expose(*args, **kwargs):
    kwargs.setdefault('content_type', 'application/json')
    kwargs.setdefault('template', 'json')
    return pecan.expose(*args, **kwargs)


def when(index, *args, **kwargs):
    kwargs.setdefault('content_type', 'application/json')
    kwargs.setdefault('template', 'json')
    return index.when(*args, **kwargs)


class RootController(object):

    @expose()
    def _lookup(self, version, *remainder):
        if version == 'v1.0':
            return V1Controller(), remainder

    @pecan.expose('json')
    def index(self):
        return {
            "versions": [
                {
                    "status": "CURRENT",
                    "links": [
                        {
                            "rel": "self",
                            "href": pecan.request.application_url + "/v1.0/"
                            }
                        ],
                    "id": "v1.0",
                    "updated": "2015-09-09"
                    }
                ]
            }


class V1Controller(object):

    def __init__(self):

        self.sub_controllers = {
            "sites": SitesController()
        }

        for name, ctrl in self.sub_controllers.items():
            setattr(self, name, ctrl)

    @pecan.expose('json')
    def index(self):
        return {
            "version": "1.0",
            "links": [
                {"rel": "self",
                 "href": pecan.request.application_url + "/v1.0"}
            ] + [
                {"rel": name,
                 "href": pecan.request.application_url + "/v1.0/" + name}
                for name in sorted(self.sub_controllers)
            ]
        }


def _extract_context_from_environ(environ):
    context_paras = {'auth_token': 'HTTP_X_AUTH_TOKEN',
                     'user': 'HTTP_X_USER_ID',
                     'tenant': 'HTTP_X_TENANT_ID',
                     'user_name': 'HTTP_X_USER_NAME',
                     'tenant_name': 'HTTP_X_PROJECT_NAME',
                     'domain': 'HTTP_X_DOMAIN_ID',
                     'user_domain': 'HTTP_X_USER_DOMAIN_ID',
                     'project_domain': 'HTTP_X_PROJECT_DOMAIN_ID',
                     'request_id': 'openstack.request_id'}
    for key in context_paras:
        context_paras[key] = environ.get(context_paras[key])
    role = environ.get('HTTP_X_ROLE')
    # TODO(zhiyuan): replace with policy check
    context_paras['is_admin'] = role == 'admin'
    return t_context.Context(**context_paras)


def _get_environment():
    return request.environ


class SitesController(rest.RestController):
    """ReST controller to handle CRUD operations of site resource"""

    @expose()
    def put(self, site_id, **kw):
        return {'message': 'PUT'}

    @expose()
    def get_one(self, site_id):
        context = _extract_context_from_environ(_get_environment())
        try:
            return {'site': models.get_site(context, site_id)}
        except exception.ResourceNotFound:
            pecan.abort(404, 'Site with id %s not found' % site_id)

    @expose()
    def get_all(self):
        context = _extract_context_from_environ(_get_environment())
        sites = models.list_sites(context, [])
        return {'sites': sites}

    @expose()
    def post(self, **kw):
        context = _extract_context_from_environ(_get_environment())
        if not context.is_admin:
            pecan.abort(400, 'Admin role required to create sites')
            return

        site_name = kw.get('name')
        is_top_site = kw.get('top', False)

        if not site_name:
            pecan.abort(400, 'Name of site required')
            return

        site_filters = [{'key': 'site_name', 'comparator': 'eq',
                         'value': site_name}]
        sites = models.list_sites(context, site_filters)
        if sites:
            pecan.abort(409, 'Site with name %s exists' % site_name)
            return

        ag_name = utils.get_ag_name(site_name)
        # top site doesn't need az
        az_name = utils.get_az_name(site_name) if not is_top_site else ''

        try:
            site_dict = {'site_id': str(uuid.uuid4()),
                         'site_name': site_name,
                         'az_id': az_name}
            site = models.create_site(context, site_dict)
        except Exception as e:
            LOG.debug(e.message)
            pecan.abort(500, 'Fail to create site')
            return

        # top site doesn't need aggregate
        if is_top_site:
            pecan.response.status = 201
            return {'site': site}
        else:
            try:
                top_client = client.Client()
                top_client.create_aggregates(context, ag_name, az_name)
                site_api = cascading_site_api.CascadingSiteNotifyAPI()
                site_api.create_site(context, site_name)
            except Exception as e:
                LOG.debug(e.message)
                # delete previously created site
                models.delete_site(context, site['site_id'])
                pecan.abort(500, 'Fail to create aggregate')
                return
            pecan.response.status = 201
            return {'site': site}

    @expose()
    def delete(self, site_id):
        return {'message': 'DELETE'}
