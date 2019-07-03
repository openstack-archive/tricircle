
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import mock
import pecan
import unittest

from oslo_config import cfg
from tricircle.common import constants as cons
from tricircle.common import exceptions
from tricircle.common import utils


class TricircleUtilsTestCase(unittest.TestCase):
    def test_bool_from_string(self):
        self.assertEqual(True, utils.bool_from_string('true'))
        self.assertEqual(False, utils.bool_from_string('false'))
        self.assertRaises(ValueError, utils.bool_from_string, 'a', strict=True)
        self.assertEqual(True, utils.bool_from_string('a', default=True))

    def test_check_string_length(self):
        self.assertIsNone(utils.check_string_length(
                          'test', 'name', max_len=255))
        self.assertRaises(exceptions.InvalidInput,
                          utils.check_string_length,
                          11, 'name', max_len=255)
        self.assertRaises(exceptions.InvalidInput,
                          utils.check_string_length,
                          '', 'name', min_len=1)
        self.assertRaises(exceptions.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, 'name', max_len=255)

    def test_get_id_from_name(self):
        output = utils.get_id_from_name(
            cons.RT_NETWORK, 'name#77b0babc-f7e4-4c14-b250-1f18835a52c2')
        self.assertEqual('77b0babc-f7e4-4c14-b250-1f18835a52c2', output)

        output = utils.get_id_from_name(
            cons.RT_NETWORK, '77b0babc-f7e4-4c14-b250-1f18835a52c2')
        self.assertEqual('77b0babc-f7e4-4c14-b250-1f18835a52c2', output)

        output = utils.get_id_from_name(
            cons.RT_NETWORK, 'name@not_uuid')
        self.assertIsNone(output)

        output = utils.get_id_from_name(
            cons.RT_PORT, '77b0babc-f7e4-4c14-b250-1f18835a52c2')
        self.assertEqual('77b0babc-f7e4-4c14-b250-1f18835a52c2', output)

        output = utils.get_id_from_name(
            cons.RT_PORT, 'not_uuid')
        self.assertIsNone(output)

    @mock.patch.object(pecan, 'response')
    def test_format_error(self, mock_response):
        output = utils.format_error(401, 'this is error', 'MyError')
        self.assertEqual({'MyError': {
            'message': 'this is error', 'code': 401
        }}, output)

        output = utils.format_error(400, 'this is error')
        self.assertEqual({'badRequest': {
            'message': 'this is error', 'code': 400
        }}, output)

        output = utils.format_error(401, 'this is error')
        self.assertEqual({'Error': {
            'message': 'this is error', 'code': 401
        }}, output)

    @mock.patch('tricircle.common.utils.format_error')
    def test_format_api_error(self, mock_format_error):
        output = utils.format_api_error(400, 'this is error')
        self.assertEqual(mock_format_error.return_value, output)

    @mock.patch('tricircle.common.utils.format_error')
    def test_format_nova_error(self, mock_format_error):
        output = utils.format_nova_error(400, 'this is error')
        self.assertEqual(mock_format_error.return_value, output)

    @mock.patch('tricircle.common.utils.format_error')
    def test_format_cinder_error(self, mock_format_error):
        output = utils.format_cinder_error(400, 'this is error')
        self.assertEqual(mock_format_error.return_value, output)

    def test_get_pagination_limit(self):
        setattr(cfg.CONF, 'pagination_max_limit', 1024)
        self.assertEqual(512, utils.get_pagination_limit(512))
        self.assertEqual(1024, utils.get_pagination_limit(2048))
        self.assertEqual(1024, utils.get_pagination_limit(-1))
