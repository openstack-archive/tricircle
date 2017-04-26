# Copyright 2017 Huawei Technologies Co., Ltd.
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

from networking_sfc.db import sfc_db
from networking_sfc.services.flowclassifier import plugin as fc_plugin

import neutron.conf.common as q_config
from neutron.db import db_base_plugin_v2
import neutron_lib.context as q_context
from neutron_lib.plugins import directory
from neutronclient.common import exceptions as client_exceptions

from oslo_config import cfg
from oslo_utils import uuidutils

from tricircle.common import client
from tricircle.common import constants
from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
import tricircle.network.central_fc_driver as fc_driver
from tricircle.network import central_plugin
import tricircle.network.central_sfc_driver as sfc_driver
import tricircle.network.central_sfc_plugin as sfc_plugin
from tricircle.network import helper
import tricircle.tests.unit.utils as test_utils
from tricircle.xjob import xmanager


_resource_store = test_utils.get_resource_store()
TOP_PORTS = _resource_store.TOP_PORTS
TOP_PORTPAIRS = _resource_store.TOP_SFC_PORT_PAIRS
TOP_PORTPAIRGROUPS = _resource_store.TOP_SFC_PORT_PAIR_GROUPS
TOP_PORTCHAINS = _resource_store.TOP_SFC_PORT_CHAINS
TOP_FLOWCLASSIFIERS = _resource_store.TOP_SFC_FLOW_CLASSIFIERS
BOTTOM1_PORTS = _resource_store.BOTTOM1_PORTS
BOTTOM2_PORTS = _resource_store.BOTTOM2_PORTS
BOTTOM1_PORTPAIRS = _resource_store.BOTTOM1_SFC_PORT_PAIRS
BOTTOM2_PORTPAIRS = _resource_store.BOTTOM2_SFC_PORT_PAIRS
BOTTOM1_PORTPAIRGROUPS = _resource_store.BOTTOM1_SFC_PORT_PAIR_GROUPS
BOTTOM2_PORTPAIRGROUPS = _resource_store.BOTTOM2_SFC_PORT_PAIR_GROUPS
BOTTOM1_PORTCHAINS = _resource_store.BOTTOM1_SFC_PORT_CHAINS
BOTTOM2_PORTCHAINS = _resource_store.BOTTOM2_SFC_PORT_CHAINS
BOTTOM1_FLOWCLASSIFIERS = _resource_store.BOTTOM1_SFC_FLOW_CLASSIFIERS
BOTTOM2_FLOWCLASSIFIERS = _resource_store.BOTTOM2_SFC_FLOW_CLASSIFIERS
TEST_TENANT_ID = test_utils.TEST_TENANT_ID
DotDict = test_utils.DotDict


class FakeNetworkHelper(helper.NetworkHelper):
    def __init__(self):
        super(FakeNetworkHelper, self).__init__()

    def _get_client(self, region_name=None):
        return FakeClient(region_name)


class FakeBaseXManager(xmanager.XManager):
    def __init__(self):
        self.clients = {constants.TOP: client.Client()}
        self.helper = FakeNetworkHelper()

    def _get_client(self, region_name=None):
        return FakeClient(region_name)

    def sync_service_function_chain(self, ctx, payload):
        (b_pod_id, t_port_chain_id, net_id) = payload[
            constants.JT_SFC_SYNC].split('#')

        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, net_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                payload = '%s#%s#%s' % (b_pod['pod_id'], t_port_chain_id,
                                        net_id)
                super(FakeBaseXManager, self).sync_service_function_chain(
                    ctx, {constants.JT_SFC_SYNC: payload})
        else:
            super(FakeBaseXManager, self).sync_service_function_chain(
                ctx, payload)


class FakeXManager(FakeBaseXManager):
    def __init__(self, fake_plugin):
        super(FakeXManager, self).__init__()
        self.xjob_handler = FakeBaseRPCAPI(fake_plugin)


