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


import mock
from mock import patch
import unittest

from neutron.db import db_base_plugin_v2

import tricircle.common.client as t_client
from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import plugin


class FakeNeutronClient(object):

    def __init__(self, site_name):
        self.site_name = site_name
        self.ports_path = ''

    def _get(self, params=None):
        site_index = self.site_name.split('_')[1]
        bottom_id = 'bottom_id_%s' % site_index
        if not params:
            return {'ports': [{'id': bottom_id, 'name': 'bottom'}]}
        if params.get('marker') == bottom_id:
            return {'ports': []}
        if 'filters' in params and params['filters'].get('id', []):
            if bottom_id in params['filters']['id']:
                return {'ports': [{'id': bottom_id, 'name': 'bottom'}]}
            else:
                return {'ports': []}
        return {'ports': [{'id': bottom_id, 'name': 'bottom'}]}

    def get(self, path, params=None):
        if self.site_name == 'site_1' or self.site_name == 'site_2':
            return self._get(params)
        else:
            raise Exception()


class FakeClient(object):
    def __init__(self, site_name):
        self.site_name = site_name
        self.client = FakeNeutronClient(self.site_name)

    def get_native_client(self, resource, ctx):
        return self.client

    def list_ports(self, ctx, filters=None):
        filter_dict = {}
        filters = filters or []
        for query_filter in filters:
            key = query_filter['key']
            value = query_filter['value']
            filter_dict[key] = value
        return self.client.get('', {'filters': filter_dict})['ports']

    def get_ports(self, ctx, port_id):
        return self.client.get('')['ports'][0]


class FakeNeutronContext(object):
    def __init__(self):
        self._session = None

    @property
    def session(self):
        if not self._session:
            self._session = FakeSession()
        return self._session


class FakeQuery(object):
    def __init__(self, records):
        self.records = records
        self.index = 0

    def _handle_pagination_by_id(self, record_id):
        for i, record in enumerate(self.records):
            if record['id'] == record_id:
                if i + 1 < len(self.records):
                    return FakeQuery(self.records[i + 1:])
                else:
                    return FakeQuery([])
        return FakeQuery([])

    def _handle_filter_by_id(self, record_id):
        for i, record in enumerate(self.records):
            if record['id'] == record_id:
                return FakeQuery(self.records[i:i + 1])
        return FakeQuery([])

    def filter(self, criteria):
        if hasattr(criteria.right, 'value'):
            record_id = criteria.right.value
            return self._handle_pagination_by_id(record_id)
        else:
            record_id = criteria.expression.right.element.clauses[0].value
            return self._handle_filter_by_id(record_id)

    def order_by(self, func):
        self.records.sort(key=lambda x: x['id'])
        return FakeQuery(self.records)

    def limit(self, limit):
        return FakeQuery(self.records[:limit])

    def next(self):
        if self.index >= len(self.records):
            raise StopIteration
        self.index += 1
        return self.records[self.index - 1]

    def __iter__(self):
        return self


class FakeSession(object):
    class WithWrapper(object):
        def __enter__(self):
            pass

        def __exit__(self, type, value, traceback):
            pass

    def begin(self):
        return FakeSession.WithWrapper()

    def query(self, model):
        return FakeQuery([{'id': 'top_id_0', 'name': 'top'},
                          {'id': 'top_id_1', 'name': 'top'},
                          {'id': 'top_id_2', 'name': 'top'},
                          {'id': 'top_id_3', 'name': 'top'}])


class FakePlugin(plugin.TricirclePlugin):
    def __init__(self):
        self.clients = {'site_1': t_client.Client('site_1'),
                        'site_2': t_client.Client('site_2')}


def fake_get_context_from_neutron_context(q_context):
    return context.get_db_context()


def fake_get_client(self, site_name):
    return FakeClient(site_name)


def fake_get_ports_from_db_with_number(self, ctx, number,
                                       last_port_id, top_set):
    return [{'id': 'top_id_0'}]


def fake_get_ports_from_top(self, context, top_bottom_map):
    return [{'id': 'top_id_0'}]


class ModelsTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def _basic_site_route_setup(self):
        site1 = {'site_id': 'site_id_1',
                 'site_name': 'site_1',
                 'az_id': 'az_id_1'}
        site2 = {'site_id': 'site_id_2',
                 'site_name': 'site_2',
                 'az_id': 'az_id_2'}
        site3 = {'site_id': 'site_id_0',
                 'site_name': 'top_site',
                 'az_id': ''}
        for site in (site1, site2, site3):
            db_api.create_site(self.context, site)
        route1 = {
            'top_id': 'top_id_1',
            'site_id': 'site_id_1',
            'bottom_id': 'bottom_id_1',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_id_2',
            'site_id': 'site_id_2',
            'bottom_id': 'bottom_id_2',
            'resource_type': 'port'}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, route1)
            core.create_resource(self.context, models.ResourceRouting, route2)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port')
    def test_get_port(self, mock_plugin_method):
        self._basic_site_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        fake_plugin.get_port(neutron_context, 'top_id_0')
        port1 = fake_plugin.get_port(neutron_context, 'top_id_1')
        port2 = fake_plugin.get_port(neutron_context, 'top_id_2')
        fake_plugin.get_port(neutron_context, 'top_id_3')

        self.assertEqual({'id': 'top_id_1', 'name': 'bottom'}, port1)
        self.assertEqual({'id': 'top_id_2', 'name': 'bottom'}, port2)
        calls = [mock.call(neutron_context, 'top_id_0', None),
                 mock.call(neutron_context, 'top_id_3', None)]
        mock_plugin_method.assert_has_calls(calls)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_pagination(self):
        self._basic_site_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context, limit=1)
        ports2 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports1[-1]['id'])
        ports3 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports2[-1]['id'])
        ports4 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports3[-1]['id'])
        ports = []
        expected_ports = [{'id': 'top_id_0', 'name': 'top'},
                          {'id': 'top_id_1', 'name': 'bottom'},
                          {'id': 'top_id_2', 'name': 'bottom'},
                          {'id': 'top_id_3', 'name': 'top'}]
        for _ports in (ports1, ports2, ports3, ports4):
            ports.extend(_ports)
        self.assertItemsEqual(expected_ports, ports)

        ports = fake_plugin.get_ports(neutron_context)
        self.assertItemsEqual(expected_ports, ports)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_filters(self):
        self._basic_site_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_0']})
        ports2 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_1']})
        ports3 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_4']})
        self.assertEqual([{'id': 'top_id_0', 'name': 'top'}], ports1)
        self.assertEqual([{'id': 'top_id_1', 'name': 'bottom'}], ports2)
        self.assertEqual([], ports3)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'delete_port')
    @patch.object(t_client.Client, 'delete_resources')
    def test_delete_port(self, mock_client_method, mock_plugin_method,
                         mock_context_method):
        self._basic_site_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context_method.return_value = tricircle_context

        fake_plugin.delete_port(neutron_context, 'top_id_0')
        fake_plugin.delete_port(neutron_context, 'top_id_1')

        calls = [mock.call(neutron_context, 'top_id_0'),
                 mock.call(neutron_context, 'top_id_1')]
        mock_plugin_method.assert_has_calls(calls)
        mock_client_method.assert_called_once_with('port', tricircle_context,
                                                   'bottom_id_1')

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
