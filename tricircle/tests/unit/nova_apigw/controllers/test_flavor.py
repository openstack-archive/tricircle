# Copyright 2015 Huawei Technologies Co., Ltd.
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

from mock import patch
import unittest

from tricircle.common import context
from tricircle.db import core
from tricircle.nova_apigw.controllers import flavor


class FlavorTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.get_admin_context()
        self.project_id = 'test_project'
        self.controller = flavor.FlavorController(self.project_id)

    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_context):
        mock_context.return_value = self.context

        body = {'flavor': {'id': '1', 'name': 'test_flavor',
                           'ram': 1024, 'vcpus': 1, 'disk': 10}}
        self.controller.post(**body)
        flavor_dict = self.controller.get_one('1')['flavor']
        self.assertEqual('1', flavor_dict['id'])
        self.assertEqual('test_flavor', flavor_dict['name'])
        self.assertEqual(1024, flavor_dict['memory_mb'])
        self.assertEqual(1, flavor_dict['vcpus'])
        self.assertEqual(10, flavor_dict['root_gb'])

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
