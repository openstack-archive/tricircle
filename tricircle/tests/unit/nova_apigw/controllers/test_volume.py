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

import mock
from mock import patch
import pecan
import unittest

from oslo_utils import uuidutils

from tricircle.common import client
from tricircle.common import constants
from tricircle.common import context
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
from tricircle.nova_apigw.controllers import volume


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class FakeVolume(object):
    def to_dict(self):
        pass


class FakeClient(object):
    def post(self, url, body):
        return FakeResponse(), FakeVolume()

    def get(self, url):
        return FakeResponse(), FakeVolume()

    def put(self, url, body):
        return FakeResponse(), FakeVolume()

    def delete(self, url):
        return FakeResponse(), None


class FakeApi(object):
    def __init__(self):
        self.client = FakeClient()


class VolumeTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.get_admin_context()
        self.project_id = 'test_project'
        self.controller = volume.VolumeController(self.project_id, '')

    def _prepare_pod(self, bottom_pod_num=1):
        t_pod = {'pod_id': 't_pod_uuid', 'pod_name': 't_region',
                 'az_name': ''}
        api.create_pod(self.context, t_pod)
        if bottom_pod_num == 1:
            b_pod = {'pod_id': 'b_pod_uuid', 'pod_name': 'b_region',
                     'az_name': 'b_az'}
            api.create_pod(self.context, b_pod)
            return t_pod, b_pod
        b_pods = []
        for i in xrange(1, bottom_pod_num + 1):
            b_pod = {'pod_id': 'b_pod_%d_uuid' % i,
                     'pod_name': 'b_region_%d' % i,
                     'az_name': 'b_az_%d' % i}
            api.create_pod(self.context, b_pod)
            b_pods.append(b_pod)
        return t_pod, b_pods

    def _validate_error_code(self, res, code):
        self.assertEqual(code, res[res.keys()[0]]['code'])

    @patch.object(pecan, 'response')
    @patch.object(FakeClient, 'post')
    @patch.object(client.Client, 'get_native_client')
    @patch.object(context, 'extract_context_from_environ')
    def test_attach_volume(self, mock_context, mock_api, mock_post,
                           mock_response):
        mock_context.return_value = self.context
        mock_api.return_value = FakeApi()
        mock_response = FakeResponse()
        mock_response.status = 202
        t_pod, b_pods = self._prepare_pod(bottom_pod_num=2)
        b_pod1 = b_pods[0]
        b_pod2 = b_pods[1]
        t_server_id = uuidutils.generate_uuid()
        b_server_id = t_server_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})

        t_volume1_id = uuidutils.generate_uuid()
        b_volume1_id = t_volume1_id
        t_volume2_id = uuidutils.generate_uuid()
        b_volume2_id = t_volume1_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume1_id, 'bottom_id': b_volume1_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume2_id, 'bottom_id': b_volume2_id,
                 'pod_id': b_pod2['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})

        # success case
        self.controller.server_id = t_server_id
        body = {'volumeAttachment': {'volumeId': t_volume1_id}}
        self.controller.post(**body)
        calls = [mock.call('server_volume', self.context)]
        mock_api.assert_has_calls(calls)
        url = "/servers/%s/os-volume_attachments" % t_server_id
        calls = [mock.call(url, body=body)]
        mock_post.assert_has_calls(calls)
        body = {'volumeAttachment': {'volumeId': t_volume1_id,
                                     'device': '/dev/vdb'}}
        self.controller.post(**body)
        calls = [mock.call('server_volume', self.context)]
        mock_api.assert_has_calls(calls)
        calls = [mock.call(url, body=body)]
        mock_post.assert_has_calls(calls)

        # failure case, bad request
        body = {'volumeAttachment': {'volumeId': t_volume2_id}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        body = {'fakePara': ''}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        body = {'volumeAttachment': {}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # each part of path should not start with digit
        body = {'volumeAttachment': {'volumeId': t_volume1_id,
                                     'device': '/dev/001disk'}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # the first part should be "dev", and only two parts are allowed
        body = {'volumeAttachment': {'volumeId': t_volume1_id,
                                     'device': '/dev/vdb/disk'}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        body = {'volumeAttachment': {'volumeId': t_volume1_id,
                                     'device': '/disk/vdb'}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, resource not found
        body = {'volumeAttachment': {'volumeId': 'fake_volume_id'}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 404)

        self.controller.server_id = 'fake_server_id'
        body = {'volumeAttachment': {'volumeId': t_volume1_id}}

        res = self.controller.post(**body)
        self._validate_error_code(res, 404)

    @patch.object(pecan, 'response')
    @patch.object(FakeClient, 'delete')
    @patch.object(client.Client, 'get_native_client')
    @patch.object(context, 'extract_context_from_environ')
    def test_detach_volume(self, mock_context, mock_api, mock_delete,
                           mock_response):
        mock_context.return_value = self.context
        mock_api.return_value = FakeApi()
        mock_response = FakeResponse()
        mock_response.status = 202
        t_pod, b_pods = self._prepare_pod(bottom_pod_num=1)
        b_pod1 = b_pods
        t_server_id = uuidutils.generate_uuid()
        b_server_id = t_server_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})

        t_volume1_id = uuidutils.generate_uuid()
        b_volume1_id = t_volume1_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume1_id, 'bottom_id': b_volume1_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})

        # success case
        self.controller.server_id = t_server_id
        body = {'volumeAttachment': {'volumeId': t_volume1_id}}
        self.controller.post(**body)
        self.controller.delete(t_volume1_id)
        calls = [mock.call('server_volume', self.context),
                 mock.call('server_volume', self.context)]
        mock_api.assert_has_calls(calls)
        url = "/servers/%s/os-volume_attachments/%s" % (
            t_server_id, t_volume1_id)
        calls = [mock.call(url)]
        mock_delete.assert_has_calls(calls)

        # failure case, resource not found
        body = {'volumeAttachment': {'volumeId': t_volume1_id}}
        self.controller.post(**body)
        self.controller.server_id = 'fake_server_id'
        res = self.controller.delete(t_volume1_id)
        self._validate_error_code(res, 404)

    @patch.object(pecan, 'response')
    @patch.object(FakeClient, 'get')
    @patch.object(client.Client, 'get_native_client')
    @patch.object(context, 'extract_context_from_environ')
    def test_get_volume_attachments(self, mock_context, mock_api,
                                    mock_get, mock_response):
        mock_context.return_value = self.context
        mock_api.return_value = FakeApi()
        mock_response = FakeResponse()
        mock_response.status = 202
        t_pod, b_pods = self._prepare_pod(bottom_pod_num=1)
        b_pod1 = b_pods
        t_server_id = uuidutils.generate_uuid()
        b_server_id = t_server_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_server_id, 'bottom_id': b_server_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_SERVER})

        t_volume1_id = uuidutils.generate_uuid()
        b_volume1_id = t_volume1_id
        t_volume2_id = uuidutils.generate_uuid()
        b_volume2_id = t_volume2_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume1_id, 'bottom_id': b_volume1_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume2_id, 'bottom_id': b_volume2_id,
                 'pod_id': b_pod1['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})

        # success case
        self.controller.server_id = t_server_id
        body = {'volumeAttachment': {'volumeId': t_volume1_id}}
        self.controller.post(**body)
        body = {'volumeAttachment': {'volumeId': t_volume2_id}}
        self.controller.post(**body)
        self.controller.get_one(t_volume1_id)
        url = "/servers/%s/os-volume_attachments/%s" % (
            t_server_id, t_volume1_id)
        calls = [mock.call(url)]
        mock_get.asset_has_calls(calls)
        self.controller.get_all()
        url = "/servers/%s/os-volume_attachments" % t_server_id
        calls = [mock.call(calls)]
        mock_get.asset_has_calls(calls)
        calls = [mock.call('server_volume', self.context),
                 mock.call('server_volume', self.context),
                 mock.call('server_volume', self.context),
                 mock.call('server_volume', self.context)]
        mock_api.assert_has_calls(calls)

        # failure case, resource not found
        self.controller.server_id = 'fake_server_id'
        res = self.controller.get_one(t_volume1_id)
        self._validate_error_code(res, 404)
        res = self.controller.get_all()
        self._validate_error_code(res, 404)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
