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
import uuid

import mock
from oslo_config import cfg

from tricircle import context
from tricircle.db import client
from tricircle.db import core
from tricircle.db import exception
from tricircle.db import models
from tricircle.db import resource_handle

FAKE_AZ = 'fake_az'
FAKE_RESOURCE = 'fake_res'
FAKE_SITE_ID = 'fake_site_id'
FAKE_SITE_NAME = 'fake_site_name'
FAKE_SERVICE_ID = 'fake_service_id'
FAKE_TYPE = 'fake_type'
FAKE_URL = 'http://127.0.0.1:12345'
FAKE_URL_INVALID = 'http://127.0.0.1:23456'
FAKE_RESOURCES = [{'name': 'res1'}, {'name': 'res2'}]


class FakeException(Exception):
    pass


class FakeClient(object):
    def __init__(self, url):
        self.endpoint = url

    def list_fake_res(self, search_opts):
        # make sure endpoint is correctly set
        if self.endpoint != FAKE_URL:
            raise FakeException()
        if not search_opts:
            return [res for res in FAKE_RESOURCES]
        else:
            return [res for res in FAKE_RESOURCES if (
                res['name'] == search_opts['name'])]

    def create_fake_res(self, name):
        if self.endpoint != FAKE_URL:
            raise FakeException()
        FAKE_RESOURCES.append({'name': name})
        return {'name': name}

    def delete_fake_res(self, name):
        if self.endpoint != FAKE_URL:
            raise FakeException()
        try:
            FAKE_RESOURCES.remove({'name': name})
        except ValueError:
            pass

    def action_fake_res(self, name, rename):
        if self.endpoint != FAKE_URL:
            raise FakeException()
        for res in FAKE_RESOURCES:
            if res['name'] == name:
                res['name'] = rename
                break


class FakeResHandle(resource_handle.ResourceHandle):
    def _get_client(self, cxt):
        return FakeClient(self.endpoint_url)

    def handle_list(self, cxt, resource, filters):
        try:
            cli = self._get_client(cxt)
            return cli.list_fake_res(
                resource_handle._transform_filters(filters))
        except FakeException:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable(FAKE_TYPE, cli.endpoint)

    def handle_create(self, cxt, resource, name):
        try:
            cli = self._get_client(cxt)
            return cli.create_fake_res(name)
        except FakeException:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable(FAKE_TYPE, cli.endpoint)

    def handle_delete(self, cxt, resource, name):
        try:
            cli = self._get_client(cxt)
            cli.delete_fake_res(name)
        except FakeException:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable(FAKE_TYPE, cli.endpoint)

    def handle_action(self, cxt, resource, action, name, rename):
        try:
            cli = self._get_client(cxt)
            cli.action_fake_res(name, rename)
        except FakeException:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable(FAKE_TYPE, cli.endpoint)


class ClientTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()

        site_dict = {
            'site_id': FAKE_SITE_ID,
            'site_name': FAKE_SITE_NAME,
            'az_id': FAKE_AZ
        }
        config_dict = {
            'service_id': FAKE_SERVICE_ID,
            'site_id': FAKE_SITE_ID,
            'service_type': FAKE_TYPE,
            'service_url': FAKE_URL
        }
        models.create_site(self.context, site_dict)
        models.create_site_service_configuration(self.context, config_dict)

        global FAKE_RESOURCES
        FAKE_RESOURCES = [{'name': 'res1'}, {'name': 'res2'}]

        cfg.CONF.set_override(name='top_site_name', override=FAKE_SITE_NAME,
                              group='client')
        self.client = client.Client()
        self.client.resource_service_map[FAKE_RESOURCE] = FAKE_TYPE
        self.client.operation_resources_map['list'].add(FAKE_RESOURCE)
        self.client.operation_resources_map['create'].add(FAKE_RESOURCE)
        self.client.operation_resources_map['delete'].add(FAKE_RESOURCE)
        self.client.operation_resources_map['action'].add(FAKE_RESOURCE)
        self.client.service_handle_map[FAKE_TYPE] = FakeResHandle(None)

    def test_list(self):
        resources = self.client.list_resources(
            FAKE_RESOURCE, self.context, [])
        self.assertEqual(resources, [{'name': 'res1'}, {'name': 'res2'}])

    def test_list_with_filters(self):
        resources = self.client.list_resources(
            FAKE_RESOURCE, self.context, [{'key': 'name',
                                           'comparator': 'eq',
                                           'value': 'res2'}])
        self.assertEqual(resources, [{'name': 'res2'}])

    def test_create(self):
        resource = self.client.create_resources(FAKE_RESOURCE, self.context,
                                                'res3')
        self.assertEqual(resource, {'name': 'res3'})
        resources = self.client.list_resources(FAKE_RESOURCE, self.context)
        self.assertEqual(resources, [{'name': 'res1'}, {'name': 'res2'},
                                     {'name': 'res3'}])

    def test_delete(self):
        self.client.delete_resources(FAKE_RESOURCE, self.context, 'res1')
        resources = self.client.list_resources(FAKE_RESOURCE, self.context)
        self.assertEqual(resources, [{'name': 'res2'}])

    def test_action(self):
        self.client.action_resources(FAKE_RESOURCE, self.context,
                                     'rename', 'res1', 'res3')
        resources = self.client.list_resources(FAKE_RESOURCE, self.context)
        self.assertEqual(resources, [{'name': 'res3'}, {'name': 'res2'}])

    def test_list_endpoint_not_found(self):
        cfg.CONF.set_override(name='auto_refresh_endpoint', override=False,
                              group='client')
        # delete the configuration so endpoint cannot be found
        models.delete_site_service_configuration(self.context, FAKE_SERVICE_ID)
        # auto refresh set to False, directly raise exception
        self.assertRaises(exception.EndpointNotFound,
                          self.client.list_resources,
                          FAKE_RESOURCE, self.context, [])

    def test_resource_not_supported(self):
        # no such resource
        self.assertRaises(exception.ResourceNotSupported,
                          self.client.list_resources,
                          'no_such_resource', self.context, [])
        # remove "create" entry for FAKE_RESOURCE
        self.client.operation_resources_map['create'].remove(FAKE_RESOURCE)
        # operation not supported
        self.assertRaises(exception.ResourceNotSupported,
                          self.client.create_resources,
                          FAKE_RESOURCE, self.context, [])

    def test_list_endpoint_not_found_retry(self):
        cfg.CONF.set_override(name='auto_refresh_endpoint', override=True,
                              group='client')
        # delete the configuration so endpoint cannot be found
        models.delete_site_service_configuration(self.context, FAKE_SERVICE_ID)

        self.client._get_admin_token = mock.Mock()
        self.client._get_endpoint_from_keystone = mock.Mock()
        self.client._get_endpoint_from_keystone.return_value = {
            FAKE_SITE_NAME: {FAKE_TYPE: FAKE_URL}
        }

        resources = self.client.list_resources(
            FAKE_RESOURCE, self.context, [])
        self.assertEqual(resources, [{'name': 'res1'}, {'name': 'res2'}])

    def test_list_endpoint_not_unique(self):
        # add a new configuration with same site and service type
        config_dict = {
            'service_id': FAKE_SERVICE_ID + '_new',
            'site_id': FAKE_SITE_ID,
            'service_type': FAKE_TYPE,
            'service_url': FAKE_URL
        }
        models.create_site_service_configuration(self.context, config_dict)
        self.assertRaises(exception.EndpointNotUnique,
                          self.client.list_resources,
                          FAKE_RESOURCE, self.context, [])

    def test_list_endpoint_not_valid(self):
        cfg.CONF.set_override(name='auto_refresh_endpoint', override=False,
                              group='client')
        update_dict = {'service_url': FAKE_URL_INVALID}
        # update url to an invalid one
        models.update_site_service_configuration(self.context,
                                                 FAKE_SERVICE_ID,
                                                 update_dict)

        # auto refresh set to False, directly raise exception
        self.assertRaises(exception.EndpointNotAvailable,
                          self.client.list_resources,
                          FAKE_RESOURCE, self.context, [])

    def test_list_endpoint_not_valid_retry(self):
        cfg.CONF.set_override(name='auto_refresh_endpoint', override=True,
                              group='client')
        update_dict = {'service_url': FAKE_URL_INVALID}
        # update url to an invalid one
        models.update_site_service_configuration(self.context,
                                                 FAKE_SERVICE_ID,
                                                 update_dict)

        self.client._get_admin_token = mock.Mock()
        self.client._get_endpoint_from_keystone = mock.Mock()
        self.client._get_endpoint_from_keystone.return_value = {
            FAKE_SITE_NAME: {FAKE_TYPE: FAKE_URL}
        }

        resources = self.client.list_resources(
            FAKE_RESOURCE, self.context, [])
        self.assertEqual(resources, [{'name': 'res1'}, {'name': 'res2'}])

    def test_update_endpoint_from_keystone(self):
        self.client._get_admin_token = mock.Mock()
        self.client._get_endpoint_from_keystone = mock.Mock()
        self.client._get_endpoint_from_keystone.return_value = {
            FAKE_SITE_NAME: {FAKE_TYPE: FAKE_URL,
                             'another_fake_type': 'http://127.0.0.1:34567'},
            'not_registered_site': {FAKE_TYPE: FAKE_URL}
        }
        models.create_site_service_configuration = mock.Mock()
        models.update_site_service_configuration = mock.Mock()
        uuid.uuid4 = mock.Mock()
        uuid.uuid4.return_value = 'another_fake_service_id'

        self.client.update_endpoint_from_keystone(self.context)
        update_dict = {'service_url': FAKE_URL}
        create_dict = {'service_id': 'another_fake_service_id',
                       'site_id': FAKE_SITE_ID,
                       'service_type': 'another_fake_type',
                       'service_url': 'http://127.0.0.1:34567'}
        # not registered site is skipped
        models.update_site_service_configuration.assert_called_once_with(
            self.context, FAKE_SERVICE_ID, update_dict)
        models.create_site_service_configuration.assert_called_once_with(
            self.context, create_dict)

    def test_get_endpoint(self):
        cfg.CONF.set_override(name='auto_refresh_endpoint', override=False,
                              group='client')
        url = self.client.get_endpoint(self.context, FAKE_SITE_ID, FAKE_TYPE)
        self.assertEqual(url, FAKE_URL)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
