# Copyright (c) 2018 NEC, Corp.
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
from mock import patch
import sys
import unittest

from oslo_config import cfg
from oslo_service import service
from tricircle.api import app
from tricircle.cmd import api
from tricircle.cmd import xjob
from tricircle.xjob import xservice


def fake_wait(self):
    return


class TestXjobCmd(unittest.TestCase):
    def setUp(self):
        super(TestXjobCmd, self).setUp()
        sys.argv = ['tricircle-cmd']
        cfg.CONF.reset()
        cfg.CONF.unregister_opts(xservice.common_opts)
        cfg.CONF.unregister_opts(app.common_opts)

    @patch.object(service.ProcessLauncher, 'wait', new=fake_wait)
    @mock.patch('tricircle.xjob.xservice.create_service')
    @mock.patch('oslo_service.service.ProcessLauncher.launch_service')
    def test_xjob_main(self, launch_service, create_service):
        xjob.main()
        launch_service.assert_called_once_with(
            create_service.return_value, workers=1)

    @patch.object(service.ProcessLauncher, 'wait', new=fake_wait)
    @mock.patch('tricircle.api.app.setup_app')
    @mock.patch('oslo_service.wsgi.Server')
    @mock.patch('oslo_service.service.ProcessLauncher.launch_service')
    def test_api_main(self, launch_service, wsgi_server, setup_app):
        api.main()
        wsgi_server.assert_called_once_with(mock.ANY, 'Tricircle Admin_API',
                                            setup_app.return_value,
                                            mock.ANY, mock.ANY)
        launch_service.assert_called_once_with(
            wsgi_server.return_value, workers=1)

    def tearDown(self):
        cfg.CONF.reset()
        cfg.CONF.unregister_opts(xservice.common_opts)
        cfg.CONF.unregister_opts(app.common_opts)
