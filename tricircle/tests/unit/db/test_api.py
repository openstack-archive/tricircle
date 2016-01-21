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

import datetime
import six
import unittest

from tricircle.common import context
from tricircle.common import exceptions
from tricircle.common import quota

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
                   'pod_name': 'test_pod_%d' % i,
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
                   'pod_name': 'test_pod_%d' % i,
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
                   'pod_name': 'test_pod_%d' % i,
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


class QuotaApiTestCase(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.get_admin_context()

    def _quota_reserve(self, context, project_id):
        """Create sample Quota, QuotaUsage and Reservation objects.

        There is no method api.quota_usage_create(), so we have to use
        api.quota_reserve() for creating QuotaUsage objects.

        Returns reservations uuids.

        """
        quotas = {}
        resources = {}
        deltas = {}
        for i, resource in enumerate(('volumes', 'gigabytes')):
            quota_obj = api.quota_create(context, project_id, resource, i + 1)
            quotas[resource] = quota_obj.hard_limit
            resources[resource] = quota.ReservableResource(resource, None)
            deltas[resource] = i + 1
        return api.quota_reserve(
            context, resources, quotas, deltas,
            datetime.datetime.utcnow(), datetime.datetime.utcnow(),
            datetime.timedelta(days=1), project_id
        )

    def _dict_from_object(self, obj, ignored_keys):
        if ignored_keys is None:
            ignored_keys = []
        if isinstance(obj, dict):
            items = obj.items()
        else:
            items = obj.iteritems()
        return {k: v for k, v in items
                if k not in ignored_keys}

    def _assertEqualObjects(self, obj1, obj2, ignored_keys=None):
        obj1 = self._dict_from_object(obj1, ignored_keys)
        obj2 = self._dict_from_object(obj2, ignored_keys)

        self.assertEqual(
            len(obj1), len(obj2),
            "Keys mismatch: %s" % six.text_type(
                set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.items():
            self.assertEqual(value, obj2[key])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())


class DBAPIReservationTestCase(QuotaApiTestCase):

    """Tests for db.api.reservation_* methods."""

    def setUp(self):
        super(DBAPIReservationTestCase, self).setUp()
        self.values = {
            'uuid': 'sample-uuid',
            'project_id': 'project1',
            'resource': 'resource',
            'delta': 42,
            'expire': (datetime.datetime.utcnow() +
                       datetime.timedelta(days=1)),
            'usage': {'id': 1}
        }

    def test_reservation_commit(self):
        reservations = self._quota_reserve(self.context, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         api.quota_usage_get_all_by_project(
                             self.context, 'project1'))
        api.reservation_commit(self.context, reservations, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         api.quota_usage_get_all_by_project(
                             self.context,
                             'project1'))

    def test_reservation_rollback(self):
        reservations = self._quota_reserve(self.context, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         api.quota_usage_get_all_by_project(
                             self.context,
                             'project1'))
        api.reservation_rollback(self.context, reservations, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 0},
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         api.quota_usage_get_all_by_project(
                             self.context,
                             'project1'))

    def test_reservation_expire(self):
        self.values['expire'] = datetime.datetime.utcnow() + \
            datetime.timedelta(days=1)
        self._quota_reserve(self.context, 'project1')
        api.reservation_expire(self.context)

        expected = {'project_id': 'project1',
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    'volumes': {'reserved': 0, 'in_use': 0}}
        self.assertEqual(expected,
                         api.quota_usage_get_all_by_project(
                             self.context,
                             'project1'))


class DBAPIQuotaClassTestCase(QuotaApiTestCase):

    """Tests for api.api.quota_class_* methods."""

    def setUp(self):
        super(DBAPIQuotaClassTestCase, self).setUp()
        self.sample_qc = api.quota_class_create(self.context, 'test_qc',
                                                'test_resource', 42)

    def test_quota_class_get(self):
        qc = api.quota_class_get(self.context, 'test_qc', 'test_resource')
        self._assertEqualObjects(self.sample_qc, qc)

    def test_quota_class_destroy(self):
        api.quota_class_destroy(self.context, 'test_qc', 'test_resource')
        self.assertRaises(exceptions.QuotaClassNotFound,
                          api.quota_class_get, self.context,
                          'test_qc', 'test_resource')

    def test_quota_class_get_not_found(self):
        self.assertRaises(exceptions.QuotaClassNotFound,
                          api.quota_class_get, self.context, 'nonexistent',
                          'nonexistent')

    def test_quota_class_get_all_by_name(self):
        api.quota_class_create(self.context, 'test2', 'res1', 43)
        api.quota_class_create(self.context, 'test2', 'res2', 44)
        self.assertEqual({'class_name': 'test_qc', 'test_resource': 42},
                         api.quota_class_get_all_by_name(self.context,
                                                         'test_qc'))
        self.assertEqual({'class_name': 'test2', 'res1': 43, 'res2': 44},
                         api.quota_class_get_all_by_name(self.context,
                                                         'test2'))

    def test_quota_class_update(self):
        api.quota_class_update(self.context, 'test_qc', 'test_resource', 43)
        updated = api.quota_class_get(self.context, 'test_qc',
                                      'test_resource')
        self.assertEqual(43, updated['hard_limit'])

    def test_quota_class_destroy_all_by_name(self):
        api.quota_class_create(self.context, 'test2', 'res1', 43)
        api.quota_class_create(self.context, 'test2', 'res2', 44)
        api.quota_class_destroy_all_by_name(self.context, 'test2')
        self.assertEqual({'class_name': 'test2'},
                         api.quota_class_get_all_by_name(self.context,
                                                         'test2'))


class DBAPIQuotaTestCase(QuotaApiTestCase):

    """Tests for api.api.reservation_* methods."""

    def test_quota_create(self):
        _quota = api.quota_create(self.context, 'project1', 'resource', 99)
        self.assertEqual('resource', _quota.resource)
        self.assertEqual(99, _quota.hard_limit)
        self.assertEqual('project1', _quota.project_id)

    def test_quota_get(self):
        _quota = api.quota_create(self.context, 'project1', 'resource', 99)
        quota_db = api.quota_get(self.context, 'project1', 'resource')
        self._assertEqualObjects(_quota, quota_db)

    def test_quota_get_all_by_project(self):
        for i in range(3):
            for j in range(3):
                api.quota_create(self.context, 'proj%d' % i, 'res%d' % j, j)
        for i in range(3):
            quotas_db = api.quota_get_all_by_project(self.context,
                                                     'proj%d' % i)
            self.assertEqual({'project_id': 'proj%d' % i,
                              'res0': 0,
                              'res1': 1,
                              'res2': 2}, quotas_db)

    def test_quota_update(self):
        api.quota_create(self.context, 'project1', 'resource1', 41)
        api.quota_update(self.context, 'project1', 'resource1', 42)
        _quota = api.quota_get(self.context, 'project1', 'resource1')
        self.assertEqual(42, _quota.hard_limit)
        self.assertEqual('resource1', _quota.resource)
        self.assertEqual('project1', _quota.project_id)

    def test_quota_update_nonexistent(self):
        self.assertRaises(exceptions.ProjectQuotaNotFound,
                          api.quota_update,
                          self.context,
                          'project1',
                          'resource1',
                          42)

    def test_quota_get_nonexistent(self):
        self.assertRaises(exceptions.ProjectQuotaNotFound,
                          api.quota_get,
                          self.context,
                          'project1',
                          'resource1')

    def test_quota_reserve(self):
        reservations = self._quota_reserve(self.context, 'project1')
        self.assertEqual(2, len(reservations))
        quota_usage = api.quota_usage_get_all_by_project(self.context,
                                                         'project1')
        self.assertEqual({'project_id': 'project1',
                          'gigabytes': {'reserved': 2, 'in_use': 0},
                          'volumes': {'reserved': 1, 'in_use': 0}},
                         quota_usage)

    def test_quota_destroy(self):
        api.quota_create(self.context, 'project1', 'resource1', 41)
        self.assertIsNone(api.quota_destroy(self.context, 'project1',
                                            'resource1'))
        self.assertRaises(exceptions.ProjectQuotaNotFound, api.quota_get,
                          self.context, 'project1', 'resource1')

    def test_quota_destroy_by_project(self):
        # Create limits, reservations and usage for project
        project = 'project1'
        self._quota_reserve(self.context, project)
        expected_usage = {'project_id': project,
                          'volumes': {'reserved': 1, 'in_use': 0},
                          'gigabytes': {'reserved': 2, 'in_use': 0}}
        expected = {'project_id': project, 'gigabytes': 2, 'volumes': 1}

        # Check that quotas are there
        self.assertEqual(expected,
                         api.quota_get_all_by_project(self.context, project))
        self.assertEqual(expected_usage,
                         api.quota_usage_get_all_by_project(self.context,
                                                            project))

        # Destroy only the limits
        api.quota_destroy_by_project(self.context, project)

        # Confirm that limits have been removed
        self.assertEqual({'project_id': project},
                         api.quota_get_all_by_project(self.context, project))

        # But that usage and reservations are the same
        self.assertEqual(expected_usage,
                         api.quota_usage_get_all_by_project(self.context,
                                                            project))

    def test_quota_destroy_sqlalchemy_all_by_project_(self):
        # Create limits, reservations and usage for project
        project = 'project1'
        self._quota_reserve(self.context, project)
        expected_usage = {'project_id': project,
                          'volumes': {'reserved': 1, 'in_use': 0},
                          'gigabytes': {'reserved': 2, 'in_use': 0}}
        expected = {'project_id': project, 'gigabytes': 2, 'volumes': 1}
        expected_result = {'project_id': project}

        # Check that quotas are there
        self.assertEqual(expected,
                         api.quota_get_all_by_project(self.context, project))
        self.assertEqual(expected_usage,
                         api.quota_usage_get_all_by_project(self.context,
                                                            project))

        # Destroy all quotas using SQLAlchemy Implementation
        api.quota_destroy_all_by_project(self.context, project,
                                         only_quotas=False)

        # Check that all quotas have been deleted
        self.assertEqual(expected_result,
                         api.quota_get_all_by_project(self.context, project))
        self.assertEqual(expected_result,
                         api.quota_usage_get_all_by_project(self.context,
                                                            project))

    def test_quota_usage_get_nonexistent(self):
        self.assertRaises(exceptions.QuotaUsageNotFound,
                          api.quota_usage_get,
                          self.context,
                          'p1',
                          'nonexitent_resource')

    def test_quota_usage_get(self):
        self._quota_reserve(self.context, 'p1')
        quota_usage = api.quota_usage_get(self.context, 'p1', 'gigabytes')
        expected = {'resource': 'gigabytes', 'project_id': 'p1',
                    'in_use': 0, 'reserved': 2, 'total': 2}
        for key, value in expected.items():
            self.assertEqual(value, quota_usage[key], key)

    def test_quota_usage_get_all_by_project(self):
        self._quota_reserve(self.context, 'p1')
        expected = {'project_id': 'p1',
                    'volumes': {'in_use': 0, 'reserved': 1},
                    'gigabytes': {'in_use': 0, 'reserved': 2}}
        self.assertEqual(expected, api.quota_usage_get_all_by_project(
                         self.context, 'p1'))
