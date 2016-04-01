# Copyright 2015 Huawei Technologies Co., Ltd.
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

"""
Routines for configuring tricircle, copy and modify from Cinder
"""

import datetime
import six

from oslo_config import cfg
import oslo_log.log as logging
from oslo_log import versionutils
from oslo_utils import importutils
from oslo_utils import timeutils

from keystoneclient import exceptions as k_exceptions

from tricircle.common import client
from tricircle.common import constants as cons
from tricircle.common import exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common import utils
from tricircle.db import api as db_api

quota_opts = [
    cfg.IntOpt('quota_instances',
               default=10,
               help='Number of instances allowed per project'),
    cfg.IntOpt('quota_cores',
               default=20,
               help='Number of instance cores allowed per project'),
    cfg.IntOpt('quota_ram',
               default=50 * 1024,
               help='Megabytes of instance RAM allowed per project'),
    cfg.IntOpt('quota_floating_ips',
               default=10,
               help='Number of floating IPs allowed per project'),
    cfg.IntOpt('quota_fixed_ips',
               default=-1,
               help='Number of fixed IPs allowed per project (this should be '
                    'at least the number of instances allowed)'),
    cfg.IntOpt('quota_metadata_items',
               default=128,
               help='Number of metadata items allowed per instance'),
    cfg.IntOpt('quota_injected_files',
               default=5,
               help='Number of injected files allowed'),
    cfg.IntOpt('quota_injected_file_content_bytes',
               default=10 * 1024,
               help='Number of bytes allowed per injected file'),
    cfg.IntOpt('quota_injected_file_path_length',
               default=255,
               help='Length of injected file path'),
    cfg.IntOpt('quota_security_groups',
               default=10,
               help='Number of security groups per project'),
    cfg.IntOpt('quota_security_group_rules',
               default=20,
               help='Number of security rules per security group'),
    cfg.IntOpt('quota_key_pairs',
               default=100,
               help='Number of key pairs per user'),
    cfg.IntOpt('quota_server_groups',
               default=10,
               help='Number of server groups per project'),
    cfg.IntOpt('quota_server_group_members',
               default=10,
               help='Number of servers per server group'),

    cfg.IntOpt('quota_volumes',
               default=10,
               help='Number of volumes allowed per project'),
    cfg.IntOpt('quota_snapshots',
               default=10,
               help='Number of volume snapshots allowed per project'),
    cfg.IntOpt('quota_consistencygroups',
               default=10,
               help='Number of consistencygroups allowed per project'),
    cfg.IntOpt('quota_gigabytes',
               default=1000,
               help='Total amount of storage, in gigabytes, allowed '
                    'for volumes and snapshots per project'),
    cfg.IntOpt('quota_backups',
               default=10,
               help='Number of volume backups allowed per project'),
    cfg.IntOpt('quota_backup_gigabytes',
               default=1000,
               help='Total amount of storage, in gigabytes, allowed '
                    'for backups per project'),
    cfg.IntOpt('per_volume_size_limit',
               default=-1,
               help='Max size allowed per volume, in gigabytes'),

    cfg.IntOpt('reservation_expire',
               default=86400,
               help='Number of seconds until a reservation expires'),
    cfg.IntOpt('until_refresh',
               default=0,
               help='Count of reservations until usage is refreshed. This '
                    'defaults to 0(off) to avoid additional load but it is '
                    'useful to turn on to help keep quota usage up to date '
                    'and reduce the impact of out of sync usage issues.'),
    cfg.IntOpt('max_age',
               default=0,
               help='Number of seconds between subsequent usage refreshes. '
                    'This defaults to 0(off) to avoid additional load but it '
                    'is useful to turn on to help keep quota usage up to date '
                    'and reduce the impact of out of sync usage issues. '
                    'Note that quotas are not updated on a periodic task, '
                    'they will update on a new reservation if max_age has '
                    'passed since the last reservation'),
    cfg.StrOpt('quota_driver',
               default='tricircle.common.quota.DbQuotaDriver',
               help='Default driver to use for quota checks'),
    cfg.BoolOpt('use_default_quota_class',
                default=True,
                help='Enables or disables use of default quota class '
                     'with default quota.'), ]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
quota_group = cfg.OptGroup(name='quota', title='quota defaults options')
cfg.CONF.register_group(quota_group)
CONF.register_opts(quota_opts, quota_group)

NON_QUOTA_KEYS = ['tenant_id', 'id']
DEFAULT_PROJECT = 'default'


