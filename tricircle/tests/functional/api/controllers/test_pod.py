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
import pecan
from pecan.configuration import set_config
from pecan.testing import load_test_app

from oslo_config import cfg
from oslo_config import fixture as fixture_config
import oslo_db.exception as db_exc

from tricircle.api import app
from tricircle.common import az_ag
from tricircle.common import context
from tricircle.common import policy
from tricircle.common import utils
from tricircle.db import core
from tricircle.tests import base


OPT_GROUP_NAME = 'keystone_authtoken'
cfg.CONF.import_group(OPT_GROUP_NAME, "keystonemiddleware.auth_token")


def fake_admin_context():
    context_paras = {'is_admin': True}
    return context.Context(**context_paras)


def fake_non_admin_context():
    context_paras = {}
    return context.Context(**context_paras)


class API_FunctionalTest(base.TestCase):

    def setUp(self):
        super(API_FunctionalTest, self).setUp()

        self.addCleanup(set_config, {}, overwrite=True)

        cfg.CONF.clear()
        cfg.CONF.register_opts(app.common_opts)

        self.CONF = self.useFixture(fixture_config.Config()).conf

        self.CONF.set_override('auth_strategy', 'noauth')
        self.CONF.set_override('tricircle_db_connection', 'sqlite:///:memory:')

        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())

        self.context = context.get_admin_context()

        policy.populate_default_rules()

        self.app = self._make_app()

    def _make_app(self, enable_acl=False):
        self.config = {
            'app': {
                'root': 'tricircle.api.controllers.root.RootController',
                'modules': ['tricircle.api'],
                'enable_acl': enable_acl,
                'errors': {
                    400: '/error',
                    '__force_dict__': True
                }
            },
        }

        return load_test_app(self.config)

    def tearDown(self):
        super(API_FunctionalTest, self).tearDown()
        cfg.CONF.unregister_opts(app.common_opts)
        pecan.set_config({}, overwrite=True)
        core.ModelBase.metadata.drop_all(core.get_engine())
        policy.reset()


