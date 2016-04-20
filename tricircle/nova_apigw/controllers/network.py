# Copyright (c) 2015 Huawei Tech. Co., Ltd.
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

import pecan
from pecan import expose
from pecan import rest

import tricircle.common.client as t_client
import tricircle.common.context as t_context


class NetworkController(rest.RestController):

    def __init__(self, project_id):
        self.project_id = project_id
        self.client = t_client.Client()

    @staticmethod
    def _construct_network_entry(network):
        network['uuid'] = network['id']
        network['label'] = network['name']
        return network

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()
        network = self.client.get_networks(context, _id)
        if not network:
            pecan.abort(404, 'Network not found')
            return
        return {'network': self._construct_network_entry(network)}

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()
        networks = self.client.list_networks(context)
        return {'networks': [self._construct_network_entry(
            network) for network in networks]}
