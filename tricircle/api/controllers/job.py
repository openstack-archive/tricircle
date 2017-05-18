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

import pecan
from pecan import expose
from pecan import rest
import six

from oslo_log import log as logging
from oslo_utils import timeutils

from tricircle.common import constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exc
from tricircle.common.i18n import _
from tricircle.common import policy
from tricircle.common import utils
from tricircle.common import xrpcapi
from tricircle.db import api as db_api

LOG = logging.getLogger(__name__)


class AsyncJobController(rest.RestController):
    # with AsyncJobController, admin can create, show, delete and
    # redo asynchronous jobs

    def __init__(self):
        self.xjob_handler = xrpcapi.XJobAPI()

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        job_resource_map = constants.job_resource_map

        if not policy.enforce(context, policy.ADMIN_API_JOB_CREATE):
            return utils.format_api_error(
                403, _("Unauthorized to create a job"))

        if 'job' not in kw:
            return utils.format_api_error(
                400, _("Request body not found"))

        job = kw['job']

        for field in ('type', 'project_id'):
            value = job.get(field)
            if value is None:
                return utils.format_api_error(
                    400, _("%(field)s isn't provided in request body") % {
                        'field': field})
            elif len(value.strip()) == 0:
                return utils.format_api_error(
                    400, _("%(field)s can't be empty") % {'field': field})

        if job['type'] not in job_resource_map.keys():
            return utils.format_api_error(
                400, _('There is no such job type: %(job_type)s') % {
                    'job_type': job['type']})

        job_type = job['type']
        project_id = job['project_id']

        if 'resource' not in job:
            return utils.format_api_error(
                400, _('Failed to create job, because the resource is not'
                       ' specified'))

        # verify that all given resources are exactly needed
        request_fields = set(job['resource'].keys())
        require_fields = set([resource_id
                              for resource_type, resource_id in
                              job_resource_map[job_type]])
        missing_fields = require_fields - request_fields
        redundant_fields = request_fields - require_fields

        if missing_fields:
                return utils.format_api_error(
                    400, _('Some required fields are not specified:'
                           ' %(field)s') % {'field': missing_fields})
        if redundant_fields:
                return utils.format_api_error(
                    400, _('Some fields are redundant: %(field)s') % {
                        'field': redundant_fields})

        # validate whether the project id is legal
        resource_type_1, resource_id_1 = (
            constants.job_primary_resource_map[job_type])
        if resource_type_1 is not None:
            filter = [{'key': 'project_id', 'comparator': 'eq',
                       'value': project_id},
                      {'key': 'resource_type', 'comparator': 'eq',
                       'value': resource_type_1},
                      {'key': 'top_id', 'comparator': 'eq',
                       'value': job['resource'][resource_id_1]}]

            routings = db_api.list_resource_routings(context, filter)
            if not routings:
                msg = (_("%(resource)s %(resource_id)s doesn't belong to the"
                         " project %(project_id)s") %
                       {'resource': resource_type_1,
                        'resource_id': job['resource'][resource_id_1],
                        'project_id': project_id})
                return utils.format_api_error(400, msg)

        # if job_type = seg_rule_setup, we should ensure the project id
        # is equal to the one from resource.
        if job_type == constants.JT_SEG_RULE_SETUP:
            if job['project_id'] != job['resource']['project_id']:
                msg = (_("Specified project_id %(project_id_1)s and resource's"
                         " project_id %(project_id_2)s are different") %
                       {'project_id_1': job['project_id'],
                        'project_id_2': job['resource']['project_id']})
                return utils.format_api_error(400, msg)

        # combine uuid into target resource id
        resource_id = '#'.join([job['resource'][resource_id]
                                for resource_type, resource_id
                                in job_resource_map[job_type]])

        try:
            # create a job and put it into execution immediately
            self.xjob_handler.invoke_method(context, project_id,
                                            constants.job_handles[job_type],
                                            job_type, resource_id)
        except Exception as e:
            LOG.exception('Failed to create job: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to create a job'))

        new_job = db_api.get_latest_job(context, constants.JS_New, job_type,
                                        resource_id)
        return {'job': self._get_more_readable_job(new_job)}

    @expose(generic=True, template='json')
    def get_one(self, id, **kwargs):
        """the return value may vary according to the value of id

        :param id: 1) if id = 'schemas', return job schemas
                   2) if id = 'detail', return all jobs
                   3) if id = $job_id, return detailed single job info
        :return: return value is decided by id parameter
        """
        context = t_context.extract_context_from_environ()
        job_resource_map = constants.job_resource_map

        if not policy.enforce(context, policy.ADMIN_API_JOB_SCHEMA_LIST):
            return utils.format_api_error(
                403, _('Unauthorized to show job information'))

        if id == 'schemas':
            job_schemas = []
            for job_type in job_resource_map.keys():
                job = {}
                resource = []
                for resource_type, resource_id in job_resource_map[job_type]:
                    resource.append(resource_id)

                job['resource'] = resource
                job['type'] = job_type
                job_schemas.append(job)

            return {'schemas': job_schemas}

        if id == 'detail':
            return self.get_all(**kwargs)

        try:
            job = db_api.get_job(context, id)
            return {'job': self._get_more_readable_job(job)}
        except Exception:
            try:
                job = db_api.get_job_from_log(context, id)
                return {'job': self._get_more_readable_job(job)}
            except t_exc.ResourceNotFound:
                return utils.format_api_error(
                    404, _('Resource not found'))

    @expose(generic=True, template='json')
    def get_all(self, **kwargs):
        """Get all the jobs. Using filters, only get a subset of jobs.

        :param kwargs: job filters
        :return: a list of jobs
        """
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_JOB_LIST):
            return utils.format_api_error(
                403, _('Unauthorized to show all jobs'))

        is_valid_filter, filters = self._get_filters(kwargs)

        if not is_valid_filter:
            msg = (_('Unsupported filter type: %(filters)s') % {
                'filters': ', '.join([filter_name for filter_name in filters])
            })
            return utils.format_api_error(400, msg)

        filters = [{'key': key,
                    'comparator': 'eq',
                    'value': value} for key, value in six.iteritems(filters)]

        try:
            jobs_in_job_table = db_api.list_jobs(context, filters)
            jobs_in_job_log_table = db_api.list_jobs_from_log(context, filters)
            jobs = jobs_in_job_table + jobs_in_job_log_table
            return {'jobs': [self._get_more_readable_job(job) for job in jobs]}
        except Exception as e:
            LOG.exception('Failed to show all asynchronous jobs: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to show all asynchronous jobs'))

    # make the job status and resource id more human readable. Split
    # resource id into several member uuid(s) to provide more detailed resource
    # information. If job entry is from job table, then remove resource id
    # and extra id from job attributes. If job entry is from job log table,
    # only remove resource id from job attributes.
    def _get_more_readable_job(self, job):
        job_resource_map = constants.job_resource_map

        if 'status' in job:
            job['status'] = constants.job_status_map[job['status']]
        else:
            job['status'] = constants.job_status_map[constants.JS_Success]

        job['resource'] = dict(zip([resource_id
                                    for resource_type, resource_id
                                    in job_resource_map[job['type']]],
                                   job['resource_id'].split('#')))
        job.pop('resource_id')

        if "extra_id" in job:
            job.pop('extra_id')

        return job

    def _get_filters(self, params):
        """Return a dictionary of query param filters from the request.

        :param params: the URI params coming from the wsgi layer
        :return (flag, filters), flag indicates whether the filters are valid,
        and the filters denote a list of key-value pairs.
        """
        filters = {}
        unsupported_filters = {}
        for filter_name in params:
            if filter_name in constants.JOB_LIST_SUPPORTED_FILTERS:
                # map filter name
                if filter_name == 'status':
                    job_status_in_db = self._get_job_status_in_db(
                        params.get(filter_name))
                    filters[filter_name] = job_status_in_db
                    continue
                filters[filter_name] = params.get(filter_name)
            else:
                unsupported_filters[filter_name] = params.get(filter_name)

        if unsupported_filters:
            return False, unsupported_filters
        return True, filters

    # map user input job status to job status stored in database
    def _get_job_status_in_db(self, job_status):
        job_status_map = {
            'fail': constants.JS_Fail,
            'success': constants.JS_Success,
            'running': constants.JS_Running,
            'new': constants.JS_New
        }
        job_status_lower = job_status.lower()
        if job_status_lower in job_status_map:
            return job_status_map[job_status_lower]
        return job_status

    @expose(generic=True, template='json')
    def delete(self, job_id):
        # delete a job from the database. If the job is running, the delete
        # operation will fail. In other cases, job will be deleted directly.
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_JOB_DELETE):
            return utils.format_api_error(
                403, _('Unauthorized to delete a job'))

        try:
            db_api.get_job_from_log(context, job_id)
            return utils.format_api_error(
                400, _('Job %(job_id)s is from job log') % {'job_id': job_id})
        except Exception:
            try:
                job = db_api.get_job(context, job_id)
            except t_exc.ResourceNotFound:
                return utils.format_api_error(
                    404, _('Job %(job_id)s not found') % {'job_id': job_id})
        try:
            # if job status = RUNNING, notify user this new one, delete
            # operation fails.
            if job['status'] == constants.JS_Running:
                return utils.format_api_error(
                    400, (_('Failed to delete the running job %(job_id)s') %
                          {"job_id": job_id}))
            # if job status = SUCCESS, move the job entry to job log table,
            # then delete it from job table.
            elif job['status'] == constants.JS_Success:
                db_api.finish_job(context, job_id, True, timeutils.utcnow())
                pecan.response.status = 200
                return {}

            db_api.delete_job(context, job_id)
            pecan.response.status = 200
            return {}
        except Exception as e:
            LOG.exception('Failed to delete the job: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to delete the job'))

    @expose(generic=True, template='json')
    def put(self, job_id):
        # we use HTTP/HTTPS PUT method to redo a job. Regularly PUT method
        # requires a request body, but considering the job redo operation
        # doesn't need more information other than job id, we will issue
        # this request without a request body.
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_JOB_REDO):
            return utils.format_api_error(
                403, _('Unauthorized to redo a job'))

        try:
            db_api.get_job_from_log(context, job_id)
            return utils.format_api_error(
                400, _('Job %(job_id)s is from job log') % {'job_id': job_id})
        except Exception:
            try:
                job = db_api.get_job(context, job_id)
            except t_exc.ResourceNotFound:
                return utils.format_api_error(
                    404, _('Job %(job_id)s not found') % {'job_id': job_id})

        try:
            # if status = RUNNING, notify user this new one and then exit
            if job['status'] == constants.JS_Running:
                return utils.format_api_error(
                    400, (_("Can't redo job %(job_id)s which is running") %
                          {'job_id': job['id']}))
            # if status = SUCCESS, notify user this new one and then exit
            elif job['status'] == constants.JS_Success:
                msg = (_("Can't redo job %(job_id)s which had run successfully"
                         ) % {'job_id': job['id']})
                return utils.format_api_error(400, msg)
            # if job status =  FAIL or job status = NEW, redo it immediately
            self.xjob_handler.invoke_method(context, job['project_id'],
                                            constants.job_handles[job['type']],
                                            job['type'], job['resource_id'])
        except Exception as e:
            LOG.exception('Failed to redo the job: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to redo the job'))
