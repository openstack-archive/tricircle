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

from tricircle.common import context
from tricircle.common.scheduler import filter_scheduler
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models
import unittest


class FilterSchedulerTest(unittest.TestCase):

    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.project_id = 'test_fs_project'
        self.az_name_1 = 'b_az_fs_1'
        self.az_name_2 = 'b_az_fs_2'
        self.filter_scheduler = filter_scheduler.FilterScheduler()

    def _prepare_binding(self, pod_id):
        binding = {'tenant_id': self.project_id,
                   'pod_id': pod_id,
                   'is_binding': True}
        api.create_pod_binding(self.context, self.project_id, pod_id)
        return binding

    def test_select_destination(self):
        b_pod_1 = {'pod_id': 'b_pod_fs_uuid_1', 'pod_name': 'b_region_fs_1',
                   'az_name': self.az_name_1}
        api.create_pod(self.context, b_pod_1)
        b_pod_2 = {'pod_id': 'b_pod_fs_uuid_2', 'pod_name': 'b_region_fs_2',
                   'az_name': self.az_name_2}
        api.create_pod(self.context, b_pod_2)
        b_pod_3 = {'pod_id': 'b_pod_fs_uuid_3', 'pod_name': 'b_region_fs_3',
                   'az_name': self.az_name_2}
        api.create_pod(self.context, b_pod_3)

        t_pod = {'pod_id': 'b_pod_fs_uuid_t_pod',
                 'pod_name': 'b_region_fs_t_pod',
                 'az_name': ''}
        api.create_pod(self.context, t_pod)
        self._prepare_binding(b_pod_1['pod_id'])
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': self.project_id}], [])
        self.assertEqual(binding_q[0]['pod_id'], b_pod_1['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], self.project_id)
        self.assertEqual(binding_q[0]['is_binding'], True)

        pod_1, _ = self.filter_scheduler.select_destination(
            self.context, '', self.project_id, pod_group='')
        self.assertEqual(pod_1['pod_id'], b_pod_1['pod_id'])
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(binding_q[0]['pod_id'], pod_1['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], self.project_id)
        self.assertEqual(binding_q[0]['is_binding'], True)

        pod_2, _ = self.filter_scheduler.select_destination(
            self.context, '', 'new_project', pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': 'new_project'}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(binding_q[0]['pod_id'], pod_2['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], 'new_project')
        self.assertEqual(binding_q[0]['is_binding'], True)

        pod_3, _ = self.filter_scheduler.select_destination(
            self.context, self.az_name_1, 'new_project', pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': 'new_project'}], [])
        self.assertEqual(len(binding_q), 1)
        self.assertEqual(binding_q[0]['pod_id'], pod_3['pod_id'])
        self.assertEqual(binding_q[0]['tenant_id'], 'new_project')
        self.assertEqual(binding_q[0]['is_binding'], True)

        pod_4, _ = self.filter_scheduler.select_destination(
            self.context, self.az_name_2, 'new_project', pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': 'new_project'}], [])
        self.assertEqual(len(binding_q), 2)
        self.assertEqual(binding_q[1]['pod_id'], pod_4['pod_id'])
        self.assertEqual(binding_q[1]['tenant_id'], 'new_project')
        self.assertEqual(binding_q[1]['is_binding'], True)

        pod_5, _ = self.filter_scheduler.select_destination(
            self.context, self.az_name_2, self.project_id, pod_group='')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 2)
        self.assertEqual(pod_5['az_name'], self.az_name_2)
        self.assertEqual(binding_q[1]['pod_id'], pod_5['pod_id'])
        self.assertEqual(binding_q[1]['tenant_id'], self.project_id)
        self.assertEqual(binding_q[1]['is_binding'], True)

        pod_6, _ = self.filter_scheduler.select_destination(
            self.context, self.az_name_1, self.project_id, pod_group='test')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 2)
        self.assertEqual(pod_6, None)

        pod_7, _ = self.filter_scheduler.select_destination(
            self.context, self.az_name_2, self.project_id, pod_group='test')
        binding_q = core.query_resource(
            self.context, models.PodBinding, [{'key': 'tenant_id',
                                               'comparator': 'eq',
                                               'value': self.project_id}], [])
        self.assertEqual(len(binding_q), 3)
        self.assertEqual(pod_7['az_name'], self.az_name_2)
        self.assertEqual(binding_q[1]['tenant_id'], self.project_id)
        self.assertEqual(binding_q[1]['is_binding'], False)
        self.assertEqual(binding_q[2]['pod_id'], pod_7['pod_id'])
        self.assertEqual(binding_q[2]['tenant_id'], self.project_id)
        self.assertEqual(binding_q[2]['is_binding'], True)