class FakeBaseRPCAPI(object):
    def __init__(self, fake_plugin):
        self.xmanager = FakeBaseXManager()

    def sync_service_function_chain(self, ctxt, project_id, portchain_id,
                                    net_id, pod_id):
        combine_id = '%s#%s#%s' % (pod_id, portchain_id, net_id)
        self.xmanager.sync_service_function_chain(
            ctxt,
            payload={constants.JT_SFC_SYNC: combine_id})

    def recycle_resources(self, ctx, project_id):
        self.xmanager.recycle_resources(ctx, payload={
            constants.JT_RESOURCE_RECYCLE: project_id})


class FakeRPCAPI(FakeBaseRPCAPI):
    def __init__(self, fake_plugin):
        self.xmanager = FakeXManager(fake_plugin)


class FakeClient(test_utils.FakeClient):

    def delete_resources(self, _type, ctx, _id):
        if _type == constants.RT_PORT_PAIR:
            pp = self.get_resource(constants.RT_PORT_PAIR, ctx, _id)
            if not pp:
                raise client_exceptions.NotFound()
            if pp['portpairgroup_id']:
                    raise client_exceptions.Conflict(constants.STR_IN_USE)
        elif _type == constants.RT_FLOW_CLASSIFIER:
            pc_list = self._res_map[self.region_name][constants.RT_PORT_CHAIN]
            for pc in pc_list:
                if _id in pc['flow_classifiers']:
                    raise client_exceptions.Conflict(constants.STR_IN_USE)

        return super(FakeClient, self).delete_resources(_type, ctx, _id)

    def create_resources(self, _type, ctx, body):
        if _type == constants.RT_PORT_PAIR:
            pp_list = self._res_map[self.region_name][constants.RT_PORT_PAIR]
            for pp in pp_list:
                if body[_type]['ingress'] == pp['ingress']:
                    raise client_exceptions.BadRequest(constants.STR_USED_BY)
        elif _type == constants.RT_PORT_PAIR_GROUP:
            ppg_list = self._res_map[self.region_name][
                constants.RT_PORT_PAIR_GROUP]
            for pp in body[_type]['port_pairs']:
                for ppg in ppg_list:
                    if pp in ppg['port_pairs']:
                        raise client_exceptions.Conflict(constants.STR_IN_USE)
        elif _type == constants.RT_FLOW_CLASSIFIER:
            fc_list = self._res_map[self.region_name][
                constants.RT_FLOW_CLASSIFIER]
            for fc in fc_list:
                if (body[_type]['logical_source_port'] ==
                        fc['logical_source_port']):
                    raise client_exceptions.BadRequest(
                        constants.STR_CONFLICTS_WITH)
        elif _type == constants.RT_PORT_CHAIN:
            pc_list = self._res_map[self.region_name][constants.RT_PORT_CHAIN]
            for fc in body[_type]['flow_classifiers']:
                for pc in pc_list:
                    if fc in pc['flow_classifiers']:
                        raise client_exceptions.Conflict(constants.STR_IN_USE)

        return super(FakeClient, self).create_resources(_type, ctx, body)

    def get_port_chains(self, ctx, portchain_id):
        return self.get_resource('port_chain', ctx, portchain_id)

    def get_port_pair_groups(self, ctx, portpairgroup_id):
        return self.get_resource('port_pair_group', ctx, portpairgroup_id)

    def get_flow_classifiers(self, ctx, flowclassifier_id):
        return self.get_resource('flow_classifier', ctx, flowclassifier_id)

    def list_port_pairs(self, ctx, filters=None):
        return self.list_resources('port_pair', ctx, filters)

    def list_flow_classifiers(self, ctx, filters=None):
        return self.list_resources('flow_classifier', ctx, filters)

    def list_port_chains(self, ctx, filters=None):
        return self.list_resources('port_chain', ctx, filters)

    def list_port_pair_groups(self, ctx, filters=None):
        return self.list_resources('port_pair_group', ctx, filters)

    def update_port_pair_groups(self, ctx, id, port_pair_group):
        filters = [{'key': 'portpairgroup_id',
                    'comparator': 'eq',
                    'value': id}]
        pps = self.list_port_pairs(ctx, filters)
        for pp in pps:
            pp['portpairgroup_id'] = None
        return self.update_resources('port_pair_group',
                                     ctx, id, port_pair_group)

    def get_ports(self, ctx, port_id):
        return self.get_resource('port', ctx, port_id)

    def delete_port_chains(self, context, portchain_id):
        pc = self.get_resource('port_chain', context, portchain_id)
        if not pc:
            raise client_exceptions.NotFound()
        self.delete_resources('port_chain', context, portchain_id)

    def delete_port_pairs(self, context, portpair_id):
        pp = self.get_resource('port_pair', context, portpair_id)
        if not pp:
            raise client_exceptions.NotFound()
        pp = self.get_resource('port_pair', context, portpair_id)
        if pp and pp.get('portpairgroup_id'):
            raise client_exceptions.Conflict("in use")
        self.delete_resources('port_pair', context, portpair_id)

    def delete_port_pair_groups(self, context, portpairgroup_id):
        ppg = self.get_resource('port_pair_group', context, portpairgroup_id)
        if not ppg:
            raise client_exceptions.NotFound()
        for pc in BOTTOM1_PORTCHAINS:
            if portpairgroup_id in pc['port_pair_groups']:
                raise client_exceptions.Conflict("in use")
        self.delete_resources('port_pair_group', context, portpairgroup_id)

    def delete_flow_classifiers(self, context, flowclassifier_id):
        fc = self.get_resource('flow_classifier', context, flowclassifier_id)
        if not fc:
            raise client_exceptions.NotFound()
        for pc in BOTTOM1_PORTCHAINS:
            if flowclassifier_id in pc['flow_classifiers']:
                raise client_exceptions.Conflict("in use")
        self.delete_resources('flow_classifier', context, flowclassifier_id)


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


