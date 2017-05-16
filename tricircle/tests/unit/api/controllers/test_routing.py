# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from mock import patch
from oslo_utils import uuidutils
import six
import unittest

import pecan

from tricircle.api.controllers import pod
from tricircle.api.controllers import routing
from tricircle.common import context
from tricircle.common import policy
from tricircle.db import api as db_api
from tricircle.db import core


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class RoutingControllerTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.controller = routing.RoutingController()
        self.context = context.get_admin_context()
        policy.populate_default_rules()

    def _validate_error_code(self, res, code):
        self.assertEqual(res[list(res.keys())[0]]['code'], code)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_context):
        mock_context.return_value = self.context

        # prepare the foreign key: pod_id
        kw_pod = {'pod': {'region_name': 'pod1', 'az_name': 'az1'}}
        pod_id = pod.PodsController().post(**kw_pod)['pod']['pod_id']

        # a variable used for later test
        project_id = uuidutils.generate_uuid()

        kw_routing = {'routing':
                      {'top_id': '09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                       'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                       'pod_id': pod_id,
                       'project_id': project_id,
                       'resource_type': 'subnet'
                       }}
        id = self.controller.post(**kw_routing)['routing']['id']
        routing = db_api.get_resource_routing(self.context, id)
        self.assertEqual('09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                         routing['top_id'])
        self.assertEqual('dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                         routing['bottom_id'])
        self.assertEqual(pod_id, routing['pod_id'])
        self.assertEqual(project_id, routing['project_id'])
        self.assertEqual('subnet', routing['resource_type'])

        routings = db_api.list_resource_routings(self.context,
                                                 [{'key': 'top_id',
                                                   'comparator': 'eq',
                                                   'value':
                                                   '09fd7cc9-d169-4b5a-'
                                                   '88e8-436ecf4d0bfe'
                                                   },
                                                  {'key': 'pod_id',
                                                   'comparator': 'eq',
                                                   'value': pod_id}
                                                  ], [])
        self.assertEqual(1, len(routings))

        # failure case, only admin can create resource routing
        self.context.is_admin = False
        res = self.controller.post(**kw_routing)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, request body not found
        kw_routing1 = {'route':
                       {'top_id': '109fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                        'bottom_id': '2dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                        'pod_id': pod_id,
                        'project_id': project_id,
                        'resource_type': 'subnet'
                        }}
        res = self.controller.post(**kw_routing1)
        self._validate_error_code(res, 400)

        # failure case, top_id is not given
        kw_routing2 = {'routing':
                       {'bottom_id': '2dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                        'pod_id': pod_id,
                        'project_id': project_id,
                        'resource_type': 'subnet'
                        }}
        res = self.controller.post(**kw_routing2)
        self._validate_error_code(res, 400)

        # failure case, top_id is empty
        kw_routing3 = {'routing':
                       {'top_id': '',
                        'bottom_id': '2dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                        'pod_id': pod_id,
                        'project_id': project_id,
                        'resource_type': 'subnet'
                        }}
        res = self.controller.post(**kw_routing3)
        self._validate_error_code(res, 400)

        # failure case, top_id is given value 'None'
        kw_routing4 = {'routing':
                       {'top_id': None,
                        'bottom_id': '2dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                        'pod_id': pod_id,
                        'project_id': project_id,
                        'resource_type': 'subnet'
                        }}
        res = self.controller.post(**kw_routing4)
        self._validate_error_code(res, 400)

        # failure case, wrong resource type
        kw_routing6 = {'routing':
                       {'top_id': '09fd7cc9-d169-4b5a-88e8-436ecf4d0b09',
                        'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e2031f',
                        'pod_id': pod_id,
                        'project_id': project_id,
                        'resource_type': 'server'
                        }}
        res = self.controller.post(**kw_routing6)
        self._validate_error_code(res, 400)

        # failure case, the resource routing already exists
        res = self.controller.post(**kw_routing)
        self._validate_error_code(res, 409)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_one(self, mock_context):
        mock_context.return_value = self.context

        # prepare the foreign key: pod_id
        kw_pod = {'pod': {'region_name': 'pod1', 'az_name': 'az1'}}
        pod_id = pod.PodsController().post(**kw_pod)['pod']['pod_id']

        # a variable used for later test
        project_id = uuidutils.generate_uuid()

        kw_routing = {'routing':
                      {'top_id': '09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                       'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                       'pod_id': pod_id,
                       'project_id': project_id,
                       'resource_type': 'port'
                       }}

        id = self.controller.post(**kw_routing)['routing']['id']

        routing = self.controller.get_one(id)
        self.assertEqual('09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                         routing['routing']['top_id'])
        self.assertEqual('dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                         routing['routing']['bottom_id'])
        self.assertEqual(pod_id, routing['routing']['pod_id'])
        self.assertEqual(project_id, routing['routing']['project_id'])
        self.assertEqual('port', routing['routing']['resource_type'])

        # failure case, only admin can get resource routing
        self.context.is_admin = False
        res = self.controller.get_one(id)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, resource routing not found
        res = self.controller.get_one(-123)
        self._validate_error_code(res, 404)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_all(self, mock_context):
        mock_context.return_value = self.context

        # prepare the foreign key: pod_id
        kw_pod1 = {'pod': {'region_name': 'pod1', 'az_name': 'az1'}}
        pod_id1 = pod.PodsController().post(**kw_pod1)['pod']['pod_id']

        # a variable used for later test
        project_id = uuidutils.generate_uuid()

        kw_routing1 = {'routing':
                       {'top_id': 'c7f641c9-8462-4007-84b2-3035d8cfb7a3',
                        'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                        'pod_id': pod_id1,
                        'project_id': project_id,
                        'resource_type': 'subnet'
                        }}

        # prepare the foreign key: pod_id
        kw_pod2 = {'pod': {'region_name': 'pod2', 'az_name': 'az1'}}
        pod_id2 = pod.PodsController().post(**kw_pod2)['pod']['pod_id']

        kw_routing2 = {'routing':
                       {'top_id': 'b669a2da-ca95-47db-a2a9-ba9e546d82ee',
                        'bottom_id': 'fd72c010-6e62-4866-b999-6dcb718dd7b4',
                        'pod_id': pod_id2,
                        'project_id': project_id,
                        'resource_type': 'port'
                        }}

        self.controller.post(**kw_routing1)
        self.controller.post(**kw_routing2)

        # no filters are applied to the routings, so all of the routings will
        # be retrieved.
        routings = self.controller.get_all()
        actual = [(routing['top_id'], routing['pod_id'])
                  for routing in routings['routings']]
        expect = [('c7f641c9-8462-4007-84b2-3035d8cfb7a3', pod_id1),
                  ('b669a2da-ca95-47db-a2a9-ba9e546d82ee', pod_id2)]
        six.assertCountEqual(self, expect, actual)

        # apply a resource type filter to the retrieved routings.
        kw_filter1 = {'resource_type': 'port'}
        routings = self.controller.get_all(**kw_filter1)
        actual = [(routing['top_id'], routing['pod_id'],
                  routing['resource_type'])
                  for routing in routings['routings']]
        expect = [('b669a2da-ca95-47db-a2a9-ba9e546d82ee', pod_id2, 'port')]
        six.assertCountEqual(self, expect, actual)

        # apply a filter and if it doesn't match with any of the retrieved
        # routings, then all of them will be discarded and the method returns
        # with []
        kw_filter2 = {'resource_type': 'port2'}
        routings = self.controller.get_all(**kw_filter2)
        self.assertEqual([], routings['routings'])

        # failure case, use an unsupported filter type
        kw_filter3 = {'resource': 'port'}
        res = self.controller.get_all(**kw_filter3)
        self._validate_error_code(res, 400)

        kw_filter4 = {'pod_id': pod_id1,
                      'resource': 'port'}
        res = self.controller.get_all(**kw_filter4)
        self._validate_error_code(res, 400)

        # failure case, only admin can show all resource routings
        self.context.is_admin = False
        res = self.controller.get_all()
        self._validate_error_code(res, 403)

        self.context.is_admin = True

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(pecan, 'response', new=mock.Mock)
    @patch.object(context, 'extract_context_from_environ')
    def test_delete(self, mock_context):
        mock_context.return_value = self.context

        # prepare the foreign key: pod_id
        kw_pod = {'pod': {'region_name': 'pod1', 'az_name': 'az1'}}
        pod_id = pod.PodsController().post(**kw_pod)['pod']['pod_id']

        # a variable used for later test
        project_id = uuidutils.generate_uuid()

        kw_routing = {'routing':
                      {'top_id': '09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe',
                       'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                       'pod_id': pod_id,
                       'project_id': project_id,
                       'resource_type': 'subnet'
                       }}

        routing = self.controller.post(**kw_routing)
        id = routing['routing']['id']
        res = self.controller.delete(id)
        self.assertEqual(200, res.status)

        routings = db_api.list_resource_routings(self.context,
                                                 [{'key': 'top_id',
                                                  'comparator': 'eq',
                                                   'value': '09fd7cc9-d'
                                                   '169-4b5a-88e8-436ecf4d0bfe'
                                                   },
                                                  {'key': 'pod_id',
                                                   'comparator': 'eq',
                                                   'value': pod_id
                                                   }], [])
        self.assertEqual(0, len(routings))

        # failure case, only admin can delete resource routing
        self.context.is_admin = False
        res = self.controller.delete(id)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, resource routing not found
        res = self.controller.delete(-123)
        self._validate_error_code(res, 404)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(pecan, 'response', new=mock.Mock)
    @patch.object(context, 'extract_context_from_environ')
    def test_put(self, mock_context):
        mock_context.return_value = self.context

        # prepare the foreign key: pod_id
        kw_pod1 = {'pod': {'region_name': 'pod1', 'az_name': 'az1'}}
        pod_id1 = pod.PodsController().post(**kw_pod1)['pod']['pod_id']

        # a variable used for later test
        project_id = uuidutils.generate_uuid()

        body = {'routing':
                {'top_id': 'c7f641c9-8462-4007-84b2-3035d8cfb7a3',
                 'bottom_id': 'dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef',
                 'pod_id': pod_id1,
                 'project_id': project_id,
                 'resource_type': 'router'
                 }}

        # both bottom_id and resource type have been changed
        body_update1 = {'routing':
                        {'bottom_id': 'fd72c010-6e62-4866-b999-6dcb718dd7b4',
                         'resource_type': 'port'
                         }}

        id = self.controller.post(**body)['routing']['id']
        routing = self.controller.put(id, **body_update1)

        self.assertEqual('port',
                         routing['routing']['resource_type'])
        self.assertEqual('fd72c010-6e62-4866-b999-6dcb718dd7b4',
                         routing['routing']['bottom_id'])
        self.assertEqual(pod_id1, routing['routing']['pod_id'])

        # failure case, only admin can update resource routing
        self.context.is_admin = False
        res = self.controller.put(id, **body_update1)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, request body not found
        body_update2 = {'route':
                        {'bottom_id': 'fd72c010-6e62-4866-b999-6dcb718dd7b4',
                         'resource_type': 'port'
                         }}
        res = self.controller.put(id, **body_update2)
        self._validate_error_code(res, 400)

        # failure case, wrong resource type
        body_update3 = {'routing':
                        {'resource_type': 'volume'}}
        res = self.controller.put(id, **body_update3)
        self._validate_error_code(res, 400)

        # failure case, the value to be updated is empty
        body_update4 = {'routing':
                        {'top_id': ''}}
        res = self.controller.put(id, **body_update4)
        self._validate_error_code(res, 400)

        # failure case, the value to be updated is None
        body_update5 = {'routing':
                        {'top_id': None}}
        res = self.controller.put(id, **body_update5)
        self._validate_error_code(res, 400)

        # failure case, the value to be updated is not appropriate
        res = self.controller.put(-123, **body_update1)
        self._validate_error_code(res, 404)

        # failure case, the pod where the new pod_id lays on
        # should exist in pod table

        # a variable used for later test
        new_pod_id = uuidutils.generate_uuid()
        body_update6 = {'routing': {'pod_id': new_pod_id}}
        res = self.controller.put(id, **body_update6)
        self._validate_error_code(res, 400)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
