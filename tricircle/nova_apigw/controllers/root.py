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
from pecan import hooks
from pecan import rest

import oslo_log.log as logging

import webob.exc as web_exc

from tricircle.common import constants
from tricircle.common import context as ctx
from tricircle.common import xrpcapi
from tricircle.nova_apigw.controllers import action
from tricircle.nova_apigw.controllers import aggregate
from tricircle.nova_apigw.controllers import flavor
from tricircle.nova_apigw.controllers import image
from tricircle.nova_apigw.controllers import network
from tricircle.nova_apigw.controllers import quota_sets
from tricircle.nova_apigw.controllers import server
from tricircle.nova_apigw.controllers import server_ips
from tricircle.nova_apigw.controllers import volume

LOG = logging.getLogger(__name__)


class ErrorHook(hooks.PecanHook):
    # NOTE(zhiyuan) pecan's default error body is not compatible with nova
    # client, clear body in this hook
    def on_error(self, state, exc):
        if isinstance(exc, web_exc.HTTPException):
            exc.body = ''
            return exc


class RootController(object):

    @pecan.expose()
    def _lookup(self, version, *remainder):
        if version == 'v2.1':
            return V21Controller(), remainder


class V21Controller(object):

    _media_type = "application/vnd.openstack.compute+json;version=2.1"

    def __init__(self):
        self.resource_controller = {
            'flavors': flavor.FlavorController,
            'os-aggregates': aggregate.AggregateController,
            'servers': server.ServerController,
            'images': image.ImageController,
            'os-quota-sets': quota_sets.QuotaSetsController,
            'limits': quota_sets.LimitsController,
            'os-networks': network.NetworkController
        }
        self.server_sub_controller = {
            'os-volume_attachments': volume.VolumeController,
            'action': action.ActionController,
            'ips': server_ips.ServerIpsController
        }

    def _get_resource_controller(self, project_id, remainder):
        if not remainder:
            pecan.abort(404)
            return
        resource = remainder[0]
        if resource not in self.resource_controller:
            pecan.abort(404)
            return
        if resource == 'servers' and len(remainder) >= 3:
            server_id = remainder[1]
            sub_resource = remainder[2]
            if sub_resource not in self.server_sub_controller:
                pecan.abort(404)
                return
            return self.server_sub_controller[sub_resource](
                project_id, server_id), remainder[3:]
        return self.resource_controller[resource](project_id), remainder[1:]

    @pecan.expose()
    def _lookup(self, project_id, *remainder):
        if project_id == 'testrpc':
            return TestRPCController(), remainder
        else:
            # If the last charater of the url path is '/', then
            # last remainder element is ''. Since pecan can't
            # handle the url properly, '' element must be removed.
            # Otherwise pecan will crashed for routing the request
            # with incorrect parameter
            num = len(remainder)
            if num >= 1 and remainder[num - 1] == '':
                new_remainder = remainder[:num - 1]
            else:
                new_remainder = remainder
            return self._get_resource_controller(project_id, new_remainder)

    @pecan.expose(generic=True, template='json')
    def index(self):
        return {
            "version": {
                "status": "CURRENT",
                "updated": "2013-07-23T11:33:21Z",
                "links": [
                    {
                        "href": pecan.request.application_url + "/v2.1/",
                        "rel": "self"
                    },
                    {
                        "href": "http://docs.openstack.org/",
                        "type": "text/html",
                        "rel": "describedby"
                    }
                ],
                "min_version": constants.NOVA_APIGW_MIN_VERSION,
                "version": constants.NOVA_APIGW_MAX_VERSION,
                "media-types": [
                    {
                        "base": "application/json",
                        "type": self._media_type
                    }
                ],
                "id": "v2.1"
            }
        }

    @index.when(method='POST')
    @index.when(method='PUT')
    @index.when(method='DELETE')
    @index.when(method='HEAD')
    @index.when(method='PATCH')
    def not_supported(self):
        pecan.abort(404)


class TestRPCController(rest.RestController):
    def __init__(self, *args, **kwargs):
        super(TestRPCController, self).__init__(*args, **kwargs)
        self.xjobapi = xrpcapi.XJobAPI()

    @expose(generic=True, template='json')
    def index(self):
        if pecan.request.method != 'GET':
            pecan.abort(405)

        context = ctx.extract_context_from_environ()

        payload = '#result from xjob rpc'

        return self.xjobapi.test_rpc(context, payload)
