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

from mock import patch
import pecan
import unittest

from oslo_utils import uuidutils

from novaclient import client

from tricircle.common import constants
from tricircle.common import context
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
from tricircle.nova_apigw.controllers import server_ips


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class ServerIpsTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_project'
        self.context.tenant = self.project_id
        self.context.user = 'test_user'
        self.controller = server_ips.ServerIpsController(self.project_id, '')

    def _prepare_pod(self, bottom_pod_num=1):
        t_pod = {'pod_id': 't_pod_uuid', 'pod_name': 't_region',
                 'az_name': ''}
        api.create_pod(self.context, t_pod)
        b_pods = []
        if bottom_pod_num == 1:
            b_pod = {'pod_id': 'b_pod_uuid', 'pod_name': 'b_region',
                     'az_name': 'b_az'}
            api.create_pod(self.context, b_pod)
            b_pods.append(b_pod)
        else:
            for i in xrange(1, bottom_pod_num + 1):
                b_pod = {'pod_id': 'b_pod_%d_uuid' % i,
                         'pod_name': 'b_region_%d' % i,
                         'az_name': 'b_az_%d' % i}
                api.create_pod(self.context, b_pod)
                b_pods.append(b_pod)
        return t_pod, b_pods

    def _prepare_server(self, pod):
        t_server_id = uuidutils.generate_uuid()
        b_server_id = t_server_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})
        return t_server_id

    def _prepare_pod_service(self, pod_id, service):
        config_dict = {'service_id': uuidutils.generate_uuid(),
                       'pod_id': pod_id,
                       'service_type': service,
                       'service_url': 'fake_pod_service'}
        api.create_pod_service_configuration(self.context, config_dict)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(client.HTTPClient, 'get')
    @patch.object(context, 'extract_context_from_environ')
    def test_list_ips(self, mock_context, mock_get):
        mock_context.return_value = self.context
        mock_get.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_NOVA)
        t_server_id = self._prepare_server(b_pods[0])
        self.controller.server_id = t_server_id
        res = self.controller.get_all()
        url = '/servers/%s/ips' % t_server_id
        mock_get.assert_called_once_with(url)
        self.assertEqual(202, res.status)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
