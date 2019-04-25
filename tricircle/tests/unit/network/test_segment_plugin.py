# Copyright 2018 Huazhong University of Science and Technology.
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
import unittest

from neutron_lib.api.definitions import provider_net
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.plugins import directory

import neutron.conf.common as q_config
from neutron.extensions import segment as extension
from neutron.plugins.ml2 import managers as n_managers
from neutron.services.segments import exceptions as sg_excp
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
import tricircle.network.central_plugin as plugin
from tricircle.network import helper
from tricircle.network.segment_plugin import TricircleSegmentPlugin
from tricircle.tests.unit.network.test_central_plugin import FakeClient as CFC
from tricircle.tests.unit.network.test_central_plugin import FakePlugin as CFP

import tricircle.tests.unit.utils as test_utils

_resource_store = test_utils.get_resource_store()
TOP_NETS = _resource_store.TOP_NETWORKS
TOP_SUBNETS = _resource_store.TOP_SUBNETS
TOP_PORTS = _resource_store.TOP_PORTS
TOP_ROUTERS = _resource_store.TOP_ROUTERS
TOP_SEGMENTS = _resource_store.TOP_NETWORKSEGMENTS
BOTTOM1_NETS = _resource_store.BOTTOM1_NETWORKS
BOTTOM1_SUBNETS = _resource_store.BOTTOM1_SUBNETS
BOTTOM1_PORTS = _resource_store.BOTTOM1_PORTS
TEST_TENANT_ID = test_utils.TEST_TENANT_ID
FakeNeutronContext = test_utils.FakeNeutronContext
TEST_TENANT_ID = test_utils.TEST_TENANT_ID


class FakeClient(CFC):
    def __init__(self, region_name=None):
        super(FakeClient, self).__init__(region_name)

    def delete_segments(self, ctx, segment_id):
        self.delete_resources('segment', ctx, segment_id)


class FakeExtensionManager(n_managers.ExtensionManager):
    def __init__(self):
        super(FakeExtensionManager, self).__init__()


class FakeHelper(helper.NetworkHelper):
    def _get_client(self, region_name=None):
        return FakeClient(region_name)


class FakeTrunkPlugin(object):

    def get_trunk_subports(self, context, filters):
        return None


class FakePlugin(TricircleSegmentPlugin):
    def start_rpc_state_reports_listener(self):
        pass

    def __init__(self):

        self.type_manager = test_utils.FakeTypeManager()
        self.extension_manager = FakeExtensionManager()
        self.extension_manager.initialize()
        self.helper = FakeHelper(self)
        self.central_plugin = CFP()

    def _get_client(self, region_name):
        return FakeClient(region_name)

    @staticmethod
    def get_network_availability_zones(network):
        zones = network.get('availability_zone_hints') \
            if network.get('availability_zone_hints') else []
        return list(zones)

    def _make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
        network = _transform_az(network)
        if 'project_id' in network:
            network['tenant_id'] = network['project_id']
        return network


def fake_get_client(region_name):
    return FakeClient(region_name)


def fake_get_context_from_neutron_context(q_context):
    return context.get_db_context()


def _transform_az(network):
    az_hints_key = 'availability_zone_hints'
    if az_hints_key in network:
        ret = test_utils.DotDict(network)
        az_str = network[az_hints_key]
        ret[az_hints_key] = jsonutils.loads(az_str) if az_str else []
        return ret
    return network


def fake_delete_network(self, context, network_id):
    fake_client = FakeClient()
    fake_client.delete_networks(context, network_id)


class PluginTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())

        cfg.CONF.register_opts(q_config.core_opts)
        cfg.CONF.register_opts(plugin.tricircle_opts)
        cfg.CONF.set_override('enable_l3_route_network', True,
                              group='tricircle')
        plugin_path = \
            'tricircle.tests.unit.network.test_segment_plugin.FakePlugin'
        cfg.CONF.set_override('core_plugin', plugin_path)
        cfg.CONF.set_override('enable_api_gateway', True)
        self.context = context.Context()

        phynet = 'bridge'
        phynet2 = 'bridge2'
        vlan_min, vlan_max = 2000, 3000
        cfg.CONF.set_override('type_drivers', ['local', 'vlan'],
                              group='tricircle')
        cfg.CONF.set_override('tenant_network_types', ['local', 'vlan'],
                              group='tricircle')
        cfg.CONF.set_override('network_vlan_ranges',
                              ['%s:%d:%d' % (phynet, vlan_min, vlan_max),
                               '%s:%d:%d' % (phynet2, vlan_min, vlan_max)],
                              group='tricircle')
        cfg.CONF.set_override('bridge_network_type', 'vlan',
                              group='tricircle')

        def fake_get_plugin(alias=plugin_constants.CORE):
            return None
        directory.get_plugin = fake_get_plugin

        global segments_plugin
        segments_plugin = FakePlugin()

    def _basic_pod_route_setup(self):
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

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(TricircleSegmentPlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_create_segment(self, mock_context):
        self._basic_pod_route_setup()
        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        # create a routed network
        top_net_id = uuidutils.generate_uuid()
        network = {'network': {
            'id': top_net_id, 'name': 'multisegment1',
            'tenant_id': TEST_TENANT_ID,
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': [],
            provider_net.PHYSICAL_NETWORK: 'bridge',
            provider_net.NETWORK_TYPE: 'vlan',
            provider_net.SEGMENTATION_ID: '2016'}}
        fake_plugin.central_plugin.create_network(neutron_context, network)
        net_filter = {'name': ['multisegment1']}
        top_net = fake_plugin.central_plugin.get_networks(
            neutron_context, net_filter)
        self.assertEqual(top_net[0]['id'], top_net_id)

        res = fake_plugin.get_segments(neutron_context)
        self.assertEqual(len(res), 1)

        # creat segment's name normally
        segment2_id = uuidutils.generate_uuid()
        segment2_name = 'test-segment2'
        segment2 = {'segment': {
            'id': segment2_id,
            'name': segment2_name,
            'network_id': top_net_id,
            extension.PHYSICAL_NETWORK: 'bridge2',
            extension.NETWORK_TYPE: 'flat',
            extension.SEGMENTATION_ID: '2016',
            'tenant_id': TEST_TENANT_ID,
            'description': None
        }}
        fake_plugin.create_segment(neutron_context, segment2)
        res = fake_plugin.get_segment(neutron_context, segment2_id)
        self.assertEqual(res['name'], segment2_name)
        net_filter = {'name': [segment2_name]}
        b_net = fake_plugin.central_plugin.get_networks(
            neutron_context, net_filter)
        self.assertFalse(b_net)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(TricircleSegmentPlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(plugin.TricirclePlugin, 'delete_network',
                  new=fake_delete_network)
    def test_delete_segment(self, mock_context):
        self._basic_pod_route_setup()
        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        # create a routed network
        top_net_id = uuidutils.generate_uuid()
        network = {'network': {
            'id': top_net_id, 'name': 'multisegment1',
            'tenant_id': TEST_TENANT_ID,
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': [],
            provider_net.PHYSICAL_NETWORK: 'bridge',
            provider_net.NETWORK_TYPE: 'vlan',
            provider_net.SEGMENTATION_ID: '2016'}}
        fake_plugin.central_plugin.create_network(neutron_context, network)

        # create a normal segment
        segment2_id = uuidutils.generate_uuid()
        segment2_name = 'test-segment3'
        segment2 = {'segment': {
            'id': segment2_id,
            'name': segment2_name,
            'network_id': top_net_id,
            extension.PHYSICAL_NETWORK: 'bridge2',
            extension.NETWORK_TYPE: 'flat',
            extension.SEGMENTATION_ID: '2016',
            'tenant_id': TEST_TENANT_ID,
            'description': None
        }}
        fake_plugin.create_segment(neutron_context, segment2)

        res = fake_plugin.get_segment(neutron_context, segment2_id)
        self.assertEqual(res['name'], segment2_name)
        net_filter = {'name': [segment2_name]}
        b_net = fake_plugin.central_plugin.get_networks(
            neutron_context, net_filter)
        self.assertFalse(b_net)

        # delete a normal segment
        fake_plugin.delete_segment(neutron_context, segment2_id)
        self.assertRaises(sg_excp.SegmentNotFound,
                          fake_plugin.get_segment,
                          neutron_context, segment2_id)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        test_utils.get_resource_store().clean()
        cfg.CONF.unregister_opts(q_config.core_opts)
        cfg.CONF.unregister_opts(plugin.tricircle_opts)
