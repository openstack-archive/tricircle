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
from tricircle.nova_apigw.controllers import aggregate


class AggregateTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.get_admin_context()
        self.project_id = 'test_project'
        self.controller = aggregate.AggregateController(self.project_id)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())

    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_context):
        mock_context.return_value = self.context

        body = {'aggregate': {'name': 'ag1',
                              'availability_zone': 'az1'}}
        aggregate_id = self.controller.post(**body)['aggregate']['id']
        aggregate_dict = self.controller.get_one(aggregate_id)['aggregate']
        self.assertEqual('ag1', aggregate_dict['name'])
        self.assertEqual('az1', aggregate_dict['availability_zone'])
        self.assertEqual('az1',
                         aggregate_dict['metadata']['availability_zone'])

    @patch.object(context, 'extract_context_from_environ')
    def test_post_action(self, mock_context):
        mock_context.return_value = self.context

        body = {'aggregate': {'name': 'ag1',
                              'availability_zone': 'az1'}}

        return_ag1 = self.controller.post(**body)['aggregate']
        action_controller = aggregate.AggregateActionController(
            self.project_id, return_ag1['id'])

        return_ag2 = action_controller.post(**body)['aggregate']

        self.assertEqual('ag1', return_ag2['name'])
        self.assertEqual('az1', return_ag2['availability_zone'])
