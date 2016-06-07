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

import functools
import sqlalchemy as sql
import time
import uuid

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import uuidutils
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import literal_column

from tricircle.common import constants
from tricircle.common.context import is_admin_context as _is_admin_context
from tricircle.common import exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LW

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
    with context.session.begin():
        return core.query_resource(context, models.Pod, filters or [],
                                   sorts or [])


def update_pod(context, pod_id, update_dict):
    with context.session.begin():
        return core.update_resource(context, models.Pod, pod_id, update_dict)


def change_pod_binding(context, pod_binding, pod_id):
    with context.session.begin():
        core.update_resource(context, models.PodBinding,
                             pod_binding['id'], pod_binding)
        core.create_resource(context, models.PodBinding,
                             {'id': uuidutils.generate_uuid(),
                              'tenant_id': pod_binding['tenant_id'],
                              'pod_id': pod_id,
                              'is_binding': True})


def get_pod_binding_by_tenant_id(context, filter_):
    with context.session.begin():
        return core.query_resource(context, models.PodBinding, filter_, [])


def get_pod_by_pod_id(context, pod_id):
    with context.session.begin():
        return core.get_resource(context, models.Pod, pod_id)


def create_pod_service_configuration(context, config_dict):
    with context.session.begin():
        return core.create_resource(context, models.PodServiceConfiguration,
                                    config_dict)


def create_pod_binding(context, tenant_id, pod_id):
    with context.session.begin():
        return core.create_resource(context, models.PodBinding,
                                    {'id': uuidutils.generate_uuid(),
                                     'tenant_id': tenant_id,
                                     'pod_id': pod_id,
                                     'is_binding': True})


def delete_pod_service_configuration(context, config_id):
    with context.session.begin():
        return core.delete_resource(context, models.PodServiceConfiguration,
                                    config_id)


def get_pod_service_configuration(context, config_id):
    with context.session.begin():
        return core.get_resource(context, models.PodServiceConfiguration,
                                 config_id)


def list_pod_service_configurations(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.PodServiceConfiguration,
                                   filters or [], sorts or [])


def update_pod_service_configuration(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, models.PodServiceConfiguration, config_id, update_dict)


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


def get_bottom_id_by_top_id_pod_name(context, top_id, pod_name, resource_type):
    """Get resource bottom id by top id and bottom pod name

    :param context: context object
    :param top_id: resource id on top
    :param pod_name: name of bottom pod
    :param resource_type: resource type
    :return:
    """
    mappings = get_bottom_mappings_by_top_id(context, top_id, resource_type)
    for pod, bottom_id in mappings:
        if pod['pod_name'] == pod_name:
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


def delete_mappings_by_top_id(context, top_id):
    with context.session.begin():
        core.delete_resources(
            context, models.ResourceRouting,
            filters=[{'key': 'top_id', 'comparator': 'eq',
                      'value': top_id}])


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
        if (pod['pod_name'] != '') and \
                (pod['az_name'] == ''):
            return pod

    return None


def get_pod_by_name(context, pod_name):

    filters = [{'key': 'pod_name', 'comparator': 'eq', 'value': pod_name}]
    pods = list_pods(context, filters=filters)

    # only one should be searched
    for pod in pods:
        if pod['pod_name'] == pod_name:
            return pod

    return None


def new_job(context, _type, resource_id):
    with context.session.begin():
        job_dict = {'id': uuidutils.generate_uuid(),
                    'type': _type,
                    'status': constants.JS_New,
                    'resource_id': resource_id,
                    'extra_id': uuidutils.generate_uuid()}
        job = core.create_resource(context, models.Job, job_dict)
        return job


def register_job(context, _type, resource_id):
    try:
        context.session.begin()
        job_dict = {'id': uuidutils.generate_uuid(),
                    'type': _type,
                    'status': constants.JS_Running,
                    'resource_id': resource_id,
                    'extra_id': constants.SP_EXTRA_ID}
        job = core.create_resource(context, models.Job, job_dict)
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


def get_latest_failed_jobs(context):
    jobs = []
    query = context.session.query(models.Job.type, models.Job.resource_id,
                                  sql.func.count(models.Job.id))
    query = query.group_by(models.Job.type, models.Job.resource_id)
    for job_type, resource_id, count in query:
        _query = context.session.query(models.Job)
        _query = _query.filter_by(type=job_type, resource_id=resource_id)
        _query = _query.order_by(sql.desc('timestamp'))
        # when timestamps of job entries are the same, sort entries by status
        # so "Fail" job is placed before "New" and "Success" jobs
        _query = _query.order_by(sql.asc('status'))
        latest_job = _query[0].to_dict()
        if latest_job['status'] == constants.JS_Fail:
            jobs.append(latest_job)
    return jobs


