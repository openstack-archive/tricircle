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

import mock
from mock import patch
import unittest

from neutron.common import constants as neutron_const
from neutron.common import rpc as neutron_rpc
from neutron import manager

from tricircle.networking_tricircle import plugin
from tricircle.networking_tricircle import rpc


FAKE_PORT_ID = 'fake_port_uuid'
FAKE_CONTEXT = object()


class RpcCallbacksTest(unittest.TestCase):
    def setUp(self):
        self.callbacks = rpc.RpcCallbacks()

    @patch.object(neutron_rpc, 'get_client', new=mock.Mock())
    def test_update_port_up(self):
        with patch.object(manager.NeutronManager,
                          'get_plugin') as get_plugin_method:
            with patch.object(plugin.TricirclePlugin,
                              'update_port_status') as update_method:
                get_plugin_method.return_value = plugin.TricirclePlugin()
                self.callbacks.update_port_up(FAKE_CONTEXT,
                                              port_id=FAKE_PORT_ID)
                update_method.assert_called_once_with(
                    FAKE_CONTEXT, FAKE_PORT_ID,
                    neutron_const.PORT_STATUS_ACTIVE)

    @patch.object(neutron_rpc, 'get_client', new=mock.Mock())
    def test_update_port_down(self):
        with patch.object(manager.NeutronManager,
                          'get_plugin') as get_plugin_method:
            with patch.object(plugin.TricirclePlugin,
                              'update_port_status') as update_method:
                get_plugin_method.return_value = plugin.TricirclePlugin()
                self.callbacks.update_port_down(FAKE_CONTEXT,
                                                port_id=FAKE_PORT_ID)
                update_method.assert_called_once_with(
                    FAKE_CONTEXT, FAKE_PORT_ID, neutron_const.PORT_STATUS_DOWN)
