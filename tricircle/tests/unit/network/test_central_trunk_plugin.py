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


import copy
from mock import patch
import six
import unittest

from six.moves import xrange
from sqlalchemy.orm import attributes
from sqlalchemy.orm import exc
from sqlalchemy.sql import elements
from sqlalchemy.sql import expression

import neutron.conf.common as q_config
from neutron.db import db_base_plugin_v2
from neutron.plugins.common import utils
from neutron_lib.api.definitions import portbindings
import neutron_lib.context as q_context
from neutron_lib.plugins import directory

from oslo_config import cfg
from oslo_utils import uuidutils

from tricircle.common import client
from tricircle.common import constants
from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import central_plugin
import tricircle.network.central_trunk_plugin as trunk_plugin
from tricircle.network import helper
from tricircle.xjob import xmanager


TOP_TRUNKS = []
TOP_SUBPORTS = []
TOP_PORTS = []
BOTTOM1_TRUNKS = []
BOTTOM2_TRUNKS = []
BOTTOM1_SUBPORTS = []
BOTTOM2_SUBPORTS = []
BOTTOM1_PORTS = []
BOTTOM2_PORTS = []
RES_LIST = [TOP_TRUNKS, TOP_SUBPORTS, TOP_PORTS,
            BOTTOM1_TRUNKS, BOTTOM2_TRUNKS, BOTTOM1_PORTS, BOTTOM2_PORTS,
            BOTTOM1_SUBPORTS, BOTTOM2_SUBPORTS]
RES_MAP = {'trunks': TOP_TRUNKS, 'subports': TOP_SUBPORTS, 'ports': TOP_PORTS}
TEST_TENANT_ID = 'test_tenant_id'


class DotDict(dict):
    def __init__(self, normal_dict=None):
        if normal_dict:
            for key, value in six.iteritems(normal_dict):
                self[key] = value

    def __getattr__(self, item):
        return self.get(item)

    def __copy__(self):
        return DotDict(self)

    def bump_revision(self):
        pass

    def save(self, session=None):
        pass


class DotList(list):
    def all(self):
        return self


class FakeBaseXManager(xmanager.XManager):
    def __init__(self):
        self.clients = {constants.TOP: client.Client()}

    def _get_client(self, region_name=None):
        return FakeClient(region_name)


class FakeXManager(FakeBaseXManager):
    def __init__(self, fake_plugin):
        super(FakeXManager, self).__init__()
        self.xjob_handler = FakeBaseRPCAPI(fake_plugin)
        self.helper = helper.NetworkHelper()


class FakeBaseRPCAPI(object):
    def __init__(self, fake_plugin):
        self.xmanager = FakeBaseXManager()

    def sync_trunk(self, ctxt, project_id, trunk_id, pod_id):
        combine_id = '%s#%s' % (pod_id, trunk_id)
        self.xmanager.sync_trunk(
            ctxt, payload={constants.JT_TRUNK_SYNC: combine_id})

    def configure_security_group_rules(self, ctxt, project_id):
        pass


class FakeRPCAPI(FakeBaseRPCAPI):
    def __init__(self, fake_plugin):
        self.xmanager = FakeXManager(fake_plugin)


