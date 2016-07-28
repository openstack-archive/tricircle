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


BOTTOM1_NETWORK = []
BOTTOM2_NETWORK = []
BOTTOM1_SUBNET = []
BOTTOM2_SUBNET = []
BOTTOM1_PORT = []
BOTTOM2_PORT = []
BOTTOM1_ROUTER = []
BOTTOM2_ROUTER = []
RES_LIST = [BOTTOM1_NETWORK, BOTTOM2_NETWORK, BOTTOM1_SUBNET, BOTTOM2_SUBNET,
            BOTTOM1_PORT, BOTTOM2_PORT, BOTTOM1_ROUTER, BOTTOM2_ROUTER]
RES_MAP = {'pod_1': {'network': BOTTOM1_NETWORK,
                     'subnet': BOTTOM1_SUBNET,
                     'port': BOTTOM1_PORT,
                     'router': BOTTOM1_ROUTER},
           'pod_2': {'network': BOTTOM2_NETWORK,
                     'subnet': BOTTOM2_SUBNET,
                     'port': BOTTOM2_PORT,
                     'router': BOTTOM2_ROUTER}}


class FakeXManager(xmanager.XManager):
    def __init__(self):
        self.clients = {'pod_1': FakeClient('pod_1'),
                        'pod_2': FakeClient('pod_2')}

    def _get_client(self, pod_name=None):
        return self.clients[pod_name]


class FakeClient(object):
    def __init__(self, pod_name=None):
        if pod_name:
            self.pod_name = pod_name
        else:
            self.pod_name = 'top'

    def list_resources(self, resource, cxt, filters=None):
        res_list = []
        filters = filters or []
        for res in RES_MAP[self.pod_name][resource]:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if res[_filter['key']] != _filter['value']:
                    is_selected = False
                    break
            if is_selected:
                res_list.append(res)
        return res_list

    def list_ports(self, cxt, filters=None):
        return self.list_resources('port', cxt, filters)

    def get_subnets(self, cxt, subnet_id):
        return self.list_resources(
            'subnet', cxt,
            [{'key': 'id', 'comparator': 'eq', 'value': subnet_id}])[0]

    def update_routers(self, cxt, *args, **kwargs):
        pass


class XManagerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        for opt in xservice.common_opts:
            if opt.name in ('worker_handle_timeout', 'job_run_expire',
                            'worker_sleep_time'):
                cfg.CONF.register_opt(opt)
        self.context = context.Context()
        self.xmanager = FakeXManager()

    @patch.object(FakeClient, 'update_routers')
    def test_configure_extra_routes(self, mock_update):
        top_router_id = 'router_id'
        for i in xrange(1, 3):
            pod_dict = {'pod_id': 'pod_id_%d' % i,
                        'pod_name': 'pod_%d' % i,
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
                'gateway_ip': '100.0.1.%d' % i,
            }
            port = {
                'network_id': network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_interface',
                'fixed_ips': [{'subnet_id': subnet['id'],
                               'ip_address': subnet['gateway_ip']}]
            }
            vm_port = {
                'network_id': network['id'],
                'device_id': 'vm%d_id' % i,
                'device_owner': 'compute:None',
                'fixed_ips': [{'subnet_id': subnet['id'],
                               'ip_address': '10.0.%d.3' % i}]
            }
            bridge_port = {
                'network_id': bridge_network['id'],
                'device_id': router['id'],
                'device_owner': 'network:router_interface',
                'fixed_ips': [{'subnet_id': bridge_subnet['id'],
                               'ip_address': bridge_subnet['gateway_ip']}]
            }
            pod_name = 'pod_%d' % i
            RES_MAP[pod_name]['network'].append(network)
            RES_MAP[pod_name]['network'].append(bridge_network)
            RES_MAP[pod_name]['subnet'].append(subnet)
            RES_MAP[pod_name]['subnet'].append(bridge_subnet)
            RES_MAP[pod_name]['port'].append(port)
            RES_MAP[pod_name]['port'].append(vm_port)
            RES_MAP[pod_name]['port'].append(bridge_port)
            RES_MAP[pod_name]['router'].append(router)

            route = {'top_id': top_router_id, 'bottom_id': router['id'],
                     'pod_id': pod_dict['pod_id'], 'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context, models.ResourceRouting,
                                     route)
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

        self.xmanager.configure_extra_routes(self.context,
                                             payload={'router': top_router_id})
        calls = [mock.call(self.context, 'router_1_id',
                           {'router': {
                               'routes': [{'nexthop': '100.0.1.2',
                                           'destination': '10.0.2.3/32'}]}}),
                 mock.call(self.context, 'router_2_id',
                           {'router': {
                               'routes': [{'nexthop': '100.0.1.1',
                                           'destination': '10.0.1.3/32'},
                                          {'nexthop': '100.0.1.1',
                                           'destination': '10.0.3.3/32'}]}}),
                 mock.call(self.context, 'router_2_id',
                           {'router': {
                               'routes': [{'nexthop': '100.0.1.1',
                                           'destination': '10.0.3.3/32'},
                                          {'nexthop': '100.0.1.1',
                                           'destination': '10.0.1.3/32'}]}})]

        called = mock_update.call_args_list[1] == calls[1]
        called = called or (mock_update.call_args_list[1] == calls[2])
        called = called and (mock_update.call_args_list[0] == calls[0])
        self.assertTrue(called)

    def test_job_handle(self):
        @xmanager._job_handle('fake_resource')
        def fake_handle(self, ctx, payload):
            pass

        fake_id = 'fake_id'
        payload = {'fake_resource': fake_id}
        fake_handle(None, self.context, payload=payload)

        jobs = core.query_resource(self.context, models.Job, [], [])
        expected_status = [constants.JS_New, constants.JS_Success]
        job_status = [job['status'] for job in jobs]
        self.assertItemsEqual(expected_status, job_status)

        self.assertEqual(fake_id, jobs[0]['resource_id'])
        self.assertEqual(fake_id, jobs[1]['resource_id'])
        self.assertEqual('fake_resource', jobs[0]['type'])
        self.assertEqual('fake_resource', jobs[1]['type'])

    def test_job_handle_exception(self):
        @xmanager._job_handle('fake_resource')
        def fake_handle(self, ctx, payload):
            raise Exception()

        fake_id = 'fake_id'
        payload = {'fake_resource': fake_id}
        fake_handle(None, self.context, payload=payload)

        jobs = core.query_resource(self.context, models.Job, [], [])
        expected_status = [constants.JS_New, constants.JS_Fail]
        job_status = [job['status'] for job in jobs]
        self.assertItemsEqual(expected_status, job_status)

        self.assertEqual(fake_id, jobs[0]['resource_id'])
        self.assertEqual(fake_id, jobs[1]['resource_id'])
        self.assertEqual('fake_resource', jobs[0]['type'])
        self.assertEqual('fake_resource', jobs[1]['type'])

    def test_job_run_expire(self):
        @xmanager._job_handle('fake_resource')
        def fake_handle(self, ctx, payload):
            pass

        fake_id = uuidutils.generate_uuid()
        payload = {'fake_resource': fake_id}
        expired_job = {
            'id': uuidutils.generate_uuid(),
            'type': 'fake_resource',
            'timestamp': datetime.datetime.now() - datetime.timedelta(0, 120),
            'status': constants.JS_Running,
            'resource_id': fake_id,
            'extra_id': constants.SP_EXTRA_ID
        }
        core.create_resource(self.context, models.Job, expired_job)
        fake_handle(None, self.context, payload=payload)

        jobs = core.query_resource(self.context, models.Job, [], [])
        expected_status = ['New', 'Fail', 'Success']
        job_status = [job['status'] for job in jobs]
        self.assertItemsEqual(expected_status, job_status)

        for i in xrange(3):
            self.assertEqual(fake_id, jobs[i]['resource_id'])
            self.assertEqual('fake_resource', jobs[i]['type'])

    @patch.object(db_api, 'get_running_job')
    @patch.object(db_api, 'register_job')
    def test_worker_handle_timeout(self, mock_register, mock_get):
        @xmanager._job_handle('fake_resource')
        def fake_handle(self, ctx, payload):
            pass

        cfg.CONF.set_override('worker_handle_timeout', 1)
        mock_register.return_value = None
        mock_get.return_value = None

        fake_id = uuidutils.generate_uuid()
        payload = {'fake_resource': fake_id}
        fake_handle(None, self.context, payload=payload)

        # nothing to assert, what we test is that fake_handle can exit when
        # timeout

    def test_get_failed_jobs(self):
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
             'status': constants.JS_Fail},  # job_uuid9
            {'timestamp': datetime.datetime(2000, 1, 1, 12, 30, 0),
             'resource_id': 'uuid3', 'type': 'res3',
             'status': constants.JS_Success}]
        for i, job_dict in enumerate(job_dict_list, 1):
            job_dict['id'] = 'job_uuid%d' % (2 * i - 1)
            job_dict['extra_id'] = 'extra_uuid%d' % (2 * i - 1)
            core.create_resource(self.context, models.Job, job_dict)
            job_dict['id'] = 'job_uuid%d' % (2 * i)
            job_dict['extra_id'] = 'extra_uuid%d' % (2 * i)
            job_dict['status'] = constants.JS_New
            core.create_resource(self.context, models.Job, job_dict)

        # for res3 + uuid3, the latest job's status is "Success", not returned
        expected_ids = ['job_uuid3', 'job_uuid5']
        returned_jobs = db_api.get_latest_failed_jobs(self.context)
        actual_ids = [job['id'] for job in returned_jobs]
        self.assertItemsEqual(expected_ids, actual_ids)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        for res in RES_LIST:
            del res[:]