class FakeSession(test_utils.FakeSession):

    def _fill_port_chain_dict(self, port_chain, model_dict, fields=None):
        model_dict['port_pair_groups'] = [
            assoc['portpairgroup_id']
            for assoc in port_chain['chain_group_associations']]
        model_dict['flow_classifiers'] = [
            assoc['flowclassifier_id']
            for assoc in port_chain['chain_classifier_associations']]

    def add_hook(self, model_obj, model_dict):
        if model_obj.__tablename__ == 'sfc_port_chains':
            self._fill_port_chain_dict(model_obj, model_dict)


class FakeDriver(object):
    def __init__(self, driver, name):
        self.obj = driver
        self.name = name


class FakeSfcDriver(sfc_driver.TricircleSfcDriver):
    def __init__(self):
        self.xjob_handler = FakeRPCAPI(self)
        self.helper = helper.NetworkHelper(self)

    def _get_client(self, region_name):
        return FakeClient(region_name)


class FakeFcDriver(fc_driver.TricircleFcDriver):
    def __init__(self):
        self.xjob_handler = FakeRPCAPI(self)
        self.helper = helper.NetworkHelper(self)

    def _get_client(self, region_name):
        return FakeClient(region_name)


class FakeFcPlugin(fc_plugin.FlowClassifierPlugin):
    def __init__(self):
        super(FakeFcPlugin, self).__init__()
        self.driver_manager.ordered_drivers = [FakeDriver(
            FakeFcDriver(), "tricircle_fc")]


class FakeSfcPlugin(sfc_plugin.TricircleSfcPlugin):
    def __init__(self):
        super(FakeSfcPlugin, self).__init__()
        self.driver_manager.ordered_drivers = [FakeDriver(
            FakeSfcDriver(), "tricircle_sfc")]

    def _get_client(self, region_name):
        return FakeClient(region_name)

    def get_port_pairs(self, context, filters=None):
        client = self._get_client('top')
        _filter = []
        for key, values in six.iteritems(filters):
            for v in values:
                _filter.append(
                    {'key': key, 'comparator': 'eq', 'value': v})
        return client.list_resources('port_pair', context, _filter)

    def get_port_chain(self, context, id, fields=None):
        client = self._get_client('top')
        filter = [{'key': 'id', 'comparator': 'eq', 'value': id}]
        portchains = client.list_resources('port_chain', context, filter)
        if portchains:
            return portchains[0]
        return None