class FakeNeutronClient(object):

    _res_map = {'top': {'trunk': TOP_TRUNKS},
                'pod_1': {'trunk': BOTTOM1_TRUNKS},
                'pod_2': {'trunk': BOTTOM2_TRUNKS}}

    def __init__(self, region_name):
        self.region_name = region_name
        self.trunks_path = ''

    def _get(self, params=None):
        trunk_list = self._res_map[self.region_name]['trunk']
        return_list = []

        if not params:
            return {'trunks': trunk_list}

        params_copy = copy.deepcopy(params)
        limit = params_copy.pop('limit', None)
        marker = params_copy.pop('marker', None)

        if params_copy:
            for trunk in trunk_list:
                is_selected = True
                for key, value in six.iteritems(params_copy):
                    if (key not in trunk
                        or not trunk[key]
                            or trunk[key] not in value):
                        is_selected = False
                        break
                if is_selected:
                    return_list.append(trunk)
        else:
            return_list = trunk_list

        if marker:
            sorted_list = sorted(return_list, key=lambda x: x['id'])
            for i, trunk in enumerate(sorted_list):
                if trunk['id'] == marker:
                    return_list = sorted_list[i + 1:]

        if limit:
            sorted_list = sorted(return_list, key=lambda x: x['id'])
            if limit > len(sorted_list):
                last_index = len(sorted_list)
            else:
                last_index = limit
            return_list = sorted_list[0: last_index]

        return {'trunks': return_list}

    def get(self, path, params=None):
        if self.region_name in ['pod_1', 'pod_2', 'top']:
            res_list = self._get(params)['trunks']
            return_list = []
            for res in res_list:
                if self.region_name != 'top':
                    res = copy.copy(res)
                return_list.append(res)
            return {'trunks': return_list}
        else:
            raise Exception()


class FakeClient(object):

    _res_map = {'top': RES_MAP,
                'pod_1': {'trunk': BOTTOM1_TRUNKS, 'port': BOTTOM1_PORTS},
                'pod_2': {'trunk': BOTTOM2_TRUNKS}}

    def __init__(self, region_name=None):
        if not region_name:
            self.region_name = 'top'
        else:
            self.region_name = region_name
        self.client = FakeNeutronClient(self.region_name)

    def get_native_client(self, resource, ctx):
        return self.client

    def create_resources(self, _type, ctx, body):
        res_list = self._res_map[self.region_name][_type]
        res = dict(body[_type])
        res_list.append(res)
        return res

    def list_resources(self, _type, ctx, filters=None):
        if self.region_name == 'top':
            res_list = self._res_map[self.region_name][_type + 's']
        else:
            res_list = self._res_map[self.region_name][_type]
        ret_list = []
        for res in res_list:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if _filter['value'] != res[_filter['key']]:
                    is_selected = False
                    break
            if is_selected:
                ret_list.append(res)
        return ret_list

    def delete_resources(self, _type, ctx, _id):
        index = -1
        if self.region_name == 'top':
            res_list = self._res_map[self.region_name][_type + 's']
        else:
            res_list = self._res_map[self.region_name][_type]
        for i, res in enumerate(res_list):
            if res['id'] == _id:
                index = i
        if index != -1:
            del res_list[index]

    def get_trunks(self, ctx, trunk_id):
        res = self.list_resources('trunk', ctx,
                                  [{'key': 'id',
                                    'comparator': 'eq',
                                    'value': trunk_id}])
        if res:
            return res[0]
        return res

    def update_trunks(self, context, trunk_id, trunk):
        trunk_data = trunk[constants.RT_TRUNK]
        if self.region_name == 'pod_1':
            btm_trunks = BOTTOM1_TRUNKS
        else:
            btm_trunks = BOTTOM2_TRUNKS

        for trunk in btm_trunks:
            if trunk['id'] == trunk_id:
                for key in trunk_data:
                    trunk[key] = trunk_data[key]
                return

    def delete_trunks(self, context, trunk_id):
        if self.region_name == 'pod_1':
            btm_trunks = BOTTOM1_TRUNKS
        else:
            btm_trunks = BOTTOM2_TRUNKS

        for trunk in btm_trunks:
            if trunk['id'] == trunk_id:
                btm_trunks.remove(trunk)
                return

    def action_trunks(self, ctx, action, resource_id, body):
        if self.region_name == 'pod_1':
            btm_trunks = BOTTOM1_TRUNKS
        else:
            btm_trunks = BOTTOM2_TRUNKS

        for trunk in btm_trunks:
            if trunk['id'] == resource_id:
                subports = body['sub_ports']
                if action == 'add_subports':
                    for subport in subports:
                        subport['trunk_id'] = resource_id
                    trunk['sub_ports'].extend(subports)
                    return
                elif action == 'remove_subports':
                    for subport in subports:
                        for b_subport in trunk['sub_ports']:
                            if subport['port_id'] == b_subport['port_id']:
                                trunk['sub_ports'].remove(b_subport)
                    return

    def list_trunks(self, ctx, filters=None):
        filter_dict = {}
        filters = filters or []
        for query_filter in filters:
            key = query_filter['key']
            # when querying trunks, "fields" is passed in the query string to
            # ask the server to only return necessary fields, which can reduce
            # the data being transfered. in test, we just return all the fields
            # since there's no need to optimize
            if key != 'fields':
                value = query_filter['value']
                filter_dict[key] = value
        return self.client.get('', filter_dict)['trunks']

    def get_ports(self, ctx, port_id):
        pass

    def list_ports(self, ctx, filters=None):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        _filters = {}
        for f in filters:
            _filters[f['key']] = [f['value']]
        return fake_plugin.get_trunk_subports(q_ctx, _filters)

    def create_ports(self, ctx, body):
        if 'ports' in body:
            ret = []
            for port in body['ports']:
                p = self.create_resources('port', ctx, {'port': port})
                p['id'] = p['device_id']
                ret.append(p)
            return ret
        return self.create_resources('port', ctx, body)