def get_latest_timestamp(context, status, _type, resource_id):
    jobs = core.query_resource(
        context, models.Job,
        [{'key': 'status', 'comparator': 'eq', 'value': status},
         {'key': 'type', 'comparator': 'eq', 'value': _type},
         {'key': 'resource_id', 'comparator': 'eq', 'value': resource_id}],
        [('timestamp', False)])
    if jobs:
        return jobs[0]['timestamp']
    else:
        return None


def get_running_job(context, _type, resource_id):
    jobs = core.query_resource(
        context, models.Job,
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
        core.update_resource(context, models.Job, job_id, job_dict)


_DEFAULT_QUOTA_NAME = 'default'


def _is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_quota_class_context(context, class_name):
    """Ensures a request has permission to access the given quota class."""
    if _is_user_context(context):
        if not context.quota_class:
            raise exceptions.NotAuthorized()
        elif context.quota_class != class_name:
            raise exceptions.NotAuthorized()


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
                LOG.warning(_LW("Deadlock detected when running "
                                "'%(func_name)s': Retrying..."),
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


@require_context
def _quota_get(context, project_id, resource, session=None):
    result = model_query(context, models.Quotas, session=session,
                         read_deleted="no").\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exceptions.ProjectQuotaNotFound(project_id=project_id)

    return result


@require_context
def quota_get(context, project_id, resource):
    return _quota_get(context, project_id, resource)


@require_context
def quota_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.Quotas, read_deleted="no").\
        filter_by(project_id=project_id).\
        all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_context
def quota_allocated_get_all_by_project(context, project_id):
    rows = model_query(context, models.Quotas, read_deleted='no').filter_by(
        project_id=project_id).all()
    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.allocated
    return result


@require_admin_context
def quota_create(context, project_id, resource, limit, allocated=0):
    quota_ref = models.Quotas()
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    if allocated:
        quota_ref.allocated = allocated

    session = core.get_session()
    with session.begin():
        quota_ref.save(session)
        return quota_ref


@require_admin_context
def quota_update(context, project_id, resource, limit):
    with context.session.begin():
        quota_ref = _quota_get(context, project_id, resource,
                               session=context.session)
        quota_ref.hard_limit = limit
        return quota_ref


@require_admin_context
def quota_allocated_update(context, project_id, resource, allocated):
    with context.session.begin():
        quota_ref = _quota_get(context, project_id, resource,
                               session=context.session)
        quota_ref.allocated = allocated
        return quota_ref


@require_admin_context
def quota_destroy(context, project_id, resource):
    with context.session.begin():
        quota_ref = _quota_get(context, project_id, resource,
                               session=context.session)
        quota_ref.delete(session=context.session)


@require_context
def _quota_class_get(context, class_name, resource, session=None):
    result = model_query(context, models.QuotaClasses, session=session,
                         read_deleted="no").\
        filter_by(class_name=class_name).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exceptions.QuotaClassNotFound(class_name=class_name)

    return result


@require_context
def quota_class_get(context, class_name, resource):
    return _quota_class_get(context, class_name, resource)


def quota_class_get_default(context):
    rows = model_query(context, models.QuotaClasses,
                       read_deleted="no").\
        filter_by(class_name=_DEFAULT_QUOTA_NAME).all()

    result = {'class_name': _DEFAULT_QUOTA_NAME}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_context
def quota_class_get_all_by_name(context, class_name):
    authorize_quota_class_context(context, class_name)

    rows = model_query(context, models.QuotaClasses, read_deleted="no").\
        filter_by(class_name=class_name).\
        all()

    result = {'class_name': class_name}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_class_create(context, class_name, resource, limit):
    quota_class_ref = models.QuotaClasses()
    quota_class_ref.class_name = class_name
    quota_class_ref.resource = resource
    quota_class_ref.hard_limit = limit

    session = core.get_session()
    with session.begin():
        quota_class_ref.save(session)
        return quota_class_ref


@require_admin_context
def quota_class_update(context, class_name, resource, limit):
    with context.session.begin():
        quota_class_ref = _quota_class_get(context, class_name, resource,
                                           session=context.session)
        quota_class_ref.hard_limit = limit

        return quota_class_ref


@require_admin_context
def quota_class_destroy(context, class_name, resource):
    with context.session.begin():
        quota_class_ref = _quota_class_get(context, class_name, resource,
                                           session=context.session)
        quota_class_ref.delete(session=context.session)


@require_admin_context
def quota_class_destroy_all_by_name(context, class_name):
    with context.session.begin():
        quota_classes = model_query(context, models.QuotaClasses,
                                    session=context.session,
                                    read_deleted="no").\
            filter_by(class_name=class_name).\
            all()

        for quota_class_ref in quota_classes:
            quota_class_ref.delete(session=context.session)


@require_context
def quota_usage_get(context, project_id, resource):
    result = model_query(context, models.QuotaUsages, read_deleted="no").\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exceptions.QuotaUsageNotFound(project_id=project_id)

    return result


@require_context
def quota_usage_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.QuotaUsages, read_deleted="no").\
        filter_by(project_id=project_id).\
        all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = dict(in_use=row.in_use, reserved=row.reserved)

    return result


