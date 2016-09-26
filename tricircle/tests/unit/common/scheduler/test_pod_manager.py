# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from stevedore import driver

from tricircle.common import context
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models

import unittest


class PodManagerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_pm_project'
        self.az_name_2 = 'b_az_pm_2'
        self.az_name_1 = 'b_az_pm_1'
        self.pod_manager = driver.DriverManager(
            namespace='tricircle.common.schedulers',
            name='pod_manager',
            invoke_on_load=True
        ).driver
        self.b_pod_1 = {'pod_id': 'b_pod_pm_uuid_1',
                        'pod_name': 'b_region_pm_1',
                        'az_name': self.az_name_1}

        self.b_pod_2 = {'pod_id': 'b_pod_pm_uuid_2',
                        'pod_name': 'b_region_pm_2',
                        'az_name': self.az_name_2}

        self.b_pod_3 = {'pod_id': 'b_pod_pm_uuid_3',
                        'pod_name': 'b_region_pm_3',
                        'az_name': self.az_name_2}

        self.b_pod_4 = {'pod_id': 'b_pod_pm_uuid_4',
                        'pod_name': 'b_region_pm_4',
                        'az_name': self.az_name_2}

    def test_get_current_binding_and_pod(self):
        api.create_pod(self.context, self.b_pod_1)
        api.create_pod_binding(
            self.context, self.project_id, self.b_pod_1['pod_id'])

        pod_b_1, pod_1 = self.pod_manager.get_current_binding_and_pod(
            self.context, self.az_name_1, self.project_id, pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(binding_q[0]['id'], pod_b_1['id'])

        pod_b_2, pod_2 = self.pod_manager.get_current_binding_and_pod(
            self.context, self.az_name_1, 'new_project_pm_1', pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': 'new_project_pm_1'}], [])
        self.assertEqual(len(binding_q), 0)
        self.assertEqual(pod_b_2, None)
        self.assertEqual(pod_2, None)

        pod_b_3, pod_3 = self.pod_manager.get_current_binding_and_pod(
            self.context, 'unknown_az', self.project_id, pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(pod_b_3, None)
        self.assertEqual(pod_3, None)

        pod_b_4, pod_4 = self.pod_manager.get_current_binding_and_pod(
            self.context, self.az_name_1, self.project_id, pod_group='test')
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(pod_b_4['id'], binding_q[0]['id'])
        self.assertEqual(pod_4, None)

    def test_create_binding(self):
        api.create_pod(self.context, self.b_pod_2)
        flag = self.pod_manager.create_binding(
            self.context, 'new_project_pm_2', self.b_pod_2['pod_id'])
        self.assertEqual(flag, True)
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': 'new_project_pm_2'}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(binding_q[0]['pod_id'], self.b_pod_2['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], 'new_project_pm_2')
        self.assertEqual(binding_q[0]['is_binding'], True)

    def test_update_binding(self):
        api.create_pod(self.context, self.b_pod_4)
        api.create_pod(self.context, self.b_pod_3)
        flag = self.pod_manager.create_binding(
            self.context, 'new_project_pm_3', self.b_pod_3['pod_id'])
        self.assertEqual(flag, True)
        current_binding = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': 'new_project_pm_3'}], [])

        flag = self.pod_manager.update_binding(
            self.context, current_binding[0], self.b_pod_4['pod_id'])
        self.assertEqual(flag, True)
        binding_q = core.query_resource(
            self.context, models.PodBinding,
            [{'key': 'tenant_id',
              'comparator': 'eq',
              'value': 'new_project_pm_3'}], [])
        self.assertEqual(len(binding_q), 2)
        self.assertEqual(binding_q[0]['pod_id'], self.b_pod_3['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], 'new_project_pm_3')
        self.assertEqual(binding_q[0]['is_binding'], False)
        self.assertEqual(binding_q[1]['pod_id'], self.b_pod_4['pod_id'])
        self.assertEqual(binding_q[1]['tenant_id'], 'new_project_pm_3')
        self.assertEqual(binding_q[1]['is_binding'], True)
