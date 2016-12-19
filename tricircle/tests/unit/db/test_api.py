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

from tricircle.common import context

from tricircle.db import api
from tricircle.db import core
from tricircle.db import models


class APITest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def test_get_bottom_mappings_by_top_id(self):
        for i in xrange(3):
            pod = {'pod_id': 'test_pod_uuid_%d' % i,
                   'region_name': 'test_pod_%d' % i,
                   'az_name': 'test_az_uuid_%d' % i}
            api.create_pod(self.context, pod)
        route1 = {
            'top_id': 'top_uuid',
            'pod_id': 'test_pod_uuid_0',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_uuid',
            'pod_id': 'test_pod_uuid_1',
            'bottom_id': 'bottom_uuid_1',
            'resource_type': 'port'}
        route3 = {
            'top_id': 'top_uuid',
            'pod_id': 'test_pod_uuid_2',
            'bottom_id': 'bottom_uuid_2',
            'resource_type': 'neutron'}
        routes = [route1, route2, route3]
        with self.context.session.begin():
            for route in routes:
                core.create_resource(
                    self.context, models.ResourceRouting, route)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_uuid', 'port')
        self.assertEqual('test_pod_uuid_1', mappings[0][0]['pod_id'])
        self.assertEqual('bottom_uuid_1', mappings[0][1])

    def test_get_bottom_mappings_by_tenant_pod(self):
        for i in xrange(3):
            pod = {'pod_id': 'test_pod_uuid_%d' % i,
                   'region_name': 'test_pod_%d' % i,
                   'az_name': 'test_az_uuid_%d' % i}
            api.create_pod(self.context, pod)
        routes = [
            {
                'route':
                {
                    'top_id': 'top_uuid',
                    'pod_id': 'test_pod_uuid_0',
                    'project_id': 'test_project_uuid_0',
                    'resource_type': 'port'
                },
            },

            {
                'route':
                {
                    'top_id': 'top_uuid_0',
                    'bottom_id': 'top_uuid_0',
                    'pod_id': 'test_pod_uuid_0',
                    'project_id': 'test_project_uuid_0',
                    'resource_type': 'port'
                },
            },

            {
                'route':
                {
                    'top_id': 'top_uuid_1',
                    'bottom_id': 'top_uuid_1',
                    'pod_id': 'test_pod_uuid_0',
                    'project_id': 'test_project_uuid_0',
                    'resource_type': 'port'
                },
            },

            {
                'route':
                {
                    'top_id': 'top_uuid_2',
                    'bottom_id': 'top_uuid_2',
                    'pod_id': 'test_pod_uuid_0',
                    'project_id': 'test_project_uuid_1',
                    'resource_type': 'port'
                },
            },

            {
                'route':
                {
                    'top_id': 'top_uuid_3',
                    'bottom_id': 'top_uuid_3',
                    'pod_id': 'test_pod_uuid_1',
                    'project_id': 'test_project_uuid_1',
                    'resource_type': 'port'
                },
            }
            ]

        with self.context.session.begin():
            for route in routes:
                core.create_resource(
                    self.context, models.ResourceRouting, route['route'])

        routings = api.get_bottom_mappings_by_tenant_pod(
            self.context,
            'test_project_uuid_0',
            'test_pod_uuid_0',
            'port'
        )
        self.assertEqual(len(routings), 2)
        self.assertEqual(routings['top_uuid_0']['top_id'], 'top_uuid_0')
        self.assertEqual(routings['top_uuid_1']['top_id'], 'top_uuid_1')

        routings = api.get_bottom_mappings_by_tenant_pod(
            self.context,
            'test_project_uuid_1',
            'test_pod_uuid_0',
            'port'
        )
        self.assertEqual(len(routings), 1)
        self.assertEqual(routings['top_uuid_2']['top_id'], 'top_uuid_2')
        self.assertEqual(routings['top_uuid_2']['bottom_id'], 'top_uuid_2')

        routings = api.get_bottom_mappings_by_tenant_pod(
            self.context,
            'test_project_uuid_1',
            'test_pod_uuid_1',
            'port'
        )
        self.assertEqual(len(routings), 1)
        self.assertEqual(routings['top_uuid_3']['top_id'], 'top_uuid_3')
        self.assertEqual(routings['top_uuid_3']['bottom_id'], 'top_uuid_3')

    def test_get_next_bottom_pod(self):
        next_pod = api.get_next_bottom_pod(self.context)
        self.assertIsNone(next_pod)
        pods = []
        for i in xrange(5):
            pod = {'pod_id': 'test_pod_uuid_%d' % i,
                   'region_name': 'test_pod_%d' % i,
                   'pod_az_name': 'test_pod_az_name_%d' % i,
                   'dc_name': 'test_dc_name_%d' % i,
                   'az_name': 'test_az_uuid_%d' % i,
                   }
            api.create_pod(self.context, pod)
            pods.append(pod)
        next_pod = api.get_next_bottom_pod(self.context)
        self.assertEqual(next_pod, pods[0])

        next_pod = api.get_next_bottom_pod(
            self.context, current_pod_id='test_pod_uuid_2')
        self.assertEqual(next_pod, pods[3])

        next_pod = api.get_next_bottom_pod(
            self.context, current_pod_id='test_pod_uuid_4')
        self.assertIsNone(next_pod)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
