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

from mock import patch
import six
import unittest

from oslo_config import cfg
from oslo_utils import uuidutils

import neutron.conf.common as q_config
from neutron_lib.api.definitions import portbindings
import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions
import neutronclient.common.exceptions as q_cli_exceptions

from tricircle.common import context
from tricircle.common import exceptions as t_exceptions
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.network import helper
import tricircle.tests.unit.utils as test_utils

_resource_store = test_utils.get_resource_store()
TOP_NETS = _resource_store.TOP_NETWORKS
TOP_SUBNETS = _resource_store.TOP_SUBNETS
BOTTOM1_NETS = _resource_store.BOTTOM1_NETWORKS
BOTTOM1_PORTS = _resource_store.BOTTOM1_PORTS
BOTTOM1_ROUTERS = _resource_store.BOTTOM1_ROUTERS


def get_resource_list(_type, is_top):
    pod = 'top' if is_top else 'pod_1'
    return _resource_store.pod_store_map[pod][_type]


def get_resource(_type, is_top, resource_id):
    for resource in get_resource_list(_type, is_top):
        if resource['id'] == resource_id:
            return resource
    raise q_exceptions.NotFound()


def list_resource(_type, is_top, filters=None):
    resource_list = get_resource_list(_type, is_top)
    if not filters:
        return [resource for resource in get_resource_list(
            _type, is_top)]
    ret = []
    for resource in resource_list:
        pick = True
        for key, value in six.iteritems(filters):
            if resource.get(key) not in value:
                pick = False
                break
        if pick:
            ret.append(resource)
    return ret


class FakeClient(test_utils.FakeClient):
    def __init__(self, region_name=None):
        super(FakeClient, self).__init__(region_name)

    def create_ports(self, context, body):
        for port in body['ports']:
            index = int(port['name'].split('-')[-1])
            if index in (1, 3, 6, 7, 8, 14, 19):
                raise q_cli_exceptions.MacAddressInUseClient(
                    message='fa:16:3e:d4:01:%02x' % index)
            port['id'] = port['name'].split('_')[-1]
        return body['ports']

    def list_networks(self, ctx, filters=None):
        networks = self.list_resources('network', ctx, filters)
        return networks

    def delete_networks(self, ctx, net_id):
        self.delete_resources('network', ctx, net_id)

    def list_subnets(self, ctx, filters=None):
        return self.list_resources('subnet', ctx, filters)

    def get_subnets(self, ctx, subnet_id):
        return self.get_resource('subnet', ctx, subnet_id)

    def delete_subnets(self, ctx, subnet_id):
        self.delete_resources('subnet', ctx, subnet_id)

    def list_routers(self, ctx, filters=None):
        return self.list_resources('router', ctx, filters)

    def delete_routers(self, ctx, router_id):
        self.delete_resources('router', ctx, router_id)

    def action_routers(self, ctx, action, *args, **kwargs):
        router_id, body = args
        if action == 'add_gateway':
            port = {
                'admin_state_up': True,
                'id': uuidutils.generate_uuid(),
                'name': '',
                'network_id': body['network_id'],
                'fixed_ips': '10.0.1.1',
                'mac_address': '',
                'device_id': router_id,
                'device_owner': 'network:router_gateway',
                'binding:vif_type': 'ovs',
                'binding:host_id': 'host_1'
            }
            BOTTOM1_PORTS.append(test_utils.DotDict(port))
        elif action == 'remove_gateway':
            self.delete_routers(ctx, router_id)


class HelperTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        cfg.CONF.register_opts(q_config.core_opts)
        self.helper = helper.NetworkHelper()
        self.context = context.Context()

    def _prepare_pods(self):
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

    def _prepare_top_network(self, project_id,
                             network_type='vlan', az_hints=None):
        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        t_net = {
            'id': t_net_id,
            'name': t_net_id,
            'tenant_id': project_id,
            'project_id': project_id,
            'description': 'description',
            'admin_state_up': False,
            'shared': False,
            'provider:network_type': network_type,
            'availability_zone_hints': az_hints
        }
        t_subnet = {
            'id': t_subnet_id,
            'network_id': t_net_id,
            'name': t_subnet_id,
            'ip_version': 4,
            'cidr': '10.0.1.0/24',
            'allocation_pools': [],
            'enable_dhcp': True,
            'gateway_ip': '10.0.1.1',
            'ipv6_address_mode': q_constants.IPV6_SLAAC,
            'ipv6_ra_mode': q_constants.IPV6_SLAAC,
            'tenant_id': project_id,
            'project_id': project_id,
            'description': 'description',
            'host_routes': [],
            'dns_nameservers': [],
            'segment_id': 'b85fd910-e483-4ef1-bdf5-b0f747d0b0d5'
        }
        TOP_NETS.append(test_utils.DotDict(t_net))
        TOP_SUBNETS.append(test_utils.DotDict(t_subnet))
        return t_net, t_subnet

    def _prepare_bottom_network(self, project_id, b_uuid=None,
                                network_type='vlan', az_hints=None):
        b_net_id = b_uuid or uuidutils.generate_uuid()
        b_net = {
            'id': b_net_id,
            'name': b_net_id,
            'tenant_id': project_id,
            'project_id': project_id,
            'description': 'description',
            'admin_state_up': False,
            'shared': False,
            'provider:network_type': network_type,
            'availability_zone_hints': az_hints
        }
        BOTTOM1_NETS.append(test_utils.DotDict(b_net))
        return b_net

    def _prepare_router(self, project_id, router_az_hints=None):
        b_router_id = uuidutils.generate_uuid()
        b_router = {
            'id': b_router_id,
            'name': b_router_id,
            'distributed': False,
            'tenant_id': project_id,
            'attached_ports': test_utils.DotList(),
            'extra_attributes': {
                'availability_zone_hints': router_az_hints
            }
        }
        BOTTOM1_ROUTERS.append(test_utils.DotDict(b_router))
        return b_router_id

    def test_is_local_network(self):
        net = {
            'provider:network_type': 'vlan',
            'availability_zone_hints': []
        }
        self.assertFalse(self.helper.is_local_network(self.context, net))

        net = {
            'provider:network_type': 'vlan',
            'availability_zone_hints': ['pod_1', 'pod_1']
        }
        self.assertFalse(self.helper.is_local_network(self.context, net))

        net = {
            'provider:network_type': 'vlan',
            'availability_zone_hints': ['pod_1']
        }
        self._prepare_pods()
        self.assertTrue(self.helper.is_local_network(self.context, net))

    def test_fill_binding_info(self):
        port_body = {
            portbindings.PROFILE: 'Open vSwitch agent'
        }
        self.helper.fill_binding_info(port_body)
        self.assertEqual(port_body, {
            portbindings.PROFILE: 'Open vSwitch agent',
            portbindings.VIF_DETAILS: {'port_filter': True,
                                       'ovs_hybrid_plug': True},
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
            portbindings.VNIC_TYPE: portbindings.VNIC_NORMAL
        })

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_top_element(self, mock_context):
        mock_context.return_value = self.context
        self._prepare_pods()
        t_port_id = uuidutils.generate_uuid()
        port_body = {
            'port': {
                'id': t_port_id,
                'name': t_port_id,
                'fixed_ips': [{'ip_address': '10.0.1.1'}],
                'mac_address': 'fa:16:3e:d4:01:01',
                'device_id': None
            }
        }
        self.helper.prepare_top_element(
            self.context, None, test_utils.TEST_TENANT_ID,
            {'pod_id': 'pod_id_0', 'region_name': 'top_pod'},
            {'id': t_port_id}, 'port', port_body)
        t_ports = list_resource('port', True)
        self.assertEqual(t_ports[0]['id'], t_port_id)

    def test_get_create_subnet_body(self):
        t_net_id = uuidutils.generate_uuid()
        t_subnet_id = uuidutils.generate_uuid()
        b_net_id = uuidutils.generate_uuid()
        project_id = uuidutils.generate_uuid()

        t_subnet = {
            'network_id': t_net_id,
            'id': t_subnet_id,
            'ip_version': 4,
            'cidr': '10.0.1.0/24',
            'gateway_ip': '10.0.1.1',
            'allocation_pools': [{'start': '10.0.1.10', 'end': '10.0.1.254'}],
            'enable_dhcp': True,
            'tenant_id': project_id
        }
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.10')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.11', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.10', body['subnet']['gateway_ip'])

        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.254')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.10', 'end': '10.0.1.253'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.254', body['subnet']['gateway_ip'])

        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.8')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.1'},
                              {'start': '10.0.1.10', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.8', body['subnet']['gateway_ip'])

        t_subnet['allocation_pools'] = [
            {'start': '10.0.1.2', 'end': '10.0.1.10'},
            {'start': '10.0.1.20', 'end': '10.0.1.254'}]
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.5')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.1', 'end': '10.0.1.4'},
                              {'start': '10.0.1.6', 'end': '10.0.1.10'},
                              {'start': '10.0.1.20', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.5', body['subnet']['gateway_ip'])

        t_subnet['gateway_ip'] = '10.0.1.11'
        t_subnet['allocation_pools'] = [
            {'start': '10.0.1.2', 'end': '10.0.1.10'},
            {'start': '10.0.1.12', 'end': '10.0.1.254'}]
        body = self.helper.get_create_subnet_body(project_id, t_subnet,
                                                  b_net_id, '10.0.1.5')
        six.assertCountEqual(self,
                             [{'start': '10.0.1.2', 'end': '10.0.1.4'},
                              {'start': '10.0.1.6', 'end': '10.0.1.254'}],
                             body['subnet']['allocation_pools'])
        self.assertEqual('10.0.1.5', body['subnet']['gateway_ip'])

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    def test_prepare_shadow_ports(self):
        port_bodys = [{
            'id': 'port-id-%d' % i,
            'fixed_ips': [{'ip_address': '10.0.1.%d' % i}],
            'mac_address': 'fa:16:3e:d4:01:%02x' % i,
            'binding:host_id': 'host1',
            'device_id': None
        } for i in range(1, 20)]
        agents = [{'type': 'Open vSwitch agent',
                   'tunnel_ip': '192.168.1.101'} for _ in range(1, 20)]
        # we just want to test the logic, so we pass None for context, a
        # malformed dict for target_pod
        ret_port_ids = self.helper.prepare_shadow_ports(
            None, 'project_id', {'region_name': 'pod1'}, 'net-id-1',
            port_bodys, agents, 5)
        req_port_ids = [port['id'] for port in port_bodys]
        six.assertCountEqual(self, ret_port_ids, req_port_ids)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    def test_prepare_shadow_port(self):
        self._prepare_pods()
        port_body = {
            'id': uuidutils.generate_uuid(),
            'fixed_ips': [{'ip_address': '10.0.1.1'}],
            'mac_address': 'fa:16:3e:d4:01:01',
            'binding:host_id': 'host1',
            'device_id': None
        }
        agent = {'type': 'Open vSwitch agent', 'tunnel_ip': '192.168.1.101'}
        self.helper.prepare_shadow_port(
            self.context, 'project_id',
            {'pod_id': 'pod_id_1', 'region_name': 'pod_1'},
            'net-id-1', port_body, agent)
        sw_ports = list_resource('port', False)
        self.assertEqual(len(sw_ports), 1)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_bottom_router(self, mock_context):
        self._prepare_pods()
        mock_context.return_value = self.context
        net = {
            'availability_zone_hints': ['az_name_1'],
            'tenant_id': test_utils.TEST_TENANT_ID
        }
        self.helper.prepare_bottom_router(self.context, net, 'fake_router_1')
        b_routers = list_resource('router', False)
        self.assertEqual(len(b_routers), 1)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_bottom_router_by_name(self, mock_context):
        router_id = self._prepare_router(test_utils.TEST_TENANT_ID,
                                         router_az_hints='az_name_1')
        mock_context.return_value = self.context
        b_router = get_resource('router', False, router_id)
        self.assertIsNotNone(b_router['id'])
        self.helper.remove_bottom_router_by_name(
            self.context, 'pod_1', router_id)
        self.assertRaises(q_exceptions.NotFound, get_resource,
                          'router', False, router_id)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_bottom_router_gateway(self, mock_context):
        self._prepare_pods()
        mock_context.return_value = self.context
        self.assertRaises(t_exceptions.NotFound,
                          self.helper.prepare_bottom_router_gateway,
                          self.context, 'pod_1', 'fake_router')

        router_id = self._prepare_router(test_utils.TEST_TENANT_ID,
                                         router_az_hints='az_name_1')
        self.assertRaises(t_exceptions.NotFound,
                          self.helper.prepare_bottom_router_gateway,
                          self.context, 'pod_1', router_id)
        b_net_id = uuidutils.generate_uuid()
        b_net = {
            'id': b_net_id,
            'name': router_id,
            'tenant_id': test_utils.TEST_TENANT_ID,
            'project_id': test_utils.TEST_TENANT_ID,
            'description': 'description',
            'admin_state_up': False,
            'shared': False,
            'provider:network_type': 'vlan',
            'availability_zone_hints': None
        }
        BOTTOM1_NETS.append(test_utils.DotDict(b_net))

        self.helper.prepare_bottom_router_gateway(
            self.context, 'pod_1', router_id)
        b_gw_ports = list_resource('port', False)
        self.assertEqual(b_gw_ports[0]['device_id'], router_id)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_bottom_router_gateway(self, mock_context):
        self._prepare_pods()
        mock_context.return_value = self.context
        self.assertRaises(t_exceptions.NotFound,
                          self.helper.remove_bottom_router_gateway,
                          self.context, 'pod_1', 'fake_router')

        router_id = self._prepare_router(test_utils.TEST_TENANT_ID,
                                         router_az_hints='az_name_1')
        b_routers = list_resource('router', False)
        self.assertEqual(b_routers[0]['id'], router_id)
        self.helper.remove_bottom_router_gateway(
            self.context, 'pod_1', router_id)
        self.assertRaises(q_exceptions.NotFound, get_resource,
                          'router', False, router_id)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_bottom_external_network_by_name(self, mock_context):
        mock_context.return_value = self.context
        b_net = self._prepare_bottom_network(test_utils.TEST_TENANT_ID,
                                             az_hints='az_name_1')
        b_net_req = get_resource('network', False, b_net['id'])
        self.assertEqual(b_net_req['id'], b_net['id'])
        self.helper.remove_bottom_external_network_by_name(
            self.context, 'pod_1', b_net['id'])
        self.assertRaises(q_exceptions.NotFound, get_resource,
                          'network', False, b_net['id'])

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_bottom_external_subnet_by_bottom_name(self, mock_context):
        self._prepare_pods()
        mock_context.return_value = self.context
        t_net, t_subnet = self._prepare_top_network(test_utils.TEST_TENANT_ID)
        self.assertRaises(
            t_exceptions.InvalidInput,
            self.helper.prepare_bottom_external_subnet_by_bottom_name,
            self.context, t_subnet, 'pod_1',
            'fake_bottom_network_name', t_subnet['id'])

        b_net = self._prepare_bottom_network(
            test_utils.TEST_TENANT_ID, b_uuid=t_net['id'])
        self.helper.prepare_bottom_external_subnet_by_bottom_name(
            self.context, t_subnet, 'pod_1',
            b_net['name'], t_subnet['id'])
        b_subnets = list_resource('subnet', False)
        self.assertEqual(len(b_subnets), 1)

    @patch.object(helper.NetworkHelper, '_get_client', new=FakeClient)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_bottom_external_subnet_by_name(self, mock_context):
        self._prepare_pods()
        mock_context.return_value = self.context
        t_net, t_subnet = self._prepare_top_network(test_utils.TEST_TENANT_ID)
        b_net = self._prepare_bottom_network(
            test_utils.TEST_TENANT_ID, b_uuid=t_net['id'])
        self.helper.prepare_bottom_external_subnet_by_bottom_name(
            self.context, t_subnet, 'pod_1',
            b_net['name'], t_subnet['id'])

        b_subnets = list_resource('subnet', False)
        self.helper.remove_bottom_external_subnet_by_name(
            self.context, 'pod_1', b_subnets[0]['name'])
        self.assertRaises(q_exceptions.NotFound, get_resource,
                          'subnet', False, t_subnet['id'])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        test_utils.get_resource_store().clean()
        cfg.CONF.unregister_opts(q_config.core_opts)
