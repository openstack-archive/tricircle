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

import copy
import itertools
import logging
import time
import traceback
import yaml

from openstack import connection
from openstack import profile

from tricircle.tests.network_sdk import network_service
from tricircle.tests.tricircle_sdk import multiregion_network_service

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SLEEP_INTERVAL = 20


class DummyRunner(object):
    class DummyResource(object):
        def __init__(self, _id):
            self.id = _id

        def __getattr__(self, item):
            return item

    def __init__(self):
        self.id_pool = {}

    def _get_id(self, _type):
        if _type not in self.id_pool:
            self.id_pool[_type] = 0
        self.id_pool[_type] += 1
        return '%s%d_id' % (_type, self.id_pool[_type])

    def create(self, region, _type, params):
        _id = self._get_id(_type)
        msg = 'create %s with id %s in %s, params: %s' % (
            _type, _id, region, params)
        LOG.info(msg)
        return self.DummyResource(_id)

    def action(self, region, _type, target, method, params):
        msg = '%s %s with id %s in %s, params: %s' % (
            method, _type, target, region, params)
        LOG.info(msg)

    def query(self, region, _type, get_one, params):
        if get_one:
            return self.DummyResource(self._get_id(_type))
        return []

    def validate(self, region, _type, predicate, conditions, params):
        msg = 'validate %s, conditions: %s' % (_type, conditions)
        LOG.info(msg)


class SDKRunner(object):
    region_map = {'central': 'CentralRegion',
                  'region1': 'RegionOne',
                  'region2': 'RegionTwo'}
    serv_reslist_map = {
        'network_sdk': ['network', 'subnet', 'port', 'router', 'fip', 'trunk',
                        'flow_classifier', 'port_pair', 'port_pair_group',
                        'port_chain'],
        'compute': ['server'],
        'image': ['image'],
        'tricircle_sdk': ['job']}
    res_alias_map = {
        'fip': 'ip'}

    def __init__(self, auth_url, project, username, password):
        self.res_serv_map = {}
        for serv in self.serv_reslist_map:
            for res in self.serv_reslist_map[serv]:
                self.res_serv_map[res] = serv

        self.connection_map = {}
        param = {
            'auth_url': auth_url,
            'project_name': project,
            'username': username,
            'password': password}

        for region in ('CentralRegion', 'RegionOne', 'RegionTwo'):
            prof = profile.Profile()
            if region == 'CentralRegion':
                serv = multiregion_network_service.MultiregionNetworkService(
                    version='v1')
                prof._add_service(serv)
            net_serv = network_service.NetworkService(version='v2')
            prof._add_service(net_serv)
            prof.set_region(profile.Profile.ALL, region)
            param['profile'] = prof
            conn = connection.Connection(**param)
            self.connection_map[region] = conn

    def create(self, region, _type, params):
        conn = self.connection_map[self.region_map[region]]
        serv = self.res_serv_map[_type]
        _type = self.res_alias_map.get(_type, _type)
        proxy = getattr(conn, serv)
        return getattr(proxy, 'create_%s' % _type)(**params)

    def action(self, region, _type, target, method, params):
        conn = self.connection_map[self.region_map[region]]
        serv = self.res_serv_map[_type]
        _type = self.res_alias_map.get(_type, _type)
        proxy = getattr(conn, serv)
        if method in ('update', 'delete'):
            method = '%s_%s' % (method, _type)
        getattr(proxy, method)(target, **params)

    def query(self, region, _type, get_one, params):
        conn = self.connection_map[self.region_map[region]]
        serv = self.res_serv_map[_type]
        _type = self.res_alias_map.get(_type, _type)
        proxy = getattr(conn, serv)
        _list = list(getattr(proxy, '%ss' % _type)(**params))
        if get_one:
            return _list[0]
        return _list

    def validate(self, region, _type, predicate, conditions, params):
        def validate_value(actual, expected):
            if isinstance(expected, list):
                actual_len = len(actual)
                expected_len = len(expected)
                if actual_len != expected_len:
                    return False
                for actual_list in itertools.permutations(actual, actual_len):
                    for expected_list in itertools.permutations(expected,
                                                                expected_len):
                        match = True
                        for i, actual_ele in enumerate(actual_list):
                            if not validate_value(actual_ele,
                                                  expected_list[i]):
                                match = False
                                break
                        if match:
                            return True
                return False
            elif isinstance(expected, dict):
                for k in expected:
                    if not validate_value(actual[k], expected[k]):
                        return False
                return True
            elif isinstance(expected, str):
                tokens = expected.split('*')
                if tokens[0] == '' and tokens[-1] == '':
                    return actual.find(tokens[1]) != -1
                elif tokens[0] == '':
                    return actual.endswith(tokens[-1])
                elif tokens[-1] == '':
                    return actual.startswith(tokens[0])
                return actual == expected
            else:
                return actual == expected

        def validate_any_condition(results, condition):
            for result in results:
                if all(validate_value(
                        getattr(result, key),
                        value) for (key, value) in condition.items()):
                    return True
            return False

        def validate_all_condition(results, condition):
            for result in results:
                if not all(validate_value(
                        getattr(result, key),
                        value) for (key, value) in condition.items()):
                    return False
            return True

        results = self.query(region, _type, False, params)
        if predicate == 'any':
            for condition in conditions:
                if not validate_any_condition(results, condition):
                    raise Exception(
                        'Validation fail, acutal results: %s, '
                        'expected results: %s' % (results, condition))
        elif predicate == 'all':
            for condition in conditions:
                if not validate_all_condition(results, condition):
                    raise Exception(
                        'Validation fail, acutal results: %s, '
                        'expected results: %s' % (results, condition))


