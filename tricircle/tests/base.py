# Copyright (c) 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutron.conf import common as n_conf
from oslo_config import cfg
from oslotest import base


CONFLICT_OPT_NAMES = [
    'api_extensions_path',
    'bind_port',
    'bind_host',
    'allow_pagination',
    'allow_sorting'
]


class TestCase(base.BaseTestCase):
    """Test case base class for all unit tests."""
    def setUp(self):
        # neutron has configuration options "api_extensions_path",
        # "bind_port"  and "bind_host"which conflicts with tricircle
        # configuration option, so unregister this option before
        # running tricircle tests
        for opt in n_conf.core_opts:
            if opt.name in CONFLICT_OPT_NAMES:
                cfg.CONF.unregister_opt(opt)
        super(TestCase, self).setUp()
