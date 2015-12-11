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

import mock
from mock import patch
import unittest

import pecan

import tricircle.api.controllers.root as root_controller

from tricircle.common import cascading_site_api
from tricircle.common import context
from tricircle.common import rpc

from tricircle.db import client
from tricircle.db import core
from tricircle.db import models


def fake_create_client(target):
    return None


def fake_cast_message(self, context, method, payload):
    return None


class ControllerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.Context()
        self.context.is_admin = True

        root_controller._get_environment = mock.Mock(return_value={})
        root_controller._extract_context_from_environ = mock.Mock(
            return_value=self.context)

        pecan.abort = mock.Mock()
        pecan.response = mock.Mock()

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())


class SitesControllerTest(ControllerTest):
    def setUp(self):
        super(SitesControllerTest, self).setUp()
        self.controller = root_controller.SitesController()

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_post_top_site(self):
        kw = {'name': 'TopSite', 'top': True}
        site_id = self.controller.post(**kw)['site']['site_id']
        site = models.get_site(self.context, site_id)
        self.assertEqual(site['site_name'], 'TopSite')
        self.assertEqual(site['az_id'], '')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    @patch.object(client.Client, 'create_resources')
    def test_post_bottom_site(self, mock_method):
        kw = {'name': 'BottomSite'}
        site_id = self.controller.post(**kw)['site']['site_id']
        site = models.get_site(self.context, site_id)
        self.assertEqual(site['site_name'], 'BottomSite')
        self.assertEqual(site['az_id'], 'az_BottomSite')
        mock_method.assert_called_once_with('aggregate', self.context,
                                            'ag_BottomSite', 'az_BottomSite')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_post_site_name_missing(self):
        kw = {'top': True}
        self.controller.post(**kw)
        pecan.abort.assert_called_once_with(400, 'Name of site required')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_post_conflict(self):
        kw = {'name': 'TopSite', 'top': True}
        self.controller.post(**kw)
        self.controller.post(**kw)
        pecan.abort.assert_called_once_with(409,
                                            'Site with name TopSite exists')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_post_not_admin(self):
        self.context.is_admin = False
        kw = {'name': 'TopSite', 'top': True}
        self.controller.post(**kw)
        pecan.abort.assert_called_once_with(
            400, 'Admin role required to create sites')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    @patch.object(client.Client, 'create_resources')
    def test_post_decide_top(self, mock_method):
        # 'top' default to False
        # top site
        kw = {'name': 'Site1', 'top': True}
        self.controller.post(**kw)
        # bottom site
        kw = {'name': 'Site2', 'top': False}
        self.controller.post(**kw)
        kw = {'name': 'Site3'}
        self.controller.post(**kw)
        calls = [mock.call('aggregate', self.context, 'ag_Site%d' % i,
                           'az_Site%d' % i) for i in xrange(2, 4)]
        mock_method.assert_has_calls(calls)

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    @patch.object(models, 'create_site')
    def test_post_create_site_exception(self, mock_method):
        mock_method.side_effect = Exception
        kw = {'name': 'BottomSite'}
        self.controller.post(**kw)
        pecan.abort.assert_called_once_with(500, 'Fail to create site')

    @patch.object(client.Client, 'create_resources')
    def test_post_create_aggregate_exception(self, mock_method):
        mock_method.side_effect = Exception
        kw = {'name': 'BottomSite'}
        self.controller.post(**kw)
        pecan.abort.assert_called_once_with(500, 'Fail to create aggregate')

        # make sure site is deleted
        site_filter = [{'key': 'site_name',
                        'comparator': 'eq',
                        'value': 'BottomSite'}]
        sites = models.list_sites(self.context, site_filter)
        self.assertEqual(len(sites), 0)

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_get_one(self):
        kw = {'name': 'TopSite', 'top': True}
        site_id = self.controller.post(**kw)['site']['site_id']
        return_site = self.controller.get_one(site_id)['site']
        self.assertEqual(return_site, {'site_id': site_id,
                                       'site_name': 'TopSite',
                                       'az_id': ''})

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    def test_get_one_not_found(self):
        self.controller.get_one('fake_id')
        pecan.abort.assert_called_once_with(404,
                                            'Site with id fake_id not found')

    @patch.object(rpc, 'create_client', new=fake_create_client)
    @patch.object(cascading_site_api.CascadingSiteNotifyAPI,
                  '_cast_message', new=fake_cast_message)
    @patch.object(client.Client, 'create_resources', new=mock.Mock)
    def test_get_all(self):
        kw1 = {'name': 'TopSite', 'top': True}
        kw2 = {'name': 'BottomSite'}
        self.controller.post(**kw1)
        self.controller.post(**kw2)
        sites = self.controller.get_all()
        actual_result = [(site['site_name'],
                         site['az_id']) for site in sites['sites']]
        expect_result = [('BottomSite', 'az_BottomSite'), ('TopSite', '')]
        self.assertItemsEqual(actual_result, expect_result)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