@require_admin_context
def _quota_usage_create(context, project_id, resource, in_use, reserved,
                        until_refresh, session=None):

    quota_usage_ref = models.QuotaUsages()
    quota_usage_ref.project_id = project_id
    quota_usage_ref.resource = resource
    quota_usage_ref.in_use = in_use
    quota_usage_ref.reserved = reserved
    quota_usage_ref.until_refresh = until_refresh
    quota_usage_ref.save(session=session)

    return quota_usage_ref


def _reservation_create(context, uuid, usage, project_id, resource, delta,
                        expire, session=None):
    reservation_ref = models.Reservation()
    reservation_ref.uuid = uuid
    reservation_ref.usage_id = usage['id']
    reservation_ref.project_id = project_id
    reservation_ref.resource = resource
    reservation_ref.delta = delta
    reservation_ref.expire = expire
    reservation_ref.save(session=session)

    return reservation_ref


# NOTE(johannes): The quota code uses SQL locking to ensure races don't
# cause under or over counting of resources. To avoid deadlocks, this
# code always acquires the lock on quota_usages before acquiring the lock
# on reservations.

def _get_quota_usages(context, session, project_id):
    # Broken out for testability
    rows = model_query(context, models.QuotaUsages,
                       read_deleted="no",
                       session=session).\
        filter_by(project_id=project_id).\
        with_lockmode('update').\
        all()
    return {row.resource: row for row in rows}


def _get_quota_usages_by_resource(context, session, project_id, resource):
    # TODO(joehuang), add user_id as part of the filter
    rows = model_query(context, models.QuotaUsages,
                       read_deleted="no",
                       session=session).\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        with_lockmode('update').\
        all()
    return {row.resource: row for row in rows}