class FakeNeutronContext(q_context.Context):
    def __init__(self):
        self._session = None
        self.is_admin = True
        self.is_advsvc = False
        self.tenant_id = TEST_TENANT_ID

    @property
    def session(self):
        if not self._session:
            self._session = FakeSession()
        return self._session

    def elevated(self):
        return self


def delete_model(res_list, model_obj, key=None):
    if not res_list:
        return
    if not key:
        key = 'id'
    if key not in res_list[0]:
        return
    index = -1
    for i, res in enumerate(res_list):
        if res[key] == model_obj[key]:
            index = i
            break
    if index != -1:
        del res_list[index]
        return


class FakeQuery(object):
    def __init__(self, records, table):
        self.records = records
        self.table = table
        self.index = 0

    def _handle_pagination_by_id(self, record_id):
        for i, record in enumerate(self.records):
            if record['id'] == record_id:
                if i + 1 < len(self.records):
                    return FakeQuery(self.records[i + 1:], self.table)
                else:
                    return FakeQuery([], self.table)
        return FakeQuery([], self.table)

    def _handle_filter(self, keys, values):
        filtered_list = []
        for record in self.records:
            selected = True
            for i, key in enumerate(keys):
                if key not in record or record[key] != values[i]:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def filter(self, *criteria):
        _filter = []
        keys = []
        values = []
        for e in criteria:
            if isinstance(e, expression.BooleanClauseList):
                e = e.clauses[0]
            if not hasattr(e, 'right') and isinstance(e, elements.False_):
                # filter is a single False value, set key to a 'INVALID_FIELD'
                # then no records will be returned
                keys.append('INVALID_FIELD')
                values.append(False)
            elif hasattr(e, 'right') and not isinstance(e.right,
                                                        elements.Null):
                _filter.append(e)
        if not _filter:
            if not keys:
                return FakeQuery(self.records, self.table)
            else:
                return self._handle_filter(keys, values)
        if hasattr(_filter[0].right, 'value'):
            keys.extend([f.left.name for f in _filter])
            values.extend([f.right.value for f in _filter])
        else:
            keys.extend([f.expression.left.name for f in _filter])
            values.extend(
                [f.expression.right.element.clauses[0].value for f in _filter])
        if _filter[0].expression.operator.__name__ == 'lt':
            return self._handle_pagination_by_id(values[0])
        else:
            return self._handle_filter(keys, values)

    def filter_by(self, **kwargs):
        filtered_list = []
        for record in self.records:
            selected = True
            for key, value in six.iteritems(kwargs):
                if key not in record or record[key] != value:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def delete(self, synchronize_session=False):
        for model_obj in self.records:
            delete_model(RES_MAP[self.table], model_obj)

    def order_by(self, func):
        self.records.sort(key=lambda x: x['id'])
        return FakeQuery(self.records, self.table)

    def enable_eagerloads(self, value):
        return FakeQuery(self.records, self.table)

    def limit(self, limit):
        return FakeQuery(self.records[:limit], self.table)

    def next(self):
        if self.index >= len(self.records):
            raise StopIteration
        self.index += 1
        return self.records[self.index - 1]

    __next__ = next

    def one(self):
        if len(self.records) == 0:
            raise exc.NoResultFound()
        return self.records[0]

    def first(self):
        if len(self.records) == 0:
            return None
        else:
            return self.records[0]

    def update(self, values):
        for record in self.records:
            for key, value in six.iteritems(values):
                record[key] = value
        return len(self.records)

    def all(self):
        return self.records

    def count(self):
        return len(self.records)

    def __iter__(self):
        return self