class RunnerEngine(object):
    def __init__(self, yaml_path, runner):
        self.task_set_map = {}
        self.task_set_id_list = []
        self.runner = runner

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        self._parse_data(data)

    def _validate_task(self, task):
        def collect_require_from_dict(requires, _dict):
            for v in _dict.values():
                if isinstance(v, list):
                    collect_require_from_list(requires, v)
                elif isinstance(v, dict):
                    collect_require_from_dict(requires, v)
                elif not isinstance(v, str):
                    continue
                elif '@' in v:
                    requires.append(v)

        def collect_require_from_list(requires, _list):
            for v in _list:
                if isinstance(v, list):
                    collect_require_from_list(requires, v)
                elif isinstance(v, dict):
                    collect_require_from_dict(requires, v)
                elif not isinstance(v, str):
                    continue
                elif '@' in v:
                    requires.append(v)

        for field in ('task_id', 'region', 'type'):
            if field not in task:
                raise Exception('Required field %s not set' % field)
        for sub_section, fields in [('action', ['target', 'method']),
                                    ('query', ['get_one']),
                                    ('validate', ['predicate', 'condition'])]:
            if sub_section in task:
                for field in fields:
                    if field not in task[sub_section]:
                        raise Exception('Required field %s for %s '
                                        'not set' % (field, sub_section))

        requires = []
        if 'params' in task:
            collect_require_from_dict(requires, task['params'])
        if 'validate' in task:
            collect_require_from_dict(requires, task['validate'])
        if 'action' in task:
            requires.append(task['action']['target'])
        depend = task.get('depend', [])
        for value in requires:
            tokens = value.split('@')
            if len(tokens) == 2 and tokens[0] not in depend:
                raise Exception(
                    'Depend list not complete for %s: %s not in %s' % (
                        task['task_id'], tokens[0], depend))
            elif len(tokens) == 3:
                task_set_id, task_id = tokens[:2]
                if task_set_id not in self.task_set_map:
                    raise Exception(
                        'Depend task set %s for %s not found' % (
                            task_set_id, task['task_id']))
                task_map, _, _ = self.task_set_map[task_set_id]
                if task_id not in task_map:
                    raise Exception(
                        'Depend task %s for %s not found' % (
                            task_id, task['task_id']))

    @staticmethod
    def _parse_dependency(depend_map):
        depend_map = copy.deepcopy(depend_map)
        ordered_list = []
        while len(depend_map):
            pop_list = []
            for _id in depend_map:
                if not depend_map[_id]:
                    ordered_list.append(_id)
                    pop_list.append(_id)
            for _id in pop_list:
                depend_map.pop(_id)
            for depend in depend_map.values():
                for _id in pop_list:
                    if _id in depend:
                        depend.remove(_id)
            if not pop_list:
                raise Exception('Unresolved dependency, '
                                'left s: %s' % depend_map.keys())
        return ordered_list

    def _parse_data(self, data):
        task_set_depend_map = {}
        task_set_tasks_map = {}
        for task_set in data:
            task_set_id = task_set['task_set_id']
            self.task_set_id_list.append(task_set_id)
            task_set_depend_map[task_set_id] = set(
                task_set.get('depend', []))
            task_set_tasks_map[task_set_id] = task_set['tasks']
        ordered_task_set_list = self._parse_dependency(task_set_depend_map)
        for task_set_id in ordered_task_set_list:
            task_map = {}
            task_depend_map = {}
            for task in task_set_tasks_map[task_set_id]:
                task_map[task['task_id']] = task
                task_depend_map[task['task_id']] = set(task.get('depend', []))
                self._validate_task(task)
            ordered_task_list = self._parse_dependency(task_depend_map)
            self.task_set_map[task_set_id] = (task_map, ordered_task_list,
                                              task_set_depend_map[task_set_id])

    @staticmethod
    def _fill_depend_field_in_list(_list, task_result_map,
                                   depend_task_result_map):
        if not _list:
            return
        for i, e in enumerate(_list):
            if isinstance(e, list):
                RunnerEngine._fill_depend_field_in_list(e, task_result_map,
                                                        depend_task_result_map)
            elif isinstance(e, dict):
                RunnerEngine._fill_depend_filed_in_dict(e, task_result_map,
                                                        depend_task_result_map)
            if not isinstance(e, str):
                continue
            tokens = e.split('@')
            if len(tokens) == 2:
                task_id, task_filed = tokens
                _list[i] = getattr(task_result_map[task_id], task_filed)
            elif len(tokens) == 3:
                task_set_id, task_id, task_filed = tokens
                _list[i] = getattr(
                    depend_task_result_map[task_set_id][task_id], task_filed)

    @staticmethod
    def _fill_depend_filed_in_dict(_dict, task_result_map,
                                   depend_task_result_map):
        if not _dict:
            return
        for k, v in _dict.items():
            if isinstance(v, list):
                RunnerEngine._fill_depend_field_in_list(v, task_result_map,
                                                        depend_task_result_map)
            elif isinstance(v, dict):
                RunnerEngine._fill_depend_filed_in_dict(v, task_result_map,
                                                        depend_task_result_map)
            if not isinstance(v, str):
                continue
            tokens = v.split('@')
            if len(tokens) == 2:
                task_id, task_filed = tokens
                _dict[k] = getattr(task_result_map[task_id], task_filed)
            elif len(tokens) == 3:
                task_set_id, task_id, task_filed = tokens
                _dict[k] = getattr(
                    depend_task_result_map[task_set_id][task_id], task_filed)

    @staticmethod
    def _fill_depend_field(params, task_result_map, depend_task_result_map):
        RunnerEngine._fill_depend_filed_in_dict(params, task_result_map,
                                                depend_task_result_map)

    @staticmethod
    def _retry(task_id, retry_num, func, *args):
        run_time = retry_num + 1
        for i in range(run_time):
            try:
                func(*args)
                break
            except Exception:
                if i == run_time - 1:
                    raise
                else:
                    time.sleep(SLEEP_INTERVAL)
                    LOG.info('Redo failed task %s', task_id)

    def run_tasks(self, task_set_id, depend_task_set_result={}):
        if task_set_id not in self.task_set_map:
            raise Exception('Task set %s not found' % task_set_id)
        (task_map, ordered_task_list,
         task_set_depend) = self.task_set_map[task_set_id]
        for set_id in task_set_depend:
            if set_id not in depend_task_set_result:
                raise Exception('Task set %s fails, reason: result for depend '
                                'task set %s not given' % (task_set_id,
                                                           set_id))
        task_result_map = {}
        for task_id in ordered_task_list:
            task = task_map[task_id]
            params = task.get('params', {})
            self._fill_depend_field(params, task_result_map,
                                    depend_task_set_result)
            try:
                if 'action' in task:
                    self._fill_depend_field(task['action'], task_result_map,
                                            depend_task_set_result)
                    self._retry(task_id, task['action'].get('retries', 0),
                                self.runner.action, task['region'],
                                task['type'], task['action']['target'],
                                task['action']['method'], params)
                elif 'query' in task:
                    result = self.runner.query(
                        task['region'], task['type'],
                        task['query']['get_one'], params)
                    task_result_map[task_id] = result
                elif 'validate' in task:
                    self._fill_depend_field(task['validate'], task_result_map,
                                            depend_task_set_result)
                    self._retry(task_id, task['validate'].get('retries', 0),
                                self.runner.validate, task['region'],
                                task['type'], task['validate']['predicate'],
                                task['validate']['condition'], params)
                else:
                    result = self.runner.create(task['region'],
                                                task['type'], params)
                    task_result_map[task_id] = result
                LOG.info('Task %s done\n' % task_id)
            except Exception:
                error_msg = 'Task %s fails, reason: %s' % (
                    task_id, traceback.format_exc())
                return task_result_map, error_msg
        return task_result_map, None

    def run_task_sets(self):
        task_set_result_map = {}
        for task_set_id in self.task_set_id_list:
            _, _, task_set_depend = self.task_set_map[task_set_id]
            depend_task_set_result = dict(
                [(_id, task_set_result_map[_id]) for _id in task_set_depend])
            task_result_map, error_msg = self.run_tasks(
                task_set_id, depend_task_set_result)
            if error_msg:
                return error_msg
            task_set_result_map[task_set_id] = task_result_map
