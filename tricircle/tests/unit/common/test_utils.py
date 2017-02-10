
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

import unittest

from tricircle.common import exceptions
from tricircle.common import utils


class TricircleUtilsTestCase(unittest.TestCase):
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