class FakeSession(object):
    class WithWrapper(object):
        def __enter__(self):
            pass

        def __exit__(self, type, value, traceback):
            pass

    def __init__(self):
        self.info = {}

    def __getattr__(self, field):
        def dummy_method(*args, **kwargs):
            pass

        return dummy_method

    @property
    def is_active(self):
        return True

    def begin(self, subtransactions=False, nested=True):
        return FakeSession.WithWrapper()

    def begin_nested(self):
        return FakeSession.WithWrapper()

    def query(self, model):
        if isinstance(model, attributes.InstrumentedAttribute):
            model = model.class_
        if model.__tablename__ not in RES_MAP:
            return FakeQuery([], model.__tablename__)
        return FakeQuery(RES_MAP[model.__tablename__],
                         model.__tablename__)

    def add(self, model_obj):
        if model_obj.__tablename__ not in RES_MAP:
            return
        model_dict = DotDict(model_obj._as_dict())
        if 'project_id' in model_dict:
            model_dict['tenant_id'] = model_dict['project_id']

        if model_obj.__tablename__ == 'subports':
            for top_trunk in TOP_TRUNKS:
                if top_trunk['id'] == model_dict['trunk_id']:
                    top_trunk['sub_ports'].append(model_dict)

        RES_MAP[model_obj.__tablename__].append(model_dict)

    def delete_top_subport(self, port_id):
        for res_list in RES_MAP.values():
            for res in res_list:
                sub_ports = res.get('sub_ports')
                if sub_ports:
                    for sub_port in sub_ports:
                        if sub_port['port_id'] == port_id:
                            sub_ports.remove(sub_port)

    def delete(self, model_obj):
        key = None
        if model_obj.get('segmentation_type'):
            key = 'port_id'
            self.delete_top_subport(model_obj['port_id'])
        for res_list in RES_MAP.values():
            delete_model(res_list, model_obj, key)


class FakePlugin(trunk_plugin.TricircleTrunkPlugin):
    def __init__(self):
        self._segmentation_types = {'vlan': utils.is_valid_vlan_tag}
        self.xjob_handler = FakeRPCAPI(self)
        self.helper = helper.NetworkHelper(self)

    def _get_client(self, region_name):
        return FakeClient(region_name)


def fake_get_context_from_neutron_context(q_context):
    ctx = context.get_db_context()
    return ctx


def fake_get_min_search_step(self):
    return 2


