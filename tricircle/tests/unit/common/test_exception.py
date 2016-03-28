
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

import six
import unittest

from tricircle.common import exceptions


class TricircleExceptionTestCase(unittest.TestCase):
    def test_default_error_msg(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = "default message"

        exc = FakeTricircleException()
        self.assertEqual('default message', six.text_type(exc))

    def test_error_msg(self):
        self.assertEqual('test',
                         six.text_type(exceptions.TricircleException('test')))

    def test_default_error_msg_with_kwargs(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = "default message: %(code)s"

        exc = FakeTricircleException(code=500)
        self.assertEqual('default message: 500', six.text_type(exc))

    def test_error_msg_exception_with_kwargs(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = "default message: %(misspelled_code)s"

        exc = FakeTricircleException(code=500)
        self.assertEqual('default message: %(misspelled_code)s',
                         six.text_type(exc))

    def test_default_error_code(self):
        class FakeTricircleException(exceptions.TricircleException):
            code = 404

        exc = FakeTricircleException()
        self.assertEqual(404, exc.kwargs['code'])

    def test_error_code_from_kwarg(self):
        class FakeTricircleException(exceptions.TricircleException):
            code = 500

        exc = FakeTricircleException(code=404)
        self.assertEqual(404, exc.kwargs['code'])

    def test_error_msg_is_exception_to_string(self):
        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = exceptions.TricircleException(exc1)
        self.assertEqual(msg, exc2.msg)

    def test_exception_kwargs_to_string(self):
        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = exceptions.TricircleException(kwarg1=exc1)
        self.assertEqual(msg, exc2.kwargs['kwarg1'])

    def test_message_in_format_string(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = 'FakeCinderException: %(message)s'

        exc = FakeTricircleException(message='message')
        self.assertEqual('FakeCinderException: message', six.text_type(exc))

    def test_message_and_kwarg_in_format_string(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = 'Error %(code)d: %(message)s'

        exc = FakeTricircleException(message='message', code=404)
        self.assertEqual('Error 404: message', six.text_type(exc))

    def test_message_is_exception_in_format_string(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = 'Exception: %(message)s'

        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = FakeTricircleException(message=exc1)
        self.assertEqual('Exception: test message', six.text_type(exc2))

    def test_no_message_input_exception_in_format_string(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = 'Error: %(message)s'

        exc = FakeTricircleException()
        out_message = six.text_type(exc)
        self.assertEqual('Error: None', out_message)

    def test_no_kwarg_input_exception_in_format_string(self):
        class FakeTricircleException(exceptions.TricircleException):
            message = 'No Kwarg Error: %(why)s, %(reason)s'

        exc = FakeTricircleException(why='why')
        out_message = six.text_type(exc)
        self.assertEqual('No Kwarg Error: %(why)s, %(reason)s', out_message)
