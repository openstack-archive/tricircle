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
import mock
from mock import patch
import unittest

from sqlalchemy.orm import exc

from neutron.db import db_base_plugin_common
from neutron.db import db_base_plugin_v2
from neutron.db import ipam_non_pluggable_backend
from neutron.extensions import availability_zone as az_ext
from neutron.ipam import subnet_alloc
import neutronclient.common.exceptions as q_exceptions

from oslo_config import cfg
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import plugin


TOP_NETS = []
TOP_SUBNETS = []
TOP_PORTS = []
TOP_ROUTERS = []
TOP_ROUTERPORT = []
TOP_SUBNETPOOLS = []
TOP_SUBNETPOOLPREFIXES = []
TOP_IPALLOCATIONS = []
TOP_VLANALLOCATIONS = []
TOP_SEGMENTS = []
BOTTOM1_NETS = []
BOTTOM1_SUBNETS = []
BOTTOM1_PORTS = []
BOTTOM1_ROUTERS = []
BOTTOM2_NETS = []
BOTTOM2_SUBNETS = []
BOTTOM2_PORTS = []
BOTTOM2_ROUTERS = []
RES_LIST = [TOP_NETS, TOP_SUBNETS, TOP_PORTS, TOP_ROUTERS, TOP_ROUTERPORT,
            TOP_SUBNETPOOLS, TOP_SUBNETPOOLPREFIXES, TOP_IPALLOCATIONS,
            TOP_VLANALLOCATIONS, TOP_SEGMENTS,
            BOTTOM1_NETS, BOTTOM1_SUBNETS, BOTTOM1_PORTS, BOTTOM1_ROUTERS,
            BOTTOM2_NETS, BOTTOM2_SUBNETS, BOTTOM2_PORTS, BOTTOM2_ROUTERS]
RES_MAP = {'networks': TOP_NETS,
           'subnets': TOP_SUBNETS,
           'ports': TOP_PORTS,
           'routers': TOP_ROUTERS,
           'routerports': TOP_ROUTERPORT,
           'ipallocations': TOP_IPALLOCATIONS,
           'subnetpools': TOP_SUBNETPOOLS,
           'subnetpoolprefixes': TOP_SUBNETPOOLPREFIXES,
           'ml2_vlan_allocations': TOP_VLANALLOCATIONS,
           'ml2_network_segments': TOP_SEGMENTS}


class DotDict(dict):
    def __init__(self, normal_dict=None):
        if normal_dict:
            for key, value in normal_dict.iteritems():
                self[key] = value

    def __getattr__(self, item):
        return self.get(item)


class FakeNeutronClient(object):

    _res_map = {'pod_1': {'network': BOTTOM1_NETS,
                          'subnet': BOTTOM1_SUBNETS,
                          'port': BOTTOM1_PORTS,
                          'router': BOTTOM1_ROUTERS},
                'pod_2': {'network': BOTTOM2_NETS,
                          'subnet': BOTTOM2_SUBNETS,
                          'port': BOTTOM2_PORTS,
                          'router': BOTTOM2_ROUTERS}}

    def __init__(self, pod_name):
        self.pod_name = pod_name
        self.ports_path = ''

    def _get(self, params=None):
        port_list = self._res_map[self.pod_name]['port']

        if not params:
            return {'ports': port_list}
        if 'marker' in params:
            sorted_list = sorted(port_list, key=lambda x: x['id'])
            for i, port in enumerate(sorted_list):
                if port['id'] == params['marker']:
                    return {'ports': sorted_list[i + 1:]}
        if 'filters' in params:
            return_list = []
            for port in port_list:
                is_selected = True
                for key, value in params['filters'].iteritems():
                    if key not in port or port[key] not in value:
                        is_selected = False
                        break
                if is_selected:
                    return_list.append(port)
            return {'ports': return_list}
        return {'ports': port_list}

    def get(self, path, params=None):
        if self.pod_name == 'pod_1' or self.pod_name == 'pod_2':
            res_list = self._get(params)['ports']
            return_list = []
            for res in res_list:
                return_list.append(copy.copy(res))
            return {'ports': return_list}
        else:
            raise Exception()


