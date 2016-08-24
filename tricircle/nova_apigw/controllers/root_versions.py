# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
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

from oslo_serialization import jsonutils
from oslo_service import wsgi
from oslo_utils import encodeutils

import webob.dec

from tricircle.common import constants


class Versions(object):

    @classmethod
    def factory(cls, global_config, **local_config):
        return cls(app=None)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if req.path != '/':
            if self.app:
                return req.get_response(self.app)

        method = req.environ.get('REQUEST_METHOD')
        not_allowed_methods = ['POST', 'PUT', 'DELETE', 'HEAD', 'PATCH']
        if method in not_allowed_methods:
            response = webob.Response()
            response.status_code = 404
            return response

        versions = {
            "versions": [
                {
                    "status": "SUPPORTED",
                    "updated": "2011-01-21T11:33:21Z",
                    "links": [
                        {"href": "http://127.0.0.1:8774/v2/",
                         "rel": "self"}
                    ],
                    "min_version": "",
                    "version": "",
                    "id": "v2.0"
                },
                {
                    "status": "CURRENT",
                    "updated": "2013-07-23T11:33:21Z",
                    "links": [
                        {
                            "href": req.application_url + "/v2.1/",
                            "rel": "self"
                        }
                    ],
                    "min_version": constants.NOVA_APIGW_MIN_VERSION,
                    "version": constants.NOVA_APIGW_MAX_VERSION,
                    "id": "v2.1"
                }
            ]
        }

        content_type = 'application/json'
        body = jsonutils.dumps(versions)
        response = webob.Response()
        response.content_type = content_type
        response.body = encodeutils.to_utf8(body)

        return response

    def __init__(self, app):
        self.app = app
