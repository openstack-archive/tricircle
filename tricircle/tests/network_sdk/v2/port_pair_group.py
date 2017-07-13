# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from openstack import resource2

from tricircle.tests.network_sdk import network_service


class PortPairGroup(resource2.Resource):
    resource_key = 'port_pair_group'
    resources_key = 'port_pair_groups'
    base_path = '/sfc/port_pair_groups'
    service = network_service.NetworkService()

    allow_create = True
    allow_get = True
    allow_update = True
    allow_delete = True
    allow_list = True

    _query_mapping = resource2.QueryParameters('name')

    name = resource2.Body('name')
    description = resource2.Body('description')
    port_pairs = resource2.Body('port_pairs', type=list)
    port_pair_group_parameters = resource2.Body('port_pair_group_parameters',
                                                type=dict)