class BaseResource(object):
    """Describe a single resource for quota checking."""

    def __init__(self, name, flag=None, parent_project_id=None):
        """Initializes a Resource.

        :param name: The name of the resource, i.e., "volumes".
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        self.name = name
        self.flag = flag
        self.parent_project_id = parent_project_id

    def quota(self, driver, context, **kwargs):
        """Given a driver and context, obtain the quota for this resource.

        :param driver: A quota driver.
        :param context: The request context.
        :param project_id: The project to obtain the quota value for.
                           If not provided, it is taken from the
                           context.  If it is given as None, no
                           project-specific quota will be searched
                           for.
        :param quota_class: The quota class corresponding to the
                            project, or for which the quota is to be
                            looked up.  If not provided, it is taken
                            from the context.  If it is given as None,
                            no quota class-specific quota will be
                            searched for.  Note that the quota class
                            defaults to the value in the context,
                            which may not correspond to the project if
                            project_id is not the same as the one in
                            the context.
        """

        # Get the project ID
        project_id = kwargs.get('project_id', context.project_id)

        # Ditto for the quota class
        quota_class = kwargs.get('quota_class', context.quota_class)

        # Look up the quota for the project
        if project_id:
            try:
                return driver.get_by_project(context, project_id, self.name)
            except t_exceptions.ProjectQuotaNotFound:
                pass

        # Try for the quota class
        if quota_class:
            try:
                return driver.get_by_class(context, quota_class, self.name)
            except t_exceptions.QuotaClassNotFound:
                pass

        # OK, return the default
        return driver.get_default(context, self,
                                  parent_project_id=self.parent_project_id)

    @property
    def default(self):
        """Return the default value of the quota."""

        if self.parent_project_id:
            return 0

        return CONF['quota'][self.flag] if self.flag else -1


class ReservableResource(BaseResource):
    """Describe a reservable resource."""

    def __init__(self, name, sync, flag=None):
        """Initializes a ReservableResource.

        Reservable resources are those resources which directly
        correspond to objects in the database, i.e., volumes, gigabytes,
        etc.  A ReservableResource must be constructed with a usage
        synchronization function, which will be called to determine the
        current counts of one or more resources.

        The usage synchronization function will be passed three
        arguments: an admin context, the project ID, and an opaque
        session object, which should in turn be passed to the
        underlying database function.  Synchronization functions
        should return a dictionary mapping resource names to the
        current in_use count for those resources; more than one
        resource and resource count may be returned.  Note that
        synchronization functions may be associated with more than one
        ReservableResource.

        :param name: The name of the resource, i.e., "volumes".
        :param sync: A dbapi methods name which returns a dictionary
                     to resynchronize the in_use count for one or more
                     resources, as described above.
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        """

        super(ReservableResource, self).__init__(name, flag=flag)
        if sync:
            self.sync = sync


class AbsoluteResource(BaseResource):
    """Describe a non-reservable resource."""

    pass


class CountableResource(AbsoluteResource):
    """Describe a resource where counts aren't based only on the project ID."""

    def __init__(self, name, count, flag=None):
        """Initializes a CountableResource.

        Countable resources are those resources which directly
        correspond to objects in the database, i.e., volumes, gigabytes,
        etc., but for which a count by project ID is inappropriate.  A
        CountableResource must be constructed with a counting
        function, which will be called to determine the current counts
        of the resource.

        The counting function will be passed the context, along with
        the extra positional and keyword arguments that are passed to
        Quota.count().  It should return an integer specifying the
        count.

        Note that this counting is not performed in a transaction-safe
        manner.  This resource class is a temporary measure to provide
        required functionality, until a better approach to solving
        this problem can be evolved.

        :param name: The name of the resource, i.e., "volumes".
        :param count: A callable which returns the count of the
                      resource.  The arguments passed are as described
                      above.
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        """

        super(CountableResource, self).__init__(name, flag=flag)
        self.count = count


# TODO(joehuang) support volume_type based quota in the future

class VolumeTypeResource(ReservableResource):
    """ReservableResource for a specific volume type."""

    def __init__(self, part_name, volume_type):
        """Initializes a VolumeTypeResource.

        :param part_name: The kind of resource, i.e., "volumes".
        :param volume_type: The volume type for this resource.
        """

        self.volume_type_name = volume_type['name']
        self.volume_type_id = volume_type['id']
        name = "%s_%s" % (part_name, self.volume_type_name)
        super(VolumeTypeResource, self).__init__(name, "_sync_%s" % part_name)


