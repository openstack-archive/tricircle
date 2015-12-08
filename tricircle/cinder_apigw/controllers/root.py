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

import oslo_log.log as logging

LOG = logging.getLogger(__name__)


class RootController(object):

    @pecan.expose()
    def _lookup(self, version, *remainder):
        if version == 'v2':
            return V2Controller(), remainder

    @pecan.expose(generic=True, template='json')
    def index(self):
        return {
            "versions": [
                {
                    "status": "CURRENT",
                    "updated": "2012-11-21T11:33:21Z",
                    "id": "v2.0",
                    "links": [
                        {
                            "href": pecan.request.application_url + "/v2/",
                            "rel": "self"
                        }
                    ]
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


class V2Controller(object):

    _media_type1 = "application/vnd.openstack.volume+xml;version=1"
    _media_type2 = "application/vnd.openstack.volume+json;version=1"

    def __init__(self):

        self.sub_controllers = {

        }

        for name, ctrl in self.sub_controllers.items():
            setattr(self, name, ctrl)

    @pecan.expose(generic=True, template='json')
    def index(self):
        return {
            "version": {
                "status": "CURRENT",
                "updated": "2012-11-21T11:33:21Z",
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": self._media_type1
                    },
                    {
                        "base": "application/json",
                        "type": self._media_type2
                    }
                ],
                "id": "v2.0",
                "links": [
                    {
                        "href": pecan.request.application_url + "/v2/",
                        "rel": "self"
                    },
                    {
                        "href": "http://docs.openstack.org/",
                        "type": "text/html",
                        "rel": "describedby"
                    }
                ]
            }
        }

    @index.when(method='POST')
    @index.when(method='PUT')
    @index.when(method='DELETE')
    @index.when(method='HEAD')
    @index.when(method='PATCH')
    def not_supported(self):
        pecan.abort(405)
