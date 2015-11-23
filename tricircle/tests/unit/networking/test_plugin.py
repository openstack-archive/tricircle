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
from neutron.common import exceptions as neutron_exceptions
from neutron.common import rpc as neutron_rpc
from neutron.db import db_base_plugin_v2

from tricircle.common import context
from tricircle.networking.plugin import TricirclePlugin


FAKE_PORT_ID = 'fake_port_uuid'
FAKE_PORT = {
    'id': FAKE_PORT_ID,
    'status': neutron_const.PORT_STATUS_DOWN
}


def fake_get_port(instance, context, port_id):
    if port_id == FAKE_PORT_ID:
        return FAKE_PORT
    else:
        raise neutron_exceptions.PortNotFound(port_id=port_id)


def fake_update_port(instance, context, port_id, port):
    FAKE_PORT['status'] = port['port']['status']
    return FAKE_PORT


class TricirclePluginTest(unittest.TestCase):
    def setUp(self):
        FAKE_PORT['status'] = neutron_const.PORT_STATUS_DOWN

    @patch.object(neutron_rpc, 'get_client', new=mock.Mock())
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2,
                  'update_port', new=fake_update_port)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2,
                  'get_port', new=fake_get_port)
    def test_update_port_status(self):
        plugin = TricirclePlugin()
        # this method requires a neutron context, but for test we just pass
        # a tricircle context
        port = plugin.update_port_status(context.Context(), FAKE_PORT_ID,
                                         neutron_const.PORT_STATUS_ACTIVE)
        self.assertEqual(FAKE_PORT['status'], neutron_const.PORT_STATUS_ACTIVE)
        self.assertIsNotNone(port)

    @patch.object(neutron_rpc, 'get_client', new=mock.Mock())
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2,
                  'update_port', new=fake_update_port)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2,
                  'get_port', new=fake_get_port)
    def test_update_port_status_port_not_found(self):
        plugin = TricirclePlugin()
        port = plugin.update_port_status(context.Context(), 'no_such_port',
                                         neutron_const.PORT_STATUS_ACTIVE)
        self.assertEqual(FAKE_PORT['status'], neutron_const.PORT_STATUS_DOWN)
        self.assertIsNone(port)
