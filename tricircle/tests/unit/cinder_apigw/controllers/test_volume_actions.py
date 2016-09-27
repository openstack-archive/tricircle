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

from cinderclient.client import HTTPClient
from oslo_utils import uuidutils

from tricircle.cinder_apigw.controllers import volume_actions as action
from tricircle.common import constants
from tricircle.common import context
from tricircle.common import exceptions
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class VolumeActionTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_project'
        self.context.tenant = self.project_id
        self.controller = action.VolumeActionController(self.project_id, '')

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

    def _prepare_pod_service(self, pod_id, service):
        config_dict = {'service_id': uuidutils.generate_uuid(),
                       'pod_id': pod_id,
                       'service_type': service,
                       'service_url': 'fake_pod_service'}
        api.create_pod_service_configuration(self.context, config_dict)
        pass

    def _prepare_volume(self, pod):
        t_volume_id = uuidutils.generate_uuid()
        b_volume_id = t_volume_id
        with self.context.session.begin():
            core.create_resource(
                self.context, models.ResourceRouting,
                {'top_id': t_volume_id, 'bottom_id': b_volume_id,
                 'pod_id': pod['pod_id'], 'project_id': self.project_id,
                 'resource_type': constants.RT_VOLUME})
        return t_volume_id

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

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_action_not_supported(self, mock_context):
        mock_context.return_value = self.context

        body = {'unsupported_action': ''}
        res = self.controller.post(**body)
        self.assertEqual('Volume action not supported',
                         res['badRequest']['message'])
        self.assertEqual(400, res['badRequest']['code'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_action_volume_not_found(self, mock_context):
        mock_context.return_value = self.context

        body = {'os-extend': ''}
        self.controller.volume_id = 'Fake_volume_id'
        res = self.controller.post(**body)
        self.assertEqual(
            'Volume %(volume_id)s could not be found.' % {
                'volume_id': self.controller.volume_id},
            res['itemNotFound']['message'])
        self.assertEqual(404, res['itemNotFound']['code'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_action_exception(self, mock_context, mock_action):
        mock_context.return_value = self.context
        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        mock_action.side_effect = exceptions.HTTPForbiddenError(
            msg='Volume operation forbidden')
        body = {'os-extend': {'new_size': 2}}
        res = self.controller.post(**body)
        # this is the message of HTTPForbiddenError exception
        self.assertEqual('Volume operation forbidden',
                         res['forbidden']['message'])
        # this is the code of HTTPForbiddenError exception
        self.assertEqual(403, res['forbidden']['code'])

        mock_action.side_effect = exceptions.ServiceUnavailable
        body = {'os-extend': {'new_size': 2}}
        res = self.controller.post(**body)
        # this is the message of ServiceUnavailable exception
        self.assertEqual('The service is unavailable',
                         res['internalServerError']['message'])
        # code is 500 by default
        self.assertEqual(500, res['internalServerError']['code'])

        mock_action.side_effect = Exception
        body = {'os-extend': {'new_size': 2}}
        res = self.controller.post(**body)
        # use default message if exception's message is empty
        self.assertEqual('Action os-extend on volume %s fails' % t_volume_id,
                         res['internalServerError']['message'])
        # code is 500 by default
        self.assertEqual(500, res['internalServerError']['code'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_extend_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)
        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {'os-extend': {'new_size': 2}}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_attach_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        t_server_id = self._prepare_server(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {'os-attach': {
            'instance_uuid': t_server_id,
            'mountpoint': '/dev/vdc'
        }}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_force_detach_volume_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        t_server_id = self._prepare_server(b_pods[0])
        self.controller.volume_id = t_volume_id
        body = {"os-force_detach": {
            "attachment_id": t_server_id,
            "connector": {
                "initiator": "iqn.2012-07.org.fake:01"}}}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_reset_status_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {"os-reset_status": {
            "status": "available",
            "attach_status": "detached",
            "migration_status": "migrating"
        }}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_set_image_metadata_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {"os-set_image_metadata": {
            "metadata": {
                "image_id": "521752a6-acf6-4b2d-bc7a-119f9148cd8c",
                "image_name": "image",
                "kernel_id": "155d900f-4e14-4e4c-a73d-069cbf4541e6",
                "ramdisk_id": "somedisk"
            }
        }}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_unset_image_metadata_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {"os-unset_image_metadata": {
            'key': 'image_name'
        }}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(HTTPClient, 'post')
    @patch.object(context, 'extract_context_from_environ')
    def test_show_image_metadata_action(self, mock_context, mock_action):
        mock_context.return_value = self.context
        mock_action.return_value = (FakeResponse(202), None)

        t_pod, b_pods = self._prepare_pod()
        self._prepare_pod_service(b_pods[0]['pod_id'], constants.ST_CINDER)
        t_volume_id = self._prepare_volume(b_pods[0])
        self.controller.volume_id = t_volume_id

        body = {"os-show_image_metadata": None}
        res = self.controller.post(**body)
        url = '/volumes/%s/action' % t_volume_id
        mock_action.assert_called_once_with(url, body=body)
        self.assertEqual(202, res.status)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
