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


import oslo_log.log as logging
import pecan
from pecan import request

from tricircle.api.controllers import pod
import tricircle.common.context as t_context


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

    @pecan.expose(generic=True, template='json')
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

    @index.when(method='POST')
    @index.when(method='PUT')
    @index.when(method='DELETE')
    @index.when(method='HEAD')
    @index.when(method='PATCH')
    def not_supported(self):
        pecan.abort(405)


class V1Controller(object):

    def __init__(self):

        self.sub_controllers = {
            "pods": pod.PodsController(),
            "bindings": pod.BindingsController()
        }

        for name, ctrl in self.sub_controllers.items():
            setattr(self, name, ctrl)

    @pecan.expose(generic=True, template='json')
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

    @index.when(method='POST')
    @index.when(method='PUT')
    @index.when(method='DELETE')
    @index.when(method='HEAD')
    @index.when(method='PATCH')
    def not_supported(self):
        pecan.abort(405)


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
