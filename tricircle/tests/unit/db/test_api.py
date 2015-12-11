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

from tricircle.common import context
from tricircle.db import api
from tricircle.db import core
from tricircle.db import models


class APITest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def test_get_bottom_mappings_by_top_id(self):
        for i in xrange(3):
            site = {'site_id': 'test_site_uuid_%d' % i,
                    'site_name': 'test_site_%d' % i,
                    'az_id': 'test_az_uuid_%d' % i}
            api.create_site(self.context, site)
        route1 = {
            'top_id': 'top_uuid',
            'site_id': 'test_site_uuid_0',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_uuid',
            'site_id': 'test_site_uuid_1',
            'bottom_id': 'bottom_uuid_1',
            'resource_type': 'port'}
        route3 = {
            'top_id': 'top_uuid',
            'site_id': 'test_site_uuid_2',
            'bottom_id': 'bottom_uuid_2',
            'resource_type': 'neutron'}
        routes = [route1, route2, route3]
        with self.context.session.begin():
            for route in routes:
                core.create_resource(
                    self.context, models.ResourceRouting, route)
        mappings = api.get_bottom_mappings_by_top_id(self.context,
                                                     'top_uuid', 'port')
        self.assertEqual('test_site_uuid_1', mappings[0][0]['site_id'])
        self.assertEqual('bottom_uuid_1', mappings[0][1])

    def test_get_next_bottom_site(self):
        next_site = api.get_next_bottom_site(self.context)
        self.assertIsNone(next_site)
        sites = []
        for i in xrange(5):
            site = {'site_id': 'test_site_uuid_%d' % i,
                    'site_name': 'test_site_%d' % i,
                    'az_id': 'test_az_uuid_%d' % i}
            api.create_site(self.context, site)
            sites.append(site)
        next_site = api.get_next_bottom_site(self.context)
        self.assertEqual(next_site, sites[0])

        next_site = api.get_next_bottom_site(
            self.context, current_site_id='test_site_uuid_2')
        self.assertEqual(next_site, sites[3])

        next_site = api.get_next_bottom_site(
            self.context, current_site_id='test_site_uuid_4')
        self.assertIsNone(next_site)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