class TestPodController(API_FunctionalTest):
    """Test version listing on root URI."""

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_no_input(self):
        pods = [
            # missing pod
            {
                "pod_xxx":
                {
                    "dc_name": "dc1",
                    "pod_az_name": "az1"
                },
                "expected_error": 400
            }]

        for test_pod in pods:
            response = self.app.post_json(
                '/v1.0/pods',
                dict(pod_xxx=test_pod['pod_xxx']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_pod['expected_error'])

    def fake_create_ag_az(context, ag_name, az_name):
        raise db_exc.DBDuplicateEntry

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(az_ag, 'create_ag_az',
                  new=fake_create_ag_az)
    def test_post_dup_db_exception(self):
        pods = [
            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "AZ1"
                },
                "expected_error": 409
            },
            ]

        self._test_and_check(pods)

    def fake_create_ag_az_exp(context, ag_name, az_name):
        raise Exception

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(core, 'create_resource',
                  new=fake_create_ag_az_exp)
    def test_post_exception(self):
        pods = [
            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "AZ1"
                },
                "expected_error": 500
            },
            ]

        self._test_and_check(pods)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_invalid_input(self):

        pods = [

            # missing az and pod
            {
                "pod":
                {
                    "dc_name": "dc1",
                    "pod_az_name": "az1"
                },
                "expected_error": 422
            },

            # missing pod
            {
                "pod":
                {
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "az1"
                },
                "expected_error": 422
            },

            # missing pod
            {
                "pod":
                {
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "",
                },
                "expected_error": 422
            },

            # missing az
            {
                "pod":
                {
                    "pod_name": "",
                    "pod_az_name": "az1",
                    "dc_name": "dc1"
                },
                "expected_error": 422
            },

            # az & pod == ""
            {
                "pod":
                {
                    "pod_name": "",
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": ""
                },
                "expected_error": 422
            },

            # invalid pod
            {
                "pod":
                {
                    "pod_name": "",
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "az1"

                },
                "expected_error": 422
            }

            ]

        self._test_and_check(pods)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_duplicate_top_region(self):

        pods = [

            # the first time to create TopRegion
            {
                "pod":
                {
                    "pod_name": "TopRegion",
                    "pod_az_name": "az1",
                    "dc_name": "dc1"
                },
                "expected_error": 200
            },

            {
                "pod":
                {
                    "pod_name": "TopRegion2",
                    "pod_az_name": "",
                    "dc_name": "dc1"
                },
                "expected_error": 409
            },

            ]

        self._test_and_check(pods)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_duplicate_pod(self):

        pods = [

            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc1",
                    "az_name": "AZ1"
                },
                "expected_error": 200
            },

            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az2",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 409
            },

            ]

        self._test_and_check(pods)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_pod_duplicate_top_region(self):

        pods = [

            # the first time to create TopRegion
            {
                "pod":
                {
                    "pod_name": "TopRegion",
                    "pod_az_name": "az1",
                    "dc_name": "dc1"
                },
                "expected_error": 200
            },

            {
                "pod":
                {
                    "pod_name": "TopRegion",
                    "pod_az_name": "az2",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 409
            },

            ]

        self._test_and_check(pods)

    def _test_and_check(self, pods):

        for test_pod in pods:
            response = self.app.post_json(
                '/v1.0/pods',
                dict(pod=test_pod['pod']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_pod['expected_error'])

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_get_all(self):

        pods = [

            # the first time to create TopRegion
            {
                "pod":
                {
                    "pod_name": "TopRegion",
                    "pod_az_name": "",
                    "dc_name": "dc1",
                    "az_name": ""
                },
                "expected_error": 200
            },

            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 200
            },

            {
                "pod":
                {
                    "pod_name": "Pod2",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 200
            },

            ]

        self._test_and_check(pods)

        response = self.app.get('/v1.0/pods')

        self.assertEqual(response.status_int, 200)
        self.assertIn('TopRegion', response)
        self.assertIn('Pod1', response)
        self.assertIn('Pod2', response)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_get_delete_one(self):

        pods = [

            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 200,
            },

            {
                "pod":
                {
                    "pod_name": "Pod2",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 200,
            },

            {
                "pod":
                {
                    "pod_name": "Pod3",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ2"
                },
                "expected_error": 200,
            },

            ]

        self._test_and_check(pods)

        response = self.app.get('/v1.0/pods')
        self.assertEqual(response.status_int, 200)

        return_pods = response.json

        for ret_pod in return_pods['pods']:

            _id = ret_pod['pod_id']
            single_ret = self.app.get('/v1.0/pods/' + str(_id))

            self.assertEqual(single_ret.status_int, 200)

            one_pod_ret = single_ret.json
            get_one_pod = one_pod_ret['pod']

            self.assertEqual(get_one_pod['pod_id'],
                             ret_pod['pod_id'])

            self.assertEqual(get_one_pod['pod_name'],
                             ret_pod['pod_name'])

            self.assertEqual(get_one_pod['pod_az_name'],
                             ret_pod['pod_az_name'])

            self.assertEqual(get_one_pod['dc_name'],
                             ret_pod['dc_name'])

            self.assertEqual(get_one_pod['az_name'],
                             ret_pod['az_name'])

            _id = ret_pod['pod_id']

            # check ag and az automaticly added
            ag_name = utils.get_ag_name(ret_pod['pod_name'])
            ag = az_ag.get_ag_by_name(self.context, ag_name)
            self.assertIsNotNone(ag)
            self.assertEqual(ag['name'],
                             utils.get_ag_name(ret_pod['pod_name']))
            self.assertEqual(ag['availability_zone'], ret_pod['az_name'])

            single_ret = self.app.delete('/v1.0/pods/' + str(_id))
            self.assertEqual(single_ret.status_int, 200)

            # make sure ag is deleted
            ag = az_ag.get_ag_by_name(self.context, ag_name)
            self.assertIsNone(ag)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_non_admin_context)
    def test_non_admin_action(self):

        pods = [
            {
                "pod":
                    {
                        "pod_name": "Pod1",
                        "pod_az_name": "az1",
                        "dc_name": "dc2",
                        "az_name": "AZ1"
                    },
                "expected_error": 401,
            },
        ]
        self._test_and_check(pods)

        response = self.app.get('/v1.0/pods/1234567890',
                                expect_errors=True)
        self.assertEqual(response.status_int, 401)

        response = self.app.get('/v1.0/pods',
                                expect_errors=True)
        self.assertEqual(response.status_int, 401)

        response = self.app.delete('/v1.0/pods/1234567890',
                                   expect_errors=True)
        self.assertEqual(response.status_int, 401)


class TestBindingController(API_FunctionalTest):
    """Test version listing on root URI."""

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_no_input(self):
        pod_bindings = [
            # missing pod_binding
            {
                "pod_xxx":
                {
                    "tenant_id": "dddddd",
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643"
                },
                "expected_error": 400
            }]

        for test_pod in pod_bindings:
            response = self.app.post_json(
                '/v1.0/bindings',
                dict(pod_xxx=test_pod['pod_xxx']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_pod['expected_error'])

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_invalid_input(self):

        pod_bindings = [

            # missing tenant_id and or az_pod_map_id
            {
                "pod_binding":
                {
                    "tenant_id": "dddddd",
                    "pod_id": ""
                },
                "expected_error": 422
            },

            {
                "pod_binding":
                {
                    "tenant_id": "",
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643"
                },
                "expected_error": 422
            },

            {
                "pod_binding":
                {
                    "tenant_id": "dddddd",
                },
                "expected_error": 422
            },

            {
                "pod_binding":
                {
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643"
                },
                "expected_error": 422
            }

            ]

        self._test_and_check(pod_bindings)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_bindings(self):

        pods = [
            {
                "pod":
                {
                    "pod_name": "Pod1",
                    "pod_az_name": "az1",
                    "dc_name": "dc2",
                    "az_name": "AZ1"
                },
                "expected_error": 200
            }
        ]

        pod_bindings = [

            {
                "pod_binding":
                {
                    "tenant_id": "dddddd",
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643",
                    "is_binding": "True"
                },
                "expected_error": 200
            },

            {
                "pod_binding":
                {
                    "tenant_id": "aaaaa",
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643",
                    "is_binding": "True"
                },
                "expected_error": 200
            },

            {
                "pod_binding":
                {
                    "tenant_id": "dddddd",
                    "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643"
                },
                "expected_error": 409
            }
        ]

        self._test_and_check_pod(pods)
        _id = self._get_az_pod_id()
        self._test_and_check(pod_bindings, _id)

        # get all
        response = self.app.get('/v1.0/bindings')
        self.assertEqual(response.status_int, 200)

        # get one
        return_pod_bindings = response.json

        for ret_pod in return_pod_bindings['pod_bindings']:

            _id = ret_pod['id']
            single_ret = self.app.get('/v1.0/bindings/' + str(_id))
            self.assertEqual(single_ret.status_int, 200)

            one_pot_ret = single_ret.json
            get_one_pod = one_pot_ret['pod_binding']

            self.assertEqual(get_one_pod['id'],
                             ret_pod['id'])

            self.assertEqual(get_one_pod['tenant_id'],
                             ret_pod['tenant_id'])

            self.assertEqual(get_one_pod['pod_id'],
                             ret_pod['pod_id'])

            _id = ret_pod['id']
            single_ret = self.app.delete('/v1.0/bindings/' + str(_id))
            self.assertEqual(single_ret.status_int, 200)

    def _get_az_pod_id(self):
        response = self.app.get('/v1.0/pods')
        self.assertEqual(response.status_int, 200)
        return_pods = response.json
        for ret_pod in return_pods['pods']:
            _id = ret_pod['pod_id']
            return _id

    def _test_and_check(self, pod_bindings, _id=None):

        for test_pod in pod_bindings:

            if _id is not None:
                test_pod['pod_binding']['pod_id'] = str(_id)

            response = self.app.post_json(
                '/v1.0/bindings',
                dict(pod_binding=test_pod['pod_binding']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_pod['expected_error'])

    def _test_and_check_pod(self, pods):

        for test_pod in pods:
            response = self.app.post_json(
                '/v1.0/pods',
                dict(pod=test_pod['pod']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_pod['expected_error'])

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_non_admin_context)
    def test_non_admin_action(self):
        pod_bindings = [
            {
                "pod_binding":
                    {
                        "tenant_id": "dddddd",
                        "pod_id": "0ace0db2-ef33-43a6-a150-42703ffda643"
                    },
                "expected_error": 401
            },
        ]

        self._test_and_check(pod_bindings)

        response = self.app.get('/v1.0/bindings/1234567890',
                                expect_errors=True)
        self.assertEqual(response.status_int, 401)

        response = self.app.get('/v1.0/bindings',
                                expect_errors=True)
        self.assertEqual(response.status_int, 401)

        response = self.app.delete('/v1.0/bindings/1234567890',
                                   expect_errors=True)
        self.assertEqual(response.status_int, 401)