class DbQuotaDriver(object):

    """Driver to perform check to enforcement of quotas.

    Also allows to obtain quota information.
    The default driver utilizes the local database.
    """

    def get_by_project(self, context, project_id, resource_name):
        """Get a specific quota by project."""

        return db_api.quota_get(context, project_id, resource_name)

    def get_by_class(self, context, quota_class, resource_name):
        """Get a specific quota by quota class."""

        return db_api.quota_class_get(context, quota_class, resource_name)

    def get_default(self, context, resource, parent_project_id=None):
        """Get a specific default quota for a resource.

        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        default_quotas = db_api.quota_class_get_default(context)
        default_quota_value = 0 if parent_project_id else resource.default
        return default_quotas.get(resource.name, default_quota_value)

    def get_defaults(self, context, resources, parent_project_id=None):
        """Given a list of resources, retrieve the default quotas.

        Use the class quotas named `_DEFAULT_QUOTA_NAME` as default quotas,
        if it exists.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        quotas = {}
        default_quotas = {}
        if CONF.quota.use_default_quota_class and not parent_project_id:
            default_quotas = db_api.quota_class_get_default(context)

        for resource in resources.values():
            if default_quotas:
                if resource.name not in default_quotas:
                    versionutils.report_deprecated_feature(LOG, _(
                        "Default quota for resource: %(res)s is set "
                        "by the default quota flag: quota_%(res)s, "
                        "it is now deprecated. Please use the "
                        "default quota class for default "
                        "quota.") % {'res': resource.name})
            quotas[resource.name] = default_quotas.get(resource.name,
                                                       (0 if parent_project_id
                                                        else resource.default))
        return quotas

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        """Given list of resources, retrieve the quotas for given quota class.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param quota_class: The name of the quota class to return
                            quotas for.
        :param defaults: If True, the default value will be reported
                         if there is no specific value for the
                         resource.
        """

        quotas = {}
        default_quotas = {}
        class_quotas = db_api.quota_class_get_all_by_name(context, quota_class)
        if defaults:
            default_quotas = db_api.quota_class_get_default(context)
        for resource in resources.values():
            if resource.name in class_quotas:
                quotas[resource.name] = class_quotas[resource.name]
                continue

            if defaults:
                quotas[resource.name] = default_quotas.get(resource.name,
                                                           resource.default)

        return quotas

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True,
                           usages=True, parent_project_id=None):
        """Retrieve quotas for a project.

        Given a list of resources, retrieve the quotas for the given
        project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.  It
                            will be ignored if project_id ==
                            context.project_id.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use, reserved and allocated
                       counts will also be returned.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        quotas = {}
        project_quotas = db_api.quota_get_all_by_project(context, project_id)
        if usages:
            project_usages = db_api.quota_usage_get_all_by_project(context,
                                                                   project_id)
            allocated_quotas = db_api.quota_allocated_get_all_by_project(
                context, project_id)
            allocated_quotas.pop('project_id')

        # Get the quotas for the appropriate class.  If the project ID
        # matches the one in the context, we use the quota_class from
        # the context, otherwise, we use the provided quota_class (if
        # any)
        if project_id == context.project_id:
            quota_class = context.quota_class
        if quota_class:
            class_quotas = db_api.quota_class_get_all_by_name(context,
                                                              quota_class)
        else:
            class_quotas = {}

        default_quotas = self.get_defaults(context, resources,
                                           parent_project_id=parent_project_id)

        for resource in resources.values():
            # Omit default/quota class values
            if not defaults and resource.name not in project_quotas:
                continue

            quotas[resource.name] = dict(
                limit=project_quotas.get(
                    resource.name,
                    class_quotas.get(resource.name,
                                     default_quotas[resource.name])),
            )

            # Include usages if desired.  This is optional because one
            # internal consumer of this interface wants to access the
            # usages directly from inside a transaction.
            if usages:
                usage = project_usages.get(resource.name, {})
                quotas[resource.name].update(
                    in_use=usage.get('in_use', 0),
                    reserved=usage.get('reserved', 0), )

                if parent_project_id or allocated_quotas:
                    quotas[resource.name].update(
                        allocated=allocated_quotas.get(resource.name, 0), )

        return quotas

    def _get_quotas(self, context, resources, keys, has_sync, project_id=None,
                    parent_project_id=None):
        """A helper method which retrieves the quotas for specific resources.

        This specific resource is identified by keys, and which apply to the
        current context.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param keys: A list of the desired quotas to retrieve.
        :param has_sync: If True, indicates that the resource must
                         have a sync attribute; if False, indicates
                         that the resource must NOT have a sync
                         attribute.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        # Filter resources
        if has_sync:
            sync_filt = lambda x: hasattr(x, 'sync')
        else:
            sync_filt = lambda x: not hasattr(x, 'sync')
        desired = set(keys)
        sub_resources = {k: v for k, v in resources.items()
                         if k in desired and sync_filt(v)}

        # Make sure we accounted for all of them...
        if len(keys) != len(sub_resources):
            unknown = desired - set(sub_resources.keys())
            raise t_exceptions.QuotaResourceUnknown(unknown=sorted(unknown))

        # Grab and return the quotas (without usages)
        quotas = self.get_project_quotas(context, sub_resources,
                                         project_id,
                                         context.quota_class, usages=False,
                                         parent_project_id=parent_project_id)

        return {k: v['limit'] for k, v in quotas.items()}

    def limit_check(self, context, resources, values, project_id=None):
        """Check simple quota limits.

        For limits--those quotas for which there is no usage
        synchronization function--this method checks that a set of
        proposed values are permitted by the limit restriction.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it is not a simple limit
        resource.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns
        nothing.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param values: A dictionary of the values to check against the
                       quota.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        # Ensure no value is less than zero
        unders = [key for key, val in values.items() if val < 0]
        if unders:
            raise t_exceptions.InvalidQuotaValue(unders=sorted(unders))

        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id

        # Get the applicable quotas
        quotas = self._get_quotas(context, resources, values.keys(),
                                  has_sync=False, project_id=project_id)
        # Check the quotas and construct a list of the resources that
        # would be put over limit by the desired values
        overs = [key for key, val in values.items()
                 if quotas[key] >= 0 and quotas[key] < val]
        if overs:
            raise t_exceptions.OverQuota(overs=sorted(overs), quotas=quotas,
                                         usages={})

    def reserve(self, context, resources, deltas, expire=None,
                project_id=None):
        """Check quotas and reserve resources.

        For counting quotas--those quotas for which there is a usage
        synchronization function--this method checks quotas against
        current usage and the desired deltas.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it does not have a usage
        synchronization function.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns a
        list of reservation UUIDs which were created.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param deltas: A dictionary of the proposed delta changes.
        :param expire: An optional parameter specifying an expiration
                       time for the reservations.  If it is a simple
                       number, it is interpreted as a number of
                       seconds and added to the current time; if it is
                       a datetime.timedelta object, it will also be
                       added to the current time.  A datetime.datetime
                       object will be interpreted as the absolute
                       expiration time.  If None is specified, the
                       default expiration time set by
                       --default-reservation-expire will be used (this
                       value will be treated as a number of seconds).
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        # Set up the reservation expiration
        if expire is None:
            expire = CONF.quota.reservation_expire
        if isinstance(expire, six.integer_types):
            expire = datetime.timedelta(seconds=expire)
        if isinstance(expire, datetime.timedelta):
            expire = timeutils.utcnow() + expire
        if not isinstance(expire, datetime.datetime):
            raise t_exceptions.InvalidReservationExpiration(expire=expire)

        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id

        # Get the applicable quotas.
        # NOTE(Vek): We're not worried about races at this point.
        #            Yes, the admin may be in the process of reducing
        #            quotas, but that's a pretty rare thing.

        # NOTE(joehuang): in Tricircle, no embeded sync function here,
        # so set has_sync=False.
        quotas = self._get_quotas(context, resources, deltas.keys(),
                                  has_sync=False, project_id=project_id)

        # NOTE(Vek): Most of the work here has to be done in the DB
        #            API, because we have to do it in a transaction,
        #            which means access to the session.  Since the
        #            session isn't available outside the DBAPI, we
        #            have to do the work there.
        return db_api.quota_reserve(context, resources, quotas, deltas,
                                    expire, CONF.quota.until_refresh,
                                    CONF.quota.max_age,
                                    project_id=project_id)

    def commit(self, context, reservations, project_id=None):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """
        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id

        db_api.reservation_commit(context, reservations, project_id=project_id)

    def rollback(self, context, reservations, project_id=None):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """
        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id

        db_api.reservation_rollback(context, reservations,
                                    project_id=project_id)

    def destroy_by_project(self, context, project_id):
        """Destroy all limit quotas associated with a project.

        Leave usage and reservation quotas intact.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        """
        db_api.quota_destroy_by_project(context, project_id)

    def expire(self, context):
        """Expire reservations.

        Explores all currently existing reservations and rolls back
        any that have expired.

        :param context: The request context, for access checks.
        """

        db_api.reservation_expire(context)


