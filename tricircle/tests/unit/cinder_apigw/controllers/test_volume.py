# Copyright 2016 OpenStack Foundation.
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
import pecan
import unittest

from tricircle.cinder_apigw.controllers import volume_type
from tricircle.common import context
from tricircle.db import api as db_api
from tricircle.db import core


class FakeResponse(object):
    def __new__(cls, code=500):
        cls.status = code
        cls.status_code = code
        return super(FakeResponse, cls).__new__(cls)


class VolumeTypeTest(unittest.TestCase):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        self.context = context.get_admin_context()
        self.project_id = 'test_project'
        self.controller = volume_type.VolumeTypeController(self.project_id)

    def _validate_error_code(self, res, code):
        self.assertEqual(code, res[res.keys()[0]]['code'])

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_post(self, mock_context):
        mock_context.return_value = self.context

        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        res = db_api.volume_type_get_by_name(self.context, 'vol-type-001')

        self.assertEqual('vol-type-001', res['name'])
        self.assertEqual('volume type 001', res['description'])
        capabilities = res['extra_specs']['capabilities']
        self.assertEqual('gpu', capabilities)

        # failure case, only admin can create volume type
        self.context.is_admin = False
        res = self.controller.post(**body)
        self._validate_error_code(res, 403)

        self.context.is_admin = True

        # failure case, volume_type body is required
        body = {'name': 'vol-type-002'}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, volume type name is empty
        body = {'volume_type': {'name': '',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, volume type name has more than 255 characters
        body = {'volume_type': {'name': ('a' * 500),
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu', }
                                }
                }
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, volume type description has more than 255 characters
        body = {'volume_type': {'name': 'vol-type-001',
                                'description': ('a' * 500),
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, is_public is invalid input
        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': 'a',
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 400)

        # failure case, volume type name is unique
        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        res = self.controller.post(**body)
        self._validate_error_code(res, 409)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_get_one(self, mock_context):
        mock_context.return_value = self.context

        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        vtype = db_api.volume_type_get_by_name(self.context, 'vol-type-001')
        res = self.controller.get_one(vtype['id'])['volume_type']

        self.assertEqual('vol-type-001', res['name'])
        self.assertEqual('volume type 001', res['description'])
        capabilities = res['extra_specs']['capabilities']
        self.assertEqual('gpu', capabilities)

        # failure case, volume type is not exist.
        fake_id = "Fake_ID"
        res = self.controller.get_one(fake_id)
        self._validate_error_code(res, 404)

        # failure case, the volume type is private.
        body = {'volume_type': {'name': 'vol-type-002',
                                'description': 'volume type 002',
                                'os-volume-type-access:is_public': False,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        vtype = db_api.volume_type_get_by_name(self.context, 'vol-type-002')
        self.context.is_admin = False
        res = self.controller.get_one(vtype['id'])
        self._validate_error_code(res, 404)

    @patch.object(context, 'extract_context_from_environ')
    def test_get_all(self, mock_context):
        mock_context.return_value = self.context

        volume_type_001 = {'volume_type': {'name': 'vol-type-001',
                                           'description': 'volume type 001',
                                           'os-volume-'
                                           'type-access:is_public': True,
                                           'extra_specs': {
                                               'capabilities': 'gpu',
                                           }}}
        volume_type_002 = {'volume_type': {'name': 'vol-type-002',
                                           'description': 'volume type 002',
                                           'os-volume-'
                                           'type-access:is_public': True,
                                           'extra_specs': {
                                               'capabilities': 'gpu',
                                           }}}
        self.controller.post(**volume_type_001)
        self.controller.post(**volume_type_002)
        volume_types = self.controller.get_all()['volume_types']

        self.assertEqual('vol-type-001', volume_types[0]['name'])
        self.assertEqual('volume type 001', volume_types[0]['description'])
        capabilities_001 = volume_types[0]['extra_specs']['capabilities']
        self.assertEqual('gpu', capabilities_001)

        self.assertEqual('vol-type-002', volume_types[1]['name'])
        self.assertEqual('volume type 002', volume_types[1]['description'])
        capabilities_002 = volume_types[1]['extra_specs']['capabilities']
        self.assertEqual('gpu', capabilities_002)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(context, 'extract_context_from_environ')
    def test_put(self, mock_context):
        mock_context.return_value = self.context

        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        body_update = {'volume_type': {'name': 'vol-type-002',
                                       'description': 'volume type 002',
                                       'os-volume-'
                                       'type-access:is_public': True,
                                       'extra_specs': {
                                           'capabilities': 'gpu',
                                       }}}
        self.controller.post(**body)
        vtype = db_api.volume_type_get_by_name(self.context, 'vol-type-001')
        res = self.controller.put(vtype['id'], **body_update)['volume_type']

        self.assertEqual('vol-type-002', res['name'])
        self.assertEqual('volume type 002', res['description'])
        capabilities = res['extra_specs']['capabilities']
        self.assertEqual('gpu', capabilities)

        # failure case, volume type name, description, is_public
        # not None at the same time
        body = {'volume_type': {'extra_specs': {
            'capabilities': 'gpu',
        }}}
        res = self.controller.put(vtype['id'], **body)
        self._validate_error_code(res, 400)
        # failure case, name exists in db
        body = {'volume_type': {'name': 'vol-type-003',
                                'description': 'volume type 003',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        res = self.controller.put(vtype['id'], **body)
        self._validate_error_code(res, 500)

    @patch.object(pecan, 'response', new=FakeResponse)
    @patch.object(db_api, 'volume_type_delete')
    @patch.object(context, 'extract_context_from_environ')
    def test_delete(self, mock_context, mock_delete):
        mock_context.return_value = self.context
        mock_delete.return_value = Exception()

        body = {'volume_type': {'name': 'vol-type-001',
                                'description': 'volume type 001',
                                'os-volume-type-access:is_public': True,
                                'extra_specs': {
                                    'capabilities': 'gpu',
                                }}}
        self.controller.post(**body)
        vtype = db_api.volume_type_get_by_name(self.context, 'vol-type-001')

        # failure case, only admin delete create volume type
        self.context.is_admin = False
        res = self.controller.delete(vtype['id'])
        self._validate_error_code(res, 403)

        # failure case, bad request
        self.context.is_admin = True
        res = self.controller.delete(_id=None)
        self._validate_error_code(res, 404)

        res = self.controller.delete(vtype['id'])
        self.assertEqual(res.status, 202)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
