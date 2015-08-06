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

from tricircle import context
from tricircle.db import core
from tricircle.db import exception
from tricircle.db import models


class ModelsTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()

    def test_obj_to_dict(self):
        site = {'site_id': 'test_site_uuid',
                'site_name': 'test_site',
                'az_id': 'test_az_uuid'}
        site_obj = models.Site.from_dict(site)
        for attr in site_obj.attributes:
            self.assertEqual(getattr(site_obj, attr), site[attr])

    def test_create(self):
        site = {'site_id': 'test_site_uuid',
                'site_name': 'test_site',
                'az_id': 'test_az_uuid'}
        site_ret = models.create_site(self.context, site)
        self.assertEqual(site_ret, site)

        service_type = {'id': 1,
                        'service_type': 'nova'}
        type_ret = models.create_service_type(self.context, service_type)
        self.assertEqual(type_ret, service_type)

        configuration = {
            'service_id': 'test_config_uuid',
            'site_id': 'test_site_uuid',
            'service_name': 'nova_service',
            'service_type': 'nova',
            'service_url': 'http://test_url'
        }
        config_ret = models.create_site_service_configuration(self.context,
                                                              configuration)
        self.assertEqual(config_ret, configuration)

    def test_update(self):
        site = {'site_id': 'test_site_uuid',
                'site_name': 'test_site',
                'az_id': 'test_az1_uuid'}
        models.create_site(self.context, site)
        update_dict = {'site_id': 'fake_uuid',
                       'site_name': 'test_site2',
                       'az_id': 'test_az2_uuid'}
        ret = models.update_site(self.context, 'test_site_uuid', update_dict)
        # primary key value will not be updated
        self.assertEqual(ret['site_id'], 'test_site_uuid')
        self.assertEqual(ret['site_name'], 'test_site2')
        self.assertEqual(ret['az_id'], 'test_az2_uuid')

    def test_delete(self):
        site = {'site_id': 'test_site_uuid',
                'site_name': 'test_site',
                'az_id': 'test_az_uuid'}
        models.create_site(self.context, site)
        models.delete_site(self.context, 'test_site_uuid')
        self.assertRaises(exception.ResourceNotFound, models.get_site,
                          self.context, 'test_site_uuid')

    def test_query(self):
        site1 = {'site_id': 'test_site1_uuid',
                 'site_name': 'test_site1',
                 'az_id': 'test_az1_uuid'}
        site2 = {'site_id': 'test_site2_uuid',
                 'site_name': 'test_site2',
                 'az_id': 'test_az2_uuid'}
        models.create_site(self.context, site1)
        models.create_site(self.context, site2)
        filters = [{'key': 'site_name',
                    'comparator': 'eq',
                    'value': 'test_site2'}]
        sites = models.list_sites(self.context, filters)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0], site2)
        filters = [{'key': 'site_name',
                    'comparator': 'eq',
                    'value': 'test_site3'}]
        sites = models.list_sites(self.context, filters)
        self.assertEqual(len(sites), 0)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