class FakeClient(object):

    _res_map = {'pod_1': {'network': BOTTOM1_NETS,
                          'subnet': BOTTOM1_SUBNETS,
                          'port': BOTTOM1_PORTS,
                          'router': BOTTOM1_ROUTERS},
                'pod_2': {'network': BOTTOM2_NETS,
                          'subnet': BOTTOM2_SUBNETS,
                          'port': BOTTOM2_PORTS,
                          'router': BOTTOM2_ROUTERS}}

    def __init__(self, pod_name):
        self.pod_name = pod_name
        self.client = FakeNeutronClient(self.pod_name)

    def get_native_client(self, resource, ctx):
        return self.client

    def create_resources(self, _type, ctx, body):
        if _type == 'port':
            res_list = self._res_map[self.pod_name][_type]
            subnet_ips_map = {}
            for res in res_list:
                fixed_ips = res.get('fixed_ips', [])
                for fixed_ip in fixed_ips:
                    if fixed_ip['subnet_id'] not in subnet_ips_map:
                        subnet_ips_map[fixed_ip['subnet_id']] = set()
                    subnet_ips_map[fixed_ip['subnet_id']].add(
                        fixed_ip['ip_address'])
            fixed_ips = body[_type].get('fixed_ips', [])
            for fixed_ip in fixed_ips:
                if fixed_ip['ip_address'] in subnet_ips_map.get(
                        fixed_ip['subnet_id'], set()):
                    raise q_exceptions.IpAddressInUseClient()
            if 'device_id' not in body[_type]:
                body[_type]['device_id'] = ''
        if 'id' not in body[_type]:
            body[_type]['id'] = uuidutils.generate_uuid()
        res_list = self._res_map[self.pod_name][_type]
        res = dict(body[_type])
        res_list.append(res)
        return res

    def list_ports(self, ctx, filters=None):
        filter_dict = {}
        filters = filters or []
        for query_filter in filters:
            key = query_filter['key']
            value = query_filter['value']
            filter_dict[key] = value
        return self.client.get('', {'filters': filter_dict})['ports']

    def get_ports(self, ctx, port_id):
        return self.client.get(
            '', params={'filters': {'id': [port_id]}})['ports'][0]

    def delete_ports(self, ctx, port_id):
        index = -1
        for i, port in enumerate(self._res_map[self.pod_name]['port']):
            if port['id'] == port_id:
                index = i
        if index != -1:
            del self._res_map[self.pod_name]['port'][index]

    def action_routers(self, ctx, action, *args, **kwargs):
        # only for mock purpose
        pass


class FakeNeutronContext(object):
    def __init__(self):
        self._session = None
        self.is_admin = True
        self.is_advsvc = False
        self.tenant_id = ''

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


def link_models(model_obj, model_dict, foreign_table, foreign_key, table, key,
                link_prop):
    if model_obj.__tablename__ == foreign_table:
        for instance in RES_MAP[table]:
            if instance[key] == model_dict[foreign_key]:
                if link_prop not in instance:
                    instance[link_prop] = []
                instance[link_prop].append(model_dict)


