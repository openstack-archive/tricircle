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
Routines for configuring tricircle, largely copy from Neutron
"""

from oslo_config import cfg
import oslo_log.log as logging

from tricircle.common import exceptions

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


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
            except exceptions.ProjectQuotaNotFound:
                pass

        # Try for the quota class
        if quota_class:
            try:
                return driver.get_by_class(context, quota_class, self.name)
            except exceptions.QuotaClassNotFound:
                pass

        # OK, return the default
        return driver.get_default(context, self,
                                  parent_project_id=self.parent_project_id)

    @property
    def default(self):
        """Return the default value of the quota."""

        if self.parent_project_id:
            return 0

        return CONF[self.flag] if self.flag else -1


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
