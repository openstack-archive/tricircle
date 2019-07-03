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
import six
import unittest

from oslo_config import cfg
from oslo_utils import uuidutils

import neutron.conf.common as q_config
import neutron.extensions.securitygroup as ext_sg
from neutron.services.trunk import exceptions as t_exc
from neutron_lib.api.definitions import portbindings
import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions
from neutron_lib.plugins import directory

from tricircle.common import client
from tricircle.common import constants
import tricircle.common.context as t_context
from tricircle.network import helper
import tricircle.network.local_plugin as plugin
import tricircle.tests.unit.utils as test_utils


_resource_store = test_utils.get_resource_store()
TOP_NETS = _resource_store.TOP_NETWORKS
TOP_SUBNETS = _resource_store.TOP_SUBNETS
TOP_PORTS = _resource_store.TOP_PORTS
TOP_SGS = _resource_store.TOP_SECURITYGROUPS
TOP_TRUNKS = _resource_store.TOP_TRUNKS
BOTTOM_NETS = _resource_store.BOTTOM1_NETWORKS
BOTTOM_SUBNETS = _resource_store.BOTTOM1_SUBNETS
BOTTOM_PORTS = _resource_store.BOTTOM1_PORTS
BOTTOM_SGS = _resource_store.BOTTOM1_SECURITYGROUPS
BOTTOM_AGENTS = _resource_store.BOTTOM1_AGENTS


def get_resource_list(_type, is_top):
    pod = 'top' if is_top else 'pod_1'
    return _resource_store.pod_store_map[pod][_type]


def create_resource(_type, is_top, body):
    get_resource_list(_type, is_top).append(body)


def update_resource(_type, is_top, resource_id, body):
    for resource in get_resource_list(_type, is_top):
        if resource['id'] == resource_id:
            resource.update(body)
            return copy.deepcopy(resource)
    raise q_exceptions.NotFound()


def get_resource(_type, is_top, resource_id):
    for resource in get_resource_list(_type, is_top):
        if resource['id'] == resource_id:
            return copy.deepcopy(resource)
    raise q_exceptions.NotFound()


def list_resource(_type, is_top, filters=None):
    resource_list = get_resource_list(_type, is_top)
    if not filters:
        return [copy.deepcopy(resource) for resource in get_resource_list(
            _type, is_top)]
    ret = []
    for resource in resource_list:
        pick = True
        for key, value in six.iteritems(filters):
            if resource.get(key) not in value:
                pick = False
                break
        if pick:
            ret.append(copy.deepcopy(resource))
    return ret


def delete_resource(_type, is_top, resource_id):
    for resource in get_resource_list(_type, is_top):
        if resource['id'] == resource_id:
            return get_resource_list(_type, is_top).remove(resource)
    raise q_exceptions.NotFound()


class FakeTypeManager(object):

    def __init__(self):
        self.drivers = {}


class FakeCorePlugin(object):
    supported_extension_aliases = ['agent']

    def __init__(self):
        self.type_manager = FakeTypeManager()

    def create_network(self, context, network):
        create_resource('network', False, network['network'])
        return network['network']

    def get_network(self, context, _id, fields=None):
        return get_resource('network', False, _id)

    def get_networks(self, context, filters=None, fields=None, sorts=None,
                     limit=None, marker=None, page_reverse=False):
        return list_resource('network', False, filters)

    def create_subnet(self, context, subnet):
        create_resource('subnet', False, subnet['subnet'])
        return subnet['subnet']

    def update_subnet(self, context, _id, subnet):
        return update_resource('subnet', False, _id, subnet['subnet'])

    def delete_subnet(self, context, _id):
        return delete_resource('subnet', False, _id)

    def get_subnet(self, context, _id, fields=None):
        return get_resource('subnet', False, _id)

    def get_subnets(self, context, filters=None, fields=None, sorts=None,
                    limit=None, marker=None, page_reverse=False):
        return list_resource('subnet', False, filters)

    def create_port(self, context, port):
        create_resource('port', False, port['port'])
        return port['port']

    def create_port_bulk(self, context, ports):
        ret_ports = []
        for port in ports['ports']:
            create_resource('port', False, port['port'])
            ret_ports.append(port['port'])
        return ret_ports

    def update_port(self, context, _id, port):
        return update_resource('port', False, _id, port['port'])

    def get_port(self, context, _id, fields=None):
        return get_resource('port', False, _id)

    def get_ports(self, context, filters=None, fields=None, sorts=None,
                  limit=None, marker=None, page_reverse=False):
        return list_resource('port', False, filters)

    def delete_port(self, context, _id, l3_port_check=False):
        delete_resource('port', False, _id)

    def create_security_group(self, context, security_group, default_sg=False):
        create_resource('security_group', False,
                        security_group['security_group'])
        return security_group['security_group']

    def get_security_group(self, context, _id, fields=None, tenant_id=None):
        return get_resource('security_group', False, _id)

    def get_security_groups(self, context, filters=None, fields=None,
                            sorts=None, limit=None, marker=None,
                            page_reverse=False, default_sg=False):
        return list_resource('security_group', False, filters)

    def get_agents(self, context, filters=None, fields=None):
        return list_resource('agent', False, filters)

    def create_or_update_agent(self, context, agent_state):
        pass


class FakeContext(object):
    def __init__(self):
        self.session = test_utils.FakeSession()
        self.auth_token = 'token'
        self.project_id = ''
        self.request_id = 'req-' + uuidutils.generate_uuid()