def fake_get_context_from_neutron_context(q_context):
    ctx = context.get_db_context()
    ctx.project_id = q_context.project_id
    return ctx


def fake_make_port_pair_group_dict(self, port_pair_group, fields=None):
    return port_pair_group


def fake_make_port_pair_dict(self, port_pair, fields=None):
    return port_pair


class FakeCorePlugin(central_plugin.TricirclePlugin):
    def __init__(self):
        pass

    def get_port(self, ctx, _id):
        return self._get_port(ctx, _id)

    def _get_port(self, ctx, _id):
        top_client = FakeClient()
        _filters = [{'key': 'id', 'comparator': 'eq', 'value': _id}]
        return top_client.list_resources('port', ctx, _filters)[0]


def fake_get_plugin(alias='core'):
    if alias == 'sfc':
        return FakeSfcPlugin()
    return FakeCorePlugin()


class PluginTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()
        xmanager.IN_TEST = True
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

    def _prepare_net_test(self, project_id, ctx, pod_name):
        t_net_id = uuidutils.generate_uuid()
        pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_net_id,
                              'bottom_id': t_net_id,
                              'pod_id': pod_id,
                              'project_id': project_id,
                              'resource_type': constants.RT_NETWORK})
        return t_net_id

    def _prepare_port_test(self, tenant_id, ctx, pod_name, net_id):
        t_port_id = uuidutils.generate_uuid()
        t_port = {
            'id': t_port_id,
            'network_id': net_id
        }
        TOP_PORTS.append(DotDict(t_port))
        b_port = {
            'id': t_port_id,
            'network_id': net_id
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

    def _update_port_pair_test(self, ppg_mappings, port_pairs):
        for pp_id, ppg_id in six.iteritems(ppg_mappings):
            for pp in port_pairs:
                if pp['id'] == pp_id:
                    pp['portpairgroup_id'] = ppg_id

    def _prepare_port_pair_test(self, project_id, t_ctx, pod_name,
                                index, ingress, egress, create_bottom,
                                portpairgroup_id=None):
        t_pp_id = uuidutils.generate_uuid()
        b_pp_id = uuidutils.generate_uuid()
        top_pp = {
            'id': t_pp_id,
            'project_id': project_id,
            'tenant_id': project_id,
            'ingress': ingress,
            'egress': egress,
            'name': 'top_pp_%d' % index,
            'service_function_parameters': {"weight": 1, "correlation": None},
            'description': "description",
            'portpairgroup_id': portpairgroup_id
        }
        TOP_PORTPAIRS.append(DotDict(top_pp))
        if create_bottom:
            btm_pp = {
                'id': b_pp_id,
                'project_id': project_id,
                'tenant_id': project_id,
                'ingress': ingress,
                'egress': egress,
                'name': 'btm_pp_%d' % index,
                'service_function_parameters': {"weight": 1,
                                                "correlation": None},
                'description': "description",
                'portpairgroup_id': portpairgroup_id
            }
            if pod_name == 'pod_1':
                BOTTOM1_PORTPAIRS.append(DotDict(btm_pp))
            else:
                BOTTOM2_PORTPAIRS.append(DotDict(btm_pp))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(t_ctx, models.ResourceRouting,
                                 {'top_id': t_pp_id,
                                  'bottom_id': b_pp_id,
                                  'pod_id': pod_id,
                                  'project_id': project_id,
                                  'resource_type': constants.RT_PORT_PAIR})

        return t_pp_id, b_pp_id

    def _prepare_port_pair_group_test(self, project_id, t_ctx, pod_name, index,
                                      t_pp_ids, create_bottom, b_pp_ids):
        t_ppg_id = uuidutils.generate_uuid()
        b_ppg_id = uuidutils.generate_uuid()

        top_ppg = {
            "group_id": 1,
            "description": "",
            "tenant_id": project_id,
            "port_pair_group_parameters": {"lb_fields": []},
            "port_pairs": t_pp_ids,
            "project_id": project_id,
            "id": t_ppg_id,
            "name": 'top_ppg_%d' % index}
        TOP_PORTPAIRGROUPS.append(DotDict(top_ppg))
        if create_bottom:
            btm_ppg = {
                "group_id": 1,
                "description": "",
                "tenant_id": project_id,
                "port_pair_group_parameters": {"lb_fields": []},
                "port_pairs": b_pp_ids,
                "project_id": project_id,
                "id": b_ppg_id,
                "name": 'btm_ppg_%d' % index}
            if pod_name == 'pod_1':
                BOTTOM1_PORTPAIRGROUPS.append(DotDict(btm_ppg))
            else:
                BOTTOM2_PORTPAIRGROUPS.append(DotDict(btm_ppg))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(t_ctx, models.ResourceRouting,
                                 {'top_id': t_ppg_id,
                                  'bottom_id': b_ppg_id,
                                  'pod_id': pod_id,
                                  'project_id': project_id,
                                  'resource_type':
                                      constants.RT_PORT_PAIR_GROUP})

        return t_ppg_id, b_ppg_id

    def _prepare_flow_classifier_test(self, project_id, t_ctx, pod_name,
                                      index, src_port_id, create_bottom):
        t_fc_id = uuidutils.generate_uuid()
        b_fc_id = uuidutils.generate_uuid()

        top_fc = {
            "source_port_range_min": None,
            "destination_ip_prefix": None,
            "protocol": None,
            "description": "",
            "l7_parameters": {},
            "source_port_range_max": None,
            "id": t_fc_id,
            "name": "t_fc_%s" % index,
            "ethertype": "IPv4",
            "tenant_id": project_id,
            "source_ip_prefix": "1.0.0.0/24",
            "logical_destination_port": None,
            "destination_port_range_min": None,
            "destination_port_range_max": None,
            "project_id": project_id,
            "logical_source_port": src_port_id}

        TOP_FLOWCLASSIFIERS.append(DotDict(top_fc))
        if create_bottom:
            btm_fc = {
                "source_port_range_min": None,
                "destination_ip_prefix": None,
                "protocol": None,
                "description": "",
                "l7_parameters": {},
                "source_port_range_max": None,
                "id": b_fc_id,
                "name": "b_fc_%s" % index,
                "ethertype": "IPv4",
                "tenant_id": project_id,
                "source_ip_prefix": "1.0.0.0/24",
                "logical_destination_port": None,
                "destination_port_range_min": None,
                "destination_port_range_max": None,
                "project_id": project_id,
                "logical_source_port": src_port_id}
            if pod_name == 'pod_1':
                BOTTOM1_FLOWCLASSIFIERS.append(DotDict(btm_fc))
            else:
                BOTTOM2_FLOWCLASSIFIERS.append(DotDict(btm_fc))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(t_ctx, models.ResourceRouting,
                                 {'top_id': t_fc_id,
                                  'bottom_id': b_fc_id,
                                  'pod_id': pod_id,
                                  'project_id': project_id,
                                  'resource_type':
                                      constants.RT_FLOW_CLASSIFIER})

        return t_fc_id, b_fc_id

    def _prepare_port_chain_test(self, project_id, t_ctx, pod_name,
                                 index, create_bottom, ids):
        t_pc_id = uuidutils.generate_uuid()
        b_pc_id = uuidutils.generate_uuid()

        top_pc = {
            "tenant_id": project_id,
            "name": "t_pc_%s" % index,
            "chain_parameters": {
                "symmetric": False, "correlation": "mpls"},
            "port_pair_groups": ids['t_ppg_id'],
            "flow_classifiers": ids['t_fc_id'],
            "project_id": project_id,
            "chain_id": 1,
            "description": "",
            "id": t_pc_id}

        TOP_PORTCHAINS.append(DotDict(top_pc))
        if create_bottom:
            btm_pc = {
                "tenant_id": project_id,
                "name": "b_pc_%s" % index,
                "chain_parameters": {
                    "symmetric": False, "correlation": "mpls"},
                "port_pair_groups": ids['b_ppg_id'],
                "flow_classifiers": ids['b_fc_id'],
                "project_id": project_id,
                "chain_id": 1,
                "description": "",
                "id": b_pc_id}
            if pod_name == 'pod_1':
                BOTTOM1_PORTCHAINS.append(DotDict(btm_pc))
            else:
                BOTTOM2_PORTCHAINS.append(DotDict(btm_pc))

            pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
            core.create_resource(t_ctx, models.ResourceRouting,
                                 {'top_id': t_pc_id,
                                  'bottom_id': b_pc_id,
                                  'pod_id': pod_id,
                                  'project_id': project_id,
                                  'resource_type': constants.RT_PORT_CHAIN})

        return t_pc_id, b_pc_id

    def test_get_client(self):
        driver = fc_driver.TricircleFcDriver()
        t_client = driver._get_client('top')
        self.assertEqual(t_client.region_name, 'top')

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    def test_get_port(self):
        self._basic_pod_setup()
        project_id = TEST_TENANT_ID
        fake_plugin = FakeSfcPlugin()
        t_ctx = context.get_db_context()
        port_id = self._prepare_port_test(project_id, t_ctx, 'pod_1', None)
        port = fake_plugin._get_port(context, port_id)
        self.assertIsNotNone(port)

    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port',
                  new=FakeCorePlugin.get_port)
    @patch.object(sfc_db.SfcDbPlugin, 'get_port_pairs',
                  new=FakeSfcPlugin.get_port_pairs)
    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_create_port_chain(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakeSfcPlugin()

        t_net_id = self._prepare_net_test(project_id, t_ctx, 'pod_1')
        ingress = self._prepare_port_test(project_id, t_ctx, 'pod_1', t_net_id)
        egress = self._prepare_port_test(project_id, t_ctx, 'pod_1', t_net_id)
        src_port_id = self._prepare_port_test(project_id,
                                              t_ctx, 'pod_1', t_net_id)
        t_pp1_id, _ = self._prepare_port_pair_test(
            project_id, t_ctx, 'pod_1', 0, ingress, egress, False)
        t_ppg1_id, _ = self._prepare_port_pair_group_test(
            project_id, t_ctx, 'pod_1', 0, [t_pp1_id], False, None)
        ppg1_mapping = {t_pp1_id: t_ppg1_id}
        self._update_port_pair_test(ppg1_mapping, TOP_PORTPAIRS)
        t_fc1_id, _ = self._prepare_flow_classifier_test(
            project_id, t_ctx, 'pod_1', 0, src_port_id, False)
        body = {"port_chain": {
            "tenant_id": project_id,
            "name": "pc1",
            "chain_parameters": {
                "symmetric": False, "correlation": "mpls"},
            "port_pair_groups": [t_ppg1_id],
            "flow_classifiers": [t_fc1_id],
            "project_id": project_id,
            "chain_id": 1,
            "description": ""}}
        t_pc1 = fake_plugin.create_port_chain(q_ctx, body)
        pp1_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pp1_id, constants.RT_PORT_PAIR)
        ppg1_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_ppg1_id, constants.RT_PORT_PAIR_GROUP)
        fc1_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_fc1_id, constants.RT_FLOW_CLASSIFIER)
        pc1_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pc1['id'], constants.RT_PORT_CHAIN)
        btm1_pp_ids = [btm_pp['id'] for btm_pp in BOTTOM1_PORTPAIRS]
        btm1_ppg_ids = [btm_ppg['id'] for btm_ppg in BOTTOM1_PORTPAIRGROUPS]
        btm1_fc_ids = [btm_fc['id'] for btm_fc in BOTTOM1_FLOWCLASSIFIERS]
        btm1_pc_ids = [btm_pc['id'] for btm_pc in BOTTOM1_PORTCHAINS]
        b_pp1_id = pp1_mappings[0][1]
        b_ppg1_id = ppg1_mappings[0][1]
        b_fc1_id = fc1_mappings[0][1]
        b_pc1_id = pc1_mappings[0][1]
        self.assertEqual([b_pp1_id], btm1_pp_ids)
        self.assertEqual([b_ppg1_id], btm1_ppg_ids)
        self.assertEqual([b_fc1_id], btm1_fc_ids)
        self.assertEqual([b_pc1_id], btm1_pc_ids)

        # make conflict
        TOP_PORTCHAINS.pop()
        TOP_FLOWCLASSIFIERS.pop()
        TOP_PORTPAIRGROUPS.pop()
        TOP_PORTPAIRS.pop()
        b_ppg1_mapping = {b_pp1_id: b_ppg1_id}
        self._update_port_pair_test(b_ppg1_mapping, BOTTOM1_PORTPAIRS)
        db_api.create_recycle_resource(
            t_ctx, t_ppg1_id, constants.RT_PORT_PAIR_GROUP, q_ctx.project_id)

        t_pp2_id, _ = self._prepare_port_pair_test(
            project_id, t_ctx, 'pod_1', 0, ingress, egress, False)
        t_ppg2_id, _ = self._prepare_port_pair_group_test(
            project_id, t_ctx, 'pod_1', 0, [t_pp2_id], False, None)
        ppg2_mapping = {t_pp2_id: t_ppg2_id}
        self._update_port_pair_test(ppg2_mapping, TOP_PORTPAIRS)
        t_fc2_id, _ = self._prepare_flow_classifier_test(
            project_id, t_ctx, 'pod_1', 0, src_port_id, False)
        body2 = {"port_chain": {
            "tenant_id": project_id,
            "name": "pc1",
            "chain_parameters": {
                "symmetric": False, "correlation": "mpls"},
            "port_pair_groups": [t_ppg2_id],
            "flow_classifiers": [t_fc2_id],
            "project_id": project_id,
            "chain_id": 1,
            "description": ""}}
        t_pc2 = fake_plugin.create_port_chain(q_ctx, body2)
        pp2_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pp2_id, constants.RT_PORT_PAIR)
        ppg2_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_ppg2_id, constants.RT_PORT_PAIR_GROUP)
        fc2_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_fc2_id, constants.RT_FLOW_CLASSIFIER)
        pc2_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pc2['id'], constants.RT_PORT_CHAIN)
        btm1_pp_ids = [btm_pp['id'] for btm_pp in BOTTOM1_PORTPAIRS]
        btm1_ppg_ids = [btm_ppg['id'] for btm_ppg in BOTTOM1_PORTPAIRGROUPS]
        btm1_fc_ids = [btm_fc['id'] for btm_fc in BOTTOM1_FLOWCLASSIFIERS]
        btm1_pc_ids = [btm_pc['id'] for btm_pc in BOTTOM1_PORTCHAINS]
        b_pp2_id = pp2_mappings[0][1]
        b_ppg2_id = ppg2_mappings[0][1]
        b_fc2_id = fc2_mappings[0][1]
        b_pc2_id = pc2_mappings[0][1]
        self.assertEqual([b_pp2_id], btm1_pp_ids)
        self.assertEqual([b_ppg2_id], btm1_ppg_ids)
        self.assertEqual([b_fc2_id], btm1_fc_ids)
        self.assertEqual([b_pc2_id], btm1_pc_ids)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_delete_port_chain(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakeSfcPlugin()
        ids = {'t_ppg_id': [uuidutils.generate_uuid()],
               'b_ppg_id': [uuidutils.generate_uuid()],
               't_fc_id': [uuidutils.generate_uuid()],
               'b_fc_id': [uuidutils.generate_uuid()]}
        t_pc_id1, _ = self._prepare_port_chain_test(
            project_id, t_ctx, 'pod_1', 0, True, ids)

        fake_plugin.delete_port_chain(q_ctx, t_pc_id1)
        pc_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pc_id1, constants.RT_PORT_CHAIN)
        self.assertEqual(len(TOP_PORTCHAINS), 0)
        self.assertEqual(len(BOTTOM1_PORTCHAINS), 0)
        self.assertEqual(len(pc_mappings), 0)

        t_pc_id2, _ = self._prepare_port_chain_test(
            project_id, t_ctx, 'pod_1', 0, True, ids)
        BOTTOM1_PORTCHAINS.pop()
        fake_plugin.delete_port_chain(q_ctx, t_pc_id2)
        pc_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pc_id2, constants.RT_PORT_CHAIN)
        self.assertEqual(len(TOP_PORTCHAINS), 0)
        self.assertEqual(len(pc_mappings), 0)

    @patch.object(sfc_db.SfcDbPlugin, '_make_port_pair_group_dict',
                  new=fake_make_port_pair_group_dict)
    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_delete_port_pair_group(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakeSfcPlugin()

        t_pp_id = uuidutils.generate_uuid()
        b_pp_id = uuidutils.generate_uuid()

        t_ppg_id1, _ = self._prepare_port_pair_group_test(
            project_id, t_ctx, 'pod_1', 0, [t_pp_id], True, [b_pp_id])
        fake_plugin.delete_port_pair_group(q_ctx, t_ppg_id1)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_ppg_id1, constants.RT_PORT_PAIR_GROUP)
        self.assertEqual(len(TOP_PORTPAIRGROUPS), 0)
        self.assertEqual(len(BOTTOM1_PORTPAIRGROUPS), 0)
        self.assertEqual(len(ppg_mappings), 0)

        t_ppg_id2, _ = self._prepare_port_pair_group_test(
            project_id, t_ctx, 'pod_1', 0, [t_pp_id], True, [b_pp_id])
        BOTTOM1_PORTPAIRGROUPS.pop()
        fake_plugin.delete_port_pair_group(q_ctx, t_ppg_id2)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_ppg_id2, constants.RT_PORT_PAIR_GROUP)
        self.assertEqual(len(TOP_PORTPAIRGROUPS), 0)
        self.assertEqual(len(ppg_mappings), 0)

    @patch.object(sfc_db.SfcDbPlugin, '_make_port_pair_dict',
                  new=fake_make_port_pair_dict)
    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_delete_port_pair(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakeSfcPlugin()

        ingress = uuidutils.generate_uuid()
        egress = uuidutils.generate_uuid()
        t_pp1_id, _ = self._prepare_port_pair_test(
            project_id, t_ctx, 'pod_1', 0, ingress, egress, True)
        fake_plugin.delete_port_pair(q_ctx, t_pp1_id)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pp1_id, constants.RT_PORT_PAIR_GROUP)
        self.assertEqual(len(TOP_PORTPAIRS), 0)
        self.assertEqual(len(BOTTOM1_PORTPAIRS), 0)
        self.assertEqual(len(ppg_mappings), 0)

        t_pp2_id, _ = self._prepare_port_pair_test(
            project_id, t_ctx, 'pod_1', 0, ingress, egress, True)
        BOTTOM1_PORTPAIRS.pop()
        fake_plugin.delete_port_pair(q_ctx, t_pp2_id)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_pp2_id, constants.RT_PORT_PAIR_GROUP)
        self.assertEqual(len(TOP_PORTPAIRS), 0)
        self.assertEqual(len(ppg_mappings), 0)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    def test_delete_flow_classifier(self):
        project_id = TEST_TENANT_ID
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        self._basic_pod_setup()
        fake_plugin = FakeFcPlugin()

        src_port_id = uuidutils.generate_uuid()

        t_fc_id1, _ = self._prepare_flow_classifier_test(
            project_id, t_ctx, 'pod_1', 0, src_port_id, True)
        fake_plugin.delete_flow_classifier(q_ctx, t_fc_id1)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_fc_id1, constants.RT_FLOW_CLASSIFIER)
        self.assertEqual(len(TOP_FLOWCLASSIFIERS), 0)
        self.assertEqual(len(BOTTOM1_FLOWCLASSIFIERS), 0)
        self.assertEqual(len(ppg_mappings), 0)

        t_fc_id2, _ = self._prepare_flow_classifier_test(
            project_id, t_ctx, 'pod_1', 0, src_port_id, True)
        BOTTOM1_FLOWCLASSIFIERS.pop()
        fake_plugin.delete_flow_classifier(q_ctx, t_fc_id2)
        ppg_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_fc_id2, constants.RT_FLOW_CLASSIFIER)
        self.assertEqual(len(TOP_FLOWCLASSIFIERS), 0)
        self.assertEqual(len(ppg_mappings), 0)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        test_utils.get_resource_store().clean()
        cfg.CONF.unregister_opts(q_config.core_opts)
        xmanager.IN_TEST = False