class QuotaEngine(object):
    """Represent the set of recognized quotas."""

    def __init__(self, quota_driver_class=None):
        """Initialize a Quota object."""

        if not quota_driver_class:
            quota_driver_class = CONF.quota.quota_driver

        if isinstance(quota_driver_class, six.string_types):
            quota_driver_class = importutils.import_object(quota_driver_class)

        self._resources = {}
        self._driver = quota_driver_class

    def __contains__(self, resource):
        return resource in self.resources

    def register_resource(self, resource):
        """Register a resource."""

        self._resources[resource.name] = resource

    def register_resources(self, resources):
        """Register a list of resources."""

        for resource in resources:
            self.register_resource(resource)

    def get_by_project(self, context, project_id, resource_name):
        """Get a specific quota by project."""

        return self._driver.get_by_project(context, project_id, resource_name)

    def get_by_class(self, context, quota_class, resource_name):
        """Get a specific quota by quota class."""

        return self._driver.get_by_class(context, quota_class, resource_name)

    def get_default(self, context, resource, parent_project_id=None):
        """Get a specific default quota for a resource.

        :param parent_project_id: The id of the current project's parent,
                                          if any.
        """

        return self._driver.get_default(context, resource,
                                        parent_project_id=parent_project_id)

    def get_defaults(self, context, parent_project_id=None):
        """Retrieve the default quotas.

        :param context: The request context, for access checks.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        return self._driver.get_defaults(context, self.resources,
                                         parent_project_id)

    def get_class_quotas(self, context, quota_class, defaults=True):
        """Retrieve the quotas for the given quota class.

        :param context: The request context, for access checks.
        :param quota_class: The name of the quota class to return
                            quotas for.
        :param defaults: If True, the default value will be reported
                         if there is no specific value for the
                         resource.
        """

        return self._driver.get_class_quotas(context, self.resources,
                                             quota_class, defaults=defaults)

    def get_project_quotas(self, context, project_id, quota_class=None,
                           defaults=True, usages=True, parent_project_id=None):
        """Retrieve the quotas for the given project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use, reserved and
                       allocated counts will also be returned.
        :param parent_project_id: The id of the current project's parent,
                                  if any.
        """

        return self._driver.get_project_quotas(
            context, self.resources,
            project_id,
            quota_class=quota_class,
            defaults=defaults,
            usages=usages,
            parent_project_id=parent_project_id)

    def count(self, context, resource, *args, **kwargs):
        """Count a resource.

        For countable resources, invokes the count() function and
        returns its result.  Arguments following the context and
        resource are passed directly to the count function declared by
        the resource.

        :param context: The request context, for access checks.
        :param resource: The name of the resource, as a string.
        """

        # Get the resource
        res = self.resources.get(resource)
        if not res or not hasattr(res, 'count'):
            raise t_exceptions.QuotaResourceUnknown(unknown=[resource])

        # TODO(joehuang): count will be calculated from bottom quota usage
        if res.count:
            return res.count(context, *args, **kwargs)
        else:
            return 0

    def limit_check(self, context, project_id=None, **values):
        """Check simple quota limits.

        For limits--those quotas for which there is no usage
        synchronization function--this method checks that a set of
        proposed values are permitted by the limit restriction.  The
        values to check are given as keyword arguments, where the key
        identifies the specific quota limit to check, and the value is
        the proposed value.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it is not a simple limit
        resource.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns
        nothing.

        :param context: The request context, for access checks.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        return self._driver.limit_check(context, self.resources, values,
                                        project_id=project_id)

    def reserve(self, context, expire=None, project_id=None, **deltas):
        """Check quotas and reserve resources.

        For counting quotas--those quotas for which there is a usage
        synchronization function--this method checks quotas against
        current usage and the desired deltas.  The deltas are given as
        keyword arguments, and current usage and other reservations
        are factored into the quota check.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it does not have a usage
        synchronization function.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns a
        list of reservation UUIDs which were created.

        :param context: The request context, for access checks.
        :param expire: An optional parameter specifying an expiration
                       time for the reservations.  If it is a simple
                       number, it is interpreted as a number of
                       seconds and added to the current time; if it is
                       a datetime.timedelta object, it will also be
                       added to the current time.  A datetime.datetime
                       object will be interpreted as the absolute
                       expiration time.  If None is specified, the
                       default expiration time set by
                       --default-reservation-expire will be used (this
                       value will be treated as a number of seconds).
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        reservations = self._driver.reserve(context, self.resources, deltas,
                                            expire=expire,
                                            project_id=project_id)

        LOG.debug("Created reservations %s", reservations)

        return reservations

    def commit(self, context, reservations, project_id=None):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        try:
            self._driver.commit(context, reservations, project_id=project_id)
        except Exception as e:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.

            msg = str(e)
            LOG.exception(_LE("Failed to commit reservations"
                              " %(reservations)s, exception %(msg)s"),
                          {'reservations': reservations, 'msg': msg})

    def rollback(self, context, reservations, project_id=None):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        try:
            self._driver.rollback(context, reservations, project_id=project_id)
        except Exception as e:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.
            msg = str(e)
            LOG.exception(_LE("Failed to roll back reservations"
                              " %(reservations)s, exception %(msg)s"),
                          {'reservations': reservations, 'msg': msg})

    def destroy_by_project(self, context, project_id):
        """Destroy all quota limits associated with a project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        """

        self._driver.destroy_by_project(context, project_id)

    def expire(self, context):
        """Expire reservations.

        Explores all currently existing reservations and rolls back
        any that have expired.

        :param context: The request context, for access checks.
        """

        self._driver.expire(context)

    def add_volume_type_opts(self, context, opts, volume_type_id):
        """Add volume type resource options.

        Adds elements to the opts hash for volume type quotas.
        If a resource is being reserved ('gigabytes', etc) and the volume
        type is set up for its own quotas, these reservations are copied
        into keys for 'gigabytes_<volume type name>', etc.

        :param context: The request context, for access checks.
        :param opts: The reservations options hash.
        :param volume_type_id: The volume type id for this reservation.
        """
        if not volume_type_id:
            return

        # NOTE(jdg): set inactive to True in volume_type_get, as we
        # may be operating on a volume that was created with a type
        # that has since been deleted.

        # quota based on volume_type is not supported currently
        # volume_type = db_api.volume_type_get(context, volume_type_id, True)

        # for quota in ('volumes', 'gigabytes', 'snapshots'):
        #     if quota in opts:
        #         vtype_quota = "%s_%s" % (quota, volume_type['name'])
        #         opts[vtype_quota] = opts[quota]

    @property
    def resource_names(self):
        return sorted(self.resources.keys())

    @property
    def resources(self):
        return self._resources


class AllQuotaEngine(QuotaEngine):
    """Represent the set of all quotas."""

    @property
    def resources(self):
        """Fetches all possible quota resources."""

        result = {}

        # Global quotas.
        # Set sync_func to None for no sync function in Tricircle
        reservable_argses = [

            ('instances', None, 'quota_instances'),
            ('cores', None, 'quota_cores'),
            ('ram', None, 'quota_ram'),
            ('security_groups', None, 'quota_security_groups'),
            ('floating_ips', None, 'quota_floating_ips'),
            ('fixed_ips', None, 'quota_fixed_ips'),
            ('server_groups', None, 'quota_server_groups'),


            ('volumes', None, 'quota_volumes'),
            ('per_volume_gigabytes', None, 'per_volume_size_limit'),
            ('snapshots', None, 'quota_snapshots'),
            ('gigabytes', None, 'quota_gigabytes'),
            ('backups', None, 'quota_backups'),
            ('backup_gigabytes', None, 'quota_backup_gigabytes'),
            ('consistencygroups', None, 'quota_consistencygroups')
        ]

        absolute_argses = [
            ('metadata_items', 'quota_metadata_items'),
            ('injected_files', 'quota_injected_files'),
            ('injected_file_content_bytes',
             'quota_injected_file_content_bytes'),
            ('injected_file_path_bytes',
             'quota_injected_file_path_length'),
        ]

        # TODO(joehuang), for countable, the count should be the
        # value in the db but not 0 here
        countable_argses = [
            ('security_group_rules', None, 'quota_security_group_rules'),
            ('key_pairs', None, 'quota_key_pairs'),
            ('server_group_members', None, 'quota_server_group_members'),
        ]

        for args in reservable_argses:
            resource = ReservableResource(*args)
            result[resource.name] = resource

        for args in absolute_argses:
            resource = AbsoluteResource(*args)
            result[resource.name] = resource

        for args in countable_argses:
            resource = CountableResource(*args)
            result[resource.name] = resource

        return result

    def register_resource(self, resource):
        raise NotImplementedError(_("Cannot register resource"))

    def register_resources(self, resources):
        raise NotImplementedError(_("Cannot register resources"))


QUOTAS = AllQuotaEngine()


class QuotaSetOperation(object):
    """Operation on Quota set."""

    def __init__(self, target_tenant_id, user_id=None):
        self.target_tenant_id = target_tenant_id
        self.user_id = user_id

    # used in test
    def update_hierarchy(self, target_tenant_id, user_id=None):
        self.target_tenant_id = target_tenant_id
        self.user_id = user_id

    class GenericProjectInfo(object):

        """Abstraction layer for Keystone V2 and V3 project objects"""

        def __init__(self, project_id, project_keystone_api_version,
                     project_parent_id=None, project_subtree=None):
            self.id = project_id
            self.keystone_api_version = project_keystone_api_version
            self.parent_id = project_parent_id
            self.subtree = project_subtree

    def _format_quota_set(self, tenant_id, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(tenant_id)

        return dict(quota_set=quota_set)

    def _keystone_client(self, context):
        c = client.Client()
        return c.get_keystone_client_by_context(context)

    def _validate_existing_resource(self, key, value, quota_values):
        if key == 'per_volume_gigabytes':
            return
        v = quota_values.get(key, {})
        _usage = v.get('in_use', 0) + v.get('reserved', 0)
        if value < _usage:
            msg = _("Quota %(key)s limit %(value)d must be equal or "
                    "greater than existing resources"
                    "%(_usage)d.") % {'key': key, 'value': value,
                                      '_usage': _usage}
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

    @staticmethod
    def _validate_integer(value, name, min_value=None, max_value=None):
        """Make sure that value is a valid integer, potentially within range.

        :param value: the value of the integer
        :param name: the name of the integer
        :param min_length: the min_length of the integer
        :param max_length: the max_length of the integer
        :returns: integer
        """
        try:
            value = int(value)
        except (TypeError, ValueError, UnicodeEncodeError):
            msg = _('%s must be an integer.') % name
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

        if min_value is not None and value < min_value:
            msg = _('%(value_name)s must be >= '
                    '%(min_value)d') % {'value_name': name,
                                        'min_value': min_value}
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

        if max_value is not None and value > max_value:
            msg = _('%(value_name)s must be <= '
                    '%(max_value)d') % {'value_name': name,
                                        'max_value': max_value}
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

        return value

    def _validate_quota_limit(self, quota, key, project_quotas=None,
                              parent_project_quotas=None):
        limit = self._validate_integer(quota[key], key, min_value=-1,
                                       max_value=cons.MAX_INT)

        if parent_project_quotas:
            free_quota = (parent_project_quotas[key]['limit'] -
                          parent_project_quotas[key]['in_use'] -
                          parent_project_quotas[key]['reserved'] -
                          parent_project_quotas[key].get('allocated', 0))

            current = 0
            if project_quotas.get(key):
                current = project_quotas[key]['limit']

            if limit - current > free_quota:
                msg = _("Free quota available is %s.") % free_quota
                LOG.error(msg=msg)
                raise t_exceptions.ValidationError(msg=msg)

        return limit

    def _get_quotas(self, context, id, usages=False, parent_project_id=None):
        values = QUOTAS.get_project_quotas(
            context, id, usages=usages,
            parent_project_id=parent_project_id)

        if usages:
            return values
        else:
            return {k: v['limit'] for k, v in values.items()}

    def _authorize_update_or_delete(self, context_project,
                                    target_project_id,
                                    parent_id):
        """Checks if update or delete are allowed in the current hierarchy.

        With hierarchical projects, only the admin of the parent or the root
        project has privilege to perform quota update and delete operations.

        :param context_project: The project in which the user is scoped to.
        :param target_project_id: The id of the project in which the
                                  user want to perform an update or
                                  delete operation.
        :param parent_id: The parent id of the project in which the user
                          want to perform an update or delete operation.
        """

        param_msg = _("context_project.parent_id = %(ctx_parent_id)s, "
                      "parent_id = %(parent_id)s, "
                      "context_project.id = %(ctx_project_id)s, "
                      "target_project_id = "
                      "%(target_project_id)s, ") % {
            "ctx_parent_id": context_project.parent_id,
            "parent_id": parent_id,
            "ctx_project_id": context_project.id,
            "target_project_id": target_project_id}

        if context_project.parent_id and parent_id != context_project.id:
            msg = _("Update and delete quota operations can only be made "
                    "by an admin of immediate parent or by the CLOUD admin."
                    "%s") % param_msg

            LOG.error(msg=msg)
            raise t_exceptions.HTTPForbiddenError(msg=msg)

        if context_project.id != target_project_id:
            if not self._is_descendant(target_project_id,
                                       context_project.subtree):
                msg = _("Update and delete quota operations can only be made "
                        "to projects in the same hierarchy of the project in "
                        "which users are scoped to."
                        "%s") % param_msg
                LOG.error(msg=msg)
                raise t_exceptions.HTTPForbiddenError(msg=msg)
        else:
            msg = _("Update and delete quota operations can only be made "
                    "by an admin of immediate parent or by the CLOUD admin."
                    "%s") % param_msg
            LOG.error(msg=msg)
            raise t_exceptions.HTTPForbiddenError(msg=msg)

    def _authorize_show(self, context_project, target_project):
        """Checks if show is allowed in the current hierarchy.

        With hierarchical projects, are allowed to perform quota show operation
        users with admin role in, at least, one of the following projects: the
        current project; the immediate parent project; or the root project.

        :param context_project: The project in which the user
                                is scoped to.
        :param target_project: The project in which the user wants
                               to perform a show operation.
        """

        param_msg = _("target_project.parent_id = %(target_parent_id)s, "
                      "target_project_id = %(target_project_id)s, "
                      "context_project.id = %(ctx_project_id)s, "
                      "context_project.parent_id = %(ctx_parent_id)s, ") % {
            "target_parent_id": target_project.parent_id,
            "target_project_id": target_project.id,
            "ctx_project_id": context_project.id,
            "ctx_parent_id": context_project.parent_id}

        if target_project.parent_id:
            if target_project.id != context_project.id:
                if not self._is_descendant(target_project.id,
                                           context_project.subtree):
                    msg = _("Show operations can only be made to projects in "
                            "the same hierarchy of the project in which users "
                            "are scoped to."
                            "%s") % param_msg
                    LOG.error(msg=msg)
                    raise t_exceptions.HTTPForbiddenError(msg=msg)

                if context_project.id != target_project.parent_id:
                    if context_project.parent_id:
                        msg = _("Only users with token scoped to immediate "
                                "parents or root projects are allowed to see "
                                "its children quotas."
                                "%s") % param_msg
                        LOG.error(msg=msg)
                        raise t_exceptions.HTTPForbiddenError(msg=msg)

        elif context_project.parent_id:
            msg = _("An user with a token scoped to a subproject is not "
                    "allowed to see the quota of its parents."
                    "%s") % param_msg
            LOG.error(msg=msg)
            raise t_exceptions.HTTPForbiddenError(msg=msg)

    def _is_descendant(self, target_project_id, subtree):
        if subtree is not None:
            for key, value in subtree.items():
                if key == target_project_id:
                    return True
                if self._is_descendant(target_project_id, value):
                    return True
        return False

    def _get_project(self, context, id, subtree_as_ids=False):
        """A Helper method to get the project hierarchy.

        Along with Hierachical Multitenancy in keystone API v3, projects can be
        hierarchically organized. Therefore, we need to know the project
        hierarchy, if any, in order to do quota operations properly.
        """
        try:
            keystone = self._keystone_client(context)
            generic_project = self.GenericProjectInfo(id, keystone.version)
            if keystone.version == 'v3':
                project = keystone.projects.get(id,
                                                subtree_as_ids=subtree_as_ids)
                generic_project.parent_id = project.parent_id

                # all projects in KeyStone will be put under the parent
                # 'default' if not specifying the parent project id when
                # creating project
                if generic_project.parent_id == DEFAULT_PROJECT:
                    generic_project.parent_id = None

                generic_project.subtree = (
                    project.subtree if subtree_as_ids else None)

        except k_exceptions.NotFound:
            msg = _("Tenant ID: %s does not exist.") % id
            LOG.error(msg=msg)
            raise t_exceptions.NotFound()

        return generic_project

    def update(self, context, **kw):

        if not context.is_admin:
            raise t_exceptions.AdminRequired

        quota_set = kw.get('quota_set')
        if not quota_set:
            raise t_exceptions.InvalidInput(reason='no quota_set')

        # TODO(joehuang): process is_force flag here

        # Get the optional argument 'skip_validation' from body,
        # if skip_validation is False, then validate existing resource.
        skip_flag = kw.get('skip_validation', True)
        if not utils.is_valid_boolstr(skip_flag):
            msg = _("Invalid value '%s' for skip_validation.") % skip_flag
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

        skip_flag = utils.bool_from_string(skip_flag)

        target_project_id = self.target_tenant_id
        bad_keys = []

        # NOTE(ankit): Pass #1 - In this loop for body['quota_set'].items(),
        # we figure out if we have any bad keys.
        for key, value in kw['quota_set'].items():
            if (key not in QUOTAS and key not in NON_QUOTA_KEYS):
                bad_keys.append(key)
                continue

        if len(bad_keys) > 0:
            msg = _("Bad key(s) in quota set: %s") % ",".join(bad_keys)
            LOG.error(msg=msg)
            raise t_exceptions.ValidationError(msg=msg)

        # Get the parent_id of the target project to verify whether we are
        # dealing with hierarchical namespace or non-hierarchical namespace.
        target_project = self._get_project(context, target_project_id)
        parent_id = target_project.parent_id

        context_project = self._get_project(context,
                                            context.project_id,
                                            subtree_as_ids=True)
        if parent_id:
            # Get the children of the project which the token is scoped to
            # in order to know if the target_project is in its hierarchy.
            self._authorize_update_or_delete(context_project,
                                             target_project.id,
                                             parent_id)
            parent_project_quotas = QUOTAS.get_project_quotas(
                context, parent_id)

        else:

            # if the target project has no parent and descendant, then
            # the operation is allowed only if the context project also
            # has no parent and descendant, that means only flat mode
            # (current mode without hierarchy) is allowed

            if not target_project.subtree and \
                    not context_project.parent_id and \
                    not context_project.subtree:
                pass
            elif context.project_id != target_project_id:
                param_msg = _("context.project_id = %(ctx_project_id)s, "
                              "target_project_id = %(target_project_id)s ") % {
                    "ctx_project_id": context.project_id,
                    "target_project_id": target_project.id}

                msg = _("Can not update quota for %s") % param_msg
                LOG.error(msg=msg)
                raise t_exceptions.HTTPForbiddenError(msg=msg)

        # NOTE(ankit): Pass #2 - In this loop for body['quota_set'].keys(),
        # we validate the quota limits to ensure that we can bail out if
        # any of the items in the set is bad. Meanwhile we validate value
        # to ensure that the value can't be lower than number of existing
        # resources.
        quota_values = QUOTAS.get_project_quotas(context, target_project_id,
                                                 defaults=False)
        valid_quotas = {}
        allocated_quotas = {}
        for key in kw['quota_set'].keys():
            if key in NON_QUOTA_KEYS:
                continue

            value = kw['quota_set'][key]
            if not skip_flag:
                self._validate_existing_resource(key, value, quota_values)

            if parent_id:
                value = self._validate_quota_limit(kw['quota_set'], key,
                                                   quota_values,
                                                   parent_project_quotas)
                original_quota = 0
                if quota_values.get(key):
                    original_quota = quota_values[key]['limit']

                allocated_quotas[key] = (
                    parent_project_quotas[key].get('allocated', 0) + value -
                    original_quota)
            else:
                value = self._validate_quota_limit(kw['quota_set'], key)
            valid_quotas[key] = value

        # NOTE(ankit): Pass #3 - At this point we know that all the keys and
        # values are valid and we can iterate and update them all in one shot
        # without having to worry about rolling back etc as we have done
        # the validation up front in the 2 loops above.
        for key, value in valid_quotas.items():
            try:

                # TODO(joehuang) support quota by user
                db_api.quota_update(context, target_project_id, key, value)
            except t_exceptions.ProjectQuotaNotFound:

                # TODO(joehuang) support quota by user
                db_api.quota_create(context, target_project_id, key, value)
            except t_exceptions.AdminRequired:
                raise

            # If hierarchical projects, update child's quota first
            # and then parents quota. In future this needs to be an
            # atomic operation.
            if parent_id:
                if key in allocated_quotas.keys():
                    try:

                        # TODO(joehuang) support quota by user
                        db_api.quota_allocated_update(context, parent_id, key,
                                                      allocated_quotas[key])
                    except t_exceptions.ProjectQuotaNotFound:
                        parent_limit = parent_project_quotas[key]['limit']

                        # TODO(joehuang) support quota by user
                        db_api.quota_create(context, parent_id, key,
                                            parent_limit,
                                            allocated=allocated_quotas[key])

        return {'quota_set': self._get_quotas(context, target_project_id,
                                              parent_project_id=parent_id)}

    def delete(self, context):
        """Delete Quota for a particular tenant.

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform a delete.

        :param context: context for the request
        :param target_tenant_id: target project id that needs to be deleted
        """

        if not context.is_admin:
            raise t_exceptions.AdminRequired

        target_project_id = self.target_tenant_id

        # Get the parent_id of the target project to verify whether we are
        # dealing with hierarchical namespace or non-hierarchical namespace.
        target_project = self._get_project(context, target_project_id)
        parent_id = target_project.parent_id

        # Get the children of the project which the token is scoped to in
        # order to know if the target_project is in its hierarchy.
        context_project = self._get_project(context,
                                            context.project_id,
                                            subtree_as_ids=True)

        if parent_id:
            self._authorize_update_or_delete(context_project,
                                             target_project.id,
                                             parent_id)
            parent_project_quotas = QUOTAS.get_project_quotas(
                context, parent_id, parent_project_id=parent_id)

        else:

            # if the target project has no parent and descendant, then
            # the operation is allowed only if the context project also
            # has no parent and descendant, that means only flat mode
            # (current mode without hierarchy) is allowed

            if not target_project.subtree and \
                    not context_project.parent_id and \
                    not context_project.subtree:
                pass
            elif context.project_id != target_project_id:
                param_msg = _("context.project_id = %(ctx_project_id)s, "
                              "target_project_id = %(target_project_id)s ") % {
                    "ctx_project_id": context.project_id,
                    "target_project_id": target_project.id}

                msg = _("Can not delete quota for %s") % param_msg
                LOG.error(msg=msg)
                raise t_exceptions.HTTPForbiddenError(msg=msg)

        try:
            project_quotas = QUOTAS.get_project_quotas(
                context, target_project.id, usages=True,
                parent_project_id=parent_id, defaults=False)
        except t_exceptions.NotAuthorized:
            msg = _("Not authorized to delete %s") % target_project_id
            LOG.exception(msg)
            raise

        # If the project which is being deleted has allocated part of its
        # quota to its sub_projects, then sub_projects' quotas should be
        # deleted first
        for key, value in project_quotas.items():
            if 'allocated' in project_quotas[key].keys():
                if project_quotas[key]['allocated'] != 0:
                    msg = _("About to delete child projects having "
                            "non-zero quota. This should not be performed"
                            " %s") % target_project_id
                    LOG.exception(msg)
                    raise t_exceptions.ChildQuotaNotZero

        # Delete child quota first and later update parent's quota.
        try:
            # TODO(joehuang) support destroy quota by user
            db_api.quota_destroy_by_project(context, target_project.id)
        except t_exceptions.AdminRequired:
            msg = _('Admin or tenant itself or parent tenant'
                    ' required to delete quota'
                    ' %s') % target_project.id
            LOG.exception(msg)
            raise

        if parent_id:
            # Update the allocated of the parent
            for key, value in project_quotas.items():
                project_hard_limit = project_quotas[key]['limit']
                parent_allocated = parent_project_quotas[key]['allocated']
                parent_allocated -= project_hard_limit
                db_api.quota_allocated_update(context, parent_id, key,
                                              parent_allocated)

    def show_default_quota(self, context):
        try:
            project = self._get_project(context, self.target_tenant_id)
            parent_id = project.parent_id
        except k_exceptions.Forbidden:
            # NOTE(e0ne): Keystone API v2 requires admin permissions for
            # project_get method. We ignore Forbidden exception for
            # non-admin users.
            parent_id = self.target_tenant_id

        return self._format_quota_set(self.target_tenant_id,
                                      QUOTAS.get_defaults(
                                          context,
                                          parent_project_id=parent_id))

    def show_detail_quota(self, context, show_usage=False):
        """Show quota for a particular tenant

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects admin of current project, immediate
        parent of the project or the CLOUD admin are able to perform
        a show.

        :param context: request context
        :param tenant_id: target project id that needs to be shown
        :param params: whether to show usage
        """
        target_project_id = self.target_tenant_id
        usage = show_usage

        try:
            # With hierarchical projects, only the admin of the current
            # project or the root project has privilege to perform quota show
            # operations.
            target_project = self._get_project(context, target_project_id)
            context_project = self._get_project(context, context.project_id,
                                                subtree_as_ids=True)

            self._authorize_show(context_project, target_project)
            parent_project_id = target_project.parent_id
        except k_exceptions.Forbidden:
            # NOTE(e0ne): Keystone API v2 requires admin permissions for
            # project_get method. We ignore Forbidden exception for
            # non-admin users.
            parent_project_id = None

        try:
            db_api.authorize_project_context(context,
                                             target_project_id)
        except t_exceptions.NotAuthorized:
            msg = _('Admin or tenant itself or parent tenant '
                    'required to show quota '
                    'tenant_id=%(tenant_id)s, '
                    'usage=%(usage)s') % {'tenant_id': target_project_id,
                                          'usage': usage}
            LOG.exception(msg)
            raise

        quotas = self._get_quotas(context, target_project_id, usage,
                                  parent_project_id=parent_project_id)
        return self._format_quota_set(target_project_id, quotas)
