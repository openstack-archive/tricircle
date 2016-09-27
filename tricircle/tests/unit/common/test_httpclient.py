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

import unittest

from tricircle.common import constants as cons
from tricircle.common import context
from tricircle.common import httpclient as hclient

from tricircle.db import api
from tricircle.db import core


def fake_get_pod_service_endpoint(ctx, pod_name, st):

    pod = api.get_pod_by_name(ctx, pod_name)
    if pod:
        f = [{'key': 'pod_id', 'comparator': 'eq',
              'value': pod['pod_id']},
             {'key': 'service_type', 'comparator': 'eq',
              'value': st}]
        pod_services = api.list_pod_service_configurations(
            ctx,
            filters=f,
            sorts=[])

        if len(pod_services) != 1:
            return ''

        return pod_services[0]['service_url']

    return ''


class HttpClientTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()

    def test_get_version_from_url(self):
        url = 'http://127.0.0.1:8774/v2.1/$(tenant_id)s'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'v2.1')

        url = 'http://127.0.0.1:8774/v2.1/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'v2.1')

        url = 'http://127.0.0.1:8774/v2.1/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'v2.1')

        url = 'https://127.0.0.1:8774/v2.1/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'v2.1')

        url = 'https://127.0.0.1/v2.1/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'v2.1')

        url = 'https://127.0.0.1/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, '')

        url = 'https://127.0.0.1/sss/'
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, 'sss')

        url = ''
        ver = hclient.get_version_from_url(url)
        self.assertEqual(ver, '')

    def test_get_bottom_url(self):
        b_endpoint = 'http://127.0.0.1:8774/v2.1/$(tenant_id)s'
        t_url = 'http://127.0.0.1:8774/v2/my_tenant_id/volumes'
        t_ver = hclient.get_version_from_url(t_url)
        b_ver = hclient.get_version_from_url(b_endpoint)

        self.assertEqual(t_ver, 'v2')
        self.assertEqual(b_ver, 'v2.1')

        b_url = hclient.get_bottom_url(t_ver, t_url, b_ver, b_endpoint)
        self.assertEqual(b_url,
                         'http://127.0.0.1:8774/v2.1/my_tenant_id/volumes')

        b_endpoint = 'http://127.0.0.1:8774/'
        b_ver = hclient.get_version_from_url(b_endpoint)
        self.assertEqual(b_ver, '')

        b_url = hclient.get_bottom_url(t_ver, t_url, b_ver, b_endpoint)
        self.assertEqual(b_url,
                         'http://127.0.0.1:8774/my_tenant_id/volumes')

        b_endpoint = 'http://127.0.0.1:8774/v2.1'
        b_ver = hclient.get_version_from_url(b_endpoint)
        self.assertEqual(b_ver, 'v2.1')

        b_url = hclient.get_bottom_url(t_ver, t_url, b_ver, b_endpoint)
        self.assertEqual(b_url,
                         'http://127.0.0.1:8774/v2.1/my_tenant_id/volumes')

        b_endpoint = 'http://127.0.0.1:8774/v2.1/'
        b_ver = hclient.get_version_from_url(b_endpoint)
        self.assertEqual(b_ver, 'v2.1')

        b_url = hclient.get_bottom_url(t_ver, t_url, b_ver, b_endpoint)
        self.assertEqual(b_url,
                         'http://127.0.0.1:8774/v2.1/my_tenant_id/volumes')

    @patch.object(hclient, 'get_pod_service_endpoint',
                  new=fake_get_pod_service_endpoint)
    def test_get_pod_service_ctx(self):
        pod_dict = {
            'pod_id': 'fake_pod_id',
            'pod_name': 'fake_pod_name',
            'az_name': 'fake_az'
        }

        config_dict = {
            'service_id': 'fake_service_id',
            'pod_id': 'fake_pod_id',
            'service_type': cons.ST_CINDER,
            'service_url': 'http://127.0.0.1:8774/v2.1/$(tenant_id)s'
        }
        t_url = 'http://127.0.0.1:8774/v2/my_tenant_id/volumes'
        api.create_pod(self.context, pod_dict)
        api.create_pod_service_configuration(self.context, config_dict)

        b_url = 'http://127.0.0.1:8774/v2.1/my_tenant_id/volumes'

        b_endpoint = hclient.get_pod_service_endpoint(self.context,
                                                      pod_dict['pod_name'],
                                                      cons.ST_CINDER)
        self.assertEqual(b_endpoint, config_dict['service_url'])

        b_ctx = hclient.get_pod_service_ctx(self.context,
                                            t_url,
                                            pod_dict['pod_name'],
                                            cons.ST_CINDER)
        self.assertEqual(b_ctx['t_ver'], 'v2')
        self.assertEqual(b_ctx['t_url'], t_url)
        self.assertEqual(b_ctx['b_ver'], 'v2.1')
        self.assertEqual(b_ctx['b_url'], b_url)

        # wrong pod name
        b_ctx = hclient.get_pod_service_ctx(self.context,
                                            t_url,
                                            pod_dict['pod_name'] + '1',
                                            cons.ST_CINDER)
        self.assertEqual(b_ctx['t_ver'], 'v2')
        self.assertEqual(b_ctx['t_url'], t_url)
        self.assertEqual(b_ctx['b_ver'], '')
        self.assertEqual(b_ctx['b_url'], '')

        # wrong service_type
        b_ctx = hclient.get_pod_service_ctx(self.context,
                                            t_url,
                                            pod_dict['pod_name'],
                                            cons.ST_CINDER + '1')
        self.assertEqual(b_ctx['t_ver'], 'v2')
        self.assertEqual(b_ctx['t_url'], t_url)
        self.assertEqual(b_ctx['b_ver'], '')
        self.assertEqual(b_ctx['b_url'], '')

    @patch.object(hclient, 'get_pod_service_endpoint',
                  new=fake_get_pod_service_endpoint)
    def test_get_pod_and_endpoint_by_name(self):
        pod_dict = {
            'pod_id': 'fake_pod_id',
            'pod_name': 'fake_pod_name',
            'az_name': 'fake_az'
        }
        api.create_pod(self.context, pod_dict)

        pod = api.get_pod_by_name(self.context, pod_dict['pod_name'] + '1')
        self.assertIsNone(pod)

        pod = api.get_pod_by_name(self.context, pod_dict['pod_name'])
        self.assertEqual(pod['pod_id'], pod_dict['pod_id'])
        self.assertEqual(pod['pod_name'], pod_dict['pod_name'])
        self.assertEqual(pod['az_name'], pod_dict['az_name'])

        config_dict = {
            'service_id': 'fake_service_id',
            'pod_id': 'fake_pod_id',
            'service_type': cons.ST_CINDER,
            'service_url': 'http://127.0.0.1:8774/v2.1/$(tenant_id)s'
        }
        api.create_pod_service_configuration(self.context, config_dict)

        endpoint = hclient.get_pod_service_endpoint(
            self.context,
            pod_dict['pod_name'],
            config_dict['service_type'])
        self.assertEqual(endpoint, config_dict['service_url'])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
