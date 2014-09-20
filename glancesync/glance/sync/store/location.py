# Copyright (c) 2014 OpenStack Foundation.
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
#
# @author: Jia Dong, HuaWei

import logging
import urlparse

from stevedore import extension

LOG = logging.getLogger(__name__)


class LocationCreator(object):

    def __init__(self):
        self.scheme = None

    def creator(self, **kwargs):
        pass


class Location(object):

    """
    Class describing the location of an image that Glance knows about
    """

    def __init__(self, store_name, store_location_class,
                 uri=None, image_id=None, store_specs=None):
        """
        Create a new Location object.

        :param store_name: The string identifier/scheme of the storage backend
        :param store_location_class: The store location class to use
                                     for this location instance.
        :param image_id: The identifier of the image in whatever storage
                         backend is used.
        :param uri: Optional URI to construct location from
        :param store_specs: Dictionary of information about the location
                            of the image that is dependent on the backend
                            store
        """
        self.store_name = store_name
        self.image_id = image_id
        self.store_specs = store_specs or {}
        self.store_location = store_location_class(self.store_specs)


class StoreLocation(object):

    """
    Base class that must be implemented by each store
    """

    def __init__(self, store_specs):
        self.specs = store_specs
        if self.specs:
            self.process_specs()


class LocationFactory(object):

    SYNC_LOCATION_NAMESPACE = "glance.sync.store.location"

    def __init__(self):
        self._locations = {}
        self._load_locations()

    def _load_locations(self):
        extension_manager = extension.ExtensionManager(
            namespace=self.SYNC_LOCATION_NAMESPACE,
            invoke_on_load=True,
        )
        for ext in extension_manager:
            if ext.name in self._locations:
                continue
            ext.obj.name = ext.name
            self._locations[ext.name] = ext.obj

    def get_instance(self, scheme, **kwargs):
        loc_creator = self._locations.get(scheme, None)
        return loc_creator.create(**kwargs)
