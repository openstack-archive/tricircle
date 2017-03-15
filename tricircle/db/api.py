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

import datetime
import functools
import sqlalchemy as sql
from sqlalchemy import or_
import time

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import uuidutils

from tricircle.common import constants
from tricircle.common.context import is_admin_context as _is_admin_context
from tricircle.common import exceptions
from tricircle.common.i18n import _

from tricircle.db import core
from tricircle.db import models


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def create_pod(context, pod_dict):
    with context.session.begin():
        return core.create_resource(context, models.Pod, pod_dict)


def delete_pod(context, pod_id):
    with context.session.begin():
        return core.delete_resource(context, models.Pod, pod_id)


def get_pod(context, pod_id):
    with context.session.begin():
        return core.get_resource(context, models.Pod, pod_id)


def list_pods(context, filters=None, sorts=None):
    return core.query_resource(context, models.Pod, filters or [],
                               sorts or [])


def update_pod(context, pod_id, update_dict):
    with context.session.begin():
        return core.update_resource(context, models.Pod, pod_id, update_dict)


def create_cached_endpoints(context, config_dict):
    with context.session.begin():
        return core.create_resource(context, models.CachedEndpoint,
                                    config_dict)


def delete_cached_endpoints(context, config_id):
    with context.session.begin():
        return core.delete_resource(context, models.CachedEndpoint,
                                    config_id)


def get_cached_endpoints(context, config_id):
    with context.session.begin():
        return core.get_resource(context, models.CachedEndpoint,
                                 config_id)


def list_cached_endpoints(context, filters=None, sorts=None):
    return core.query_resource(context, models.CachedEndpoint,
                               filters or [], sorts or [])


def update_cached_endpoints(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, models.CachedEndpoint, config_id, update_dict)


def create_resource_mapping(context, top_id, bottom_id, pod_id, project_id,
                            resource_type):
    try:
        context.session.begin()
        route = core.create_resource(context, models.ResourceRouting,
                                     {'top_id': top_id,
                                      'bottom_id': bottom_id,
                                      'pod_id': pod_id,
                                      'project_id': project_id,
                                      'resource_type': resource_type})
        context.session.commit()
        return route
    except db_exc.DBDuplicateEntry:
        # entry has already been created
        context.session.rollback()
        return None
    finally:
        context.session.close()


def list_resource_routings(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.ResourceRouting,
                                   filters or [], sorts or [])


def get_resource_routing(context, id):
    with context.session.begin():
        return core.get_resource(context, models.ResourceRouting, id)


def delete_resource_routing(context, id):
    with context.session.begin():
        return core.delete_resource(context, models.ResourceRouting, id)


def update_resource_routing(context, id, update_dict):
    with context.session.begin():
        return core.update_resource(context, models.ResourceRouting, id,
                                    update_dict)


def get_bottom_mappings_by_top_id(context, top_id, resource_type):
    """Get resource id and pod name on bottom

    :param context: context object
    :param top_id: resource id on top
    :param resource_type: resource type
    :return: a list of tuple (pod dict, bottom_id)
    """
    route_filters = [{'key': 'top_id', 'comparator': 'eq', 'value': top_id},
                     {'key': 'resource_type',
                      'comparator': 'eq',
                      'value': resource_type}]
    mappings = []
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        for route in routes:
            if not route['bottom_id']:
                continue
            pod = core.get_resource(context, models.Pod, route['pod_id'])
            mappings.append((pod, route['bottom_id']))
    return mappings


def delete_pre_created_resource_mapping(context, name):
    with context.session.begin():
        entries = core.query_resource(
            context, models.ResourceRouting,
            filters=[{'key': 'top_id', 'comparator': 'eq',
                      'value': name}], sorts=[])
        if entries:
            core.delete_resources(
                context, models.ResourceRouting,
                filters=[{'key': 'top_id', 'comparator': 'eq',
                          'value': entries[0]['bottom_id']}])
            core.delete_resource(context, models.ResourceRouting,
                                 entries[0]['id'])


def get_pod_by_top_id(context, _id):
    """Get pod resource from pod table by top id of resource

    :param context: context object
    :param _id: the top id of resource
    :returns: pod resource
    """
    route_filters = [{'key': 'top_id', 'comparator': 'eq', 'value': _id}]
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        if not routes or len(routes) != 1:
            return None
        route = routes[0]
        if not route['bottom_id']:
            return None
        return core.get_resource(context, models.Pod, route['pod_id'])


