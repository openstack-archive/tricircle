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
from openstack import utils

from tricircle.tests.network_sdk import network_service


class Trunk(resource2.Resource):
    resource_key = 'trunk'
    resources_key = 'trunks'
    base_path = '/trunks'
    service = network_service.NetworkService()

    allow_create = True
    allow_get = True
    allow_update = True
    allow_delete = True
    allow_list = True

    status = resource2.Body('status')
    name = resource2.Body('name')
    port_id = resource2.Body('port_id')
    sub_ports = resource2.Body('sub_ports', type=list)

    def add_subports(self, session, **body):
        url = utils.urljoin(self.base_path, self.id, 'add_subports')
        resp = session.put(url, endpoint_filter=self.service, json=body)
        return resp.json()

    def remove_subports(self, session, **body):
        url = utils.urljoin(self.base_path, self.id, 'remove_subports')
        resp = session.put(url, endpoint_filter=self.service, json=body)
        return resp.json()
