# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

from mock import patch
import urlparse

import pecan
from pecan.configuration import set_config
from pecan.testing import load_test_app

from requests import Response

from oslo_config import cfg
from oslo_config import fixture as fixture_config
from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from tricircle.cinder_apigw import app

from tricircle.common import constants as cons
from tricircle.common import context
from tricircle.common import httpclient as hclient

from tricircle.db import api as db_api
from tricircle.db import core

from tricircle.tests import base


OPT_GROUP_NAME = 'keystone_authtoken'
cfg.CONF.import_group(OPT_GROUP_NAME, "keystonemiddleware.auth_token")

FAKE_AZ = 'fake_az'
fake_volumes = []


def fake_volumes_forward_req(ctx, action, b_header, b_url, b_req_body):
    resp = Response()
    resp.status_code = 404

    parse = urlparse.urlsplit(b_url)
    if action == 'POST':
        b_body = jsonutils.loads(b_req_body)
        if b_body.get('volume'):
            vol = b_body['volume']
            vol['id'] = uuidutils.generate_uuid()
            stored_vol = {
                'volume': vol,
                'host': parse.hostname
            }
            fake_volumes.append(stored_vol)
            resp.status_code = 202
            vol_dict = {'volume': vol}

            resp._content = jsonutils.dumps(vol_dict)
            # resp.json = vol_dict
            return resp

    b_path = parse.path
    pos = b_path.rfind('/volumes')
    op = ''
    if pos > 0:
        op = b_path[pos:]
        op = op[len('/volumes'):]

    if action == 'GET':
        if op == '' or op == '/detail':
            tenant_id = b_path[:pos]
            pos2 = tenant_id.rfind('/')
            if pos2 > 0:
                tenant_id = tenant_id[(pos2 + 1):]
            else:
                resp.status_code = 404
                return resp
            ret_vols = []
            cmp_host = parse.hostname
            for temp_vol in fake_volumes:
                if temp_vol['host'] != cmp_host:
                    continue

                if temp_vol['volume']['project_id'] == tenant_id:
                    ret_vols.append(temp_vol['volume'])

            vol_dicts = {'volumes': ret_vols}
            resp._content = jsonutils.dumps(vol_dicts)
            resp.status_code = 200
            return resp
        elif op != '':
            if op[0] == '/':
                _id = op[1:]
                for vol in fake_volumes:
                    if vol['volume']['id'] == _id:
                        vol_dict = {'volume': vol['volume']}
                        resp._content = jsonutils.dumps(vol_dict)
                        resp.status_code = 200
                        return resp
    if action == 'DELETE':
        if op != '':
            if op[0] == '/':
                _id = op[1:]
                for vol in fake_volumes:
                    if vol['volume']['id'] == _id:
                        fake_volumes.remove(vol)
                        resp.status_code = 202
                        return resp
    if action == 'PUT':
        b_body = jsonutils.loads(b_req_body)
        update_vol = b_body.get('volume', {})
        if op != '':
            if op[0] == '/':
                _id = op[1:]
                for vol in fake_volumes:
                    if vol['volume']['id'] == _id:
                        vol['volume'].update(update_vol)
                        vol_dict = {'volume': vol['volume']}
                        resp._content = jsonutils.dumps(vol_dict)
                        resp.status_code = 200
                        return resp
    else:
        resp.status_code = 404

    return resp