def get_bottom_id_by_top_id_region_name(context, top_id,
                                        region_name, resource_type):
    """Get resource bottom id by top id and bottom pod name

    :param context: context object
    :param top_id: resource id on top
    :param region_name: name of bottom pod
    :param resource_type: resource type
    :return:
    """
    mappings = get_bottom_mappings_by_top_id(context, top_id, resource_type)
    for pod, bottom_id in mappings:
        if pod['region_name'] == region_name:
            return bottom_id
    return None


def get_bottom_mappings_by_tenant_pod(context,
                                      tenant_id,
                                      pod_id,
                                      resource_type):
    """Get resource routing for specific tenant and pod

    :param context: context object
    :param tenant_id: tenant id to look up
    :param pod_id: pod to look up
    :param resource_type: specific resource
    :return: a dic {top_id : route}
    """
    route_filters = [{'key': 'pod_id',
                      'comparator': 'eq',
                      'value': pod_id},
                     {'key': 'project_id',
                      'comparator': 'eq',
                      'value': tenant_id},
                     {'key': 'resource_type',
                      'comparator': 'eq',
                      'value': resource_type}]
    routings = {}
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        for _route in routes:
            if not _route['bottom_id']:
                continue
            routings[_route['top_id']] = _route
    return routings


def delete_mappings_by_top_id(context, top_id, pod_id=None):
    """Delete resource routing entry based on top resource ID

    If pod ID is also provided, only entry in the specific pod will be deleted

    :param context: context object
    :param top_id: top resource ID
    :param pod_id: optional pod ID
    :return: None
    """
    filters = [{'key': 'top_id', 'comparator': 'eq', 'value': top_id}]
    if pod_id:
        filters.append({'key': 'pod_id', 'comparator': 'eq', 'value': pod_id})
    with context.session.begin():
        core.delete_resources(context, models.ResourceRouting, filters=filters)


def delete_mappings_by_bottom_id(context, bottom_id):
    with context.session.begin():
        core.delete_resources(
            context, models.ResourceRouting,
            filters=[{'key': 'bottom_id', 'comparator': 'eq',
                      'value': bottom_id}])


def get_next_bottom_pod(context, current_pod_id=None):
    pods = list_pods(context, sorts=[(models.Pod.pod_id, True)])
    # NOTE(zhiyuan) number of pods is small, just traverse to filter top pod
    pods = [pod for pod in pods if pod['az_name']]
    for index, pod in enumerate(pods):
        if not current_pod_id:
            return pod
        if pod['pod_id'] == current_pod_id and index < len(pods) - 1:
            return pods[index + 1]
    return None


def get_top_pod(context):

    filters = [{'key': 'az_name', 'comparator': 'eq', 'value': ''}]
    pods = list_pods(context, filters=filters)

    # only one should be searched
    for pod in pods:
        if (pod['region_name'] != '') and \
                (pod['az_name'] == ''):
            return pod

    return None


def get_pod_by_name(context, region_name):

    filters = [{'key': 'region_name',
                'comparator': 'eq', 'value': region_name}]
    pods = list_pods(context, filters=filters)

    # only one should be searched
    for pod in pods:
        if pod['region_name'] == region_name:
            return pod

    return None


def find_pods_by_az_or_region(context, az_or_region):
    # if az_or_region is None or empty, returning None value directly.
    if not az_or_region:
        return None
    query = context.session.query(models.Pod)
    query = query.filter(or_(models.Pod.region_name == az_or_region,
                             models.Pod.az_name == az_or_region))

    return [obj.to_dict() for obj in query]


def find_pod_by_az_or_region(context, az_or_region):
    pods = find_pods_by_az_or_region(context, az_or_region)

    # if pods is None, returning None value directly.
    if pods is None:
        return None
    # if no pod is matched, then we will raise an exception
    if len(pods) < 1:
        raise exceptions.PodNotFound(az_or_region)
    # if the pods list only contain one pod, then this pod will be
    # returned back
    if len(pods) == 1:
        return pods[0]
    # if the pods list contains more than one pod, then we will raise an
    # exception
    if len(pods) > 1:
        raise exceptions.InvalidInput(
            reason='Multiple pods with the same az_name are found')