def fake_get_trunk_plugin(trunk):
    return FakeTrunkPlugin()


class FakeTrunkPlugin(object):

    def get_trunk(self, context, trunk_id, fields=None):
        raise t_exc.TrunkNotFound(trunk_id=trunk_id)

    def get_trunks(self, context, filters=None, fields=None,
                   sorts=None, limit=None, marker=None, page_reverse=False):
        return []

    def create_trunk(self, context, trunk):
        pass


class FakeClient(object):
    def list_networks(self, **kwargs):
        return {'networks': list_resource('network', True, kwargs)}

    def list_subnets(self, **kwargs):
        return {'subnets': list_resource('subnet', True, kwargs)}

    def create_port(self, port):
        if 'id' not in port['port']:
            port['port']['id'] = uuidutils.generate_uuid()
        if 'fixed_ips' not in port['port']:
            for subnet in TOP_SUBNETS:
                if subnet['network_id'] == port['port']['network_id']:
                    ip = {'subnet_id': subnet['id'],
                          'ip_address': subnet['cidr'][:-4] + '3'}
                    port['port']['fixed_ips'] = [ip]
        create_resource('port', True, port['port'])
        return port

    def show_port(self, port_id):
        return {'port': get_resource('port', True, port_id)}

    def list_ports(self, **kwargs):
        def find_ip_address(port, ip_address):
            for ip in port.get('fixed_ips', []):
                if ip['ip_address'] == ip_address:
                    return True
            return False

        ports = []
        for port in TOP_PORTS:
            pick = True
            for key, value in six.iteritems(kwargs):
                if key == 'fixed_ips':
                    if not find_ip_address(port, value.split('=')[1]):
                        pick = False
                        break
                elif port.get(key) != value:
                    pick = False
                    break
            if pick:
                ports.append(copy.deepcopy(port))
        return {'ports': ports}

    def list_security_groups(self, **kwargs):
        return {'security_groups': list_resource('security_group',
                                                 True, kwargs)}


class FakeNeutronHandle(object):
    def _get_client(self, context):
        return FakeClient()

    def handle_get(self, context, _type, _id):
        return get_resource(_type, True, _id)

    def handle_create(self, context, _type, body):
        if _type == 'port':
            return FakeClient().create_port(body)['port']
        create_resource(_type, True, body[_type])
        return body[_type]

    def handle_update(self, context, _type, _id, body):
        pass

    def handle_list(self, cxt, resource, filters):
        if resource == 'trunk':
            for trunk in TOP_TRUNKS:
                if trunk['port_id'] == filters[0]['value']:
                    return [trunk]
        return []

    def handle_delete(self, context, _type, _id):
        delete_resource(_type, True, _id)


class FakePlugin(plugin.TricirclePlugin):
    def __init__(self):
        self.core_plugin = FakeCorePlugin()
        self.neutron_handle = FakeNeutronHandle()
        self.on_trunk_create = {}
        self.on_subnet_delete = {}