class CinderVolumeFunctionalTest(base.TestCase):

    def setUp(self):
        super(CinderVolumeFunctionalTest, self).setUp()

        self.addCleanup(set_config, {}, overwrite=True)

        cfg.CONF.register_opts(app.common_opts)

        self.CONF = self.useFixture(fixture_config.Config()).conf

        self.CONF.set_override('auth_strategy', 'noauth')

        self.app = self._make_app()

        self._init_db()

    def _make_app(self, enable_acl=False):
        self.config = {
            'app': {
                'root':
                    'tricircle.cinder_apigw.controllers.root.RootController',
                'modules': ['tricircle.cinder_apigw'],
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
            'service_type': cons.ST_CINDER,
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
        super(CinderVolumeFunctionalTest, self).tearDown()
        cfg.CONF.unregister_opts(app.common_opts)
        pecan.set_config({}, overwrite=True)
        core.ModelBase.metadata.drop_all(core.get_engine())
        del fake_volumes[:]


class TestVolumeController(CinderVolumeFunctionalTest):

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_post_error_case(self):

        volumes = [
            {
                "volume_xxx":
                {
                    "name": 'vol_1',
                    "size": 10,
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 400
            },

            # no AZ parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "size": 10,
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },

            # incorrect AZ parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "availability_zone": FAKE_AZ + FAKE_AZ,
                    "size": 10,
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 500
            },

            ]

        self._test_and_check(volumes, 'my_tenant_id')

    def fake_create_resource(context, ag_name, az_name):
        raise Exception

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    @patch.object(core, 'create_resource',
                  new=fake_create_resource)
    def test_post_exception(self):
        volumes = [
            # no 'volume' parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "availability_zone": FAKE_AZ,
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 500
            }
            ]

        self._test_and_check(volumes, 'my_tenant_id')

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_post_one_and_get_one(self):

        tenant1_volumes = [
            # normal volume with correct parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 10,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },

            # same tenant, multiple volumes
            {
                "volume":
                {
                    "name": 'vol_2',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 20,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },

            # same tenant, different az
            {
                "volume":
                {
                    "name": 'vol_3',
                    "availability_zone": FAKE_AZ + '2',
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 20,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },
            ]

        tenant2_volumes = [
            # different tenant, same az
            {
                "volume":
                {
                    "name": 'vol_4',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 20,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id_2',
                    "metadata": {}
                },
                "expected_error": 202
            },
            ]

        self._test_and_check(tenant1_volumes, 'my_tenant_id')
        self._test_and_check(tenant2_volumes, 'my_tenant_id_2')

        self._test_detail_check('my_tenant_id', 3)
        self._test_detail_check('my_tenant_id_2', 1)

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_post_one_and_delete_one(self):

        volumes = [
            # normal volume with correct parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 10,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },
        ]

        self._test_and_check_delete(volumes, 'my_tenant_id')

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_get(self):
        response = self.app.get('/v2/my_tenant_id/volumes')
        self.assertEqual(response.status_int, 200)
        json_body = jsonutils.loads(response.body)
        vols = json_body.get('volumes')
        self.assertEqual(0, len(vols))

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_get_all(self):
        update_dict = {'pod_az_name': 'fake_pod_az2'}
        # update pod2 to set pod_az_name
        db_api.update_pod(self.context, 'fake_pod_id2', update_dict)

        volumes = [
            # normal volume with correct parameter
            {
                "volume":
                {
                    "name": 'vol_1',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 10,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },

            # same tenant, multiple volumes
            {
                "volume":
                {
                    "name": 'vol_2',
                    "availability_zone": FAKE_AZ,
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 20,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },

            # same tenant, different az
            {
                "volume":
                {
                    "name": 'vol_3',
                    "availability_zone": FAKE_AZ + '2',
                    "source_volid": '',
                    "consistencygroup_id": '',
                    "snapshot_id": '',
                    "source_replica": '',
                    "size": 20,
                    "user_id": '',
                    "imageRef": '',
                    "attach_status": "detached",
                    "volume_type": '',
                    "project_id": 'my_tenant_id',
                    "metadata": {}
                },
                "expected_error": 202
            },
        ]
        tenant_id = 'my_tenant_id'
        for volume in volumes:
            self.app.post_json('/v2/' + tenant_id + '/volumes',
                               dict(volume=volume['volume']),
                               expect_errors=True)
        query_string = '?availability_zone=' + FAKE_AZ
        resp = self.app.get('/v2/' + tenant_id + '/volumes' + query_string)
        self.assertEqual(resp.status_int, 200)
        json_body = jsonutils.loads(resp.body)
        ret_vols = json_body.get('volumes')
        self.assertEqual(len(ret_vols), 2)

        query_string = '?availability_zone=' + FAKE_AZ + '2'
        resp = self.app.get('/v2/' + tenant_id + '/volumes' + query_string)
        self.assertEqual(resp.status_int, 200)
        json_body = jsonutils.loads(resp.body)
        ret_vols = json_body.get('volumes')
        self.assertEqual(len(ret_vols), 1)

    @patch.object(hclient, 'forward_req',
                  new=fake_volumes_forward_req)
    def test_put(self):
        volume = {
            "volume":
            {
                "name": 'vol_1',
                "availability_zone": FAKE_AZ,
                "source_volid": '',
                "consistencygroup_id": '',
                "snapshot_id": '',
                "source_replica": '',
                "size": 10,
                "user_id": '',
                "imageRef": '',
                "attach_status": "detached",
                "volume_type": '',
                "project_id": 'my_tenant_id',
                "metadata": {}
            },
            "expected_error": 202
        }

        tenant_id = 'my_tenant_id'
        resp = self.app.post_json('/v2/' + tenant_id + '/volumes',
                                  dict(volume=volume['volume']),
                                  expect_errors=True)
        volume_dict = jsonutils.loads(resp.body)
        volume_id = volume_dict['volume']['id']

        update_dict = {"volume": {"name": 'vol_2'}}
        resp = self.app.put_json('/v2/' + tenant_id + '/volumes/' + volume_id,
                                 dict(volume=update_dict['volume']),
                                 expect_errors=True)
        volume_dict = jsonutils.loads(resp.body)
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(volume_dict['volume']['name'], 'vol_2')

    def _test_and_check(self, volumes, tenant_id):
        for test_vol in volumes:
            if test_vol.get('volume'):
                response = self.app.post_json(
                    '/v2/' + tenant_id + '/volumes',
                    dict(volume=test_vol['volume']),
                    expect_errors=True)
            elif test_vol.get('volume_xxx'):
                response = self.app.post_json(
                    '/v2/' + tenant_id + '/volumes',
                    dict(volume_xxx=test_vol['volume_xxx']),
                    expect_errors=True)
            else:
                return

            self.assertEqual(response.status_int,
                             test_vol['expected_error'])

            if response.status_int == 202:
                json_body = jsonutils.loads(response.body)
                res_vol = json_body.get('volume')
                query_resp = self.app.get(
                    '/v2/' + tenant_id + '/volumes/' + res_vol['id'])
                self.assertEqual(query_resp.status_int, 200)
                json_body = jsonutils.loads(query_resp.body)
                query_vol = json_body.get('volume')

                self.assertEqual(res_vol['id'], query_vol['id'])
                self.assertEqual(res_vol['name'], query_vol['name'])
                self.assertEqual(res_vol['availability_zone'],
                                 query_vol['availability_zone'])
                self.assertIn(res_vol['availability_zone'],
                              [FAKE_AZ, FAKE_AZ + '2'])

    def _test_and_check_delete(self, volumes, tenant_id):
        for test_vol in volumes:
            if test_vol.get('volume'):
                response = self.app.post_json(
                    '/v2/' + tenant_id + '/volumes',
                    dict(volume=test_vol['volume']),
                    expect_errors=True)
            self.assertEqual(response.status_int,
                             test_vol['expected_error'])
            if response.status_int == 202:
                json_body = jsonutils.loads(response.body)
                _id = json_body.get('volume')['id']
                query_resp = self.app.get(
                    '/v2/' + tenant_id + '/volumes/' + _id)
                self.assertEqual(query_resp.status_int, 200)

                delete_resp = self.app.delete(
                    '/v2/' + tenant_id + '/volumes/' + _id)
                self.assertEqual(delete_resp.status_int, 202)

    def _test_detail_check(self, tenant_id, vol_size):
        resp = self.app.get(
            '/v2/' + tenant_id + '/volumes' + '/detail',
            expect_errors=True)
        self.assertEqual(resp.status_int, 200)
        json_body = jsonutils.loads(resp.body)
        ret_vols = json_body.get('volumes')
        self.assertEqual(len(ret_vols), vol_size)
