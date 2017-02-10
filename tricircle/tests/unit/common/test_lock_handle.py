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

import unittest

import neutronclient.common.exceptions as q_exceptions
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.common import context
from tricircle.common import exceptions
from tricircle.common import lock_handle
from tricircle.db import api
from tricircle.db import core


RES = []


def list_resource(t_ctx, q_ctx, pod, ele, _type):
    for res in RES:
        if res['name'] == ele['id']:
            return [res]
    return []


def create_resource(t_ctx, q_ctx, pod, body, _type):
    body['id'] = uuidutils.generate_uuid()
    RES.append(body)
    return body


class LockHandleTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.project_id = 'project_id'
        self.t_ctx = context.Context()
        self.q_ctx = object()

    def _prepare_pod(self):
        return api.create_pod(self.t_ctx, {'pod_id': 'pod_id_1',
                                           'region_name': 'pod_1',
                                           'az_name': 'az_name_1'})

    def test_get_create_element_new(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        is_new, b_resource_id = lock_handle.get_or_create_element(
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)
        self.assertEqual(is_new, True)
        self.assertEqual(b_resource_id, RES[0]['id'])

    def test_get_create_element_routing_valid(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        lock_handle.get_or_create_element(
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)
        is_new, b_resource_id = lock_handle.get_or_create_element(
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)
        self.assertEqual(is_new, False)
        self.assertEqual(b_resource_id, RES[0]['id'])

    def test_get_create_element_routing_expire_resource_exist(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        routing = api.create_resource_mapping(self.t_ctx, resource_id, None,
                                              pod['pod_id'], self.project_id,
                                              _type)
        api.update_resource_routing(self.t_ctx, routing['id'],
                                    {'created_at': constants.expire_time,
                                     'updated_at': constants.expire_time})

        RES.append({'id': uuidutils.generate_uuid(),
                    'name': resource_id})
        is_new, b_resource_id = lock_handle.get_or_create_element(
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)
        self.assertEqual(is_new, True)
        self.assertEqual(b_resource_id, RES[0]['id'])

    def test_get_create_element_routing_expire_resource_missing(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        routing = api.create_resource_mapping(self.t_ctx, resource_id, None,
                                              pod['pod_id'], self.project_id,
                                              _type)
        api.update_resource_routing(self.t_ctx, routing['id'],
                                    {'created_at': constants.expire_time,
                                     'updated_at': constants.expire_time})

        is_new, b_resource_id = lock_handle.get_or_create_element(
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)
        self.assertEqual(is_new, True)
        self.assertEqual(b_resource_id, RES[0]['id'])

    def test_get_create_element_routing_conflict(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        api.create_resource_mapping(self.t_ctx, resource_id, None,
                                    pod['pod_id'], self.project_id, _type)
        self.assertRaises(
            exceptions.RoutingCreateFail, lock_handle.get_or_create_element,
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, create_resource)

    def test_get_create_element_create_fail(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}

        def fake_create_resource(t_ctx, q_ctx, pod, body, _type):
            raise q_exceptions.ConnectionFailed()

        self.assertRaises(
            q_exceptions.ConnectionFailed, lock_handle.get_or_create_element,
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            list_resource, fake_create_resource)
        routing = api.get_bottom_id_by_top_id_region_name(
            self.t_ctx, resource_id, pod['region_name'], _type)
        self.assertIsNone(routing)

    def test_get_list_element_create_fail(self):
        pod = self._prepare_pod()
        resource_id = 'fake_resource_id'
        _type = 'fake_resource'
        ele = {'id': resource_id}
        body = {'name': resource_id}
        routing = api.create_resource_mapping(self.t_ctx, resource_id, None,
                                              pod['pod_id'], self.project_id,
                                              _type)
        api.update_resource_routing(self.t_ctx, routing['id'],
                                    {'created_at': constants.expire_time,
                                     'updated_at': constants.expire_time})

        def fake_list_resource(t_ctx, q_ctx, pod, body, _type):
            raise q_exceptions.ConnectionFailed()

        self.assertRaises(
            q_exceptions.ConnectionFailed, lock_handle.get_or_create_element,
            self.t_ctx, self.q_ctx, self.project_id, pod, ele, _type, body,
            fake_list_resource, create_resource)
        # the original routing is not deleted
        routing = api.get_resource_routing(self.t_ctx, routing['id'])
        self.assertIsNone(routing['bottom_id'])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        del RES[:]