def unlink_models(res_list, model_dict, foreign_key, key, link_prop,
                  link_ele_foreign_key, link_ele_key):
    if foreign_key not in model_dict:
        return
    for instance in res_list:
        if instance[key] == model_dict[foreign_key]:
            if link_prop not in instance:
                return
            index = -1
            for i, res in enumerate(instance[link_prop]):
                if res[link_ele_foreign_key] == model_dict[link_ele_key]:
                    index = i
                    break
            if index != -1:
                del instance[link_prop][index]
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
        if hasattr(criteria[0].right, 'value'):
            keys = [e.left.name for e in criteria]
            values = [e.right.value for e in criteria]
        else:
            keys = [e.expression.left.name for e in criteria]
            values = [
                e.expression.right.element.clauses[0].value for e in criteria]
        if criteria[0].expression.operator.__name__ == 'lt':
            return self._handle_pagination_by_id(values[0])
        else:
            return self._handle_filter(keys, values)

    def filter_by(self, **kwargs):
        filtered_list = []
        for record in self.records:
            selected = True
            for key, value in kwargs.iteritems():
                if key not in record or record[key] != value:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def delete(self):
        for model_obj in self.records:
            unlink_models(RES_MAP['routers'], model_obj, 'router_id',
                          'id', 'attached_ports', 'port_id', 'port_id')
            delete_model(RES_MAP[self.table], model_obj, key='port_id')

    def outerjoin(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

    def join(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

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
            for key, value in values.iteritems():
                record[key] = value
        return len(self.records)

    def all(self):
        return self.records

    def __iter__(self):
        return self


class FakeSession(object):
    class WithWrapper(object):
        def __enter__(self):
            pass

        def __exit__(self, type, value, traceback):
            pass

    def begin(self, subtransactions=False):
        return FakeSession.WithWrapper()

    def begin_nested(self):
        return FakeSession.WithWrapper()

    def query(self, model):
        if model.__tablename__ not in RES_MAP:
            return FakeQuery([], model.__tablename__)
        return FakeQuery(RES_MAP[model.__tablename__],
                         model.__tablename__)

    def add(self, model_obj):
        if model_obj.__tablename__ not in RES_MAP:
            return
        model_dict = DotDict(model_obj._as_dict())

        if model_obj.__tablename__ == 'networks':
            model_dict['subnets'] = []
        if model_obj.__tablename__ == 'ports':
            model_dict['dhcp_opts'] = []
            model_dict['security_groups'] = []

        link_models(model_obj, model_dict,
                    'subnetpoolprefixes', 'subnetpool_id',
                    'subnetpools', 'id', 'prefixes')
        link_models(model_obj, model_dict,
                    'ipallocations', 'port_id',
                    'ports', 'id', 'fixed_ips')
        link_models(model_obj, model_dict,
                    'subnets', 'network_id', 'networks', 'id', 'subnets')

        if model_obj.__tablename__ == 'routerports':
            for port in TOP_PORTS:
                if port['id'] == model_dict['port_id']:
                    model_dict['port'] = port
                    port.update(model_dict)
                    break
        link_models(model_obj, model_dict,
                    'routerports', 'router_id',
                    'routers', 'id', 'attached_ports')

        RES_MAP[model_obj.__tablename__].append(model_dict)

    def _cascade_delete(self, model_dict, foreign_key, table, key):
        if foreign_key not in model_dict:
            return
        index = -1
        for i, instance in enumerate(RES_MAP[table]):
            if instance[foreign_key] == model_dict[key]:
                index = i
                break
        if index != -1:
            del RES_MAP[table][index]

    def delete(self, model_obj):
        unlink_models(RES_MAP['routers'], model_obj, 'router_id', 'id',
                      'attached_ports', 'port_id', 'id')
        self._cascade_delete(model_obj, 'port_id', 'ipallocations', 'id')
        for res_list in RES_MAP.values():
            delete_model(res_list, model_obj)

    def flush(self):
        pass


class FakeRPCAPI(object):
    def configure_extra_routes(self, context, router_id):
        pass


class FakePlugin(plugin.TricirclePlugin):
    def __init__(self):
        self.set_ipam_backend()
        self.xjob_handler = FakeRPCAPI()
        self.vlan_driver = plugin.TricircleVlanTypeDriver()

        phynet = 'bridge'
        cfg.CONF.set_override('bridge_physical_network', phynet,
                              group='tricircle')
        TOP_VLANALLOCATIONS.append(
            DotDict({'physical_network': phynet,
                     'vlan_id': 2000, 'allocated': False}))

    def _get_client(self, pod_name):
        return FakeClient(pod_name)

    def _make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
        return network

    def _make_subnet_dict(self, subnet, fields=None, context=None):
        return subnet


def fake_get_context_from_neutron_context(q_context):
    return context.get_db_context()


def fake_get_client(self, pod_name):
    return FakeClient(pod_name)


def fake_make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
    return network


def fake_make_subnet_dict(self, subnet, fields=None, context=None):
    return subnet


@staticmethod
def fake_generate_ip(context, subnets):
    suffix = 1
    for allocation in TOP_IPALLOCATIONS:
        if allocation['subnet_id'] == subnets[0]['id']:
            ip = allocation['ip_address']
            current_suffix = int(ip[ip.rindex('.') + 1:])
            if current_suffix >= suffix:
                suffix = current_suffix
    suffix += 1
    cidr = subnets[0]['cidr']
    new_ip = cidr[:cidr.rindex('.') + 1] + ('%d' % suffix)
    return {'ip_address': new_ip, 'subnet_id': subnets[0]['id']}


@staticmethod
def _allocate_specific_ip(context, subnet_id, ip_address):
    pass


class PluginTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def _basic_pod_route_setup(self):
        pod1 = {'pod_id': 'pod_id_1',
                'pod_name': 'pod_1',
                'az_name': 'az_name_1'}
        pod2 = {'pod_id': 'pod_id_2',
                'pod_name': 'pod_2',
                'az_name': 'az_name_2'}
        pod3 = {'pod_id': 'pod_id_0',
                'pod_name': 'top_pod',
                'az_name': ''}
        for pod in (pod1, pod2, pod3):
            db_api.create_pod(self.context, pod)
        route1 = {
            'top_id': 'top_id_1',
            'pod_id': 'pod_id_1',
            'bottom_id': 'bottom_id_1',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_id_2',
            'pod_id': 'pod_id_2',
            'bottom_id': 'bottom_id_2',
            'resource_type': 'port'}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, route1)
            core.create_resource(self.context, models.ResourceRouting, route2)

    def _basic_port_setup(self):
        TOP_PORTS.extend([{'id': 'top_id_0', 'name': 'top'},
                          {'id': 'top_id_1', 'name': 'top'},
                          {'id': 'top_id_2', 'name': 'top'},
                          {'id': 'top_id_3', 'name': 'top'}])
        BOTTOM1_PORTS.append({'id': 'bottom_id_1', 'name': 'bottom'})
        BOTTOM2_PORTS.append({'id': 'bottom_id_2', 'name': 'bottom'})

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port')
    def test_get_port(self, mock_plugin_method):
        self._basic_pod_route_setup()
        self._basic_port_setup()

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
        self._basic_pod_route_setup()
        self._basic_port_setup()

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
        self._basic_pod_route_setup()
        self._basic_port_setup()

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

        TOP_ROUTERS.append({'id': 'router_id'})
        b_routers_list = [BOTTOM1_ROUTERS, BOTTOM2_ROUTERS]
        b_ports_list = [BOTTOM1_PORTS, BOTTOM2_PORTS]
        for i in xrange(1, 3):
            router_id = 'router_%d_id' % i
            b_routers_list[i - 1].append({'id': router_id})
            route = {
                'top_id': 'router_id',
                'pod_id': 'pod_id_%d' % i,
                'bottom_id': router_id,
                'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context,
                                     models.ResourceRouting, route)
            # find port and add device_id
            for port in b_ports_list[i - 1]:
                port_id = 'bottom_id_%d' % i
                if port['id'] == port_id:
                    port['device_id'] = router_id
        ports = fake_plugin.get_ports(neutron_context,
                                      filters={'device_id': ['router_id']})
        expected = [{'id': 'top_id_1', 'name': 'bottom',
                     'device_id': 'router_id'},
                    {'id': 'top_id_2', 'name': 'bottom',
                     'device_id': 'router_id'}]
        self.assertItemsEqual(expected, ports)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'delete_port')
    @patch.object(FakeClient, 'delete_ports')
    def test_delete_port(self, mock_client_method, mock_plugin_method,
                         mock_context_method):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context_method.return_value = tricircle_context

        fake_plugin.delete_port(neutron_context, 'top_id_0')
        fake_plugin.delete_port(neutron_context, 'top_id_1')

        calls = [mock.call(neutron_context, 'top_id_0'),
                 mock.call(neutron_context, 'top_id_1')]
        mock_plugin_method.assert_has_calls(calls)
        mock_client_method.assert_called_once_with(tricircle_context,
                                                   'bottom_id_1')

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'update_network')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'create_network')
    def test_network_az(self, mock_create, mock_update, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        network = {'network': {
            'id': 'net_id', 'name': 'net_az',
            'availability_zone_hints': ['az_name_1', 'az_name_2']}}
        mock_create.return_value = {'id': 'net_id', 'name': 'net_az'}
        mock_update.return_value = network['network']
        fake_plugin.create_network(neutron_context, network)
        mock_update.assert_called_once_with(
            neutron_context, 'net_id',
            {'network': {
                'availability_zone_hints': '["az_name_1", "az_name_2"]'}})

        err_network = {'network': {
            'id': 'net_id', 'name': 'net_az',
            'availability_zone_hints': ['az_name_1', 'az_name_3']}}
        mock_create.return_value = {'id': 'net_id', 'name': 'net_az'}
        self.assertRaises(az_ext.AvailabilityZoneNotFound,
                          fake_plugin.create_network,
                          neutron_context, err_network)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        network = {'network': {
            'id': 'net_id', 'name': 'net_az',
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': ['az_name_1', 'az_name_2']}}
        fake_plugin.create_network(neutron_context, network)

    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_generate_ip', new=fake_generate_ip)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(subnet_alloc.SubnetAllocator, '_lock_subnetpool',
                  new=mock.Mock)
    def test_prepare_element(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        for pod in db_api.list_pods(t_ctx):
            if not pod['az_name']:
                t_pod = pod
            else:
                b_pod = pod

        # test _prepare_top_element
        pool_id = fake_plugin._get_bridge_subnet_pool_id(
            t_ctx, q_ctx, 'project_id', t_pod)
        net, subnet = fake_plugin._get_bridge_network_subnet(
            t_ctx, q_ctx, 'project_id', t_pod, pool_id)
        port = fake_plugin._get_bridge_interface(
            t_ctx, q_ctx, 'project_id', pod, net['id'], 'b_router_id')

        top_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': 'pod_id_0'}], []):
                top_entry_map[entry['resource_type']] = entry
        self.assertEqual(net['id'], subnet['network_id'])
        self.assertEqual(net['id'], port['network_id'])
        self.assertEqual(subnet['id'], port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(top_entry_map['network']['bottom_id'], net['id'])
        self.assertEqual(top_entry_map['subnet']['bottom_id'], subnet['id'])
        self.assertEqual(top_entry_map['port']['bottom_id'], port['id'])

        # test _prepare_bottom_element
        _, b_port_id = fake_plugin._get_bottom_bridge_elements(
            q_ctx, 'project_id', b_pod, net, subnet, port)
        b_port = fake_plugin._get_client(b_pod['pod_name']).get_ports(
            t_ctx, b_port_id)

        bottom_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': b_pod['pod_id']}], []):
                bottom_entry_map[entry['resource_type']] = entry
        self.assertEqual(bottom_entry_map['network']['top_id'], net['id'])
        self.assertEqual(bottom_entry_map['network']['bottom_id'],
                         b_port['network_id'])
        self.assertEqual(bottom_entry_map['subnet']['top_id'], subnet['id'])
        self.assertEqual(bottom_entry_map['subnet']['bottom_id'],
                         b_port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(bottom_entry_map['port']['top_id'], port['id'])
        self.assertEqual(bottom_entry_map['port']['bottom_id'], b_port_id)

    def _prepare_router_test(self, tenant_id):
        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        t_router_id = uuidutils.generate_uuid()

        t_net = {
            'id': t_net_id,
            'name': 'top_net',
            'availability_zone_hints': ['az_name_1'],
            'tenant_id': tenant_id
        }
        t_subnet = {
            'id': t_subnet_id,
            'network_id': t_net_id,
            'name': 'top_subnet',
            'ip_version': 4,
            'cidr': '10.0.0.0/24',
            'allocation_pools': [],
            'enable_dhcp': True,
            'gateway_ip': '10.0.0.1',
            'ipv6_address_mode': '',
            'ipv6_ra_mode': '',
            'tenant_id': tenant_id
        }
        t_router = {
            'id': t_router_id,
            'name': 'top_router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': []
        }
        TOP_NETS.append(DotDict(t_net))
        TOP_SUBNETS.append(DotDict(t_subnet))
        TOP_ROUTERS.append(DotDict(t_router))

        return t_net_id, t_subnet_id, t_router_id

    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_allocate_specific_ip', new=_allocate_specific_ip)
    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_generate_ip', new=fake_generate_ip)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(subnet_alloc.SubnetAllocator, '_lock_subnetpool',
                  new=mock.Mock)
    @patch.object(FakeRPCAPI, 'configure_extra_routes')
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface(self, mock_context, mock_action, mock_rpc):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = 'test_tenant_id'
        t_net_id, t_subnet_id, t_router_id = self._prepare_router_test(
            tenant_id)

        t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, b_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_port_id, 'port')[0]
        b_port = fake_plugin._get_client('pod_1').get_ports(q_ctx, b_port_id)
        b_net_id = b_port['network_id']
        b_subnet_id = b_port['fixed_ips'][0]['subnet_id']
        _, map_net_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_net_id, 'network')[0]
        _, map_subnet_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_subnet_id, 'subnet')[0]
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, 'router')[0]

        self.assertEqual(b_net_id, map_net_id)
        self.assertEqual(b_subnet_id, map_subnet_id)
        mock_rpc.assert_called_once_with(t_ctx, t_router_id)
        for b_net in BOTTOM1_NETS:
            if 'provider:segmentation_id' in b_net:
                self.assertEqual(TOP_VLANALLOCATIONS[0]['vlan_id'],
                                 b_net['provider:segmentation_id'])
        self.assertEqual(True, TOP_VLANALLOCATIONS[0]['allocated'])
        self.assertEqual(TOP_VLANALLOCATIONS[0]['vlan_id'],
                         TOP_SEGMENTS[0]['segmentation_id'])

        bridge_port_name = constants.bridge_port_name % (tenant_id,
                                                         b_router_id)
        _, t_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port_name, 'port')[0]
        _, b_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_id, 'port')[0]

        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        t_net = {
            'id': t_net_id,
            'name': 'another_top_net',
            'availability_zone_hints': ['az_name_1'],
            'tenant_id': tenant_id
        }
        t_subnet = {
            'id': t_subnet_id,
            'network_id': t_net_id,
            'name': 'another_top_subnet',
            'ip_version': 4,
            'cidr': '10.0.1.0/24',
            'allocation_pools': [],
            'enable_dhcp': True,
            'gateway_ip': '10.0.1.1',
            'ipv6_address_mode': '',
            'ipv6_ra_mode': '',
            'tenant_id': tenant_id
        }
        TOP_NETS.append(DotDict(t_net))
        TOP_SUBNETS.append(DotDict(t_subnet))

        # action_routers is mocked, manually add device_id
        for port in BOTTOM1_PORTS:
            if port['id'] == b_bridge_port_id:
                port['device_id'] = b_router_id

        another_t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, another_b_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, another_t_port_id, 'port')[0]
        another_b_port = fake_plugin._get_client('pod_1').get_ports(
            q_ctx, another_b_port_id)

        calls = [mock.call(t_ctx, 'add_interface', b_router_id,
                           {'port_id': b_bridge_port_id}),
                 mock.call(t_ctx, 'add_interface', b_router_id,
                           {'port_id': b_port['id']}),
                 mock.call(t_ctx, 'add_interface', b_router_id,
                           {'port_id': another_b_port['id']})]
        mock_action.assert_has_calls(calls)
        self.assertEqual(mock_action.call_count, 3)

    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_allocate_specific_ip', new=_allocate_specific_ip)
    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_generate_ip', new=fake_generate_ip)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(subnet_alloc.SubnetAllocator, '_lock_subnetpool',
                  new=mock.Mock)
    @patch.object(FakeRPCAPI, 'configure_extra_routes', new=mock.Mock)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = 'test_tenant_id'
        t_net_id, t_subnet_id, t_router_id = self._prepare_router_test(
            tenant_id)

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            entry_num = len(entries)

        mock_action.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        self.assertEqual(0, len(TOP_ROUTERS[0]['attached_ports']))

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # two new entries, for top and bottom bridge ports
            self.assertEqual(entry_num + 2, len(entries))
        # top and bottom interface is deleted, only bridge port left
        self.assertEqual(1, len(TOP_PORTS))
        self.assertEqual(1, len(BOTTOM1_PORTS))

        mock_action.side_effect = None
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id})
        # bottom interface and bridge port
        self.assertEqual(2, len(BOTTOM1_PORTS))
        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # one more entry, for bottom interface
            self.assertEqual(entry_num + 3, len(entries))

    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_allocate_specific_ip', new=_allocate_specific_ip)
    @patch.object(ipam_non_pluggable_backend.IpamNonPluggableBackend,
                  '_generate_ip', new=fake_generate_ip)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(subnet_alloc.SubnetAllocator, '_lock_subnetpool',
                  new=mock.Mock)
    @patch.object(FakeRPCAPI, 'configure_extra_routes', new=mock.Mock)
    @patch.object(FakeClient, 'delete_ports')
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception_port_left(self, mock_context,
                                               mock_action, mock_delete):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = 'test_tenant_id'
        t_net_id, t_subnet_id, t_router_id = self._prepare_router_test(
            tenant_id)
        mock_action.side_effect = q_exceptions.ConnectionFailed
        mock_delete.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        # fail to delete bottom interface, so top interface is also there
        self.assertEqual(1, len(TOP_ROUTERS[0]['attached_ports']))

        mock_action.side_effect = None
        mock_delete.side_effect = None
        t_port_id = TOP_ROUTERS[0]['attached_ports'][0]['port_id']
        # test that we can reuse the left interface to attach
        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'port_id': t_port_id})
        # bottom interface and bridge port
        self.assertEqual(2, len(BOTTOM1_PORTS))

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