def new_job(context, project_id, _type, resource_id):
    with context.session.begin():
        job_dict = {'id': uuidutils.generate_uuid(),
                    'type': _type,
                    'status': constants.JS_New,
                    'project_id': project_id,
                    'resource_id': resource_id,
                    'extra_id': uuidutils.generate_uuid()}
        job = core.create_resource(context,
                                   models.AsyncJob, job_dict)
        return job


def register_job(context, project_id, _type, resource_id):
    try:
        context.session.begin()
        job_dict = {'id': uuidutils.generate_uuid(),
                    'type': _type,
                    'status': constants.JS_Running,
                    'project_id': project_id,
                    'resource_id': resource_id,
                    'extra_id': constants.SP_EXTRA_ID}
        job = core.create_resource(context,
                                   models.AsyncJob, job_dict)
        context.session.commit()
        return job
    except db_exc.DBDuplicateEntry:
        context.session.rollback()
        return None
    except db_exc.DBDeadlock:
        context.session.rollback()
        return None
    finally:
        context.session.close()


def get_latest_failed_or_new_jobs(context):
    current_timestamp = timeutils.utcnow()
    time_span = datetime.timedelta(seconds=CONF.redo_time_span)
    latest_timestamp = current_timestamp - time_span
    failed_jobs = []
    new_jobs = []

    # first we group the jobs by type and resource id, and in each group we
    # pick the latest timestamp
    stmt = context.session.query(
        models.AsyncJob.type, models.AsyncJob.resource_id,
        sql.func.max(models.AsyncJob.timestamp).label('timestamp'))
    stmt = stmt.filter(models.AsyncJob.timestamp >= latest_timestamp)
    stmt = stmt.group_by(models.AsyncJob.type,
                         models.AsyncJob.resource_id).subquery()

    # then we join the result with the original table and group again, in each
    # group, we pick the "minimum" of the status, for status, the ascendant
    # sort sequence is "0_Fail", "1_Success", "2_Running", "3_New"
    query = context.session.query(models.AsyncJob.type,
                                  models.AsyncJob.resource_id,
                                  models.AsyncJob.project_id,
                                  sql.func.min(models.AsyncJob.status)).join(
        stmt, sql.and_(models.AsyncJob.type == stmt.c.type,
                       models.AsyncJob.resource_id == stmt.c.resource_id,
                       models.AsyncJob.timestamp == stmt.c.timestamp))
    query = query.group_by(models.AsyncJob.project_id,
                           models.AsyncJob.type,
                           models.AsyncJob.resource_id)

    for job_type, resource_id, project_id, status in query:
        if status == constants.JS_Fail:
            failed_jobs.append({'type': job_type, 'resource_id': resource_id,
                                'project_id': project_id})
        elif status == constants.JS_New:
            new_jobs.append({'type': job_type, 'resource_id': resource_id,
                             'project_id': project_id})
    return failed_jobs, new_jobs


def list_jobs(context, filters=None, sorts=None):
    with context.session.begin():
        # get all jobs from job table
        jobs = core.query_resource(context, models.AsyncJob,
                                   filters or [], sorts or [])
        return jobs


def list_jobs_from_log(context, filters=None, sorts=None):
    with context.session.begin():
        # get all jobs from job log table, because the job log table only
        # stores successful jobs, so this method merely returns successful jobs
        if filters is not None:
            for filter in filters:
                if filter.get('key') == 'status':
                    job_status = filter['value']
                    # job entry in job log table has no status attribute.
                    if job_status == constants.JS_Success:
                        filters.remove(filter)
                    else:
                        return []

        jobs_in_log = core.query_resource(
            context, models.AsyncJobLog, filters or [], sorts or [])
        return jobs_in_log


def get_job(context, job_id):
    with context.session.begin():
        return core.get_resource(context, models.AsyncJob, job_id)


def get_job_from_log(context, job_id):
    with context.session.begin():
        return core.get_resource(context, models.AsyncJobLog, job_id)


def delete_job(context, job_id):
    with context.session.begin():
        return core.delete_resource(context, models.AsyncJob, job_id)


def get_latest_job(context, status, _type, resource_id):
    jobs = core.query_resource(
        context, models.AsyncJob,
        [{'key': 'status', 'comparator': 'eq', 'value': status},
         {'key': 'type', 'comparator': 'eq', 'value': _type},
         {'key': 'resource_id', 'comparator': 'eq', 'value': resource_id}],
        [('timestamp', False)])
    if jobs:
        return jobs[0]
    else:
        return None