class FakeCorePlugin(central_plugin.TricirclePlugin):
    def __init__(self):
        pass

    def get_port(self, context, port_id):
        return {portbindings.HOST_ID: None,
                'device_id': None}

    def get_ports(self, ctx, filters):
        top_client = FakeClient()
        _filters = []
        for key, values in six.iteritems(filters):
            for v in values:
                _filters.append({'key': key, 'comparator': 'eq', 'value': v})
        return top_client.list_resources('port', ctx, _filters)

    def update_port(self, context, id, port):
        port_body = port['port']
        for _port in TOP_PORTS:
            if _port['id'] == id:
                for key, value in six.iteritems(port_body):
                    _port[key] = value


class PluginTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        xmanager.IN_TEST = True

        def fake_get_plugin(alias='core'):
            if alias == 'trunk':
                return FakePlugin()
            return FakeCorePlugin()
        directory.get_plugin = fake_get_plugin

    def _basic_pod_setup(self):
        pod1 = {'pod_id': 'pod_id_1',
                'region_name': 'pod_1',
                'az_name': 'az_name_1'}
        pod2 = {'pod_id': 'pod_id_2',
                'region_name': 'pod_2',
                'az_name': 'az_name_2'}
        pod3 = {'pod_id': 'pod_id_0',
                'region_name': 'top_pod',
                'az_name': ''}
        for pod in (pod1, pod2, pod3):
            db_api.create_pod(self.context, pod)

    def _prepare_port_test(self, tenant_id, ctx, pod_name, index,
                           device_onwer='compute:None', create_bottom=True):
        t_port_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        t_net_id = uuidutils.generate_uuid()

        t_port = {
            'id': t_port_id,
            'name': 'top_port_%d' % index,
            'description': 'old_top_description',
            'extra_dhcp_opts': [],
            'device_owner': device_onwer,
            'security_groups': [],
            'device_id': '68f46ee4-d66a-4c39-bb34-ac2e5eb85470',
            'admin_state_up': True,
            'network_id': t_net_id,
            'tenant_id': tenant_id,
            'mac_address': 'fa:16:3e:cd:76:4%s' % index,
            'project_id': 'tenant_id',
            'binding:host_id': 'zhiyuan-5',
            'status': 'ACTIVE',
            'network_id': t_net_id,
            'fixed_ips': [{'subnet_id': t_subnet_id}]
        }
        TOP_PORTS.append(DotDict(t_port))

        if create_bottom:
            b_port = {
                'id': t_port_id,
                'name': t_port_id,
                'description': 'old_bottom_description',
                'extra_dhcp_opts': [],
                'device_owner': device_onwer,
                'security_groups': [],
                'device_id': '68f46ee4-d66a-4c39-bb34-ac2e5eb85470',
                'admin_state_up': True,
                'network_id': t_net_id,
                'tenant_id': tenant_id,
                'device_owner': 'compute:None',
                'extra_dhcp_opts': [],
                'mac_address': 'fa:16:3e:cd:76:40',
                'project_id': 'tenant_id',
                'binding:host_id': 'zhiyuan-5',
                'status': 'ACTIVE',
                'network_id': t_net_id,
                'fixed_ips': [{'subnet_id': t_subnet_id}]
            }
            if pod_name == 'pod_1':
                BOTTOM1_PORTS.append(DotDict(b_port))
            else:
                BOTTOM2_PORTS.append(DotDict(b_port))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(ctx, models.ResourceRouting,
                                 {'top_id': t_port_id,
                                  'bottom_id': t_port_id,
                                  'pod_id': pod_id,
                                  'project_id': tenant_id,
                                  'resource_type': constants.RT_PORT})

        return t_port_id

    def _prepare_trunk_test(self, project_id, ctx, pod_name, index,
                            is_create_bottom, t_uuid=None, b_uuid=None):
        t_trunk_id = t_uuid or uuidutils.generate_uuid()
        b_trunk_id = b_uuid or uuidutils.generate_uuid()
        t_parent_port_id = uuidutils.generate_uuid()
        t_sub_port_id = self._prepare_port_test(
            project_id, ctx, pod_name, index, create_bottom=is_create_bottom)

        t_subport = {
            'segmentation_type': 'vlan',
            'port_id': t_sub_port_id,
            'segmentation_id': 164,
            'trunk_id': t_trunk_id}

        t_trunk = {
            'id': t_trunk_id,
            'name': 'top_trunk_%d' % index,
            'status': 'DOWN',
            'description': 'created',
            'admin_state_up': True,
            'port_id': t_parent_port_id,
            'tenant_id': project_id,
            'project_id': project_id,
            'sub_ports': [t_subport]
        }
        TOP_TRUNKS.append(DotDict(t_trunk))
        TOP_SUBPORTS.append(DotDict(t_subport))

        b_trunk = None
        if is_create_bottom:
            b_subport = {
                'segmentation_type': 'vlan',
                'port_id': t_sub_port_id,
                'segmentation_id': 164,
                'trunk_id': b_trunk_id}

            b_trunk = {
                'id': b_trunk_id,
                'name': 'top_trunk_%d' % index,
                'status': 'UP',
                'description': 'created',
                'admin_state_up': True,
                'port_id': t_parent_port_id,
                'tenant_id': project_id,
                'project_id': project_id,
                'sub_ports': [b_subport]
            }

            if pod_name == 'pod_1':
                BOTTOM1_SUBPORTS.append(DotDict(t_subport))
                BOTTOM1_TRUNKS.append(DotDict(b_trunk))
            else:
                BOTTOM2_SUBPORTS.append(DotDict(t_subport))
                BOTTOM2_TRUNKS.append(DotDict(b_trunk))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(ctx, models.ResourceRouting,
                                 {'top_id': t_trunk_id,
                                  'bottom_id': b_trunk_id,
                                  'pod_id': pod_id,
                                  'project_id': project_id,
                                  'resource_type': constants.RT_TRUNK})

        return t_trunk, b_trunk

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_get_trunk(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk, b_trunk = self._prepare_trunk_test(project_id, t_ctx,
                                                    'pod_1', 1, True)
        res = fake_plugin.get_trunk(q_ctx, t_trunk['id'])
        t_trunk['status'] = b_trunk['status']
        t_trunk['sub_ports'][0].pop('trunk_id')
        six.assertCountEqual(self, t_trunk, res)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_get_trunks(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk1, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_1', 1, True)
        t_trunk2, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_1', 2, True)
        t_trunk3, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_2', 3, True)
        t_trunk4, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_2', 4, True)
        t_trunk5, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_1', 5, False)
        t_trunk6, _ = self._prepare_trunk_test(project_id, t_ctx,
                                               'pod_1', 6, False)
        res = fake_plugin.get_trunks(q_ctx)
        self.assertEqual(len(res), 6)

        res = fake_plugin.get_trunks(
            q_ctx, filters={'id': [t_trunk1['id']]}, limit=3)

        t_trunk1['status'] = 'UP'
        res[0]['sub_ports'][0]['trunk_id'] = t_trunk1['id']
        six.assertCountEqual(self, [t_trunk1], res)

        res = fake_plugin.get_trunks(q_ctx, filters={'id': [t_trunk5['id']]})
        t_trunk5['sub_ports'][0].pop('trunk_id')
        six.assertCountEqual(self, [t_trunk5], res)

        trunks = fake_plugin.get_trunks(q_ctx,
                                        filters={'status': ['UP'],
                                                 'description': ['created']})
        self.assertEqual(len(trunks), 4)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(FakePlugin, '_get_min_search_step',
                  new=fake_get_min_search_step)
    def test_get_trunks_pagination(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk1, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_1', 1, True,
            '101779d0-e30e-495a-ba71-6265a1669701',
            '1b1779d0-e30e-495a-ba71-6265a1669701')
        t_trunk2, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_1', 2, True,
            '201779d0-e30e-495a-ba71-6265a1669701',
            '2b1779d0-e30e-495a-ba71-6265a1669701')
        t_trunk3, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_2', 3, True,
            '301779d0-e30e-495a-ba71-6265a1669701',
            '3b1779d0-e30e-495a-ba71-6265a1669701')
        t_trunk4, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_2', 4, True,
            '401779d0-e30e-495a-ba71-6265a1669701',
            '4b1779d0-e30e-495a-ba71-6265a1669701')
        t_trunk5, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_2', 5, False,
            '501779d0-e30e-495a-ba71-6265a1669701')
        t_trunk6, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_2', 6, False,
            '601779d0-e30e-495a-ba71-6265a1669701')
        t_trunk7, _ = self._prepare_trunk_test(
            project_id, t_ctx, 'pod_2', 7, False,
            '601779d0-e30e-495a-ba71-6265a1669701')

        # limit no marker
        res = fake_plugin.get_trunks(q_ctx, limit=3)
        res_trunk_ids = [trunk['id'] for trunk in res]
        except_trunk_ids = [t_trunk1['id'], t_trunk2['id'], t_trunk3['id']]
        self.assertEqual(res_trunk_ids, except_trunk_ids)

        # limit and top pod's marker
        res = fake_plugin.get_trunks(q_ctx, limit=3, marker=t_trunk5['id'])
        res_trunk_ids = [trunk['id'] for trunk in res]
        except_trunk_ids = [t_trunk6['id'], t_trunk7['id']]
        self.assertEqual(res_trunk_ids, except_trunk_ids)

        # limit and bottom pod's marker
        res = fake_plugin.get_trunks(q_ctx, limit=6, marker=t_trunk1['id'])
        res_trunk_ids = [trunk['id'] for trunk in res]
        except_trunk_ids = [t_trunk2['id'], t_trunk3['id'], t_trunk4['id'],
                            t_trunk5['id'], t_trunk6['id'], t_trunk7['id']]
        self.assertEqual(res_trunk_ids, except_trunk_ids)

        # limit and bottom pod's marker and filters
        res = fake_plugin.get_trunks(q_ctx, limit=6, marker=t_trunk1['id'],
                                     filters={'status': ['UP']})
        res_trunk_ids = [trunk['id'] for trunk in res]
        except_trunk_ids = [t_trunk2['id'], t_trunk3['id'], t_trunk4['id']]
        self.assertEqual(res_trunk_ids, except_trunk_ids)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_update_trunk(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk, b_trunk = self._prepare_trunk_test(project_id, t_ctx,
                                                    'pod_1', 1, True)
        update_body = {'trunk': {
            'name': 'new_name',
            'description': 'updated',
            'admin_state_up': False}
        }
        updated_top_trunk = fake_plugin.update_trunk(q_ctx, t_trunk['id'],
                                                     update_body)
        self.assertEqual(updated_top_trunk['name'], 'new_name')
        self.assertEqual(updated_top_trunk['description'], 'updated')
        self.assertEqual(updated_top_trunk['admin_state_up'], False)

        updated_btm_trunk = fake_plugin.get_trunk(q_ctx, t_trunk['id'])
        self.assertEqual(updated_btm_trunk['name'], 'new_name')
        self.assertEqual(updated_btm_trunk['description'], 'updated')
        self.assertEqual(updated_btm_trunk['admin_state_up'], False)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_delete_trunk(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk, b_trunk = self._prepare_trunk_test(project_id, t_ctx,
                                                    'pod_1', 1, True)

        fake_plugin.delete_trunk(q_ctx, t_trunk['id'])
        self.assertEqual(len(TOP_TRUNKS), 0)
        self.assertEqual(len(BOTTOM1_TRUNKS), 0)
        route_filters = [{'key': 'top_id',
                          'comparator': 'eq',
                          'value': t_trunk['id']}]
        routes = core.query_resource(t_ctx, models.ResourceRouting,
                                     route_filters, [])
        self.assertEqual(len(routes), 0)

    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_ports',
                  new=FakeCorePlugin.get_ports)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'update_port',
                  new=FakeCorePlugin.update_port)
    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_action_subports(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk, b_trunk = self._prepare_trunk_test(project_id, t_ctx,
                                                    'pod_1', 1, True)

        add_subport_id1 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  1, create_bottom=False)
        add_subport_id2 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  2, create_bottom=False)
        add_subport_id3 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  3, create_bottom=False)
        add_subport_id4 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  4, create_bottom=False)
        add_subport_id5 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  5, create_bottom=False)
        add_subport_id6 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  6, create_bottom=True)
        add_subport_id7 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  7, create_bottom=True)
        add_subport_id8 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  8, create_bottom=False)
        add_subport_id9 = self._prepare_port_test(project_id, t_ctx, 'pod_1',
                                                  9, create_bottom=False)

        # Avoid warning: assigned to but never used
        ids = [add_subport_id1, add_subport_id2, add_subport_id3,
               add_subport_id4, add_subport_id5, add_subport_id6,
               add_subport_id7, add_subport_id8, add_subport_id9]
        ids.sort()

        remove_subports = {'segmentation_type': 'vlan',
                           'port_id': uuidutils.generate_uuid(),
                           'segmentation_id': 165}
        b_trunk['sub_ports'].append(remove_subports)

        add_subports = []
        for _id in xrange(1, 10):
            port_id = eval("add_subport_id%d" % _id)
            subport = {
                'segmentation_type': 'vlan',
                'port_id': port_id,
                'segmentation_id': _id}
            add_subports.append(subport)

        fake_plugin.add_subports(q_ctx, t_trunk['id'],
                                 {'sub_ports': add_subports})

        top_subports = TOP_TRUNKS[0]['sub_ports']
        btm_subports = BOTTOM1_TRUNKS[0]['sub_ports']

        except_btm_subports = []
        for subport in b_trunk['sub_ports']:
            if subport['segmentation_id'] == 164:
                except_btm_subports.extend([subport])
        for subport in add_subports:
            subport['trunk_id'] = b_trunk['id']
        except_btm_subports.extend(add_subports)
        six.assertCountEqual(self, btm_subports, except_btm_subports)

        except_top_subports = []
        for subport in t_trunk['sub_ports']:
            if subport['segmentation_id'] == 164:
                except_top_subports.extend([subport])
        for subport in add_subports:
            subport['trunk_id'] = t_trunk['id']
        except_top_subports.extend(add_subports)
        except_btm_subports.extend(add_subports)
        six.assertCountEqual(self, top_subports, except_top_subports)

        self.assertEqual(len(BOTTOM1_PORTS), 10)
        map_filters = [{'key': 'resource_type',
                        'comparator': 'eq',
                        'value': constants.RT_PORT},
                       {'key': 'project_id',
                        'comparator': 'eq',
                        'value': project_id}]

        port_mappings = db_api.list_resource_routings(t_ctx, map_filters)
        self.assertEqual(len(port_mappings), 10)

    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'update_port',
                  new=FakeCorePlugin.update_port)
    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_remove_subports(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakePlugin()

        t_trunk, b_trunk = self._prepare_trunk_test(project_id, t_ctx,
                                                    'pod_1', 1, True)
        subport_id = t_trunk['sub_ports'][0]['port_id']

        remove_subport = {'sub_ports': [{'port_id': subport_id}]}
        fake_plugin.remove_subports(q_ctx, t_trunk['id'], remove_subport)

        top_subports = TOP_TRUNKS[0]['sub_ports']
        btm_subports = BOTTOM1_TRUNKS[0]['sub_ports']
        self.assertEqual(len(top_subports), 0)
        self.assertEqual(len(btm_subports), 0)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
        cfg.CONF.unregister_opts(q_config.core_opts)
        xmanager.IN_TEST = False
