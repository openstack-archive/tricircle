
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

from mock import patch
from oslo_config import cfg
import oslo_messaging as messaging
import unittest

from tricircle.xjob import xmanager
from tricircle.xjob import xservice

CONF = cfg.CONF


def fake_rpc_start(self, override_pool_size=None):
    return


class FakeXManager(xmanager.XManager):
    """Fake xmanager for tests."""
    def __init__(self, host=None, service_name=None):
        super(FakeXManager, self).__init__(host=host,
                                           service_name=service_name)

    def test_method(self):
        return 'manager'


class ExtendedXService(xservice.XService):
    def test_method(self):
        return 'service'


class XServiceTest(unittest.TestCase):
    """Test cases for XServices."""

    def setUp(self):
        for opt in xservice.common_opts:
            if opt.name == 'enable_api_gateway':
                CONF.unregister_opt(opt)
        CONF.register_opts(xservice.common_opts)

    @patch.object(messaging.MessageHandlingServer, 'start',
                  new=fake_rpc_start)
    def test_message_gets_to_manager(self):
        t_manager = FakeXManager()
        serv = xservice.XService('test', 'test', 'test', t_manager)
        serv.start()
        self.assertEqual('manager', serv.test_method())

    @patch.object(messaging.MessageHandlingServer, 'start',
                  new=fake_rpc_start)
    def test_override_manager_method(self):
        t_manager = FakeXManager()
        serv = ExtendedXService('test', 'test', 'test', t_manager)
        serv.start()
        self.assertEqual('service', serv.test_method())

    @patch.object(messaging.MessageHandlingServer, 'start',
                  new=fake_rpc_start)
    def test_service_create(self):
        t_manager = FakeXManager()
        CONF.set_override('host', 'tricircle-foo')
        serv = xservice.XService.create(manager=t_manager)
        serv.start()
        self.assertEqual('manager', serv.test_method())
        self.assertEqual('tricircle-foo', serv.host)

    @patch.object(messaging.MessageHandlingServer, 'start',
                  new=fake_rpc_start)
    def test_service_create_extend(self):
        CONF.set_override('host', 'tricircle-bar')
        serv = xservice.create_service()
        self.assertEqual('tricircle-bar', serv.host)

    def tearDown(self):
        CONF.unregister_opts(xservice.common_opts)