@require_context
@_retry_on_deadlock
def quota_reserve(context, resources, quotas, deltas, expire,
                  until_refresh, max_age, project_id=None):
    elevated = context.elevated()
    with context.session.begin():
        if project_id is None:
            project_id = context.project_id

        # Get the current usages
        usages = _get_quota_usages(context, context.session, project_id)

        # Handle usage refresh
        refresh = False
        work = set(deltas.keys())
        while work:
            resource = work.pop()

            # Do we need to refresh the usage?
            if resource not in usages:
                usages[resource] = _quota_usage_create(elevated,
                                                       project_id,
                                                       resource,
                                                       0, 0,
                                                       until_refresh or None,
                                                       session=context.session)
                refresh = True
            elif usages[resource].in_use < 0:
                # Negative in_use count indicates a desync, so try to
                # heal from that...
                refresh = True
            elif usages[resource].until_refresh is not None:
                usages[resource].until_refresh -= 1
                if usages[resource].until_refresh <= 0:
                    refresh = True
            elif max_age and usages[resource].updated_at is not None and (
                (usages[resource].updated_at -
                    timeutils.utcnow()).seconds >= max_age):
                refresh = True

            if refresh:
                # no actural usage refresh here

                # refresh from the bottom pod
                usages[resource].until_refresh = until_refresh or None

                # Because more than one resource may be refreshed
                # by the call to the sync routine, and we don't
                # want to double-sync, we make sure all refreshed
                # resources are dropped from the work set.
                work.discard(resource)

                # NOTE(Vek): We make the assumption that the sync
                #            routine actually refreshes the
                #            resources that it is the sync routine
                #            for.  We don't check, because this is
                #            a best-effort mechanism.

        # Check for deltas that would go negative
        unders = [r for r, delta in deltas.items()
                  if delta < 0 and delta + usages[r].in_use < 0]

        # Now, let's check the quotas
        # NOTE(Vek): We're only concerned about positive increments.
        #            If a project has gone over quota, we want them to
        #            be able to reduce their usage without any
        #            problems.
        overs = [r for r, delta in deltas.items()
                 if quotas[r] >= 0 and delta >= 0 and
                 quotas[r] < delta + usages[r].in_use + usages[r].reserved]

        # NOTE(Vek): The quota check needs to be in the transaction,
        #            but the transaction doesn't fail just because
        #            we're over quota, so the OverQuota raise is
        #            outside the transaction.  If we did the raise
        #            here, our usage updates would be discarded, but
        #            they're not invalidated by being over-quota.

        # Create the reservations
        if not overs:
            reservations = []
            for resource, delta in deltas.items():
                reservation = _reservation_create(elevated,
                                                  str(uuid.uuid4()),
                                                  usages[resource],
                                                  project_id,
                                                  resource, delta, expire,
                                                  session=context.session)
                reservations.append(reservation.uuid)

                # Also update the reserved quantity
                # NOTE(Vek): Again, we are only concerned here about
                #            positive increments.  Here, though, we're
                #            worried about the following scenario:
                #
                #            1) User initiates resize down.
                #            2) User allocates a new instance.
                #            3) Resize down fails or is reverted.
                #            4) User is now over quota.
                #
                #            To prevent this, we only update the
                #            reserved value if the delta is positive.
                if delta > 0:
                    usages[resource].reserved += delta

    if unders:
        LOG.warning(_LW("Change will make usage less than 0 for the following "
                        "resources: %s"), unders)
    if overs:
        usages = {k: dict(in_use=v['in_use'], reserved=v['reserved'])
                  for k, v in usages.items()}
        raise exceptions.OverQuota(overs=sorted(overs), quotas=quotas,
                                   usages=usages)

    return reservations


def _quota_reservations(session, context, reservations):
    """Return the relevant reservations."""

    # Get the listed reservations
    return model_query(context, models.Reservation,
                       read_deleted="no",
                       session=session).\
        filter(models.Reservation.uuid.in_(reservations)).\
        with_lockmode('update').\
        all()


@require_context
@_retry_on_deadlock
def reservation_commit(context, reservations, project_id=None):
    with context.session.begin():
        usages = _get_quota_usages(context, context.session, project_id)

        for reservation in _quota_reservations(context.session,
                                               context,
                                               reservations):
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta
            usage.in_use += reservation.delta

            reservation.delete(session=context.session)


@require_context
@_retry_on_deadlock
def reservation_rollback(context, reservations, project_id=None):
    with context.session.begin():
        usages = _get_quota_usages(context, context.session, project_id)

        for reservation in _quota_reservations(context.session,
                                               context,
                                               reservations):
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta

            reservation.delete(session=context.session)


def quota_destroy_by_project(*args, **kwargs):
    """Destroy all limit quotas associated with a project.

    Leaves usage and reservation quotas intact.
    """
    quota_destroy_all_by_project(only_quotas=True, *args, **kwargs)


