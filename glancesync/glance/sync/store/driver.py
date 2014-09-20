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

"""Base class for all storage backends"""

from oslo.config import cfg
from stevedore import extension

from glance.common import exception
import glance.openstack.common.log as logging
from glance.openstack.common.gettextutils import _
from glance.openstack.common import importutils
from glance.openstack.common import strutils

LOG = logging.getLogger(__name__)


class StoreFactory(object):

    SYNC_STORE_NAMESPACE = "glance.sync.store.driver"

    def __init__(self):
        self._stores = {}
        self._load_store_drivers()

    def _load_store_drivers(self):
        extension_manager = extension.ExtensionManager(
            namespace=self.SYNC_STORE_NAMESPACE,
            invoke_on_load=True,
        )
        for ext in extension_manager:
            if ext.name in self._stores:
                continue
            ext.obj.name = ext.name
            self._stores[ext.name] = ext.obj

    def get_instance(self, from_scheme='filesystem', to_scheme=None):
        _store_driver = self._stores.get(from_scheme)
        if to_scheme and to_scheme != from_scheme and _store_driver:
            func_name = 'copy_to_%s' % to_scheme
            if not getattr(_store_driver, func_name, None):
                return None
        return _store_driver


class Store(object):

    def copy_to(self, source_location, dest_location, candidate_path=None):
        pass
