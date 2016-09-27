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


import unittest

from tricircle.common import az_ag
from tricircle.common import context

from tricircle.db import api
from tricircle.db import core
from tricircle.db import models

FAKE_AZ = 'fake_az'

FAKE_SITE_ID = 'fake_pod_id'
FAKE_SITE_NAME = 'fake_pod_name'
FAKE_SERVICE_ID = 'fake_service_id'

FAKE_SITE_ID_2 = 'fake_pod_id_2'
FAKE_SITE_NAME_2 = 'fake_pod_name_2'
FAKE_SERVICE_ID_2 = 'fake_service_id_2'

FAKE_TOP_NAME = 'RegionOne'
FAKE_TOP_ID = 'fake_top_pod_id'
FAKE_TOP_SERVICE_ID = 'fake_top_service_id'
FAKE_TOP_ENDPOINT = 'http://127.0.0.1:8774/v2/$(tenant_id)s'

FAKE_TYPE = 'fake_type'
FAKE_URL = 'http://127.0.0.1:12345'
FAKE_URL_INVALID = 'http://127.0.0.1:23456'

FAKE_SERVICE_TYPE = 'cinder'
FAKE_SERVICE_ENDPOINT = 'http://127.0.0.1:8774/v2.1/$(tenant_id)s'
FAKE_SERVICE_ENDPOINT_2 = 'http://127.0.0.2:8774/v2.1/$(tenant_id)s'

FAKE_TENANT_ID = 'my tenant'


class FakeException(Exception):
    pass


class AZAGTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()

        top_pod = {
            'pod_id': FAKE_TOP_ID,
            'pod_name': FAKE_TOP_NAME,
            'az_name': ''
        }

        config_dict_top = {
            'service_id': FAKE_TOP_SERVICE_ID,
            'pod_id': FAKE_TOP_ID,
            'service_type': FAKE_SERVICE_TYPE,
            'service_url': FAKE_TOP_ENDPOINT
        }

        pod_dict = {
            'pod_id': FAKE_SITE_ID,
            'pod_name': FAKE_SITE_NAME,
            'az_name': FAKE_AZ
        }

        pod_dict2 = {
            'pod_id': FAKE_SITE_ID_2,
            'pod_name': FAKE_SITE_NAME_2,
            'az_name': FAKE_AZ
        }

        config_dict = {
            'service_id': FAKE_SERVICE_ID,
            'pod_id': FAKE_SITE_ID,
            'service_type': FAKE_SERVICE_TYPE,
            'service_url': FAKE_SERVICE_ENDPOINT
        }

        config_dict2 = {
            'service_id': FAKE_SERVICE_ID_2,
            'pod_id': FAKE_SITE_ID_2,
            'service_type': FAKE_SERVICE_TYPE,
            'service_url': FAKE_SERVICE_ENDPOINT_2
        }

        api.create_pod(self.context, pod_dict)
        api.create_pod(self.context, pod_dict2)
        api.create_pod(self.context, top_pod)
        api.create_pod_service_configuration(self.context, config_dict)
        api.create_pod_service_configuration(self.context, config_dict2)
        api.create_pod_service_configuration(self.context, config_dict_top)

    def test_get_pod_by_az_tenant(self):

        pod1, _ = az_ag.get_pod_by_az_tenant(self.context,
                                             FAKE_AZ + FAKE_AZ,
                                             FAKE_TENANT_ID)
        self.assertIsNone(pod1)
        pods = az_ag.list_pods_by_tenant(self.context, FAKE_TENANT_ID)
        self.assertEqual(len(pods), 0)

        # schedule one
        pod2, _ = az_ag.get_pod_by_az_tenant(self.context,
                                             FAKE_AZ,
                                             FAKE_TENANT_ID)

        pod_bindings = core.query_resource(self.context,
                                           models.PodBinding,
                                           [{'key': 'tenant_id',
                                             'comparator': 'eq',
                                             'value': FAKE_TENANT_ID}],
                                           [])
        self.assertIsNotNone(pod_bindings)
        if pod_bindings[0]['pod_id'] == FAKE_SITE_ID:
            self.assertEqual(pod2['pod_name'], FAKE_SITE_NAME)
            self.assertEqual(pod2['pod_id'], FAKE_SITE_ID)
            self.assertEqual(pod2['az_name'], FAKE_AZ)

        else:
            self.assertEqual(pod2['pod_name'], FAKE_SITE_NAME_2)
            self.assertEqual(pod2['pod_id'], FAKE_SITE_ID_2)
            self.assertEqual(pod2['az_name'], FAKE_AZ)

        # scheduled one should always be bound
        pod3, _ = az_ag.get_pod_by_az_tenant(self.context,
                                             FAKE_AZ,
                                             FAKE_TENANT_ID)

        self.assertEqual(pod2['pod_name'], pod3['pod_name'])
        self.assertEqual(pod2['pod_id'], pod3['pod_id'])
        self.assertEqual(pod2['az_name'], pod3['az_name'])

    def test_list_pods_by_tenant(self):

        pod1, _ = az_ag.get_pod_by_az_tenant(self.context,
                                             FAKE_AZ + FAKE_AZ,
                                             FAKE_TENANT_ID)
        pods = az_ag.list_pods_by_tenant(self.context, FAKE_TENANT_ID)
        self.assertIsNone(pod1)
        self.assertEqual(len(pods), 0)

        # TODO(joehuang): tenant bound to multiple pods in one AZ

        # schedule one
        pod2, _ = az_ag.get_pod_by_az_tenant(self.context,
                                             FAKE_AZ,
                                             FAKE_TENANT_ID)
        pods = az_ag.list_pods_by_tenant(self.context, FAKE_TENANT_ID)
        self.assertDictEqual(pods[0], pod2)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