@require_admin_context
@_retry_on_deadlock
def quota_destroy_all_by_project(context, project_id, only_quotas=False):
    """Destroy all quotas associated with a project.

    This includes limit quotas, usage quotas and reservation quotas.
    Optionally can only remove limit quotas and leave other types as they are.

    :param context: The request context, for access checks.
    :param project_id: The ID of the project being deleted.
    :param only_quotas: Only delete limit quotas, leave other types intact.
    """
    with context.session.begin():
        quotas = model_query(context, models.Quotas, session=context.session,
                             read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for quota_ref in quotas:
            quota_ref.delete(session=context.session)

        if only_quotas:
            return

        quota_usages = model_query(context, models.QuotaUsages,
                                   session=context.session,
                                   read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for quota_usage_ref in quota_usages:
            quota_usage_ref.delete(session=context.session)

        reservations = model_query(context, models.Reservation,
                                   session=context.session,
                                   read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for reservation_ref in reservations:
            reservation_ref.delete(session=context.session)


@require_admin_context
@_retry_on_deadlock
def reservation_expire(context):
    with context.session.begin():
        current_time = timeutils.utcnow()
        results = model_query(context, models.Reservation,
                              session=context.session,
                              read_deleted="no").\
            filter(models.Reservation.expire < current_time).\
            all()

        if results:
            for reservation in results:
                if reservation.delta >= 0:
                    reservation.usage.reserved -= reservation.delta
                    reservation.usage.save(session=context.session)

                reservation.delete(session=context.session)


def _dict_with_extra_specs_if_authorized(context, inst_type_query):
    """Convert type query result to dict with extra_spec and rate_limit.

    Takes a volume type query returned by sqlalchemy and returns it
    as a dictionary, converting the extra_specs entry from a list
    of dicts.

    NOTE:
    the contents of extra-specs are admin readable only.
    If the context passed in for this request is not about admin,
    we will return an empty extra-specs dict rather than
    providing extra-specs details.

    :param context: The request context, for access checks.
    :param inst_type_query: list of extra-specs.
    :returns dictionary of extra-specs.

    Example of response of admin context:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]
    to a single dict:
    'extra_specs' : {'k1': 'v1'}

    """

    inst_type_dict = dict(inst_type_query)
    if not context.is_admin:
        del (inst_type_dict['extra_specs'])
    else:
        extra_specs = {x['key']: x['value']
                       for x in inst_type_query['extra_specs']}
        inst_type_dict['extra_specs'] = extra_specs
    return inst_type_dict


@require_context
def _volume_type_get_by_name(context, name, session=None):
    result = model_query(context, models.VolumeTypes, session=session). \
        options(joinedload('extra_specs')). \
        filter_by(name=name). \
        first()

    if not result:
        raise exceptions.VolumeTypeNotFoundByName(volume_type_name=name)

    return _dict_with_extra_specs_if_authorized(context, result)


@require_context
def volume_type_get_by_name(context, name, session=None):
    """Return a dict describing specific volume_type.

    :param context: The request context, for access checks.
    :param name: The name of volume type to be found.
    :returns Volume type.
    """
    return _volume_type_get_by_name(context, name, session)


def _volume_type_get_query(context, session=None, read_deleted='no'):
    query = model_query(context, models.VolumeTypes,
                        session=session,
                        read_deleted=read_deleted). \
        options(joinedload('extra_specs'))

    if not context.is_admin:
        is_public = True
        the_filter = [models.VolumeTypes.is_public == is_public]
        query.filter(or_(*the_filter))

    return query


def _volume_type_get_db_object(context, id, session=None, inactive=False):
    read_deleted = "yes" if inactive else "no"
    result = _volume_type_get_query(
        context, session, read_deleted). \
        filter_by(id=id). \
        first()
    return result


@require_context
def _volume_type_get(context, id, session=None, inactive=False):
    result = _volume_type_get_db_object(context, id, session, inactive)

    if not result:
        raise exceptions.VolumeTypeNotFound(volume_type_id=id)

    vtype = _dict_with_extra_specs_if_authorized(context, result)

    return vtype


@require_context
def volume_type_get(context, id, inactive=False):
    """Return a dict describing specific volume_type.

    :param context: The request context, for access checks.
    :param id: The id of volume type to be found.
    :returns Volume type.
    """

    return _volume_type_get(context, id,
                            session=None,
                            inactive=inactive)


@require_context
def volume_type_delete(context, id, session):
    """delete a volume_type by id.

    :param context: The request context, for access checks.
    :param id: The id of volume type to be deleted.
    """
    model_query(context, models.VolumeTypes, session=session, read_deleted="no").\
        filter_by(id=id). \
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})

    model_query(context, models.VolumeTypeExtraSpecs, session=session, read_deleted="no"). \
        filter_by(volume_type_id=id). \
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


def is_valid_model_filters(model, filters):
    """Return True if filter values exist on the model

    :param model: a Cinder model
    :param filters: dictionary of filters
    """
    for key in filters.keys():
        if not hasattr(model, key):
            return False
    return True


def _process_volume_types_filters(query, filters):
    context = filters.pop('context', None)

    if filters.get('is_public'):
        the_filter = [models.VolumeTypes.is_public == filters['is_public']]

        if filters['is_public'] and context.project_id is not None:
            projects_attr = getattr(models.VolumeTypes, 'projects')
            the_filter.append(
                [projects_attr.any(project_id=context.project_id,
                                   deleted=0)])

        if len(the_filter) > 1:
            query = query.filter(or_(*the_filter))
        else:
            query = query.filter(the_filter[0])

    if 'is_public' in filters:
        del filters['is_public']

    if filters:
        # Ensure that filters' keys exist on the model
        if not is_valid_model_filters(models.VolumeTypes, filters):
            return

        if filters.get('extra_specs') is not None:
            the_filter = []
            searchdict = filters.get('extra_specs')
            extra_specs = getattr(models.VolumeTypes, 'extra_specs')
            for k, v in searchdict.items():
                the_filter.append([extra_specs.any(key=k, value=v,
                                                   deleted=False)])

            if len(the_filter) > 1:
                query = query.filter(and_(*the_filter))
            else:
                query = query.filter(the_filter[0])
            del filters['extra_specs']
        query = query.filter_by(**filters)
    return query


@require_context
def volume_type_get_all(context, inactive=False, filters=None,
                        list_result=False):
    """Returns a dict describing all volume_types with name as key.

    :param context: context to query under
    :param inactive: Pass true as argument if you want deleted volume types
                     returned also.
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_type_filters
                    function for more information
    :param list_result: For compatibility, if list_result = True, return
                        a list instead of dict.
    :returns: list/dict of matching volume types
    """
    read_deleted = 'yes' if inactive else 'no'
    session = core.get_session()
    with session.begin():
        filters = filters or {}
        filters['context'] = context
        # Generate the query
        query = _volume_type_get_query(context, session=session,
                                       read_deleted=read_deleted)
        query = _process_volume_types_filters(query, filters)

        # No volume types would match, return empty dict or list
        if query is None:
            if list_result:
                return []
            return {}

        rows = query.all()

        if list_result:
            result = [_dict_with_extra_specs_if_authorized(context, row)
                      for row in rows]
            return result
        result = {row['name']: _dict_with_extra_specs_if_authorized(context,
                                                                    row)
                  for row in rows}
        return result


@require_context
def _volume_type_ref_get(context, id, session=None, inactive=False):
    read_deleted = "yes" if inactive else "no"
    result = model_query(context,
                         models.VolumeTypes,
                         session=session,
                         read_deleted=read_deleted).\
        options(joinedload('extra_specs')).\
        filter_by(id=id).\
        first()

    if not result:
        raise exceptions.VolumeTypeNotFound(volume_type_id=id)

    return result


@handle_db_data_error
@require_admin_context
def volume_type_update(context, volume_type_id, values):
    """Update volume type by volume_type_id.

    :param volume_type_id: id of volume type to be updated
    :param values: dictionary of values to be updated
    :returns: updated volume type
    """
    session = core.get_session()
    with session.begin():
        try:
            # Check it exists
            volume_type_ref = _volume_type_ref_get(context,
                                                   volume_type_id,
                                                   session)
            if not volume_type_ref:
                raise exceptions.VolumeTypeNotFound(type_id=volume_type_id)

            # No description change
            if values['description'] is None:
                del values['description']

            # No is_public change
            if values['is_public'] is None:
                del values['is_public']

            # No name change
            if values['name'] is None:
                del values['name']
            else:
                # Volume type name is unique. If change to a name that
                # belongs to a different volume_type , it should be
                # prevented.
                check_vol_type = None
                try:
                    check_vol_type = \
                        volume_type_get_by_name(context,
                                                values['name'],
                                                session=session)
                except exceptions.VolumeTypeNotFoundByName:
                    pass
                else:
                    if check_vol_type.get('id') != volume_type_id:
                        raise exceptions.VolumeTypeExists(id=values['name'])

            volume_type_ref.update(values)
            volume_type_ref.save(session=session)
        except Exception:
            raise exceptions.VolumeTypeUpdateFailed(id=volume_type_id)

        return _dict_with_extra_specs_if_authorized(context, volume_type_ref)


@require_context
def volume_type_project_query(context, session=None, inactive=False,
                              filters=None):
    """Get a query of volume type project.

    :param context: context to query under
    :param inactive: Pass true as argument if you want deleted
           volume type projects returned also.
    :param filters: dictionary of filters.
    """
    read_deleted = "yes" if inactive else "no"
    filters = filters or {}
    return model_query(context, models.VolumeTypeProjects, session=session,
                       read_deleted=read_deleted).filter_by(**filters)


@require_context
def get_server_mappings_by_top_id(context, server_id):
    server_mappings = \
        get_bottom_mappings_by_top_id(context, server_id, constants.RT_SERVER)

    if not server_mappings:
        raise exceptions.ServerMappingsNotFound(server_id=server_id)

    return server_mappings


@require_context
def get_volume_mappings_by_top_id(context, volume_id):
    volume_mappings = \
        get_bottom_mappings_by_top_id(context, volume_id, constants.RT_VOLUME)

    if not volume_mappings:
        raise exceptions.VolumeMappingsNotFound(volume_id=volume_id)

    return volume_mappings
