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

from openstack import resource2

from tricircle.tests.tricircle_sdk import multiregion_network_service


class Job(resource2.Resource):
    resource_key = 'job'
    resources_key = 'jobs'
    base_path = '/jobs'
    service = multiregion_network_service.MultiregionNetworkService()

    allow_list = True
    allow_get = True

    resource = resource2.Body('resource', type=dict)
    type = resource2.Body('type')
    timestamp = resource2.Body('timestamp')
    project_id = resource2.Body('project_id')
    status = resource2.Body('status')