class PluginTest(unittest.TestCase):
    def setUp(self):
        cfg.CONF.register_opts(q_config.core_opts)
        self.tenant_id = uuidutils.generate_uuid()
        self.plugin = FakePlugin()
        self.context = FakeContext()

    def _prepare_resource(self, az_hints=None, enable_dhcp=True):
        network_id = uuidutils.generate_uuid()
        subnet_id = uuidutils.generate_uuid()
        port_id = uuidutils.generate_uuid()
        sg_id = uuidutils.generate_uuid()
        t_net = {'id': network_id,
                 'tenant_id': self.tenant_id,
                 'name': 'net1',
                 'provider:network_type': constants.NT_VLAN,
                 'subnets': [subnet_id],
                 'availability_zone_hints': az_hints}
        t_subnet = {'id': subnet_id,
                    'tenant_id': self.tenant_id,
                    'name': 'subnet1',
                    'network_id': network_id,
                    'cidr': '10.0.1.0/24',
                    'gateway_ip': '10.0.1.1',
                    'ip_version': 4,
                    'allocation_pools': [{'start': '10.0.1.2',
                                          'end': '10.0.1.254'}],
                    'enable_dhcp': enable_dhcp}
        t_port = {'id': port_id,
                  'tenant_id': self.tenant_id,
                  'admin_state_up': True,
                  'name': constants.dhcp_port_name % subnet_id,
                  'network_id': network_id,
                  'mac_address': 'fa:16:3e:96:41:02',
                  'device_owner': 'network:dhcp',
                  'device_id': 'reserved_dhcp_port',
                  'fixed_ips': [{'subnet_id': subnet_id,
                                 'ip_address': '10.0.1.2'}],
                  'binding:profile': {}}
        t_sg = {
            'id': sg_id,
            'tenant_id': self.tenant_id,
            'name': 'default',
            'security_group_rules': [{
                'remote_group_id': sg_id,
                'direction': 'ingress',
                'remote_ip_prefix': None,
                'protocol': None,
                'ethertype': 'IPv4',
                'port_range_max': -1,
                'port_range_min': -1,
                'security_group_id': sg_id}]
        }
        TOP_NETS.append(t_net)
        TOP_SUBNETS.append(t_subnet)
        TOP_PORTS.append(t_port)
        TOP_SGS.append(t_sg)
        return t_net, t_subnet, t_port, t_sg

    def _get_bottom_resources_with_net(self, net, subnet, port):
        b_net = get_resource('network', False, net['id'])
        b_subnet = get_resource('subnet', False, subnet['id'])
        b_port = get_resource('port', False, port['id'])
        b_net.pop('project_id')
        return b_net, b_subnet, b_port

    def _get_bottom_resources_without_net(self, subnet, port):
        b_net = get_resource('network', False, subnet['network_id'])
        b_subnet = get_resource('subnet', False, subnet['id'])
        b_port = get_resource('port', False, port['id'])
        return b_net, b_subnet, b_port

    def _validate(self, b_net, b_subnet, b_port, t_net, t_subnet, t_port):

        t_net.pop('provider:network_type')
        t_net.pop('availability_zone_hints')
        b_net_type = b_net.pop('provider:network_type')
        b_subnet.pop('project_id')
        pool = t_subnet.pop('allocation_pools')[0]
        b_pools = b_subnet.pop('allocation_pools')
        t_gateway_ip = t_subnet.pop('gateway_ip')
        b_gateway_ip = b_subnet.pop('gateway_ip')

        def ip_to_digit(ip):
            return int(ip[ip.rindex('.') + 1:])

        if t_gateway_ip:
            pool_range = list(range(ip_to_digit(t_gateway_ip),
                                    ip_to_digit(pool['end']) + 1))
            # we include the top gateway ip in the bottom ip allocation pool
            b_pool_range1 = list(range(ip_to_digit(b_pools[0]['start']),
                                       ip_to_digit(b_pools[0]['end']) + 1))
            b_pool_range2 = list(range(ip_to_digit(b_pools[1]['start']),
                                       ip_to_digit(b_pools[1]['end']) + 1))
            b_pool_range = b_pool_range1 + [
                ip_to_digit(b_gateway_ip)] + b_pool_range2
        else:
            self.assertIsNone(t_gateway_ip)
            self.assertIsNone(b_gateway_ip)
            pool_range = list(range(ip_to_digit(pool['start']),
                                    ip_to_digit(pool['end'])))
            b_pool_range = list(range(ip_to_digit(b_pools[0]['start']),
                                      ip_to_digit(b_pools[0]['end'])))
        t_port.pop('name')
        b_port.pop('name')
        self.assertDictEqual(t_net, b_net)
        self.assertDictEqual(t_subnet, b_subnet)
        self.assertSetEqual(set(pool_range), set(b_pool_range))
        self.assertEqual('vlan', b_net_type)
        self.assertDictEqual(t_port, b_port)

    def _prepare_vm_port(self, t_net, t_subnet, index, t_sgs=[]):
        port_id = uuidutils.generate_uuid()
        cidr = t_subnet['cidr']
        ip_address = '%s.%d' % (cidr[:cidr.rindex('.')], index + 3)
        mac_address = 'fa:16:3e:96:41:0%d' % (index + 3)
        t_port = {'id': port_id,
                  'tenant_id': self.tenant_id,
                  'admin_state_up': True,
                  'network_id': t_net['id'],
                  'mac_address': mac_address,
                  'fixed_ips': [{'subnet_id': t_subnet['id'],
                                 'ip_address': ip_address}],
                  'binding:profile': {},
                  'security_groups': t_sgs}
        TOP_PORTS.append(t_port)
        return t_port

    def test__in_subnet_delete(self):
        self.context.request_id = None
        self.assertEqual(False, self.plugin._in_subnet_delete(self.context))

    def test__adapt_network_body(self):
        network = {'provider:network_type': constants.NT_LOCAL}
        self.plugin._adapt_network_body(network)
        self.assertEqual({}, network)

    def test__adapt_port_body_for_call(self):
        port = {}
        self.plugin._adapt_port_body_for_call(port)
        self.assertIsNotNone(port['mac_address'])
        self.assertIsNotNone(port['fixed_ips'])

    def test__construct_params(self):
        filters = {'filter': 'aaa'}
        sorts = [['name', True]]
        limit = 10
        marker = 'bbb'
        params = {'filter': 'aaa', 'sort_key': ['name'],
                  'limit': limit, 'marker': marker}

        params.update({'sort_dir': ['desc']})
        self.assertEqual(params,
                         self.plugin._construct_params(
                             filters, sorts, limit, marker, True))

        params.update({'sort_dir': ['asc']})
        self.assertEqual(params,
                         self.plugin._construct_params(
                             filters, sorts, limit, marker, False))

    def test__get_neutron_region(self):
        cfg.CONF.set_override('local_region_name', None, 'tricircle')
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        self.assertEqual('Pod1', self.plugin._get_neutron_region())

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test__ensure_subnet(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        b_net = copy.deepcopy(t_net)

        subnet_ids = self.plugin._ensure_subnet(
            self.context, b_net, is_top=False)
        self.assertEqual(t_net['subnets'], subnet_ids)

        b_net['subnets'] = []
        subnet_ids = self.plugin._ensure_subnet(
            self.context, b_net, is_top=False)
        self.assertEqual(t_net['subnets'], subnet_ids)

        t_net['subnets'] = []
        self.assertEqual([], self.plugin._ensure_subnet(self.context, t_net))

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_get_subnet_no_bottom_network(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        self.plugin.get_subnet(self.context, t_subnet['id'])
        b_net, b_subnet, b_port = self._get_bottom_resources_without_net(
            t_subnet, t_port)
        self._validate(b_net, b_subnet, b_port, t_net, t_subnet, t_port)

    @patch.object(t_context, 'get_context_from_neutron_context')
    def test_get_subnet(self, mock_context):
        mock_context.return_value = self.context
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        self.plugin.get_network(self.context, t_net['id'])
        self.plugin.get_subnet(self.context, t_subnet['id'])
        b_net, b_subnet, b_port = self._get_bottom_resources_with_net(
            t_net, t_subnet, t_port)
        self._validate(b_net, b_subnet, b_port, t_net, t_subnet, t_port)

    def test_create_subnet(self):
        _, t_subnet, _, _ = self._prepare_resource()
        subnet = {'subnet': t_subnet}
        self.plugin.create_subnet(self.context, subnet)
        self.assertDictEqual(t_subnet,
                             get_resource('subnet', False, t_subnet['id']))

        delete_resource('subnet', False, t_subnet['id'])
        t_subnet['name'] = t_subnet['id']
        self.plugin.create_subnet(self.context, subnet)
        self.assertDictEqual(t_subnet,
                             get_resource('subnet', False, t_subnet['id']))

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test__create_bottom_network(self):
        self.plugin.neutron_handle.handle_get = mock.Mock(return_value=None)
        self.assertRaises(q_exceptions.NetworkNotFound,
                          self.plugin._create_bottom_network,
                          self.context, 'fake_net_id')

        t_net, _, _, _ = self._prepare_resource()
        self.plugin.neutron_handle.handle_get = mock.Mock(return_value=t_net)
        _, b_net = self.plugin._create_bottom_network(
            self.context, t_net['id'])
        self.assertDictEqual(b_net,
                             get_resource('network', False, t_net['id']))

    def test_create_network(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        network = {'network': t_net}
        self.plugin.create_network(self.context, network)
        b_net = get_resource('network', False, t_net['id'])
        self.assertDictEqual(t_net, b_net)

        t_net['id'] = uuidutils.generate_uuid()
        t_net['name'] = None
        self.plugin.create_network(self.context, network)
        b_net = get_resource('network', False, t_net['id'])
        self.assertDictEqual(t_net, b_net)

        t_net['id'] = None
        t_net['name'] = uuidutils.generate_uuid()
        self.plugin.create_network(self.context, network)
        b_net = get_resource('network', False, t_net['id'])
        t_net['id'] = t_net['name']
        self.assertDictEqual(t_net, b_net)

    @patch.object(t_context, 'get_context_from_neutron_context')
    def test_get_network(self, mock_context):
        t_net, t_subnet, t_port, _ = self._prepare_resource()

        self.plugin._start_subnet_delete(self.context)
        self.assertRaises(q_exceptions.NotFound,
                          self.plugin.get_network, self.context, t_net['id'])
        self.plugin._end_subnet_delete(self.context)

        self.plugin.get_network(self.context, t_net['id'])
        b_net, b_subnet, b_port = self._get_bottom_resources_with_net(
            t_net, t_subnet, t_port)
        self._validate(b_net, b_subnet, b_port, t_net, t_subnet, t_port)

        mock_context.return_value = self.context
        mock_context.return_value.auth_token = None
        self.assertRaises(q_exceptions.NetworkNotFound,
                          self.plugin.get_network,
                          self.context, uuidutils.generate_uuid())

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_get_network_no_gateway(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        update_resource('subnet', True, t_subnet['id'], {'gateway_ip': None})
        self.plugin.get_network(self.context, t_net['id'])
        b_net, b_subnet, b_port = self._get_bottom_resources_with_net(
            t_net, t_subnet, t_port)
        self._validate(b_net, b_subnet, b_port, t_net, t_subnet, t_port)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(client.Client, 'get_admin_token', new=mock.Mock)
    def test_get_networks(self):
        az_hints = ['Pod1', 'Pod2']
        t_net1, t_subnet1, t_port1, _ = self._prepare_resource()
        t_net2, t_subnet2, t_port2, _ = self._prepare_resource(az_hints)
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        self.plugin.get_networks(self.context,
                                 {'id': [t_net1['id'], t_net2['id'],
                                         'fake_net_id']})
        b_net1, b_subnet1, b_port1 = self._get_bottom_resources_with_net(
            t_net1, t_subnet1, t_port1)
        b_net2, b_subnet2, b_port2 = self._get_bottom_resources_with_net(
            t_net2, t_subnet2, t_port2)
        self._validate(b_net1, b_subnet1, b_port1, t_net1, t_subnet1, t_port1)
        self._validate(b_net2, b_subnet2, b_port2, t_net2, t_subnet2, t_port2)

        except_networks = [{
            'id': net['id'],
            'name': net['name'],
            'project_id': net['tenant_id'],
            'provider:network_type': constants.NT_VLAN,
            'subnets': net['subnets'],
            'tenant_id': net['tenant_id']
        } for net in [t_net1, t_net2]]
        self.assertListEqual(
            except_networks, self.plugin.get_networks(self.context))
        self.assertListEqual(
            except_networks, self.plugin.get_networks(self.context,
                                                      {'id': [t_net1['id'],
                                                              t_net2['id']]}))

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(client.Client, 'get_admin_token', new=mock.Mock)
    def test_get_invaild_networks(self):
        az_hints = ['Pod2', 'Pod3']
        t_net1, t_subnet1, t_port1, _ = self._prepare_resource(az_hints)
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        net_filter = {
            'id': [t_net1.get('id')]
        }
        nets = self.plugin.get_networks(self.context, net_filter)
        six.assertCountEqual(self, nets, [])

    @patch.object(t_context, 'get_context_from_neutron_context')
    @patch.object(FakeNeutronHandle, 'handle_get')
    def test_get_subnet_notfound(self, mock_handle_get, mock_context):
        t_net, t_subnet, t_port, _ = self._prepare_resource(
            az_hints='fake_region')
        self.assertRaises(q_exceptions.SubnetNotFound,
                          self.plugin.get_subnet,
                          self.context, t_port['id'])

        mock_handle_get.return_value = None
        self.assertRaises(q_exceptions.SubnetNotFound,
                          self.plugin.get_subnet,
                          self.context, uuidutils.generate_uuid())

        mock_context.return_value = self.context
        mock_context.return_value.auth_token = None
        self.assertRaises(q_exceptions.SubnetNotFound,
                          self.plugin.get_subnet,
                          self.context, uuidutils.generate_uuid())

    @patch.object(t_context, 'get_context_from_neutron_context')
    @patch.object(client.Client, 'get_admin_token', new=mock.Mock)
    def test_get_subnets(self, mock_context):
        az_hints = ['Pod1', 'Pod2']
        mock_context.return_value = self.context
        t_net1, t_subnet1, t_port1, _ = self._prepare_resource()
        t_net2, t_subnet2, t_port2, _ = self._prepare_resource(az_hints)
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        self.plugin.get_subnets(self.context,
                                {'id': [t_subnet1['id'], t_subnet2['id'],
                                        'fake_net_id']})
        b_net1, b_subnet1, b_port1 = self._get_bottom_resources_without_net(
            t_subnet1, t_port1)
        b_net2, b_subnet2, b_port2 = self._get_bottom_resources_without_net(
            t_subnet2, t_port2)
        self._validate(b_net1, b_subnet1, b_port1, t_net1, t_subnet1, t_port1)
        self._validate(b_net2, b_subnet2, b_port2, t_net2, t_subnet2, t_port2)

        delete_resource('subnet', False, t_subnet1['id'])
        t_net1, t_subnet1, t_port1, _ = self._prepare_resource()
        b_subnets = self.plugin.get_subnets(self.context)
        self.assertEqual(len(b_subnets), 1)

        b_subnets = self.plugin.get_subnets(self.context, {
            'id': [t_subnet1['id'], t_subnet2['id']]})
        self.assertEqual(len(b_subnets), 2)

        mock_context.return_value.auth_token = None
        b_subnets = self.plugin.get_subnets(self.context, {
            'id': [t_subnet1['id'], t_subnet2['id'], 'fake_net_id']})
        self.assertEqual(len(b_subnets), 2)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(client.Client, 'get_admin_token', new=mock.Mock)
    def test_get_invaild_subnets(self):
        az_hints = ['Pod2', 'Pod3']
        t_net1, t_subnet1, t_port1, _ = self._prepare_resource(az_hints)
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        net_filter = {
            'id': [t_subnet1.get('id')]
        }
        subnets = self.plugin.get_subnets(self.context, net_filter)
        six.assertCountEqual(self, subnets, [])

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        port = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'security_groups': []}
        }
        t_port = self.plugin.create_port(self.context, port)
        b_port = get_resource('port', False, t_port['id'])
        self.assertDictEqual(t_port, b_port)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port_route_snat(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        port = {'name': 'route_snat',
                'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                'network_id': t_net['id'],
                'device_owner': q_constants.DEVICE_OWNER_ROUTER_SNAT}

        t_port = self.plugin.create_port(self.context, {'port': port})
        b_port = get_resource('port', False, t_port['id'])
        self.assertDictEqual(t_port, b_port)

        port = {'id': uuidutils.generate_uuid(),
                'name': 'route_snat',
                'fixed_ips': [{'subnet_id': t_subnet['id'],
                               'ip_address': '10.0.1.3'}],
                'network_id': t_net['id'],
                'device_owner': q_constants.DEVICE_OWNER_ROUTER_SNAT}

        t_snat_port = {'id': uuidutils.generate_uuid(),
                       'tenant_id': self.tenant_id,
                       'admin_state_up': True,
                       'name': constants.snat_port_name % t_subnet['id'],
                       'network_id': t_net['id'],
                       'mac_address': 'fa:16:3e:96:41:03',
                       'device_owner': q_constants.DEVICE_OWNER_ROUTER_SNAT,
                       'device_id': 'reserved_snat_port',
                       'fixed_ips': [{'subnet_id': t_subnet['id'],
                                      'ip_address': '10.0.1.3'}],
                       'binding:profile': {}}
        TOP_PORTS.append(t_snat_port)

        t_port = self.plugin.create_port(self.context, {'port': port})
        b_port = get_resource('port', False, t_port['id'])
        self.assertDictEqual(t_port, b_port)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port_lbaas(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()
        port = {'name': 'loadbalancer-lb-1',
                'network_id': t_net['id'],
                'mac_address': q_constants.ATTR_NOT_SPECIFIED,
                'admin_state_up': False,
                'device_id': 'lb_1',
                'device_owner': q_constants.DEVICE_OWNER_LOADBALANCERV2,
                'fixed_ips': [{'subnet_id': t_subnet['id']}]}

        t_port = self.plugin.create_port(self.context, {'port': port})
        b_port = get_resource('port', False, t_port['id'])
        self.assertDictEqual(t_port, b_port)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port_ip_specified(self):
        t_net, t_subnet, t_port, t_sg = self._prepare_resource()

        port_body = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': [{'subnet_id': t_subnet['id']}]}
        }
        self.assertRaises(q_exceptions.InvalidIpForNetwork,
                          self.plugin.create_port, self.context, port_body)

        port_body = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': [{'ip_address': '10.0.1.4'}]}
        }
        self.assertRaises(q_exceptions.InvalidIpForNetwork,
                          self.plugin.create_port, self.context, port_body)

        t_vm_port = self._prepare_vm_port(t_net, t_subnet, 1, [t_sg['id']])
        b_port = self.plugin.create_port(self.context, port_body)
        self.assertDictEqual(t_vm_port, b_port)

    @patch.object(FakeCorePlugin, 'create_or_update_agent')
    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port_with_tunnel_ip(self, mock_agent):
        t_net, t_subnet, t_port, t_sg = self._prepare_resource()

        # core plugin supports "agent" extension and body contains tunnel ip
        port_body = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'security_groups': [],
                     portbindings.HOST_ID: 'host1',
                     portbindings.PROFILE: {
                         constants.PROFILE_TUNNEL_IP: '192.168.1.101',
                         constants.PROFILE_AGENT_TYPE: 'Open vSwitch agent'}}
        }
        self.plugin.create_port(self.context, port_body)
        agent_state = copy.copy(helper.OVS_AGENT_DATA_TEMPLATE)
        agent_state['agent_type'] = 'Open vSwitch agent'
        agent_state['host'] = 'host1'
        agent_state['configurations']['tunneling_ip'] = '192.168.1.101'
        mock_agent.assert_called_once_with(self.context, agent_state)

        # core plugin supports "agent" extension but body doesn't contain
        # tunnel ip
        port_body = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'security_groups': []}
        }
        self.plugin.create_port(self.context, port_body)

        # core plugin doesn't support "agent" extension but body contains
        # tunnel ip
        FakeCorePlugin.supported_extension_aliases = []
        port_body = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'security_groups': [],
                     portbindings.HOST_ID: 'host1',
                     portbindings.PROFILE: {
                         constants.PROFILE_TUNNEL_IP: '192.168.1.101',
                         constants.PROFILE_AGENT_TYPE: 'Open vSwitch agent'}}
        }
        self.plugin.create_port(self.context, port_body)
        FakeCorePlugin.supported_extension_aliases = ['agent']

        # create_or_update_agent is called only when core plugin supports
        # "agent" extension and body contains tunnel ip
        mock_agent.assert_has_calls([mock.call(self.context, agent_state)])

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_create_port_bulk(self):
        t_net, t_subnet, t_port, t_sg = self._prepare_resource()
        t_ports = []
        for i in (1, 2):
            t_vm_port = self._prepare_vm_port(t_net, t_subnet, i, [t_sg['id']])
            t_ports.append(t_vm_port)
        self.plugin.get_ports(self.context,
                              {'id': [t_ports[0]['id'], t_ports[1]['id'],
                                      'fake_port_id']})
        b_ports = []
        b_port1 = get_resource('port', False, t_ports[0]['id'])
        b_port1['device_owner'] = constants.DEVICE_OWNER_SHADOW
        b_port1['name'] = 'shadow_' + b_port1['id']
        b_ports.append({'port': b_port1})
        b_port2 = get_resource('port', False, t_ports[1]['id'])
        b_port2['device_owner'] = constants.DEVICE_OWNER_SUBPORT
        b_port2['device_id'] = b_port2['id']
        b_ports.append({'port': b_port2})

        t_vm_port = self._prepare_vm_port(t_net, t_subnet, 3, [t_sg['id']])
        t_vm_port['device_owner'] = None
        b_ports.append({'port': t_vm_port})

        ret_b_ports = self.plugin.create_port_bulk(
            self.context, {'ports': b_ports})
        self.assertEqual(len(ret_b_ports), 2)
        self.assertListEqual(b_ports, [{'port': b_port2}, {'port': t_vm_port}])

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(FakePlugin, '_ensure_trunk', new=mock.Mock)
    def test_get_port(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource()

        t_vm_port = self._prepare_vm_port(t_net, t_subnet, 1)
        t_port = self.plugin.get_port(self.context, t_vm_port['id'])
        b_port = get_resource('port', False, t_port['id'])
        self.assertDictEqual(t_port, b_port)

    @patch.object(FakePlugin, '_ensure_trunk', new=mock.Mock)
    @patch.object(t_context, 'get_context_from_neutron_context')
    @patch.object(FakeNeutronHandle, 'handle_get')
    def test_get_port_notfound(self, mock_handle_get, mock_context):
        mock_context.return_value = self.context
        mock_context.return_value.auth_token = None
        self.assertRaises(q_exceptions.PortNotFound,
                          self.plugin.get_port, self.context, 'fake_port_id')

        mock_context.return_value.auth_token = 'fake_auth_token'
        mock_handle_get.return_value = None
        self.assertRaises(q_exceptions.PortNotFound,
                          self.plugin.get_port,
                          self.context, uuidutils.generate_uuid())

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(plugin.TricirclePlugin, '_handle_security_group',
                  new=mock.Mock)
    @patch.object(directory, 'get_plugin', new=fake_get_trunk_plugin)
    @patch.object(FakeTrunkPlugin, 'create_trunk')
    def test_get_port_trunk(self, mock_create_trunk):
        _, _, parent_port, _ = self._prepare_resource()
        _, _, subport, _ = self._prepare_resource()
        t_trunk_id = uuidutils.generate_uuid()
        parent_port['trunk_details'] = {'trunk_id': t_trunk_id,
                                        'sub_ports': [
                                            {"segmentation_type": "vlan",
                                             "port_id": subport['id'],
                                             "segmentation_id": 100}]}
        t_trunk = {
            'id': t_trunk_id,
            'name': 'top_trunk_1',
            'status': 'DOWN',
            'description': 'created',
            'admin_state_up': True,
            'port_id': parent_port['id'],
            'sub_ports': []
        }
        TOP_TRUNKS.append(t_trunk)

        self.plugin.get_port(self.context, parent_port['id'])
        mock_create_trunk.assert_called_once_with(self.context,
                                                  {'trunk': t_trunk})

    @patch.object(t_context, 'get_context_from_neutron_context')
    @patch.object(FakeCorePlugin, 'get_ports')
    def test_get_ports(self, mock_get_ports, mock_context):
        mock_context.return_value = self.context
        t_net, t_subnet, t_port, t_sg = self._prepare_resource()
        t_ports = []
        for i in (1, 2):
            t_vm_port = self._prepare_vm_port(t_net, t_subnet, i, [t_sg['id']])
            t_ports.append(t_vm_port)
        self.plugin.get_ports(self.context,
                              {'id': [t_ports[0]['id'], t_ports[1]['id'],
                                      'fake_port_id']})
        for i in (0, 1):
            b_port = get_resource('port', False, t_ports[i]['id'])
            b_port.pop('project_id')
            self.assertDictEqual(t_ports[i], b_port)

        self.plugin.get_ports(self.context)
        mock_get_ports.assert_called_with(self.context,
                                          None, None, None, None, None, False)

        mock_get_ports.return_value = t_ports
        b_ports = self.plugin.get_ports(
            self.context, {'id': [t_ports[0]['id'], t_ports[1]['id']]})
        self.assertEqual(len(b_ports), 2)

        mock_context.return_value.auth_token = None
        b_ports = self.plugin.get_ports(
            self.context, {'id': [t_ports[0]['id'], t_ports[1]['id'],
                                  'fake_port_id']})
        self.assertEqual(len(b_ports), 2)

    @patch.object(t_context, 'get_context_from_neutron_context')
    @patch.object(FakeNeutronHandle, 'handle_update')
    def test_update_port(self, mock_update, mock_context):
        t_net, t_subnet, _, _ = self._prepare_resource()
        b_net = self.plugin.get_network(self.context, t_net['id'])
        cfg.CONF.set_override('region_name', 'Pod1', 'nova')
        mock_context.return_value = self.context
        port_id = 'fake_port_id'
        host_id = 'fake_host'
        fake_port = {
            'id': port_id,
            'network_id': b_net['id'],
            'binding:vif_type': 'fake_vif_type',
            'binding:host_id': host_id,
            portbindings.VIF_DETAILS: {},
            portbindings.VNIC_TYPE: 'normal'
        }
        fake_agent = {
            'agent_type': 'Open vSwitch agent',
            'host': host_id,
            'configurations': {
                'tunneling_ip': '192.168.1.101'}}
        create_resource('port', False, fake_port)
        create_resource('agent', False, fake_agent)
        update_body = {'port': {'device_owner': 'compute:None',
                                'binding:host_id': host_id}}

        self.plugin.update_port(self.context, port_id, update_body)
        # network is not vxlan type
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'fake_vif_type',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        # update network type from vlan to vxlan
        update_resource('network', False, b_net['id'],
                        {'provider:network_type': 'vxlan'})

        self.plugin.update_port(self.context, port_id, update_body)
        # port vif type is not recognized
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'fake_vif_type',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        # update network type from fake_vif_type to ovs
        update_resource('port', False, port_id,
                        {'binding:vif_type': 'ovs'})

        self.plugin.update_port(self.context, port_id,
                                {'port': {'device_owner': 'compute:None',
                                 'binding:host_id': 'fake_another_host'}})
        # agent in the specific host is not found
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id':
                                              'fake_another_host',
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        self.plugin.update_port(self.context, port_id, update_body)
        # default p2p mode, update with agent host tunnel ip
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'tunnel_ip': '192.168.1.101',
                                          'type': 'Open vSwitch agent',
                                          'host': host_id,
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        cfg.CONF.set_override('cross_pod_vxlan_mode', 'l2gw', 'client')
        cfg.CONF.set_override('l2gw_tunnel_ip', '192.168.1.105', 'tricircle')
        update_body = {'port': {'device_owner': 'compute:None',
                                'binding:host_id': host_id}}
        self.plugin.update_port(self.context, port_id, update_body)
        # l2gw mode, update with configured l2 gateway tunnel ip
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'tunnel_ip': '192.168.1.105',
                                          'type': 'Open vSwitch agent',
                                          'host': 'fake_host',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        cfg.CONF.set_override('l2gw_tunnel_ip', None, 'tricircle')
        cfg.CONF.set_override('cross_pod_vxlan_mode', 'l2gw', 'client')
        self.plugin.update_port(self.context, port_id, update_body)
        # l2gw mode, but l2 gateway tunnel ip is not configured
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        cfg.CONF.set_override('cross_pod_vxlan_mode', 'noop', 'client')
        self.plugin.update_port(self.context, port_id, update_body)
        # noop mode
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})

        FakeCorePlugin.supported_extension_aliases = []
        self.plugin.update_port(self.context, port_id, update_body)
        # core plugin doesn't support "agent" extension
        mock_update.assert_called_with(
            self.context, 'port', port_id,
            {'port': {'binding:profile': {'region': 'Pod1',
                                          'device': 'compute:None',
                                          'binding:vif_type': 'ovs',
                                          'binding:host_id': host_id,
                                          portbindings.VIF_DETAILS: {},
                                          portbindings.VNIC_TYPE: 'normal'}}})
        FakeCorePlugin.supported_extension_aliases = ['agent']

        self.plugin.update_port(self.context, port_id,
                                {'port': {portbindings.PROFILE: {
                                    constants.PROFILE_FORCE_UP: True}}})
        b_port = get_resource('port', False, port_id)
        # port status is update to active
        self.assertEqual(q_constants.PORT_STATUS_ACTIVE, b_port['status'])

    @patch.object(t_context, 'get_context_from_neutron_context')
    def test_delete_port(self, mock_context):
        mock_context.return_value = self.context
        t_net, _, t_port, _ = self._prepare_resource()

        port = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'device_owner': q_constants.DEVICE_OWNER_ROUTER_SNAT,
                     'name': 'test-port',
                     'security_groups': []}
        }
        b_port = self.plugin.create_port(self.context, port)
        b_port_valid = get_resource('port', False, b_port['id'])
        self.assertEqual(b_port_valid['id'], b_port['id'])

        self.plugin.delete_port(self.context, b_port['id'])
        self.assertRaises(q_exceptions.NotFound,
                          get_resource, 'port', False, b_port['id'])

        port = {
            'port': {'network_id': t_net['id'],
                     'fixed_ips': q_constants.ATTR_NOT_SPECIFIED,
                     'device_owner': q_constants.DEVICE_OWNER_COMPUTE_PREFIX,
                     'name': 'test-port',
                     'security_groups': []}
        }
        b_port = self.plugin.create_port(self.context, port)
        b_port_valid = get_resource('port', False, b_port['id'])
        self.assertEqual(b_port_valid['id'], b_port['id'])
        t_port = get_resource('port', True, b_port['id'])
        self.assertEqual(b_port['id'], t_port['id'])

        self.plugin.delete_port(self.context, b_port['id'])
        self.assertRaises(q_exceptions.NotFound,
                          get_resource, 'port', False, b_port['id'])
        self.assertRaises(q_exceptions.NotFound,
                          get_resource, 'port', True, t_port['id'])

    @patch.object(t_context, 'get_context_from_neutron_context')
    def test_update_subnet(self, mock_context):
        _, t_subnet, t_port, _ = self._prepare_resource(enable_dhcp=False)
        mock_context.return_value = self.context
        subnet = {
            'subnet': {'enable_dhcp': 'True'}
        }
        subnet_id = t_subnet['id']
        port_id = t_port['id']
        self.plugin.get_subnet(self.context, subnet_id)
        self.plugin.update_subnet(self.context, subnet_id, subnet)
        b_port = get_resource('port', False, port_id)
        self.assertEqual(b_port['device_owner'], 'network:dhcp')

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_delete_subnet(self):
        t_net, t_subnet, t_port, _ = self._prepare_resource(enable_dhcp=False)
        self.plugin.get_network(self.context, t_net['id'])
        self.plugin.delete_subnet(self.context, t_subnet['id'])
        self.assertRaises(q_exceptions.NotFound,
                          get_resource, 'subnet', False, t_subnet['id'])

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test__handle_security_group(self):
        t_ctx = t_context.get_db_context()

        port = {'security_groups': q_constants.ATTR_NOT_SPECIFIED}
        self.plugin._handle_security_group(t_ctx, self.context, port)
        b_sgs = list_resource('security_group', False)
        self.assertListEqual(b_sgs, [])

        port = {'security_groups': []}
        self.plugin._handle_security_group(t_ctx, self.context, port)
        b_sgs = list_resource('security_group', False)
        self.assertEqual(b_sgs, [])

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(FakeNeutronHandle, 'handle_get')
    def test_get_security_group(self, mock_handle_get):
        sg_id = uuidutils.generate_uuid()
        mock_handle_get.return_value = None
        self.assertRaises(ext_sg.SecurityGroupNotFound,
                          self.plugin.get_security_group,
                          self.context, sg_id)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    @patch.object(FakeCorePlugin, 'get_security_groups')
    def test_get_security_groups_mock(self, mock_get_sgs):
        _, _, _, t_sg1 = self._prepare_resource()
        _, _, _, t_sg2 = self._prepare_resource()
        self.plugin.get_security_groups(self.context)
        mock_get_sgs.assert_called_with(self.context,
                                        None, None, None, None, None,
                                        False, False)

    @patch.object(t_context, 'get_context_from_neutron_context', new=mock.Mock)
    def test_get_security_groups(self):
        _, _, _, t_sg1 = self._prepare_resource()
        _, _, _, t_sg2 = self._prepare_resource()
        self.plugin.get_security_groups(self.context,
                                        {'id': [t_sg1['id'], t_sg2['id'],
                                                'fake_sg_id']})
        b_sg = get_resource('security_group', False, t_sg1['id'])
        self.assertEqual(b_sg['id'], t_sg1['id'])
        b_sg = get_resource('security_group', False, t_sg2['id'])
        self.assertEqual(b_sg['id'], t_sg2['id'])

        b_sgs = self.plugin.get_security_groups(self.context,
                                                {'id': [t_sg1['id'],
                                                        t_sg2['id']]})
        self.assertEqual(len(b_sgs), 2)

    def tearDown(self):
        cfg.CONF.unregister_opts(q_config.core_opts)
        test_utils.get_resource_store().clean()
