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

from six.moves import xrange
import unittest

from tricircle.common import context
from tricircle.common import exceptions

from tricircle.db import api
from tricircle.db import core
from tricircle.db import models


class APITest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def _create_pod(self, index, test_az_uuid):
        pod_body = {'pod_id': 'test_pod_uuid_%d' % index,
                    'region_name': 'test_pod_%d' % index,
                    'pod_az_name': 'test_pod_az_name_%d' % index,
                    'dc_name': 'test_dc_name_%d' % index,
                    'az_name': test_az_uuid,
                    }
        api.create_pod(self.context, pod_body)

    def _create_resource_mappings(self):
        route1 = {
            'top_id': 'top_uuid',
            'pod_id': 'test_pod_uuid_0',
            'resource_type': 'network'}
        route2 = {
            'top_id': 'top_uuid',
            'pod_id': 'test_pod_uuid_1',
            'bottom_id': 'top_uuid',
            'resource_type': 'network'}
        route3 = {
            'top_id': 'top_uuid2',
            'pod_id': 'test_pod_uuid_2',
            'bottom_id': 'bottom_uuid_2',
            'resource_type': 'port'}

        routes = [route1, route2, route3]
        with self.context.session.begin():
            for route in routes:
                core.create_resource(
                    self.context, models.ResourceRouting, route)

    def test_get_bottom_id_by_top_id_region_name(self):
        self._create_pod(0, 'test_az_uuid_0')
        self._create_pod(1, 'test_az_uuid_1')
        self._create_pod(2, 'test_az_uuid_2')
        self._create_resource_mappings()
        region_name = 'test_pod_0'
        bottom_id = api.get_bottom_id_by_top_id_region_name(
            self.context, 'top_uuid', region_name, 'network')
        self.assertIsNone(bottom_id)

        region_name = 'test_pod_1'
        bottom_id = api.get_bottom_id_by_top_id_region_name(
            self.context, 'top_uuid', region_name, 'network')
        self.assertEqual(bottom_id, 'top_uuid')

    def test_get_bottom_mappings_by_top_id(self):
        self._create_pod(0, 'test_az_uuid_0')
        self._create_pod(1, 'test_az_uuid_1')
        self._create_pod(2, 'test_az_uuid_2')
        self._create_resource_mappings()
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_uuid', 'network')
        self.assertEqual('test_pod_uuid_1', mappings[0][0]['pod_id'])
        self.assertEqual('top_uuid', mappings[0][1])

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

    def test_get_pod_by_top_id(self):
        self._create_pod(1, 'test_az_uuid1')
        self._create_pod(2, 'test_az_uuid2')
        routes = [
            {
                'top_id': 'top_uuid_1',
                'bottom_id': 'bottom_uuid_1',
                'pod_id': 'test_pod_uuid_1',
                'project_id': 'test_project_uuid_1',
                'resource_type': 'port'
            },
            {
                'top_id': 'top_uuid_2',
                'bottom_id': 'bottom_uuid_2-1',
                'pod_id': 'test_pod_uuid_1',
                'project_id': 'test_project_uuid_1',
                'resource_type': 'network'
            },
            {
                'top_id': 'top_uuid_2',
                'bottom_id': 'bottom_uuid_2-2',
                'pod_id': 'test_pod_uuid_2',
                'project_id': 'test_project_uuid_1',
                'resource_type': 'network'
            },
            {
                'top_id': 'top_uuid_3',
                'bottom_id': '',
                'pod_id': 'test_pod_uuid_1',
                'project_id': 'test_project_uuid_1',
                'resource_type': 'port'
            }
        ]

        with self.context.session.begin():
            for route in routes:
                core.create_resource(
                    self.context, models.ResourceRouting, route)
        pod = api.get_pod_by_top_id(self.context, 'top_uuid_1')
        self.assertEqual(pod['pod_id'], 'test_pod_uuid_1')
        pod = api.get_pod_by_top_id(self.context, 'top_uuid_2')
        # more than one routing entries found, method returns None
        self.assertIsNone(pod)
        pod = api.get_pod_by_top_id(self.context, 'top_uuid_3')
        # bottom_id is empty, method returns None
        self.assertIsNone(pod)

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

    def test_find_pod_by_az_or_region(self):
        self._create_pod(0, 'test_az_uuid1')
        self._create_pod(1, 'test_az_uuid1')
        self._create_pod(2, 'test_az_uuid2')

        az_region = None
        pod = api.find_pod_by_az_or_region(self.context, az_region)
        self.assertIsNone(pod)

        az_region = 'test_pod_3'
        self.assertRaises(exceptions.PodNotFound,
                          api.find_pod_by_az_or_region,
                          self.context, az_region)

        az_region = 'test_pod_0'
        pod = api.find_pod_by_az_or_region(self.context, az_region)
        self.assertEqual(pod['region_name'], az_region)

        az_region = 'test_az_uuid2'
        pod = api.find_pod_by_az_or_region(self.context, az_region)
        self.assertEqual(pod['az_name'], az_region)

        az_region = 'test_az_uuid1'
        self.assertRaises(exceptions.InvalidInput,
                          api.find_pod_by_az_or_region,
                          self.context, az_region)

    def test_get_top_pod(self):
        self._create_pod(0, '')
        self._create_pod(1, 'test_az_uuid1')
        self._create_pod(2, 'test_az_uuid2')

        pod = api.get_top_pod(self.context)
        self.assertEqual(pod['region_name'], 'test_pod_0')
        self.assertEqual(pod['az_name'], '')

    def test_get_pod_by_region(self):
        self._create_pod(0, 'test_az_uuid1')
        self._create_pod(1, 'test_az_uuid1')
        self._create_pod(2, 'test_az_uuid2')

        region_name = 'test_pod_3'
        pod = api.get_pod_by_name(self.context, region_name)
        self.assertIsNone(pod)

        region_name = 'test_pod_0'
        pod = api.get_pod_by_name(self.context, region_name)
        self.assertEqual(pod['region_name'], region_name)

    def test_get_pod(self):
        self._create_pod(0, 'test_az_uuid1')
        self._create_pod(1, 'test_az_uuid1')
        self._create_pod(2, 'test_az_uuid2')

        pod_id = 'test_pod_uuid_0'
        pod = api.get_pod(self.context, pod_id)
        self.assertEqual(pod['pod_id'], pod_id)

        pod_id = 'test_pod_uuid_3'
        self.assertRaises(
            exceptions.ResourceNotFound, api.get_pod, self.context, pod_id)

    def test_delete_mappings_by_bottom_id(self):
        self._create_pod(0, 'test_az_uuid_0')
        self._create_pod(1, 'test_az_uuid_1')
        self._create_pod(2, 'test_az_uuid_2')
        self._create_resource_mappings()
        bottom_id = 'bottom_uuid_1'
        api.delete_mappings_by_bottom_id(self.context, bottom_id)

        filters = [{'key': 'bottom_id', 'comparator': 'eq',
                    'value': bottom_id}]
        routing = core.query_resource(
            self.context, models.ResourceRouting, filters, [])
        self.assertEqual(len(routing), 0)

    def test_delete_mappings_by_top_id(self):
        self._create_pod(0, 'test_az_uuid_0')
        self._create_pod(1, 'test_az_uuid_1')
        self._create_pod(2, 'test_az_uuid_2')
        self._create_resource_mappings()
        top_id = 'top_uuid'

        api.delete_mappings_by_top_id(self.context, top_id,
                                      pod_id='test_pod_uuid_0')
        mappings = api.get_bottom_mappings_by_top_id(
            self.context, top_id, 'network')
        # entry in pod_uuid_0 is deleted, entry in pod_uuid_1 is left
        self.assertEqual(1, len(mappings))
        self.assertEqual('test_pod_uuid_1', mappings[0][0]['pod_id'])

        api.delete_mappings_by_top_id(self.context, top_id)
        mappings = api.get_bottom_mappings_by_top_id(
            self.context, top_id, 'network')
        self.assertEqual(0, len(mappings))

    def test_update_pod(self):
        self._create_pod(0, 'test_az_uuid_0')
        pod_body = {
            'region_name': 'test_pod_1',
            'pod_az_name': 'test_pod_az_name_1',
            'dc_name': 'test_dc_name_1',
            'az_name': 'test_az_uuid_1'}

        updated_pod = api.update_pod(self.context, 'test_pod_uuid_0', pod_body)
        self.assertEqual(updated_pod['region_name'], 'test_pod_1')
        self.assertEqual(updated_pod['pod_az_name'], 'test_pod_az_name_1')
        self.assertEqual(updated_pod['dc_name'], 'test_dc_name_1')
        self.assertEqual(updated_pod['az_name'], 'test_az_uuid_1')

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
