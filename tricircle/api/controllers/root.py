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
from pecan import rest


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


class SitesController(rest.RestController):

    @expose(generic=True)
    def index(self):
        if pecan.request.method != 'GET':
            pecan.abort(405)
        return {'message': 'GET'}

    @when(index, method='PUT')
    def put(self, **kw):
        return {'message': 'PUT'}

    @when(index, method='POST')
    def post(self, **kw):
        return {'message': 'POST'}

    @when(index, method='DELETE')
    def delete(self):
        return {'message': 'DELETE'}
