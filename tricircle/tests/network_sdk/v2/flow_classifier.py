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


class FlowClassifier(resource2.Resource):
    resource_key = 'flow_classifier'
    resources_key = 'flow_classifiers'
    base_path = '/sfc/flow_classifiers'
    service = network_service.NetworkService()

    allow_create = True
    allow_get = True
    allow_update = True
    allow_delete = True
    allow_list = True

    _query_mapping = resource2.QueryParameters('name')

    name = resource2.Body('name')
    description = resource2.Body('description')
    ethertype = resource2.Body('ingress')
    protocol = resource2.Body('protocol')
    source_port_range_min = resource2.Body('source_port_range_min')
    source_port_range_max = resource2.Body('source_port_range_max')
    destination_port_range_min = resource2.Body('destination_port_range_min')
    destination_port_range_max = resource2.Body('destination_port_range_max')
    source_ip_prefix = resource2.Body('source_ip_prefix')
    destination_ip_prefix = resource2.Body('destination_ip_prefix')
    logical_source_port = resource2.Body('logical_source_port')
    logical_destination_port = resource2.Body('logical_destination_port')
    l7_parameters = resource2.Body('l7_parameters', type=dict)
