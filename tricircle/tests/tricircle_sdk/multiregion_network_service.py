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

from openstack import service_description
from openstack import service_filter

from tricircle.tests.tricircle_sdk.v1 import _proxy


class MultiregionNetworkService(service_description.ServiceDescription):
    valid_versions = [service_filter.ValidVersion('v1')]
    proxy_class = _proxy.Proxy

    def __init__(self, version=None):
        # TODO(zhiyuan) register a proper service type in keystone
        super(MultiregionNetworkService, self).__init__(
            service_type='tricircle_sdk')
