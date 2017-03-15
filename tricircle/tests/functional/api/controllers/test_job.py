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

import copy
from mock import patch
from oslo_config import cfg
from oslo_config import fixture as fixture_config
from oslo_utils import timeutils
from oslo_utils import uuidutils
from six.moves import xrange

import pecan
from pecan.configuration import set_config
from pecan.testing import load_test_app

from tricircle.api import app
from tricircle.common import constants
from tricircle.common import context
from tricircle.common import policy
from tricircle.common import xrpcapi
from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.db import models
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
            },
        }

        return load_test_app(self.config)

    def tearDown(self):
        super(API_FunctionalTest, self).tearDown()
        cfg.CONF.unregister_opts(app.common_opts)
        pecan.set_config({}, overwrite=True)
        core.ModelBase.metadata.drop_all(core.get_engine())
        policy.reset()


class TestAsyncJobController(API_FunctionalTest):
    """Test version listing on root URI."""

    def setUp(self):
        super(TestAsyncJobController, self).setUp()
        self.job_resource_map = constants.job_resource_map
        self.all_job_types = list(self.job_resource_map.keys())

    def fake_new_job(context, project_id, type, resource_id):
        raise Exception

    def fake_invoke_method(self, context, project_id, method, type, id):
        db_api.new_job(context, project_id, type, id)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_no_input(self):
        job = self._prepare_job_element(constants.JT_CONFIGURE_ROUTE)

        jobs = [
            # missing job
            {
                "job_xxx": job,
                "expected_error": 400
            },
        ]

        for test_job in jobs:
            response = self.app.post_json(
                '/v1.0/jobs',
                dict(job_xxx=test_job['job_xxx']),
                expect_errors=True)

            self.assertEqual(response.status_int,
                             test_job['expected_error'])

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(db_api, 'new_job',
                  new=fake_new_job)
    def test_post_exception(self):
        job = self._prepare_job_element(constants.JT_CONFIGURE_ROUTE)

        jobs = [
            {
                "job": job,
                "expected_error": 500
            },
        ]
        self._test_and_check(jobs)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    def test_post_invalid_input(self):
        for job_type in self.all_job_types:
            job = self._prepare_job_element(job_type)

            # wrong job type parameter: no job type is provided
            job_1 = copy.deepcopy(job)
            job_1.pop('type')

            # wrong job type parameter: job type is empty
            job_2 = copy.deepcopy(job)
            job_2['type'] = ''

            # wrong job type parameter: job type is wrong
            job_3 = copy.deepcopy(job)
            job_3['type'] = job['type'] + '_1'

            # wrong resource parameter: no resource is provided
            job_4 = copy.deepcopy(job)
            job_4.pop('resource')

            # wrong resource parameter: lack of necessary resource
            job_5 = copy.deepcopy(job)
            job_5['resource'].popitem()

            # wrong resource parameter: redundant resource
            job_6 = copy.deepcopy(job)
            job_6['resource']['fake_resource'] = 'fake_resource'

            # wrong project id parameter: no project id is provided
            job_7 = copy.deepcopy(job)
            job_7.pop('project_id')

            # wrong project id parameter: project id is empty
            job_8 = copy.deepcopy(job)
            job_8['project_id'] = ''

            # wrong project id parameter: project is not the
            # owner of resource
            job_9 = copy.deepcopy(job)
            job_9['project_id'] = uuidutils.generate_uuid()

            jobs = [
                {
                    "job": job_1,
                    "expected_error": 400
                },
                {
                    "job": job_2,
                    "expected_error": 400
                },
                {
                    "job": job_3,
                    "expected_error": 400
                },
                {
                    "job": job_4,
                    "expected_error": 400
                },
                {
                    "job": job_5,
                    "expected_error": 400
                },
                {
                    "job": job_6,
                    "expected_error": 400
                },
                {
                    "job": job_7,
                    "expected_error": 400
                },
                {
                    "job": job_8,
                    "expected_error": 400
                },
                {
                    "job": job_9,
                    "expected_error": 400
                },
            ]

            self._test_and_check(jobs)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(xrpcapi.XJobAPI, 'invoke_method',
                  new=fake_invoke_method)
    def test_post_job(self):
        for job_type in self.all_job_types:
            job = self._prepare_job_element(job_type)

            jobs = [
                # create an entirely new job
                {
                    "job": job,
                    "expected_error": 200
                },
                # target job already exists in the job table and its status
                # is NEW, then this newer job will be picked by job handler.
                {
                    "job": job,
                    "expected_error": 200
                },
            ]

            self._test_and_check(jobs)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(xrpcapi.XJobAPI, 'invoke_method',
                  new=fake_invoke_method)
    def test_get_one_and_get_all(self):
        all_job_ids = {}
        all_job_project_ids = {}

        index = 0
        for job_type in self.all_job_types:
            job = self._prepare_job_element(job_type)

            jobs = [
                {
                    "job": job,
                    "expected_error": 200
                },
            ]

            self._test_and_check(jobs)

            response = self.app.get('/v1.0/jobs')
            return_job = response.json

            all_job_ids[index] = return_job['jobs'][index]['id']
            all_job_project_ids[job_type] = (
                return_job['jobs'][index]['project_id'])

            index = index + 1

        service_uris = ['jobs', 'jobs/detail']
        amount_of_all_jobs = len(self.all_job_types)
        # with no filters all jobs are returned
        for service_uri in service_uris:
            response_1 = self.app.get('/v1.0/%(service_uri)s' % {
                'service_uri': service_uri})
            return_jobs_1 = response_1.json

            self.assertEqual(amount_of_all_jobs, len(return_jobs_1['jobs']))
            self.assertIn('status', response_1)
            self.assertIn('resource', response_1)
            self.assertIn('project_id', response_1)
            self.assertIn('id', response_1)
            self.assertIn('timestamp', response_1)
            self.assertIn('type', response_1)

            self.assertNotIn('extra_id', response_1)
            self.assertNotIn('resource_id', response_1)

        # use job status filter
        response_2 = self.app.get('/v1.0/jobs?status=new')
        return_jobs_2 = response_2.json

        self.assertEqual(amount_of_all_jobs, len(return_jobs_2['jobs']))

        response = self.app.get('/v1.0/jobs?status=fail')
        return_jobs_3 = response.json

        self.assertEqual(0, len(return_jobs_3['jobs']))

        amount_of_fail_jobs = int(amount_of_all_jobs / 3)
        for i in xrange(amount_of_fail_jobs):
            db_api.finish_job(self.context,
                              all_job_ids[i], False,
                              timeutils.utcnow())

        amount_of_succ_jobs = int(amount_of_all_jobs / 3)
        for i in xrange(amount_of_succ_jobs):
            db_api.finish_job(self.context,
                              all_job_ids[amount_of_fail_jobs + i], True,
                              timeutils.utcnow())

        for service_uri in service_uris:
            response = self.app.get('/v1.0/%(service_uri)s?status=fail' % {
                'service_uri': service_uri})
            return_jobs = response.json

            self.assertEqual(amount_of_fail_jobs, len(return_jobs['jobs']))

            response = self.app.get('/v1.0/%(service_uri)s?status=success'
                                    '' % {'service_uri': service_uri})
            return_jobs = response.json

            self.assertEqual(amount_of_succ_jobs, len(return_jobs['jobs']))

            # use job type filter or project id filter
            for job_type in self.all_job_types:
                response = self.app.get('/v1.0/%(service_uri)s?type=%(type)s'
                                        '' % {'service_uri': service_uri,
                                              'type': job_type})
                return_job = response.json

                self.assertEqual(1, len(return_job['jobs']))

                response = self.app.get(
                    '/v1.0/%(service_uri)s?project_id=%(project_id)s' % {
                        'service_uri': service_uri,
                        'project_id': all_job_project_ids[job_type]})
                return_job = response.json

                self.assertEqual(1, len(return_job['jobs']))

                # combine job type filter and project id filter
                response = self.app.get(
                    '/v1.0/%(service_uri)s?project_id=%(project_id)s&'
                    'type=%(type)s' % {
                        'service_uri': service_uri,
                        'project_id': all_job_project_ids[job_type],
                        'type': job_type})
                return_job = response.json

                self.assertEqual(1, len(return_job['jobs']))

            # combine job type filter, project id filter and job status filter
            for i in xrange(amount_of_all_jobs):
                if i < amount_of_fail_jobs:
                    # this aims to test service "/v1.0/jobs/{id}"
                    response_1 = self.app.get('/v1.0/jobs/%(id)s' % {
                        'id': all_job_ids[i]})
                    return_job_1 = response_1.json

                    response_2 = self.app.get(
                        '/v1.0/%(service_uri)s?'
                        'project_id=%(project_id)s&'
                        'type=%(type)s&'
                        'status=%(status)s' % {
                            'service_uri': service_uri,
                            'project_id': return_job_1['job']['project_id'],
                            'type': return_job_1['job']['type'],
                            'status': 'fail'})

                    return_job_2 = response_2.json

                    self.assertEqual(1, len(return_job_2['jobs']))

                elif ((i >= amount_of_fail_jobs
                       ) and (i < amount_of_fail_jobs + amount_of_succ_jobs)):
                    # those jobs are set to 'success' and they are moved to
                    # job log. their job ids are not stored in all_job_ids
                    job_type = self.all_job_types[i]
                    response = self.app.get(
                        '/v1.0/%(service_uri)s?project_id=%(project_id)s&'
                        'type=%(type)s&status=%(status)s' % {
                            'service_uri': service_uri,
                            'project_id': all_job_project_ids[job_type],
                            'type': job_type,
                            'status': 'success'})

                    return_job = response.json

                    self.assertEqual(1, len(return_job['jobs']))

                    response_2 = self.app.get(
                        '/v1.0/%(service_uri)s?status=%(status)s'
                        '&type=%(type)s' % {
                            'service_uri': service_uri,
                            'status': "success-x",
                            'type': job_type})
                    return_job_2 = response_2.json
                    self.assertEqual(0, len(return_job_2['jobs']))

                else:
                    response_1 = self.app.get('/v1.0/jobs/%(id)s' % {
                        'id': all_job_ids[i]})
                    return_job_1 = response_1.json

                    response_2 = self.app.get(
                        '/v1.0/%(service_uri)s?project_id=%(project_id)s&'
                        'type=%(type)s&status=%(status)s' % {
                            'service_uri': service_uri,
                            'project_id': return_job_1['job']['project_id'],
                            'type': return_job_1['job']['type'],
                            'status': 'new'})

                    return_job_2 = response_2.json

                    self.assertEqual(1, len(return_job_2['jobs']))

                    response_3 = self.app.get(
                        '/v1.0/%(service_uri)s?status=%(status)s'
                        '&type=%(type)s' % {
                            'service_uri': service_uri,
                            'status': "new-x",
                            'type': return_job_1['job']['type']})
                    return_job_3 = response_3.json
                    self.assertEqual(0, len(return_job_3['jobs']))

            # use unsupported filter, it will raise 400 error
            response = self.app.get('/v1.0/%(service_uri)s?'
                                    'fake_filter=%(fake_filter)s'
                                    '' % {'service_uri': service_uri,
                                          'fake_filter': "fake_filter"},
                                    expect_errors=True)

            self.assertEqual(response.status_int, 400)

            # use invalid filter, it will return empty set
            response = self.app.get('/v1.0/%(service_uri)s?status=%(status)s'
                                    '' % {'service_uri': service_uri,
                                          'status': "new-x"})
            return_job = response.json
            self.assertEqual(0, len(return_job['jobs']))

        @patch.object(context, 'extract_context_from_environ',
                      new=fake_admin_context)
        def test_get_job_schemas(self):
            response = self.app.get('/v1.0/jobs/schemas')
            return_job_schemas = response.json

            job_schemas = []
            for job_type in self.all_job_types:
                job = {}
                resource = []
                for resource_type, resource_id in (
                        self.job_resource_map[job_type]):
                    resource.append(resource_id)
                job['resource'] = resource
                job['type'] = job_type
                job_schemas.append(job)

            self.assertEqual(job_schemas, return_job_schemas['schemas'])

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(xrpcapi.XJobAPI, 'invoke_method',
                  new=fake_invoke_method)
    def test_delete_job(self):

        for job_type in self.all_job_types:
            job = self._prepare_job_element(job_type)

            jobs = [
                {
                    "job": job,
                    "expected_error": 200
                },
            ]

            self._test_and_check(jobs)

        response = self.app.get('/v1.0/jobs')
        return_job = response.json

        jobs = return_job['jobs']

        # delete a new job
        for job in jobs:
            response_1 = self.app.delete(
                '/v1.0/jobs/%(id)s' % {'id': job['id']},
                expect_errors=True)
            return_value_1 = response_1.json

            self.assertEqual(response_1.status_int, 200)
            self.assertEqual(return_value_1, {})

        response_2 = self.app.get('/v1.0/jobs')
        return_job_2 = response_2.json
        self.assertEqual(0, len(return_job_2['jobs']))

        response_3 = self.app.delete('/v1.0/jobs/123', expect_errors=True)
        self.assertEqual(response_3.status_int, 404)

        # delete a running job
        job_type_4 = constants.JT_NETWORK_UPDATE
        job_4 = self._prepare_job_element(job_type_4)
        resource_id_4 = '#'.join([job_4['resource'][resource_id]
                                  for resource_type, resource_id
                                  in self.job_resource_map[job_type_4]])
        job_running_4 = db_api.register_job(self.context,
                                            job_4['project_id'],
                                            job_type_4,
                                            resource_id_4)

        self.assertEqual(constants.JS_Running, job_running_4['status'])
        response_4 = self.app.delete('/v1.0/jobs/%(id)s' % {
            'id': job_running_4['id']}, expect_errors=True)

        self.assertEqual(response_4.status_int, 400)

        # delete a failed job
        job_type_5 = constants.JT_NETWORK_UPDATE
        job_5 = self._prepare_job_element(job_type_5)

        job_dict_5 = {
            "job": job_5,
            "expected_error": 200
        }

        response_5 = self.app.post_json('/v1.0/jobs',
                                        dict(job=job_dict_5['job']),
                                        expect_errors=True)
        return_job_5 = response_5.json

        self.assertEqual(response_5.status_int, 200)

        db_api.finish_job(self.context,
                          return_job_5['job']['id'],
                          False, timeutils.utcnow())

        job_fail_5 = db_api.get_job(self.context, return_job_5['job']['id'])
        self.assertEqual(constants.JS_Fail, job_fail_5['status'])
        response_6 = self.app.delete('/v1.0/jobs/%(id)s' % {
            'id': return_job_5['job']['id']}, expect_errors=True)

        self.assertEqual(response_6.status_int, 200)

        # delete a successful job
        job_type_6 = constants.JT_NETWORK_UPDATE
        job_6 = self._prepare_job_element(job_type_6)

        job_dict_6 = {
            "job": job_6,
            "expected_error": 200
        }

        response_6 = self.app.post_json('/v1.0/jobs',
                                        dict(job=job_dict_6['job']),
                                        expect_errors=True)
        return_job_6 = response_6.json

        with self.context.session.begin():
            job_dict = {'status': constants.JS_Success,
                        'timestamp': timeutils.utcnow(),
                        'extra_id': uuidutils.generate_uuid()}
            core.update_resource(self.context, models.AsyncJob,
                                 return_job_6['job']['id'], job_dict)

        job_succ_6 = db_api.get_job(self.context, return_job_6['job']['id'])
        self.assertEqual(constants.JS_Success, job_succ_6['status'])
        response_7 = self.app.delete('/v1.0/jobs/%(id)s' % {
            'id': return_job_6['job']['id']}, expect_errors=True)

        self.assertEqual(response_7.status_int, 200)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_admin_context)
    @patch.object(xrpcapi.XJobAPI, 'invoke_method',
                  new=fake_invoke_method)
    def test_redo_job(self):

        for job_type in self.all_job_types:
            job = self._prepare_job_element(job_type)

            jobs = [
                # create an entirely new job
                {
                    "job": job,
                    "expected_error": 200
                },
            ]

            self._test_and_check(jobs)

        response = self.app.get('/v1.0/jobs')
        return_job = response.json

        jobs = return_job['jobs']

        # redo a new job
        for job in jobs:
            response_1 = self.app.put('/v1.0/jobs/%(id)s' % {'id': job['id']},
                                      expect_errors=True)

            self.assertEqual(response_1.status_int, 200)

        response_2 = self.app.put('/v1.0/jobs/123', expect_errors=True)
        self.assertEqual(response_2.status_int, 404)

        # redo a running job
        job_type_3 = constants.JT_NETWORK_UPDATE
        job_3 = self._prepare_job_element(job_type_3)
        resource_id_3 = '#'.join([job_3['resource'][resource_id]
                                  for resource_type, resource_id
                                  in self.job_resource_map[job_type_3]])
        job_running_3 = db_api.register_job(self.context,
                                            job_3['project_id'],
                                            job_type_3,
                                            resource_id_3)

        self.assertEqual(constants.JS_Running, job_running_3['status'])
        response_3 = self.app.put('/v1.0/jobs/%(id)s' % {
            'id': job_running_3['id']}, expect_errors=True)

        self.assertEqual(response_3.status_int, 400)

        # redo a failed job
        job_type_4 = constants.JT_NETWORK_UPDATE
        job_4 = self._prepare_job_element(job_type_4)

        job_dict_4 = {
            "job": job_4,
            "expected_error": 200
        }

        response_4 = self.app.post_json('/v1.0/jobs',
                                        dict(job=job_dict_4['job']),
                                        expect_errors=True)
        return_job_4 = response_4.json

        self.assertEqual(response_4.status_int, 200)

        db_api.finish_job(self.context,
                          return_job_4['job']['id'],
                          False, timeutils.utcnow())

        job_fail_4 = db_api.get_job(self.context, return_job_4['job']['id'])
        self.assertEqual(constants.JS_Fail, job_fail_4['status'])
        response_5 = self.app.put('/v1.0/jobs/%(id)s' % {
            'id': return_job_4['job']['id']}, expect_errors=True)

        self.assertEqual(response_5.status_int, 200)

        # redo a successful job
        job_type_6 = constants.JT_NETWORK_UPDATE
        job_6 = self._prepare_job_element(job_type_6)

        job_dict_6 = {
            "job": job_6,
            "expected_error": 200
        }

        response_6 = self.app.post_json('/v1.0/jobs',
                                        dict(job=job_dict_6['job']),
                                        expect_errors=True)
        return_job_6 = response_6.json

        with self.context.session.begin():
            job_dict = {'status': constants.JS_Success,
                        'timestamp': timeutils.utcnow(),
                        'extra_id': uuidutils.generate_uuid()}
            core.update_resource(self.context, models.AsyncJob,
                                 return_job_6['job']['id'], job_dict)

        job_succ_6 = db_api.get_job(self.context, return_job_6['job']['id'])
        self.assertEqual(constants.JS_Success, job_succ_6['status'])
        response_7 = self.app.put('/v1.0/jobs/%(id)s' % {
            'id': return_job_6['job']['id']}, expect_errors=True)

        self.assertEqual(response_7.status_int, 400)

    @patch.object(context, 'extract_context_from_environ',
                  new=fake_non_admin_context)
    def test_non_admin_action(self):
        job_type = constants.JT_NETWORK_UPDATE
        job = self._prepare_job_element(job_type)

        jobs = [
            {
                "job": job,
                "expected_error": 403
            },
        ]
        self._test_and_check(jobs)

        response_1 = self.app.get('/v1.0/jobs/1234567890',
                                  expect_errors=True)
        self.assertEqual(response_1.status_int, 403)

        response_2 = self.app.get('/v1.0/jobs',
                                  expect_errors=True)
        self.assertEqual(response_2.status_int, 403)

        response_3 = self.app.delete('/v1.0/jobs/1234567890',
                                     expect_errors=True)
        self.assertEqual(response_3.status_int, 403)

        response_4 = self.app.put('/v1.0/jobs/1234567890',
                                  expect_errors=True)
        self.assertEqual(response_4.status_int, 403)

    def _test_and_check(self, jobs):

        for test_job in jobs:
            response = self.app.post_json(
                '/v1.0/jobs', dict(job=test_job['job']),
                expect_errors=True)
            self.assertEqual(response.status_int, test_job['expected_error'])

    def _prepare_job_element(self, job_type):
        # in order to create a job, we need three elements: job type,
        # job resource and project id.
        job = {}
        job['resource'] = {}
        job['type'] = job_type

        for resource_type, resource_id in self.job_resource_map[job_type]:
            job['resource'][resource_id] = uuidutils.generate_uuid()

        job['project_id'] = self._prepare_project_id_for_job(job)

        return job

    def _prepare_project_id_for_job(self, job):
        # prepare the project id for job creation, currently job parameter
        # contains job type and job resource information.
        job_type = job['type']
        if job_type == constants.JT_SEG_RULE_SETUP:
            project_id = job['resource']['project_id']
        else:
            project_id = uuidutils.generate_uuid()
            pod_id = uuidutils.generate_uuid()

            resource_type, resource_id = (
                constants.job_primary_resource_map[job_type])
            routing = db_api.create_resource_mapping(
                self.context, job['resource'][resource_id],
                job['resource'][resource_id], pod_id, project_id,
                resource_type)
            self.assertIsNotNone(routing)

        return project_id

    def _validate_error_code(self, res, code):
        self.assertEqual(res[list(res.keys())[0]]['code'], code)
