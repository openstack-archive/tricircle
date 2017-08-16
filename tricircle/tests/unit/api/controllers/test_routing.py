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
from six.moves import xrange

from oslo_config import cfg
import pecan

from tricircle.api import app
from tricircle.api.controllers import pod
from tricircle.api.controllers import routing
from tricircle.common import context
from tricircle.common import policy
from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.tests import base


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class RoutingControllerTest(base.TestCase):
    def setUp(self):
        super(RoutingControllerTest, self).setUp()

        cfg.CONF.clear()
        cfg.CONF.register_opts(app.common_opts)
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

        kw_routing = self._prepare_routing_element('subnet')
        id = self.controller.post(**kw_routing)['routing']['id']
        routing = db_api.get_resource_routing(self.context, id)

        self.assertEqual('subnet', routing['resource_type'])

        routings = db_api.list_resource_routings(self.context,
                                                 [{'key': 'resource_type',
                                                   'comparator': 'eq',
                                                   'value':
                                                   'subnet'
                                                   },
                                                  ])
        self.assertEqual(1, len(routings))

        # failure case, only admin can create resource routing
        self.context.is_admin = False
        kw_routing = self._prepare_routing_element('subnet')
        res = self.controller.post(**kw_routing)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, request body not found
        kw_routing1 = {'route':
                       {'top_id': uuidutils.generate_uuid(),
                        'bottom_id': uuidutils.generate_uuid(),
                        }}
        res = self.controller.post(**kw_routing1)
        self._validate_error_code(res, 400)

        # failure case, top_id is not given
        kw_routing2 = self._prepare_routing_element('router')
        kw_routing2['routing'].pop('top_id')
        res = self.controller.post(**kw_routing2)
        self._validate_error_code(res, 400)

        # failure case, top_id is empty
        kw_routing3 = self._prepare_routing_element('router')
        kw_routing3['routing'].update({'top_id': ''})
        res = self.controller.post(**kw_routing3)
        self._validate_error_code(res, 400)

        # failure case, top_id is given value 'None'
        kw_routing4 = self._prepare_routing_element('security_group')
        kw_routing4['routing'].update({'top_id': None})
        res = self.controller.post(**kw_routing4)
        self._validate_error_code(res, 400)

        # failure case, wrong resource type
        kw_routing6 = self._prepare_routing_element('server')
        self.controller.post(**kw_routing6)
        self._validate_error_code(res, 400)

        # failure case, the resource routing already exists
        kw_routing7 = self._prepare_routing_element('router')
        self.controller.post(**kw_routing7)
        res = self.controller.post(**kw_routing7)
        self._validate_error_code(res, 409)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_one(self, mock_context):
        mock_context.return_value = self.context

        kw_routing = self._prepare_routing_element('port')
        id = self.controller.post(**kw_routing)['routing']['id']

        routing = self.controller.get_one(id)
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
    def test_get_routings_with_pagination(self, mock_context):
        self.context.project_id = uuidutils.generate_uuid()

        mock_context.return_value = self.context

        # test when no pagination and filters are applied to the list
        # operation, then all of the routings will be retrieved.
        count = 1
        total_routings = 4
        for resource_type in ('subnet', 'router', 'security_group', 'network'):
            kw_routing = self._prepare_routing_element(resource_type)
            # for test convenience, the first routing has a different
            # project ID from later ones.
            if count > 1:
                kw_routing['routing']['project_id'] = self.context.project_id
            self.controller.post(**kw_routing)
            count += 1

        routings = self.controller.get_all()
        ids = [routing['id']
               for key, values in six.iteritems(routings)
               for routing in values]
        self.assertEqual([4, 3, 2], ids)

        for filter_name in ('router', 'security_group', 'network'):
            filters = {'resource_type': filter_name}
            routings = self.controller.get_all(**filters)
            items = [routing['resource_type']
                     for key, values in six.iteritems(routings)
                     for routing in values]
            self.assertEqual(1, len(items))

        # test when pagination limit varies in range [1, total_routings+1)
        for i in xrange(1, total_routings+1):
            routings = []
            total_pages = 0

            routing = self.controller.get_all(limit=i)
            total_pages += 1
            routings.extend(routing['routings'])

            while 'routings_links' in routing:
                link = routing['routings_links'][0]['href']
                _, marker_dict = link.split('&')
                # link is like '/v1.0/routings?limit=1&marker=1', after split,
                # marker_dict is a string like 'marker=1'.
                _, marker_value = marker_dict.split('=')
                routing = self.controller.get_all(limit=i, marker=marker_value)
                if len(routing['routings']) > 0:
                    total_pages += 1
                routings.extend(routing['routings'])
            # assert that total pages will decrease as the limit increase.
            # because the first routing has a different project ID and can't
            # be retrieved by current admin role of project, so the number
            # of actual total routings we can get is total_routings-1.
            pages = int((total_routings - 1) / i)
            if (total_routings - 1) % i:
                pages += 1
            self.assertEqual(pages, total_pages)
            self.assertEqual(total_routings - 1, len(routings))

            for i in xrange(total_routings-1):
                self.assertEqual(total_routings - i, routings[i]['id'])

            set1 = set(['router', 'security_group', 'network'])
            set2 = set([routing1['resource_type'] for routing1 in routings])
            self.assertEqual(set1, set2)

        # test cases when pagination and filters are used
        routings = self.controller.get_all(resource_type='network', limit=1)
        self.assertEqual(1, len(routings['routings']))

        routings = self.controller.get_all(resource_type='subnet', limit=2)
        self.assertEqual(0, len(routings['routings']))

        # apply a filter and if it doesn't match with any of the retrieved
        # routings, then all of them will be discarded and the method returns
        # with [].
        kw_filter2 = {'resource_type': 'port2'}
        routings = self.controller.get_all(**kw_filter2)

        # test cases when limit from client is abnormal
        routings = self.controller.get_all(limit=0)
        self.assertEqual(total_routings - 1, len(routings['routings']))

        routings = self.controller.get_all(limit=-1)
        self.assertEqual(total_routings - 1, len(routings['routings']))

        res = self.controller.get_all(limit='20x')
        self._validate_error_code(res, 400)

        # test cases when pagination limit from client is greater than
        # max limit
        pagination_max_limit_backup = cfg.CONF.pagination_max_limit
        cfg.CONF.set_override('pagination_max_limit', 2)
        routings = self.controller.get_all(limit=3)
        self.assertEqual(2, len(routings['routings']))
        cfg.CONF.set_override('pagination_max_limit',
                              pagination_max_limit_backup)

        # test case when marker reaches 1, then no link to next page
        routings = self.controller.get_all(limit=2, marker=3)
        self.assertNotIn('routings_links', routings)

        # test cases when marker is abnormal
        res = self.controller.get_all(limit=2, marker=-1)
        self._validate_error_code(res, 400)

        res = self.controller.get_all(limit=2, marker=0)
        self._validate_error_code(res, 400)

        res = self.controller.get_all(limit=2, marker="last")
        self._validate_error_code(res, 400)

        # failure case, use an unsupported filter type
        kw_filter3 = {'resource': 'port'}
        res = self.controller.get_all(**kw_filter3)
        self._validate_error_code(res, 400)

        kw_filter4 = {'pod_id': "pod_id_1",
                      'resource': 'port'}
        res = self.controller.get_all(**kw_filter4)
        self._validate_error_code(res, 400)

        # failure case, id can't be converted to an integer
        kw_filter5 = {'id': '4s'}
        res = self.controller.get_all(**kw_filter5)
        self._validate_error_code(res, 400)

        # test when specify project ID filter from client, if this
        # project ID is different from the one from context, then
        # it will be ignored, project ID from context will be
        # used instead.
        res = self.controller.get_all()
        kw_filter6 = {'project_id': uuidutils.generate_uuid()}
        res1 = self.controller.get_all(**kw_filter6)

        kw_filter7 = {'project_id': self.context.project_id}
        res2 = self.controller.get_all(**kw_filter7)
        self.assertEqual(len(res2['routings']), len(res1['routings']))
        self.assertEqual(len(res['routings']), len(res2['routings']))

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_all_non_admin(self, mock_context):
        mock_context.return_value = self.context

        kw_routing1 = self._prepare_routing_element('subnet')
        self.controller.post(**kw_routing1)

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
                                                   }])
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

        body = self._prepare_routing_element('subnet')

        # both bottom_id and resource type have been changed
        body_update1 = {'routing':
                        {'bottom_id': uuidutils.generate_uuid(),
                         'resource_type': 'port'
                         }}

        id = self.controller.post(**body)['routing']['id']
        routing = self.controller.put(id, **body_update1)

        self.assertEqual('port',
                         routing['routing']['resource_type'])
        self.assertEqual(body_update1['routing']['bottom_id'],
                         routing['routing']['bottom_id'])

        # failure case, only admin can update resource routing
        self.context.is_admin = False
        res = self.controller.put(id, **body_update1)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, request body not found
        body_update2 = {'route':
                        {'bottom_id': uuidutils.generate_uuid(),
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

    def _prepare_routing_element(self, resource_type):
        """Prepare routing fields except id

        :return: A Dictionary with top_id, bottom_id, pod_id,
        project_id, resource_type
        """

        fake_routing = {
            'routing': {
                'top_id': uuidutils.generate_uuid(),
                'bottom_id': uuidutils.generate_uuid(),
                'pod_id': uuidutils.generate_uuid(),
                'project_id': uuidutils.generate_uuid(),
                'resource_type': resource_type,
            }
        }

        return fake_routing

    def tearDown(self):
        cfg.CONF.unregister_opts(app.common_opts)
        core.ModelBase.metadata.drop_all(core.get_engine())

        super(RoutingControllerTest, self).tearDown()
