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
import inspect
import unittest

import oslo_db.exception
import sqlalchemy as sql

from tricircle.common import context
from tricircle.common import exceptions
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models


def _get_field_value(column):
    """Get field value for resource creating

    returning None indicates that not setting this field in resource dict
    """
    if column.nullable:
        # just skip nullable column
        return None
    if isinstance(column.type, sql.Text):
        return 'fake_text'
    elif isinstance(column.type, sql.Enum):
        return column.type.enums[0]
    elif isinstance(column.type, sql.String):
        return 'fake_str'
    elif isinstance(column.type, sql.Integer):
        return 1
    elif isinstance(column.type, sql.Float):
        return 1.0
    elif isinstance(column.type, sql.Boolean):
        return True
    elif isinstance(column.type, sql.DateTime):
        return datetime.datetime.utcnow()
    else:
        return None


def _construct_resource_dict(resource_class):
    ret_dict = {}
    for field in inspect.getmembers(resource_class):
        if field[0] in resource_class.attributes:
            field_value = _get_field_value(field[1])
            if field_value is not None:
                ret_dict[field[0]] = field_value
    return ret_dict


def _sort_model_by_foreign_key(resource_class_list):
    """Apply topology sorting to obey foreign key constraints"""
    relation_map = {}
    table_map = {}
    # {table: (set(depend_on_table), set(depended_by_table))}
    for resource_class in resource_class_list:
        table = resource_class.__tablename__
        if table not in relation_map:
            relation_map[table] = (set(), set())
        if table not in table_map:
            table_map[table] = resource_class
        for field in inspect.getmembers(resource_class):
            if field[0] in resource_class.attributes:
                f_keys = field[1].foreign_keys
                for f_key in f_keys:
                    f_table = f_key.column.table.name
                    # just skip self reference
                    if table == f_table:
                        continue
                    relation_map[table][0].add(f_table)
                    if f_table not in relation_map:
                        relation_map[f_table] = (set(), set())
                    relation_map[f_table][1].add(table)

    sorted_list = []
    total = len(relation_map)

    while len(sorted_list) < total:
        candidate_table = None
        for table in relation_map:
            # no depend-on table
            if not relation_map[table][0]:
                candidate_table = table
                sorted_list.append(candidate_table)
                for _table in relation_map[table][1]:
                    relation_map[_table][0].remove(table)
                break
        del relation_map[candidate_table]

    return [table_map[table] for table in sorted_list]


class ModelsTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def test_obj_to_dict(self):
        pod = {'pod_id': 'test_pod_uuid',
               'region_name': 'test_pod',
               'pod_az_name': 'test_pod_az_name',
               'dc_name': 'test_dc_name',
               'az_name': 'test_az_uuid'}
        pod_obj = models.Pod.from_dict(pod)
        for attr in pod_obj.attributes:
            self.assertEqual(getattr(pod_obj, attr), pod[attr])

    def test_create(self):
        pod = {'pod_id': 'test_pod_uuid',
               'region_name': 'test_pod',
               'pod_az_name': 'test_pod_az_name',
               'dc_name': 'test_dc_name',
               'az_name': 'test_az_uuid'}
        pod_ret = api.create_pod(self.context, pod)
        self.assertEqual(pod_ret, pod)

        configuration = {
            'service_id': 'test_config_uuid',
            'pod_id': 'test_pod_uuid',
            'service_type': 'nova',
            'service_url': 'http://test_url'
        }
        config_ret = api.create_cached_endpoints(self.context,
                                                 configuration)
        self.assertEqual(config_ret, configuration)

    def test_update(self):
        pod = {'pod_id': 'test_pod_uuid',
               'region_name': 'test_pod',
               'az_name': 'test_az1_uuid'}
        api.create_pod(self.context, pod)
        update_dict = {'pod_id': 'fake_uuid',
                       'region_name': 'test_pod2',
                       'az_name': 'test_az2_uuid'}
        ret = api.update_pod(self.context, 'test_pod_uuid', update_dict)
        # primary key value will not be updated
        self.assertEqual(ret['pod_id'], 'test_pod_uuid')
        self.assertEqual(ret['region_name'], 'test_pod2')
        self.assertEqual(ret['az_name'], 'test_az2_uuid')

    def test_delete(self):
        pod = {'pod_id': 'test_pod_uuid',
               'region_name': 'test_pod',
               'az_name': 'test_az_uuid'}
        api.create_pod(self.context, pod)
        api.delete_pod(self.context, 'test_pod_uuid')
        self.assertRaises(exceptions.ResourceNotFound, api.get_pod,
                          self.context, 'test_pod_uuid')

    def test_query(self):
        pod1 = {'pod_id': 'test_pod1_uuid',
                'region_name': 'test_pod1',
                'pod_az_name': 'test_pod_az_name1',
                'dc_name': 'test_dc_name1',
                'az_name': 'test_az1_uuid'}
        pod2 = {'pod_id': 'test_pod2_uuid',
                'region_name': 'test_pod2',
                'pod_az_name': 'test_pod_az_name2',
                'dc_name': 'test_dc_name1',
                'az_name': 'test_az2_uuid'}
        api.create_pod(self.context, pod1)
        api.create_pod(self.context, pod2)
        filters = [{'key': 'region_name',
                    'comparator': 'eq',
                    'value': 'test_pod2'}]
        pods = api.list_pods(self.context, filters)
        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0], pod2)
        filters = [{'key': 'region_name',
                    'comparator': 'eq',
                    'value': 'test_pod3'}]
        pods = api.list_pods(self.context, filters)
        self.assertEqual(len(pods), 0)

    def test_sort(self):
        pod1 = {'pod_id': 'test_pod1_uuid',
                'region_name': 'test_pod1',
                'pod_az_name': 'test_pod_az_name1',
                'dc_name': 'test_dc_name1',
                'az_name': 'test_az1_uuid'}
        pod2 = {'pod_id': 'test_pod2_uuid',
                'region_name': 'test_pod2',
                'pod_az_name': 'test_pod_az_name2',
                'dc_name': 'test_dc_name1',
                'az_name': 'test_az2_uuid'}
        pod3 = {'pod_id': 'test_pod3_uuid',
                'region_name': 'test_pod3',
                'pod_az_name': 'test_pod_az_name3',
                'dc_name': 'test_dc_name1',
                'az_name': 'test_az3_uuid'}
        pods = [pod1, pod2, pod3]
        for pod in pods:
            api.create_pod(self.context, pod)
        pods = api.list_pods(self.context,
                             sorts=[(models.Pod.pod_id, False)])
        self.assertEqual(pods, [pod3, pod2, pod1])

    def test_resources(self):
        """Create all the resources to test model definition"""
        try:
            model_list = []
            for _, model_class in inspect.getmembers(models):
                if inspect.isclass(model_class) and (
                        issubclass(model_class, core.ModelBase)):
                    model_list.append(model_class)
            for model_class in _sort_model_by_foreign_key(model_list):
                create_dict = _construct_resource_dict(model_class)
                with self.context.session.begin():
                    core.create_resource(
                        self.context, model_class, create_dict)
        except Exception as e:
            msg = str(e)
            self.fail('test_resources raised Exception unexpectedly %s' % msg)

    def test_resource_routing_unique_key(self):
        pod = {'pod_id': 'test_pod1_uuid',
               'region_name': 'test_pod1',
               'az_name': 'test_az1_uuid'}
        api.create_pod(self.context, pod)
        routing = {'top_id': 'top_uuid',
                   'pod_id': 'test_pod1_uuid',
                   'resource_type': 'port'}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, routing)
        self.assertRaises(oslo_db.exception.DBDuplicateEntry,
                          core.create_resource,
                          self.context, models.ResourceRouting, routing)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
