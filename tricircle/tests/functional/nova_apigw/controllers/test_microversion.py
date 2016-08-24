# Copyright (c) 2015 Huawei Tech. Co., Ltd.
# All Rights Reserved.
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
from novaclient import api_versions
from novaclient.v2 import client as n_client
import pecan
from pecan.configuration import set_config
from pecan.testing import load_test_app

from tricircle.common import constants
from tricircle.common import constants as cons
from tricircle.common import context
from tricircle.common import resource_handle
from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.nova_apigw import app
from tricircle.nova_apigw.controllers import server
from tricircle.tests import base

from oslo_config import cfg
from oslo_config import fixture as fixture_config

FAKE_AZ = 'fake_az'


def get_tricircle_client(self, pod):
    return FakeTricircleClient()


class FakeTricircleClient(object):

    def __init__(self):
        pass

    def list_servers(self, cxt, filters=None):
        handle = FakeNovaAPIGWResourceHandle()
        return handle.handle_list(cxt, 'server', filters)


class FakeNovaAPIGWResourceHandle(resource_handle.NovaResourceHandle):
    def __init__(self):
        self.auth_url = 'auth_url'
        self.endpoint_url = 'endpoint_url'

    def handle_list(self, cxt, resource, filters):
        super(FakeNovaAPIGWResourceHandle, self).handle_list(
            cxt, resource, filters)
        return []


class FakeNovaClient(object):
    def __init__(self):
        self.servers = FakeNovaServer()

    def set_management_url(self, url):
        pass


class FakeNovaServer(object):
    def __init__(self):
        pass

    def list(self, detailed=True, search_opts=None, marker=None, limit=None,
             sort_keys=None, sort_dirs=None):
        return []


