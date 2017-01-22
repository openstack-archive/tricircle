# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import mock
from mock import patch
import six
from six.moves import xrange
import unittest

from oslo_config import cfg
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.common import context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.xjob import xmanager
from tricircle.xjob import xservice


TOP_NETWORK = []
BOTTOM1_NETWORK = []
BOTTOM2_NETWORK = []
TOP_SUBNET = []
BOTTOM1_SUBNET = []
BOTTOM2_SUBNET = []
BOTTOM1_PORT = []
BOTTOM2_PORT = []
TOP_ROUTER = []
BOTTOM1_ROUTER = []
BOTTOM2_ROUTER = []
TOP_SG = []
BOTTOM1_SG = []
BOTTOM2_SG = []
TOP_FIP = []
BOTTOM1_FIP = []
BOTTOM2_FIP = []
RES_LIST = [TOP_NETWORK, BOTTOM1_NETWORK, BOTTOM2_NETWORK, TOP_SUBNET,
            BOTTOM1_SUBNET, BOTTOM2_SUBNET, BOTTOM1_PORT, BOTTOM2_PORT,
            TOP_ROUTER, BOTTOM1_ROUTER, BOTTOM2_ROUTER, TOP_SG, BOTTOM1_SG,
            BOTTOM2_SG, TOP_FIP, BOTTOM1_FIP, BOTTOM2_FIP]
RES_MAP = {'top': {'network': TOP_NETWORK,
                   'subnet': TOP_SUBNET,
                   'router': TOP_ROUTER,
                   'security_group': TOP_SG,
                   'floatingips': TOP_FIP},
           'pod_1': {'network': BOTTOM1_NETWORK,
                     'subnet': BOTTOM1_SUBNET,
                     'port': BOTTOM1_PORT,
                     'router': BOTTOM1_ROUTER,
                     'security_group': BOTTOM1_SG,
                     'floatingips': BOTTOM1_FIP},
           'pod_2': {'network': BOTTOM2_NETWORK,
                     'subnet': BOTTOM2_SUBNET,
                     'port': BOTTOM2_PORT,
                     'router': BOTTOM2_ROUTER,
                     'security_group': BOTTOM2_SG,
                     'floatingips': BOTTOM2_FIP}}


class FakeXManager(xmanager.XManager):
    def __init__(self):
        self.clients = {'top': FakeClient(),
                        'pod_1': FakeClient('pod_1'),
                        'pod_2': FakeClient('pod_2')}


class FakeClient(object):
    def __init__(self, region_name=None):
        if region_name:
            self.region_name = region_name
        else:
            self.region_name = 'top'

    def list_resources(self, resource, cxt, filters=None):
        res_list = []
        filters = filters or []
        for res in RES_MAP[self.region_name][resource]:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if res[_filter['key']] not in _filter['value']:
                    is_selected = False
                    break
            if is_selected:
                res_list.append(res)
        return res_list

    def list_ports(self, cxt, filters=None):
        return self.list_resources('port', cxt, filters)

    def list_subnets(self, cxt, filters=None):
        return self.list_resources('subnet', cxt, filters)

    def get_subnets(self, cxt, subnet_id):
        return self.list_resources(
            'subnet', cxt,
            [{'key': 'id', 'comparator': 'eq', 'value': subnet_id}])[0]

    def get_routers(self, cxt, router_id):
        return self.list_resources(
            'router', cxt,
            [{'key': 'id', 'comparator': 'eq', 'value': router_id}])[0]

    def update_routers(self, cxt, *args, **kwargs):
        pass

    def list_security_groups(self, cxt, filters=None):
        return self.list_resources('security_group', cxt, filters)

    def get_security_groups(self, cxt, sg_id):
        return self.list_resources(
            'security_group', cxt,
            [{'key': 'id', 'comparator': 'eq', 'value': sg_id}])[0]

    def delete_security_group_rules(self, cxt, sg_id):
        pass

    def create_security_group_rules(self, cxt, *args, **kwargs):
        pass

    def list_floatingips(self, cxt, filters=None):
        return self.list_resources('floatingips', cxt, filters)


class XManagerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        for opt in xservice.common_opts:
            if opt.name in ('worker_handle_timeout', 'job_run_expire',
                            'worker_sleep_time', 'redo_time_span'):
                cfg.CONF.register_opt(opt)
        self.context = context.Context()
        self.xmanager = FakeXManager()

    def _prepare_dnat_test(self):
        for subnet in BOTTOM2_SUBNET:
            if 'ext' in subnet['id']:
                ext_subnet = subnet
        ext_cidr = ext_subnet['cidr']
        ext_cidr_prefix = ext_cidr[:ext_cidr.rindex('.')]
        vm_ports = []
        # get one vm port from each bottom pod
        for ports in [BOTTOM1_PORT, BOTTOM2_PORT]:
            for port in ports:
                if port['device_owner'] == 'compute:None':
                    vm_ports.append(port)
                    break
        for i, vm_port in enumerate(vm_ports):
            vm_ip = vm_port['fixed_ips'][0]['ip_address']
            fip = {'floating_network_id': ext_subnet['network_id'],
                   'floating_ip_address': '%s.%d' % (ext_cidr_prefix, i + 1),
                   'port_id': vm_port['id'],
                   'fixed_ip_address': vm_ip}
            TOP_FIP.append(fip)
            BOTTOM2_FIP.append(fip)

    def _prepare_snat_test(self, top_router_id):
        ext_network = {'id': 'ext_network_id',
                       'router:external': True}
        ext_subnet = {
            'id': 'ext_subnet_id',
            'network_id': ext_network['id'],
            'cidr': '162.3.124.0/24',
            'gateway_ip': '162.3.124.1'
        }
        for router in TOP_ROUTER:
            if router['id'] == top_router_id:
                router['external_gateway_info'] = {
                    'network_id': ext_network['id']}
        router = {'id': 'ns_router_id'}
        for subnet in BOTTOM2_SUBNET:
            if 'bridge' in subnet['id']:
                bridge_subnet = subnet
        bridge_port = {
            'network_id': bridge_subnet['network_id'],
            'device_id': router['id'],
            'device_owner': 'network:router_interface',
            'fixed_ips': [{'subnet_id': bridge_subnet['id'],
                           'ip_address': bridge_subnet['gateway_ip']}]
        }
        BOTTOM2_NETWORK.append(ext_network)
        BOTTOM2_SUBNET.append(ext_subnet)
        BOTTOM2_PORT.append(bridge_port)
        BOTTOM2_ROUTER.append(router)
        route = {'top_id': top_router_id, 'bottom_id': router['id'],
                 'pod_id': 'pod_id_2', 'resource_type': constants.RT_NS_ROUTER}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, route)
        return bridge_subnet['gateway_ip'], router['id']

    def _prepare_east_west_network_test(self, top_router_id):
        bridge_infos = []

        router = {'id': top_router_id}
        TOP_ROUTER.append(router)
        for i in xrange(1, 3):
            pod_dict = {'pod_id': 'pod_id_%d' % i,
                        'region_name': 'pod_%d' % i,
                        'az_name': 'az_name_%d' % i}
            db_api.create_pod(self.context, pod_dict)

            network = {'id': 'network_%d_id' % i}
            bridge_network = {'id': 'bridge_network_%d_id' % i}
            router = {'id': 'router_%d_id' % i}
            subnet = {
                'id': 'subnet_%d_id' % i,
                'network_id': network['id'],
                'cidr': '10.0.%d.0/24' % i,
                'gateway_ip': '10.0.%d.1' % i,
            }
            bridge_subnet = {
                'id': 'bridge_subnet_%d_id' % i,
                'network_id': bridge_network['id'],
                'cidr': '100.0.1.0/24',
                'gateway_ip': '100.0.1.1',
            }
            port = {
                'network_id': network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_interface',
                'fixed_ips': [{'subnet_id': subnet['id'],
                               'ip_address': subnet['gateway_ip']}]
            }
            vm_port = {
                'id': 'vm_port_%d_id' % i,
                'network_id': network['id'],
                'device_id': 'vm%d_id' % i,
                'device_owner': 'compute:None',
                'fixed_ips': [{'subnet_id': subnet['id'],
                               'ip_address': '10.0.%d.3' % i}]
            }
            bridge_cidr = bridge_subnet['cidr']
            bridge_port_ip = '%s.%d' % (bridge_cidr[:bridge_cidr.rindex('.')],
                                        2 + i)
            bridge_port = {
                'network_id': bridge_network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_gateway',
                'fixed_ips': [{'subnet_id': bridge_subnet['id'],
                               'ip_address': bridge_port_ip}]
            }
            region_name = 'pod_%d' % i
            RES_MAP[region_name]['network'].append(network)
            RES_MAP[region_name]['network'].append(bridge_network)
            RES_MAP[region_name]['subnet'].append(subnet)
            RES_MAP[region_name]['subnet'].append(bridge_subnet)
            RES_MAP[region_name]['port'].append(port)
            RES_MAP[region_name]['port'].append(vm_port)
            RES_MAP[region_name]['port'].append(bridge_port)
            RES_MAP[region_name]['router'].append(router)

            route = {'top_id': top_router_id, 'bottom_id': router['id'],
                     'pod_id': pod_dict['pod_id'], 'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context, models.ResourceRouting,
                                     route)

            bridge_info = {
                'router_id': router['id'],
                'bridge_ip': bridge_port['fixed_ips'][0]['ip_address'],
                'vm_ips': ['10.0.%d.3' % i]}
            bridge_infos.append(bridge_info)

        BOTTOM1_NETWORK.append({'id': 'network_3_id'})
        BOTTOM1_SUBNET.append({'id': 'subnet_3_id',
                               'network_id': 'network_3_id',
                               'cidr': '10.0.3.0/24',
                               'gateway_ip': '10.0.3.1'})
        BOTTOM1_PORT.append({'network_id': 'network_3_id',
                             'device_id': 'router_1_id',
                             'device_owner': 'network:router_interface',
                             'fixed_ips': [{'subnet_id': 'subnet_3_id',
                                            'ip_address': '10.0.3.1'}]})
        BOTTOM1_PORT.append({'network_id': 'network_3_id',
                             'device_id': 'vm3_id',
                             'device_owner': 'compute:None',
                             'fixed_ips': [{'subnet_id': 'subnet_3_id',
                                            'ip_address': '10.0.3.3'}]})
        bridge_infos[0]['vm_ips'].append('10.0.3.3')
        return bridge_infos

    def _check_extra_routes_calls(self, except_list, actual_list):
        except_map = {}
        for except_call in except_list:
            ctx, router_id, routes_body = except_call[1]
            except_map[router_id] = (ctx, routes_body['router']['routes'])
        for actual_call in actual_list:
            ctx, router_id, routes_body = actual_call[0]
            expect_ctx, expect_routes = except_map[router_id]
            self.assertEqual(expect_ctx, ctx)
            six.assertCountEqual(self, expect_routes,
                                 routes_body['router']['routes'])

    @patch.object(FakeClient, 'update_routers')
    def test_configure_extra_routes_with_floating_ips(self, mock_update):
        top_router_id = 'router_id'
        bridge_infos = self._prepare_east_west_network_test(top_router_id)
        ns_bridge_ip, ns_router_id = self._prepare_snat_test(top_router_id)
        self._prepare_dnat_test()
        db_api.new_job(self.context, constants.JT_ROUTER, top_router_id)
        self.xmanager.configure_extra_routes(
            self.context, payload={constants.JT_ROUTER: top_router_id})
        calls = []
        ns_routes = []
        for i in range(2):
            routes = []
            for ip in bridge_infos[i]['vm_ips']:
                route = {'nexthop': bridge_infos[i]['bridge_ip'],
                         'destination': ip + '/32'}
                routes.append(route)
                ns_routes.append(route)
            routes.append({'nexthop': ns_bridge_ip,
                           'destination': '0.0.0.0/0'})
            call = mock.call(self.context, bridge_infos[1 - i]['router_id'],
                             {'router': {'routes': routes}})
            calls.append(call)
        calls.append(mock.call(self.context, ns_router_id,
                               {'router': {'routes': ns_routes}}))
        self._check_extra_routes_calls(calls, mock_update.call_args_list)

    @patch.object(FakeClient, 'update_routers')
    def test_configure_extra_routes_with_external_network(self, mock_update):
        top_router_id = 'router_id'
        bridge_infos = self._prepare_east_west_network_test(top_router_id)
        ns_bridge_ip, ns_router_id = self._prepare_snat_test(top_router_id)
        db_api.new_job(self.context, constants.JT_ROUTER, top_router_id)
        self.xmanager.configure_extra_routes(
            self.context, payload={constants.JT_ROUTER: top_router_id})
        calls = []
        ns_routes = []
        for i in range(2):
            routes = []
            for ip in bridge_infos[i]['vm_ips']:
                route = {'nexthop': bridge_infos[i]['bridge_ip'],
                         'destination': ip + '/32'}
                routes.append(route)
                ns_routes.append(route)
            routes.append({'nexthop': ns_bridge_ip,
                           'destination': '0.0.0.0/0'})
            call = mock.call(self.context, bridge_infos[1 - i]['router_id'],
                             {'router': {'routes': routes}})
            calls.append(call)
        calls.append(mock.call(self.context, ns_router_id,
                               {'router': {'routes': ns_routes}}))
        self._check_extra_routes_calls(calls, mock_update.call_args_list)

    @patch.object(FakeClient, 'update_routers')
    def test_configure_extra_routes(self, mock_update):
        top_router_id = 'router_id'
        bridge_infos = self._prepare_east_west_network_test(top_router_id)
        db_api.new_job(self.context, constants.JT_ROUTER, top_router_id)
        self.xmanager.configure_extra_routes(
            self.context, payload={constants.JT_ROUTER: top_router_id})
        calls = []
        for i in range(2):
            routes = []
            for ip in bridge_infos[i]['vm_ips']:
                routes.append({'nexthop': bridge_infos[i]['bridge_ip'],
                               'destination': ip + '/32'})
            call = mock.call(self.context, bridge_infos[1 - i]['router_id'],
                             {'router': {'routes': routes}})
            calls.append(call)
        self._check_extra_routes_calls(calls, mock_update.call_args_list)

    @patch.object(FakeClient, 'delete_security_group_rules')
    @patch.object(FakeClient, 'create_security_group_rules')
    def test_configure_security_group_rules(self, mock_create, mock_delete):
        project_id = uuidutils.generate_uuid()
        sg_id = uuidutils.generate_uuid()
        sg_rule_id_1 = uuidutils.generate_uuid()
        sg_rule_id_2 = uuidutils.generate_uuid()
        sg = {'id': sg_id,
              'tenant_id': project_id,
              'name': 'default',
              'security_group_rules': [{
                  'id': sg_rule_id_1,
                  'remote_group_id': sg_id,
                  'direction': 'ingress',
                  'remote_ip_prefix': None,
                  'protocol': None,
                  'ethertype': 'IPv4',
                  'port_range_max': -1,
                  'port_range_min': -1,
                  'security_group_id': sg_id},
                  {'id': sg_rule_id_2,
                   'remote_group_id': None,
                   'direction': 'engress',
                   'remote_ip_prefix': None,
                   'protocol': None,
                   'ethertype': 'IPv4',
                   'port_range_max': -1,
                   'port_range_min': -1,
                   'security_group_id': sg_id}]}
        RES_MAP['top']['security_group'].append(sg)

        for i in xrange(1, 3):
            pod_dict = {'pod_id': 'pod_id_%d' % i,
                        'region_name': 'pod_%d' % i,
                        'az_name': 'az_name_%d' % i}
            db_api.create_pod(self.context, pod_dict)

            network = {'id': 'network_%d_id' % i,
                       'tenant_id': project_id}
            subnet = {'id': 'subnet_%d_id' % i,
                      'network_id': network['id'],
                      'cidr': '10.0.%d.0/24' % i,
                      'gateway_ip': '10.0.%d.1' % i,
                      'tenant_id': project_id}
            RES_MAP['top']['network'].append(network)
            RES_MAP['top']['subnet'].append(subnet)

            region_name = 'pod_%d' % i
            RES_MAP[region_name]['security_group'].append(sg)
            route = {'top_id': sg_id, 'bottom_id': sg_id,
                     'pod_id': pod_dict['pod_id'],
                     'resource_type': 'security_group'}
            with self.context.session.begin():
                core.create_resource(self.context, models.ResourceRouting,
                                     route)

        db_api.new_job(self.context, constants.JT_SEG_RULE_SETUP, project_id)
        self.xmanager.configure_security_group_rules(
            self.context, payload={constants.JT_SEG_RULE_SETUP: project_id})

        calls = [mock.call(self.context, sg_rule_id_1)]
        mock_delete.assert_has_calls(calls)
        call_rules_id = [
            call_arg[0][1] for call_arg in mock_delete.call_args_list]
        # bottom security group already has sg_rule_id_2, so this rule will
        # not be deleted
        self.assertNotIn(sg_rule_id_2, call_rules_id)

        calls = [mock.call(self.context,
                           {'security_group_rules': [
                               {'remote_group_id': None,
                                'direction': 'ingress',
                                'remote_ip_prefix': '10.0.1.0/24',
                                'protocol': None,
                                'ethertype': 'IPv4',
                                'port_range_max': -1,
                                'port_range_min': -1,
                                'security_group_id': sg_id},
                               {'remote_group_id': None,
                                'direction': 'ingress',
                                'remote_ip_prefix': '10.0.2.0/24',
                                'protocol': None,
                                'ethertype': 'IPv4',
                                'port_range_max': -1,
                                'port_range_min': -1,
                                'security_group_id': sg_id}]})]
        mock_create.assert_has_calls(calls)

    def test_job_handle(self):
        job_type = 'fake_resource'

        @xmanager._job_handle(job_type)
        def fake_handle(self, ctx, payload):
            pass

        fake_id = 'fake_id'
        payload = {job_type: fake_id}
        db_api.new_job(self.context, job_type, fake_id)
        fake_handle(None, self.context, payload=payload)

        logs = core.query_resource(self.context, models.AsyncJobLog, [], [])

        self.assertEqual(fake_id, logs[0]['resource_id'])
        self.assertEqual(job_type, logs[0]['type'])

    def test_job_handle_exception(self):
        job_type = 'fake_resource'

        @xmanager._job_handle(job_type)
        def fake_handle(self, ctx, payload):
            raise Exception()

        fake_id = 'fake_id'
        payload = {job_type: fake_id}
        db_api.new_job(self.context, job_type, fake_id)
        fake_handle(None, self.context, payload=payload)

        jobs = core.query_resource(self.context, models.AsyncJob, [], [])
        expected_status = [constants.JS_New, constants.JS_Fail]
        job_status = [job['status'] for job in jobs]
        six.assertCountEqual(self, expected_status, job_status)

        self.assertEqual(fake_id, jobs[0]['resource_id'])
        self.assertEqual(fake_id, jobs[1]['resource_id'])
        self.assertEqual(job_type, jobs[0]['type'])
        self.assertEqual(job_type, jobs[1]['type'])

    def test_job_run_expire(self):
        job_type = 'fake_resource'

        @xmanager._job_handle(job_type)
        def fake_handle(self, ctx, payload):
            pass

        fake_id = uuidutils.generate_uuid()
        payload = {job_type: fake_id}
        db_api.new_job(self.context, job_type, fake_id)
        expired_job = {
            'id': uuidutils.generate_uuid(),
            'type': job_type,
            'timestamp': datetime.datetime.now() - datetime.timedelta(0, 200),
            'status': constants.JS_Running,
            'resource_id': fake_id,
            'extra_id': constants.SP_EXTRA_ID
        }
        core.create_resource(self.context, models.AsyncJob, expired_job)
        fake_handle(None, self.context, payload=payload)

        logs = core.query_resource(self.context, models.AsyncJobLog, [], [])

        self.assertEqual(fake_id, logs[0]['resource_id'])
        self.assertEqual(job_type, logs[0]['type'])

    @patch.object(db_api, 'get_running_job')
    @patch.object(db_api, 'register_job')
    def test_worker_handle_timeout(self, mock_register, mock_get):
        job_type = 'fake_resource'

        @xmanager._job_handle(job_type)
        def fake_handle(self, ctx, payload):
            pass

        cfg.CONF.set_override('worker_handle_timeout', 1)
        mock_register.return_value = None
        mock_get.return_value = None

        fake_id = uuidutils.generate_uuid()
        payload = {job_type: fake_id}
        db_api.new_job(self.context, job_type, fake_id)
        fake_handle(None, self.context, payload=payload)

        # nothing to assert, what we test is that fake_handle can exit when
        # timeout

    @patch('oslo_utils.timeutils.utcnow')
    def test_get_failed_or_new_jobs(self, mock_now):
        mock_now.return_value = datetime.datetime(2000, 1, 2, 12, 0, 0)
        job_dict_list = [
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 0, 0),
             'resource_id': 'uuid1', 'type': 'res1',
             'status': constants.JS_Fail},  # job_uuid1
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 5, 0),
             'resource_id': 'uuid1', 'type': 'res1',
             'status': constants.JS_Fail},  # job_uuid3
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 20, 0),
             'resource_id': 'uuid2', 'type': 'res2',
             'status': constants.JS_Fail},  # job_uuid5
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 15, 0),
             'resource_id': 'uuid2', 'type': 'res2',
             'status': constants.JS_Fail},  # job_uuid7
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 25, 0),
             'resource_id': 'uuid3', 'type': 'res3',
             'status': constants.JS_Success},  # job_uuid9
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 30, 0),
             'resource_id': 'uuid4', 'type': 'res4',
             'status': constants.JS_New},  # job_uuid11
            {'timestamp': datetime.datetime(1999, 12, 31, 12, 0, 0),
             'resource_id': 'uuid5', 'type': 'res5',
             'status': constants.JS_Fail},  # job_uuid13
            {'timestamp': datetime.datetime(1999, 12, 31, 11, 59, 59),
             'resource_id': 'uuid6', 'type': 'res6',
             'status': constants.JS_Fail}]  # job_uuid15
        for i, job_dict in enumerate(job_dict_list, 1):
            job_dict['id'] = 'job_uuid%d' % (2 * i - 1)
            job_dict['extra_id'] = 'extra_uuid%d' % (2 * i - 1)
            core.create_resource(self.context, models.AsyncJob, job_dict)
            job_dict['id'] = 'job_uuid%d' % (2 * i)
            job_dict['extra_id'] = 'extra_uuid%d' % (2 * i)
            job_dict['status'] = constants.JS_New
            core.create_resource(self.context, models.AsyncJob, job_dict)

        # for res3 + uuid3, the latest job's status is "Success", not returned
        # for res6 + uuid6, the latest job is out of the redo time span
        expected_failed_jobs = [
            {'resource_id': 'uuid1', 'type': 'res1'},
            {'resource_id': 'uuid2', 'type': 'res2'},
            {'resource_id': 'uuid5', 'type': 'res5'}]
        expected_new_jobs = [{'resource_id': 'uuid4', 'type': 'res4'}]
        (failed_jobs,
         new_jobs) = db_api.get_latest_failed_or_new_jobs(self.context)
        six.assertCountEqual(self, expected_failed_jobs, failed_jobs)
        six.assertCountEqual(self, expected_new_jobs, new_jobs)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
