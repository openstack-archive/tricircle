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

from openstack.network.v2 import _proxy

import tricircle.tests.network_sdk.v2.trunk as _trunk


class Proxy(_proxy.Proxy):
    def create_trunk(self, **attrs):
        return self._create(_trunk.Trunk, **attrs)

    def delete_trunk(self, trunk, ignore_missing=True):
        self._delete(_trunk.Trunk, trunk, ignore_missing=ignore_missing)

    def update_trunk(self, trunk, **attrs):
        return self._update(_trunk.Trunk, trunk, **attrs)

    def trunks(self, **query):
        return self._list(_trunk.Trunk, pagination=False, **query)

    def add_subports(self, trunk, subports=[]):
        trunk = self._get_resource(_trunk.Trunk, trunk)
        body = {'sub_ports': subports}
        return trunk.add_subports(self._session, **body)

    def remove_subports(self, trunk, subports=[]):
        trunk = self._get_resource(_trunk.Trunk, trunk)
        body = {'sub_ports': subports}
        return trunk.remove_subports(self._session, **body)