class MicroVersionFunctionTest(base.TestCase):

    def setUp(self):
        super(MicroVersionFunctionTest, self).setUp()

        self.addCleanup(set_config, {}, overwrite=True)

        cfg.CONF.register_opts(app.common_opts)

        self.CONF = self.useFixture(fixture_config.Config()).conf

        self.CONF.set_override('auth_strategy', 'noauth')
        self.CONF.set_override('tricircle_db_connection', 'sqlite:///:memory:')

        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())

        self.app = self._make_app()

        self._init_db()

    def _make_app(self, enable_acl=False):
        self.config = {
            'app': {
                'root': 'tricircle.nova_apigw.controllers.root.RootController',
                'modules': ['tricircle.nova_apigw'],
                'enable_acl': enable_acl,
                'errors': {
                    400: '/error',
                    '__force_dict__': True
                }
            },
        }

        return load_test_app(self.config)

    def _init_db(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        # enforce foreign key constraint for sqlite
        core.get_engine().execute('pragma foreign_keys=on')
        self.context = context.Context()

        pod_dict = {
            'pod_id': 'fake_pod_id',
            'pod_name': 'fake_pod_name',
            'az_name': FAKE_AZ
        }

        config_dict = {
            'service_id': 'fake_service_id',
            'pod_id': 'fake_pod_id',
            'service_type': cons.ST_NOVA,
            'service_url': 'http://127.0.0.1:8774/v2/$(tenant_id)s'
        }

        pod_dict2 = {
            'pod_id': 'fake_pod_id' + '2',
            'pod_name': 'fake_pod_name' + '2',
            'az_name': FAKE_AZ + '2'
        }

        config_dict2 = {
            'service_id': 'fake_service_id' + '2',
            'pod_id': 'fake_pod_id' + '2',
            'service_type': cons.ST_CINDER,
            'service_url': 'http://10.0.0.2:8774/v2/$(tenant_id)s'
        }

        top_pod = {
            'pod_id': 'fake_top_pod_id',
            'pod_name': 'RegionOne',
            'az_name': ''
        }

        top_config = {
            'service_id': 'fake_top_service_id',
            'pod_id': 'fake_top_pod_id',
            'service_type': cons.ST_CINDER,
            'service_url': 'http://127.0.0.1:19998/v2/$(tenant_id)s'
        }

        db_api.create_pod(self.context, pod_dict)
        db_api.create_pod(self.context, pod_dict2)
        db_api.create_pod(self.context, top_pod)
        db_api.create_pod_service_configuration(self.context, config_dict)
        db_api.create_pod_service_configuration(self.context, config_dict2)
        db_api.create_pod_service_configuration(self.context, top_config)

    def tearDown(self):
        super(MicroVersionFunctionTest, self).tearDown()
        cfg.CONF.unregister_opts(app.common_opts)
        pecan.set_config({}, overwrite=True)
        core.ModelBase.metadata.drop_all(core.get_engine())


class MicroversionsTest(MicroVersionFunctionTest):

    min_version = constants.NOVA_APIGW_MIN_VERSION
    max_version = 'compute %s' % constants.NOVA_APIGW_MAX_VERSION
    lower_boundary = str(float(constants.NOVA_APIGW_MIN_VERSION) - 0.1)
    upper_boundary = 'compute %s' % str(
        float(constants.NOVA_APIGW_MAX_VERSION) + 0.1)
    vaild_version = 'compute 2.30'
    vaild_leagcy_version = '2.5'
    invaild_major = 'compute a.2'
    invaild_minor = 'compute 2.a'
    latest_version = 'compute 2.latest'
    invaild_compute_format = 'compute2.30'
    only_major = '2'
    invaild_major2 = '1.5'
    invaild_major3 = 'compute 3.2'
    invaild_version = '2.30'
    invaild_leagecy_version = 'compute 2.5'
    invaild_version2 = 'aa 2.30'
    invaild_version3 = 'compute 2.30 2.31'
    invaild_version4 = 'acompute 2.30'

    tenant_id = 'tenant_id'

    def _make_headers(self, version, type='current'):
        headers = {}
        headers['X_TENANT_ID'] = self.tenant_id
        if version is None:
            type = 'leagecy'
            version = constants.NOVA_APIGW_MIN_VERSION

        if type == 'both':
            headers[constants.NOVA_API_VERSION_REQUEST_HEADER] = version
            headers[constants.LEGACY_NOVA_API_VERSION_REQUEST_HEADER] = '2.5'
        elif type == 'current':
            headers[constants.NOVA_API_VERSION_REQUEST_HEADER] = version
        else:
            headers[constants.LEGACY_NOVA_API_VERSION_REQUEST_HEADER] = version

        return headers

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_no_header(self, mock_client):
        headers = self._make_headers(None)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(
                constants.NOVA_APIGW_MIN_VERSION),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_vaild_version(self, mock_client):
        headers = self._make_headers(self.vaild_version)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(self.vaild_version.split()[1]),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_vaild_leagcy_version(self, mock_client):
        headers = self._make_headers(self.vaild_leagcy_version, 'leagcy')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(self.vaild_leagcy_version),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_latest_version(self, mock_client):
        headers = self._make_headers(self.latest_version)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(
                constants.NOVA_APIGW_MAX_VERSION),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_min_version(self, mock_client):
        headers = self._make_headers(self.min_version, 'leagecy')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(self.min_version),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_max_version(self, mock_client):
        headers = self._make_headers(self.max_version)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers)
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(self.max_version.split()[1]),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_major(self, mock_client):
        headers = self._make_headers(self.invaild_major)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_major2(self, mock_client):
        headers = self._make_headers(self.invaild_major2, 'leagecy')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_major3(self, mock_client):
        headers = self._make_headers(self.invaild_major3)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_minor(self, mock_client):
        headers = self._make_headers(self.invaild_minor)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_lower_boundary(self, mock_client):
        headers = self._make_headers(self.lower_boundary)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_upper_boundary(self, mock_client):
        headers = self._make_headers(self.upper_boundary)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_compute_format(self, mock_client):
        headers = self._make_headers(self.invaild_compute_format)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_only_major(self, mock_client):
        headers = self._make_headers(self.only_major, 'leagecy')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_version(self, mock_client):
        headers = self._make_headers(self.invaild_version)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_leagecy_version(self, mock_client):
        headers = self._make_headers(self.invaild_leagecy_version, 'leagecy')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_both_version(self, mock_client):
        headers = self._make_headers(self.vaild_version, 'both')
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        self.app.get(url, headers=headers, expect_errors=True)
        # The new format microversion priority to leagecy
        mock_client.assert_called_with(
            api_version=api_versions.APIVersion(self.vaild_version.split()[1]),
            auth_token=None, auth_url='auth_url',
            direct_use=False, project_id=None,
            timeout=60, username=None, api_key=None)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_version2(self, mock_client):
        headers = self._make_headers(self.invaild_version2)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_version3(self, mock_client):
        headers = self._make_headers(self.invaild_version3)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)

    @mock.patch.object(server.ServerController, '_get_client',
                       new=get_tricircle_client)
    @mock.patch.object(n_client, 'Client')
    def test_microversions_invaild_version4(self, mock_client):
        headers = self._make_headers(self.invaild_version4)
        url = '/v2.1/' + self.tenant_id + '/servers/detail'
        mock_client.return_value = FakeNovaClient()
        res = self.app.get(url, headers=headers, expect_errors=True)
        self.assertEqual(406, res.status_int)
