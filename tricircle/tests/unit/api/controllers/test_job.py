# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
import mock
from mock import patch
from oslo_config import cfg
import oslo_db.exception as db_exc
from oslo_utils import timeutils
from oslo_utils import uuidutils
import re
from six.moves import xrange
import time

import pecan

from tricircle.api import app
from tricircle.api.controllers import job
from tricircle.common import constants
from tricircle.common import context
from tricircle.common import policy
from tricircle.common import xrpcapi
from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.tests import base


class FakeRPCAPI(xrpcapi.XJobAPI):
    def invoke_method(self, ctxt, project_id, method, _type, id):
        db_api.new_job(ctxt, project_id, _type, id)


class FakeAsyncJobController(job.AsyncJobController):
    def __init__(self):
        self.xjob_handler = FakeRPCAPI()


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


def mock_db_test_stub(i):
    if i == 0:
        raise db_exc.DBDeadlock


class AsyncJobControllerTest(base.TestCase):
    def setUp(self):
        super(AsyncJobControllerTest, self).setUp()

        cfg.CONF.clear()
        cfg.CONF.register_opts(app.common_opts)
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.controller = FakeAsyncJobController()
        self.context = context.get_admin_context()
        self.job_resource_map = constants.job_resource_map
        policy.populate_default_rules()

    @patch.object(db_api, 'db_test_stub', new=mock_db_test_stub)
    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_context):
        mock_context.return_value = self.context

        # cover all job types
        for job_type in self.job_resource_map.keys():
            job = self._prepare_job_element(job_type)

            kw_job = {'job': job}

            # failure case, only admin can create the job
            self.context.is_admin = False
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 403)

            self.context.is_admin = True

            # failure case, request body not found
            kw_job_1 = {'job_1': job}
            res = self.controller.post(**kw_job_1)
            self._validate_error_code(res, 400)

            # failure case, wrong job type parameter
            job_type_backup = job.pop('type')
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['type'] = ''
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['type'] = job_type_backup + '_1'
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['type'] = job_type_backup

            # failure case, wrong resource parameter
            job_resource_backup = job.pop('resource')
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['resource'] = copy.deepcopy(job_resource_backup)
            job['resource'].popitem()
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            fake_resource = 'fake_resource'
            job['resource'][fake_resource] = fake_resource
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['resource'] = job_resource_backup

            # failure case, wrong project id parameter
            project_id_backup = job.pop('project_id')
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['project_id'] = ''
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['project_id'] = uuidutils.generate_uuid()
            res = self.controller.post(**kw_job)
            self._validate_error_code(res, 400)

            job['project_id'] = project_id_backup

            # successful case, create an entirely new job. Because the job
            # status returned from controller has been formatted, so we not
            # only validate the database records, but also validate the return
            # value of the controller.
            job_1 = self.controller.post(**kw_job)['job']
            job_in_db_1 = db_api.get_job(self.context, job_1['id'])
            self.assertEqual(job_type, job_in_db_1['type'])
            self.assertEqual(job['project_id'], job_in_db_1['project_id'])
            self.assertEqual(constants.JS_New, job_in_db_1['status'])

            self.assertEqual('NEW', job_1['status'])
            self.assertEqual(len(constants.job_resource_map[job['type']]),
                             len(job_1['resource']))
            self.assertFalse('resource_id' in job_1)
            self.assertFalse('extra_id' in job_1)
            db_api.delete_job(self.context, job_1['id'])

            # successful case, target job already exists in the job table
            # and its status is NEW, then this newer job will be picked by
            # job handler.
            job_2 = self.controller.post(**kw_job)['job']
            job_in_db_2 = db_api.get_job(self.context, job_2['id'])
            job_3 = self.controller.post(**kw_job)['job']
            job_in_db_3 = db_api.get_job(self.context, job_3['id'])

            self.assertEqual(job_type, job_in_db_2['type'])
            self.assertEqual(job['project_id'], job_in_db_2['project_id'])
            self.assertEqual(constants.JS_New, job_in_db_2['status'])

            self.assertEqual('NEW', job_2['status'])
            self.assertEqual(len(constants.job_resource_map[job['type']]),
                             len(job_2['resource']))
            self.assertFalse('resource_id' in job_2)
            self.assertFalse('extra_id' in job_2)

            self.assertEqual(job_type, job_in_db_3['type'])
            self.assertEqual(job['project_id'], job_in_db_3['project_id'])
            self.assertEqual(constants.JS_New, job_in_db_3['status'])

            self.assertEqual('NEW', job_3['status'])
            self.assertEqual(len(constants.job_resource_map[job['type']]),
                             len(job_3['resource']))
            self.assertFalse('resource_id' in job_3)
            self.assertFalse('extra_id' in job_3)

            db_api.finish_job(self.context, job_3['id'], False,
                              timeutils.utcnow())
            db_api.delete_job(self.context, job_3['id'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_one_and_get_all(self, mock_context):
        self.context.project_id = uuidutils.generate_uuid()
        mock_context.return_value = self.context

        # failure case, only admin can list the job's info
        self.context.is_admin = False
        res = self.controller.get_one("schemas")
        self._validate_error_code(res, 403)
        res = self.controller.get_one("detail")
        self._validate_error_code(res, 403)
        res = self.controller.get_one(uuidutils.generate_uuid())
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, parameter error
        res = self.controller.get_one("schemas_1")
        self._validate_error_code(res, 404)

        res = self.controller.get_one(uuidutils.generate_uuid())
        self._validate_error_code(res, 404)

        # successful case, set id="schemas" to get job schemas
        job_schemas_2 = self.controller.get_one("schemas")
        job_schemas_3 = []
        for job_type in self.job_resource_map.keys():
            job = {}
            resource = []
            for resource_type, resource_id in self.job_resource_map[job_type]:
                resource.append(resource_id)
            job['resource'] = resource
            job['type'] = job_type
            job_schemas_3.append(job)

        self.assertEqual(job_schemas_3, job_schemas_2['schemas'])

        # successful case, set id="detail" to get all jobs.
        # first, we need to create jobs in job table.
        amount_of_all_jobs = len(self.job_resource_map.keys())
        all_job_ids = {}
        index = 0
        for job_type in self.job_resource_map.keys():
            job = self._prepare_job_element(job_type)
            # for test convenience, all jobs have same project ID
            job['project_id'] = self.context.project_id

            resource_id = '#'.join([job['resource'][resource_id]
                                    for resource_type, resource_id
                                    in self.job_resource_map[job_type]])
            job_1 = db_api.new_job(self.context,
                                   job['project_id'], job_type,
                                   resource_id)
            all_job_ids[index] = job_1['id']
            index = index + 1
            time.sleep(1)

            # validate if the id=job_id, get_one(id=job_id) can take effective
            job_2 = self.controller.get_one(job_1['id'])['job']
            self.assertEqual(job_1['type'], job_2['type'])
            self.assertEqual(job_1['project_id'], job_2['project_id'])
            self.assertEqual("NEW", job_2['status'])

        jobs_1 = self.controller.get_one("detail")
        self.assertEqual(amount_of_all_jobs, len(jobs_1['jobs']))

        # create jobs in job log table, in order to validate
        # get_one(id=detail) can also get the jobs from job log
        amount_of_succ_jobs = int(len(all_job_ids) / 2)
        for i in xrange(amount_of_succ_jobs):
            db_api.finish_job(self.context, all_job_ids[i], True,
                              timeutils.utcnow())
            time.sleep(1)

        jobs_2 = self.controller.get_one("detail")
        self.assertEqual(amount_of_all_jobs, len(jobs_2['jobs']))

        job_status_filter_1 = {'status': 'success'}
        jobs_3 = self.controller.get_one("detail", **job_status_filter_1)
        self.assertEqual(amount_of_succ_jobs, len(jobs_3['jobs']))

        # set marker in job log
        res = self.controller.get_all(marker=jobs_3['jobs'][0]['id'],
                                      limit=amount_of_succ_jobs)
        self.assertEqual(amount_of_succ_jobs - 1, len(res['jobs']))

        job_status_filter_2 = {'status': 'new'}
        amount_of_new_jobs = amount_of_all_jobs - amount_of_succ_jobs
        jobs_4 = self.controller.get_one("detail", **job_status_filter_2)
        self.assertEqual(amount_of_new_jobs, len(jobs_4['jobs']))

        # set marker in job
        res = self.controller.get_all(marker=jobs_4['jobs'][0]['id'],
                                      limit=amount_of_new_jobs)
        self.assertEqual(amount_of_new_jobs, len(res['jobs']))

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_all_jobs_with_pagination(self, mock_context):
        self.context.project_id = uuidutils.generate_uuid()
        mock_context.return_value = self.context

        # map job type to project id for later project id filter validation.
        job_project_id_map = {}
        amount_of_all_jobs = len(self.job_resource_map.keys())
        amount_of_running_jobs = 3
        count = 1

        # cover all job types.
        for job_type in self.job_resource_map.keys():
            job = self._prepare_job_element(job_type)
            if count > 1:
                # for test convenience, the first job has a project ID
                # that is different from the context.project_id
                job['project_id'] = self.context.project_id

            job_project_id_map[job_type] = job['project_id']

            resource_id = '#'.join([job['resource'][resource_id]
                                    for resource_type, resource_id
                                    in self.job_resource_map[job_type]])
            if count <= amount_of_running_jobs:
                db_api.register_job(self.context,
                                    job['project_id'], job_type,
                                    resource_id)
                # because jobs are sorted by timestamp, without time delay then
                # all jobs are created at the same time, paginate_query can't
                # identify them
                time.sleep(1)
            else:
                db_api.new_job(self.context,
                               job['project_id'], job_type,
                               resource_id)
                time.sleep(1)
            count = count + 1

        # query the jobs with several kinds of filters.
        # supported filters: project id, job status, job type.
        job_status_filter_1 = {'status': 'new'}
        job_status_filter_2 = {'status': 'fail'}
        job_status_filter_3 = {'status': 'running'}
        invalid_filter = {'status': "new-x"}
        unsupported_filter = {'fake_filter': "fake_filter"}
        count = 1
        for job_type in self.job_resource_map.keys():
            job_type_filter_1 = {'type': job_type}
            job_type_filter_2 = {'type': job_type + '_1'}

            # failure case, only admin can list the jobs
            self.context.is_admin = False
            res = self.controller.get_all()
            self._validate_error_code(res, 403)

            self.context.is_admin = True

            # test when specify project ID filter from client, if this
            # project ID is different from the one from context, then
            # it will be ignored, project ID from context will be
            # used instead.
            filter1 = {'project_id': uuidutils.generate_uuid()}
            res1 = self.controller.get_all(**filter1)

            filter2 = {'project_id': self.context.project_id}
            res2 = self.controller.get_all(**filter2)
            self.assertEqual(len(res2['jobs']), len(res1['jobs']))

            res3 = self.controller.get_all()
            # there is one job whose project ID is different from
            # context.project_id. As the list operation only retrieves the
            # jobs whose project ID equals to context.project_id, so this
            # special job entry won't be retrieved.
            self.assertEqual(len(res3['jobs']), len(res2['jobs']))

            # successful case, filter by job type
            jobs_job_type_filter_1 = self.controller.get_all(
                **job_type_filter_1)
            if count == 1:
                self.assertEqual(0, len(jobs_job_type_filter_1['jobs']))
            else:
                self.assertEqual(1, len(jobs_job_type_filter_1['jobs']))

            jobs_job_type_filter_2 = self.controller.get_all(
                **job_type_filter_2)
            self.assertEqual(0, len(jobs_job_type_filter_2['jobs']))

            # successful case, filter by job status and job type
            if count <= amount_of_running_jobs:
                all_filters = dict(list(job_status_filter_3.items()) +
                                   list(job_type_filter_1.items()))
                jobs_all_filters = self.controller.get_all(**all_filters)
                if count == 1:
                    self.assertEqual(0, len(jobs_all_filters['jobs']))
                else:
                    self.assertEqual(1, len(jobs_all_filters['jobs']))
            else:
                all_filters = dict(list(job_status_filter_1.items()) +
                                   list(job_type_filter_1.items()))
                jobs_all_filters = self.controller.get_all(**all_filters)
                self.assertEqual(1, len(jobs_all_filters['jobs']))

            # successful case, contradictory filter
            contradict_filters = dict(list(job_status_filter_2.items()) +
                                      list((job_type_filter_2.items())))
            jobs_contradict_filters = self.controller.get_all(
                **contradict_filters)
            self.assertEqual(0, len(jobs_contradict_filters['jobs']))
            count = count + 1

        # failure case, unsupported filter
        res = self.controller.get_all(**unsupported_filter)
        self._validate_error_code(res, 400)

        # successful case, invalid filter
        jobs_invalid_filter = self.controller.get_all(**invalid_filter)
        self.assertEqual(0, len(jobs_invalid_filter['jobs']))

        # successful case, list jobs without filters
        jobs_empty_filters = self.controller.get_all()
        self.assertEqual(amount_of_all_jobs - 1,
                         len(jobs_empty_filters['jobs']))

        # successful case, filter by job status
        jobs_job_status_filter_1 = self.controller.get_all(
            **job_status_filter_1)
        self.assertEqual(amount_of_all_jobs - amount_of_running_jobs,
                         len(jobs_job_status_filter_1['jobs']))

        jobs_job_status_filter_2 = self.controller.get_all(
            **job_status_filter_2)
        self.assertEqual(0, len(jobs_job_status_filter_2['jobs']))

        jobs_job_status_filter_3 = self.controller.get_all(
            **job_status_filter_3)
        self.assertEqual(amount_of_running_jobs - 1,
                         len(jobs_job_status_filter_3['jobs']))

        # test for paginate query
        job_paginate_no_filter_1 = self.controller.get_all()
        self.assertEqual(amount_of_all_jobs - 1,
                         len(job_paginate_no_filter_1['jobs']))

        # no limit no marker
        job_paginate_filter_1 = {'status': 'new'}
        jobs_paginate_filter_1 = self.controller.get_all(
            **job_paginate_filter_1)
        self.assertEqual(amount_of_all_jobs - amount_of_running_jobs,
                         len(jobs_paginate_filter_1['jobs']))

        # failed cases, unsupported limit type
        job_paginate_filter_2 = {'limit': '2test'}
        res = self.controller.get_all(**job_paginate_filter_2)
        self._validate_error_code(res, 400)

        # successful cases
        job_paginate_filter_4 = {'status': 'new', 'limit': '2'}
        res = self.controller.get_all(**job_paginate_filter_4)
        self.assertEqual(2, len(res['jobs']))

        job_paginate_filter_5 = {'status': 'new', 'limit': 2}
        res = self.controller.get_all(**job_paginate_filter_5)
        self.assertEqual(2, len(res['jobs']))

        job_paginate_filter_6 = {'status': 'running', 'limit': 1}
        res1 = self.controller.get_all(**job_paginate_filter_6)

        marker = res1['jobs'][0]['id']
        job_paginate_filter_7 = {'status': 'running', 'marker': marker}
        res2 = self.controller.get_all(**job_paginate_filter_7)
        self.assertEqual(amount_of_running_jobs - 1, len(res2['jobs']))

        job_paginate_filter_8 = {'status': 'new', 'limit': 3}
        res = self.controller.get_all(**job_paginate_filter_8)
        self.assertGreaterEqual(res['jobs'][0]['timestamp'],
                                res['jobs'][1]['timestamp'])
        self.assertGreaterEqual(res['jobs'][1]['timestamp'],
                                res['jobs'][2]['timestamp'])

        # unsupported marker type
        res = self.controller.get_all(marker=None)
        self.assertEqual(amount_of_all_jobs - 1, len(res['jobs']))

        res = self.controller.get_all(marker='-123')
        self._validate_error_code(res, 400)

        # marker not in job table and job log table
        job_paginate_filter_9 = {'marker': uuidutils.generate_uuid()}
        res = self.controller.get_all(**job_paginate_filter_9)
        self._validate_error_code(res, 400)

        # test marker and limit
        limit = 2
        pt = '/v1.0/jobs\?limit=\w+&marker=([\w-]+)'
        job_paginate_filter = {'status': 'new', 'limit': limit}
        res = self.controller.get_all(**job_paginate_filter)
        while 'jobs_links' in res:
            m = re.match(pt, res['jobs_links'][0]['href'])
            marker = m.group(1)
            self.assertEqual(limit, len(res['jobs']))
            job_paginate_filter = {'status': 'new', 'limit': limit,
                                   'marker': marker}
            res = self.controller.get_all(**job_paginate_filter)

        job_paginate_filter_10 = {'status': 'running'}
        res = self.controller.get_all(**job_paginate_filter_10)
        self.assertEqual(amount_of_running_jobs - 1, len(res['jobs']))
        # add some rows to job log table
        for i in xrange(amount_of_running_jobs - 1):
            db_api.finish_job(self.context, res['jobs'][i]['id'], True,
                              timeutils.utcnow())
            time.sleep(1)
        res_success_log = db_api.list_jobs_from_log(self.context, None)
        self.assertEqual(amount_of_running_jobs - 1, len(res_success_log))

        res_in_job = db_api.list_jobs(self.context, None)
        self.assertEqual(amount_of_all_jobs - (amount_of_running_jobs - 1),
                         len(res_in_job))

        job_paginate_filter_11 = {'limit': 2}
        res = self.controller.get_all(**job_paginate_filter_11)
        self.assertIsNotNone(res['jobs_links'][0]['href'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(pecan, 'response', new=mock.Mock)
    @patch.object(context, 'extract_context_from_environ')
    def test_delete(self, mock_context):
        mock_context.return_value = self.context

        # cover all job types.
        # each 'for' loop adds one item in job log table, we set count variable
        # to record dynamic total job entries in job log table.
        count = 1
        for job_type in self.job_resource_map.keys():
            job = self._prepare_job_element(job_type)

            resource_id = '#'.join([job['resource'][resource_id]
                                    for resource_type, resource_id
                                    in self.job_resource_map[job_type]])

            # failure case, only admin can delete the job
            job_1 = db_api.new_job(self.context, job['project_id'],
                                   job_type,
                                   resource_id)
            self.context.is_admin = False
            res = self.controller.delete(job_1['id'])
            self._validate_error_code(res, 403)

            self.context.is_admin = True
            db_api.delete_job(self.context, job_1['id'])

            # failure case, job not found
            res = self.controller.delete(-123)
            self._validate_error_code(res, 404)

            # failure case, delete a running job
            job_2 = db_api.register_job(self.context,
                                        job['project_id'],
                                        job_type, resource_id)
            job = db_api.get_job(self.context, job_2['id'])
            res = self.controller.delete(job_2['id'])
            self._validate_error_code(res, 400)

            # finish the job and delete it
            db_api.finish_job(self.context, job_2['id'], False,
                              timeutils.utcnow())
            db_api.delete_job(self.context, job_2['id'])

            # successful case, delete a successful job. successful job from
            # job log can't be deleted, here this successful job is from
            # job table.
            job_3 = self._prepare_job_element(job_type)
            resource_id_3 = '#'.join([job_3['resource'][resource_id_3]
                                      for resource_type_3, resource_id_3
                                      in self.job_resource_map[job_type]])

            job_4 = db_api.new_job(self.context,
                                   job_3['project_id'],
                                   job_type, resource_id_3)

            with self.context.session.begin():
                job_dict = {'status': constants.JS_Success,
                            'timestamp': timeutils.utcnow(),
                            'extra_id': uuidutils.generate_uuid()}
                core.update_resource(self.context, models.AsyncJob,
                                     job_4['id'], job_dict)

            job_4_succ = db_api.get_job(self.context, job_4['id'])
            self.controller.delete(job_4['id'])

            filters_job_4 = [
                {'key': 'type', 'comparator': 'eq',
                 'value': job_4_succ['type']},
                {'key': 'status', 'comparator': 'eq',
                 'value': job_4_succ['status']},
                {'key': 'resource_id', 'comparator': 'eq',
                 'value': job_4_succ['resource_id']},
                {'key': 'extra_id', 'comparator': 'eq',
                 'value': job_4_succ['extra_id']}]
            self.assertEqual(0, len(db_api.list_jobs(self.context,
                                                     filters_job_4)))
            self.assertEqual(count,
                             len(db_api.list_jobs_from_log(self.context)))
            count = count + 1

            # successful case, delete a new job
            job_5 = db_api.new_job(self.context,
                                   job['project_id'], job_type,
                                   resource_id)
            self.controller.delete(job_5['id'])

            filters_job_5 = [
                {'key': 'type', 'comparator': 'eq', 'value': job_5['type']},
                {'key': 'status', 'comparator': 'eq',
                 'value': job_5['status']},
                {'key': 'resource_id', 'comparator': 'eq',
                 'value': job_5['resource_id']},
                {'key': 'extra_id', 'comparator': 'eq',
                 'value': job_5['extra_id']}]
            self.assertEqual(0, len(db_api.list_jobs(self.context,
                                                     filters_job_5)))

            # successful case, delete a failed job
            job_6 = db_api.new_job(self.context,
                                   job['project_id'], job_type,
                                   resource_id)
            db_api.finish_job(self.context, job_6['id'], False,
                              timeutils.utcnow())
            job_6_failed = db_api.get_job(self.context, job_6['id'])
            self.controller.delete(job_6['id'])
            filters_job_6 = [
                {'key': 'type', 'comparator': 'eq',
                 'value': job_6_failed['type']},
                {'key': 'status', 'comparator': 'eq',
                 'value': job_6_failed['status']},
                {'key': 'resource_id', 'comparator': 'eq',
                 'value': job_6_failed['resource_id']},
                {'key': 'extra_id', 'comparator': 'eq',
                 'value': job_6_failed['extra_id']}]
            self.assertEqual(0, len(db_api.list_jobs(self.context,
                                                     filters_job_6)))

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(pecan, 'response', new=mock.Mock)
    @patch.object(context, 'extract_context_from_environ')
    def test_put(self, mock_context):
        mock_context.return_value = self.context

        # cover all job types
        for job_type in self.job_resource_map.keys():
            job = self._prepare_job_element(job_type)

            resource_id = '#'.join([job['resource'][resource_id]
                                    for resource_type, resource_id
                                    in self.job_resource_map[job_type]])

            # failure case, only admin can redo the job
            job_1 = db_api.new_job(self.context,
                                   job['project_id'],
                                   job_type, resource_id)
            self.context.is_admin = False
            res = self.controller.put(job_1['id'])
            self._validate_error_code(res, 403)

            self.context.is_admin = True
            db_api.delete_job(self.context, job_1['id'])

            # failure case, job not found
            res = self.controller.put(-123)
            self._validate_error_code(res, 404)

            # failure case, redo a running job
            job_2 = db_api.register_job(self.context,
                                        job['project_id'],
                                        job_type, resource_id)
            res = self.controller.put(job_2['id'])
            self._validate_error_code(res, 400)
            db_api.finish_job(self.context, job_2['id'], False,
                              timeutils.utcnow())
            db_api.delete_job(self.context, job_2['id'])

            # failure case, redo a successful job
            job_3 = self._prepare_job_element(job_type)

            resource_id_3 = '#'.join([job_3['resource'][resource_id_3]
                                      for resource_type_3, resource_id_3
                                      in self.job_resource_map[job_type]])

            job_4 = db_api.new_job(self.context,
                                   job_3['project_id'],
                                   job_type, resource_id_3)
            with self.context.session.begin():
                job_dict = {'status': constants.JS_Success,
                            'timestamp': timeutils.utcnow(),
                            'extra_id': uuidutils.generate_uuid()}
                core.update_resource(self.context, models.AsyncJob,
                                     job_4['id'], job_dict)

            res = self.controller.put(job_4['id'])
            self._validate_error_code(res, 400)
            db_api.finish_job(self.context, job_4['id'], True,
                              timeutils.utcnow())

            # successful case, redo a failed job
            job_5 = db_api.new_job(self.context,
                                   job['project_id'],
                                   job_type, resource_id)
            db_api.finish_job(self.context, job_5['id'], False,
                              timeutils.utcnow())
            self.controller.put(job_5['id'])

            db_api.delete_job(self.context, job_5['id'])

            # successful case, redo a new job
            job_6 = db_api.new_job(self.context,
                                   job['project_id'],
                                   job_type, resource_id)
            self.controller.put(job_6['id'])

            db_api.delete_job(self.context, job_6['id'])

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
        if job_type in (constants.JT_SEG_RULE_SETUP,
                        constants.JT_RESOURCE_RECYCLE):
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

    def tearDown(self):
        cfg.CONF.unregister_opts(app.common_opts)
        core.ModelBase.metadata.drop_all(core.get_engine())

        super(AsyncJobControllerTest, self).tearDown()
