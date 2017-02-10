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

import neutronclient.common.exceptions as q_exceptions

from tricircle.common import context
from tricircle.common import exceptions
from tricircle.common import resource_handle


class FakeHttpClient(object):
    endpoint_url = 'fake_endpoint_url'


class FakeNeutronClient(object):
    def __init__(self):
        self.httpclient = FakeHttpClient()

    def create_network(self, body):
        pass

    def show_network(self, _id):
        pass

    def update_network(self, _id, body):
        pass

    def list_networks(self, **search_opts):
        pass

    def delete_network(self, _id):
        pass

    def remove_gateway_router(self, _id):
        pass


class FakeResourceHandle(resource_handle.NeutronResourceHandle):
    def _get_client(self, cxt):
        return FakeNeutronClient()


class ResourceHandleTest(unittest.TestCase):
    def setUp(self):
        self.context = context.Context()
        self.handle = FakeResourceHandle('fake_auth_url')

    @patch.object(FakeNeutronClient, 'create_network')
    def test_handle_create(self, mock_create):
        body = {'name': 'net1'}
        self.handle.handle_create(self.context, 'network', body)
        mock_create.assert_called_once_with(body)

    @patch.object(FakeNeutronClient, 'create_network')
    def test_handle_create_fail(self, mock_create):
        body = {'name': 'net1'}
        mock_create.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_create,
                          self.context, 'network', body)
        self.assertIsNone(self.handle.endpoint_url)

    @patch.object(FakeNeutronClient, 'show_network')
    def test_handle_get(self, mock_get):
        fake_network_id = 'fake_network_id'
        self.handle.handle_get(self.context, 'network', fake_network_id)
        mock_get.assert_called_once_with(fake_network_id)

    @patch.object(FakeNeutronClient, 'show_network')
    def test_handle_get_fail(self, mock_get):
        fake_network_id = 'fake_network_id'
        mock_get.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_get,
                          self.context, 'network', fake_network_id)
        self.assertIsNone(self.handle.endpoint_url)
        mock_get.side_effect = q_exceptions.NotFound
        ret = self.handle.handle_get(self.context, 'network', fake_network_id)
        self.assertIsNone(ret)

    @patch.object(FakeNeutronClient, 'update_network')
    def test_handle_update(self, mock_update):
        fake_network_id = 'fake_network_id'
        body = {'name': 'net2'}
        self.handle.handle_update(self.context, 'network',
                                  fake_network_id, body)
        mock_update.assert_called_once_with(fake_network_id, body)

    @patch.object(FakeNeutronClient, 'update_network')
    def test_handle_update_fail(self, mock_update):
        fake_network_id = 'fake_network_id'
        body = {'name': 'net2'}
        mock_update.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_update,
                          self.context, 'network', fake_network_id, body)
        self.assertIsNone(self.handle.endpoint_url)

    @patch.object(FakeNeutronClient, 'list_networks')
    def test_handle_list(self, mock_list):
        self.handle.handle_list(self.context, 'network',
                                [{'key': 'name', 'comparator': 'eq',
                                  'value': 'net1'}])
        # resource_handle will transform the filter format
        mock_list.assert_called_once_with(name='net1')

    @patch.object(FakeNeutronClient, 'list_networks')
    def test_handle_list_fail(self, mock_list):
        mock_list.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_list, self.context, 'network',
                          [{'key': 'name', 'comparator': 'eq',
                            'value': 'net1'}])
        self.assertIsNone(self.handle.endpoint_url)

    @patch.object(FakeNeutronClient, 'delete_network')
    def test_handle_delete(self, mock_delete):
        fake_network_id = 'fake_network_id'
        self.handle.handle_delete(self.context, 'network', fake_network_id)
        mock_delete.assert_called_once_with(fake_network_id)

    @patch.object(FakeNeutronClient, 'delete_network')
    def test_handle_delete_fail(self, mock_delete):
        fake_network_id = 'fake_network_id'
        mock_delete.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_delete,
                          self.context, 'network', fake_network_id)
        self.assertIsNone(self.handle.endpoint_url)
        mock_delete.side_effect = q_exceptions.NotFound
        ret = self.handle.handle_delete(self.context, 'network',
                                        fake_network_id)
        self.assertIsNone(ret)

    @patch.object(FakeNeutronClient, 'remove_gateway_router')
    def test_handle_action(self, mock_action):
        fake_router_id = 'fake_router_id'
        self.handle.handle_action(self.context, 'router', 'remove_gateway',
                                  fake_router_id)
        mock_action.assert_called_once_with(fake_router_id)

    @patch.object(FakeNeutronClient, 'remove_gateway_router')
    def test_handle_action_fail(self, mock_action):
        fake_router_id = 'fake_router_id'
        mock_action.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(exceptions.EndpointNotAvailable,
                          self.handle.handle_action, self.context, 'router',
                          'remove_gateway', fake_router_id)
        self.assertIsNone(self.handle.endpoint_url)