def get_running_job(context, _type, resource_id):
    jobs = core.query_resource(
        context, models.AsyncJob,
        [{'key': 'resource_id', 'comparator': 'eq', 'value': resource_id},
         {'key': 'status', 'comparator': 'eq', 'value': constants.JS_Running},
         {'key': 'type', 'comparator': 'eq', 'value': _type}], [])
    if jobs:
        return jobs[0]
    else:
        return None


def finish_job(context, job_id, successful, timestamp):
    status = constants.JS_Success if successful else constants.JS_Fail
    with context.session.begin():
        job_dict = {'status': status,
                    'timestamp': timestamp,
                    'extra_id': uuidutils.generate_uuid()}
        job = core.update_resource(context, models.AsyncJob, job_id, job_dict)
        if status == constants.JS_Success:
            log_dict = {'id': uuidutils.generate_uuid(),
                        'type': job['type'],
                        'project_id': job['project_id'],
                        'timestamp': timestamp,
                        'resource_id': job['resource_id']}
            context.session.query(models.AsyncJob).filter(
                sql.and_(models.AsyncJob.type == job['type'],
                         models.AsyncJob.resource_id == job['resource_id'],
                         models.AsyncJob.timestamp <= timestamp)).delete(
                synchronize_session=False)
            core.create_resource(context, models.AsyncJobLog, log_dict)
        else:
            # sqlite has problem handling "<" operator on timestamp, so we
            # slide the timestamp a bit and use "<="
            timestamp = timestamp - datetime.timedelta(microseconds=1)
            context.session.query(models.AsyncJob).filter(
                sql.and_(models.AsyncJob.type == job['type'],
                         models.AsyncJob.resource_id == job['resource_id'],
                         models.AsyncJob.timestamp <= timestamp)).delete(
                synchronize_session=False)


def ensure_agent_exists(context, pod_id, host, _type, tunnel_ip):
    try:
        context.session.begin()
        agents = core.query_resource(
            context, models.ShadowAgent,
            [{'key': 'host', 'comparator': 'eq', 'value': host},
             {'key': 'type', 'comparator': 'eq', 'value': _type}], [])
        if agents:
            return
        core.create_resource(context, models.ShadowAgent,
                             {'id': uuidutils.generate_uuid(),
                              'pod_id': pod_id,
                              'host': host,
                              'type': _type,
                              'tunnel_ip': tunnel_ip})
        context.session.commit()
    except db_exc.DBDuplicateEntry:
        # agent has already been created
        context.session.rollback()
    finally:
        context.session.close()


def get_agent_by_host_type(context, host, _type):
    agents = core.query_resource(
        context, models.ShadowAgent,
        [{'key': 'host', 'comparator': 'eq', 'value': host},
         {'key': 'type', 'comparator': 'eq', 'value': _type}], [])
    return agents[0] if agents else None


def _is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if _is_user_context(context):
        if not context.project_id:
            raise exceptions.NotAuthorized()
        elif context.project_id != project_id:
            raise exceptions.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if _is_user_context(context):
        if not context.user_id:
            raise exceptions.NotAuthorized()
        elif context.user_id != user_id:
            raise exceptions.NotAuthorized()


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not _is_admin_context(args[0]):
            raise exceptions.AdminRequired()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not _is_admin_context(args[0]) and not _is_user_context(args[0]):
            raise exceptions.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def _retry_on_deadlock(f):
    """Decorator to retry a DB API call if Deadlock was received."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        while True:
            try:
                return f(*args, **kwargs)
            except db_exc.DBDeadlock:
                LOG.warning("Deadlock detected when running "
                            "'%(func_name)s': Retrying...",
                            dict(func_name=f.__name__))
                # Retry!
                time.sleep(0.5)
                continue
    functools.update_wrapper(wrapped, f)
    return wrapped


def handle_db_data_error(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except db_exc.DBDataError:
            msg = _('Error writing field to database')
            LOG.exception(msg)
            raise exceptions.Invalid(msg)
        except Exception as e:
            LOG.exception(str(e))
            raise

    return wrapper


def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or context.session
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    elif read_deleted == 'int_no':
        query = query.filter_by(deleted=0)
    else:
        raise Exception(
            _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and _is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query


def is_valid_model_filters(model, filters):
    """Return True if filter values exist on the model

    :param model: a Cinder model
    :param filters: dictionary of filters
    """
    for key in filters.keys():
        if not hasattr(model, key):
            return False
    return True
