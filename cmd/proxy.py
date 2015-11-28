# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import eventlet

if __name__ == "__main__":
    eventlet.monkey_patch()

import sys
import traceback

from oslo_config import cfg
from oslo_log import log as logging

from tricircle.common.i18n import _LE
from tricircle.common.nova_lib import conductor_rpcapi
from tricircle.common.nova_lib import db_api as nova_db_api
from tricircle.common.nova_lib import exception as nova_exception
from tricircle.common.nova_lib import objects as nova_objects
from tricircle.common.nova_lib import objects_base
from tricircle.common.nova_lib import quota
from tricircle.common.nova_lib import rpc as nova_rpc
from tricircle.proxy import service


def block_db_access():
    class NoDB(object):
        def __getattr__(self, attr):
            return self

        def __call__(self, *args, **kwargs):
            stacktrace = "".join(traceback.format_stack())
            LOG = logging.getLogger('nova.compute')
            LOG.error(_LE('No db access allowed in nova-compute: %s'),
                      stacktrace)
            raise nova_exception.DBNotAllowed('nova-compute')

    nova_db_api.IMPL = NoDB()


def set_up_nova_object_indirection():
    conductor = conductor_rpcapi.ConductorAPI()
    conductor.client.target.exchange = "nova"
    objects_base.NovaObject.indirection_api = conductor


def process_command_line_arguments():
    logging.register_options(cfg.CONF)
    logging.set_defaults()
    cfg.CONF(sys.argv[1:])
    logging.setup(cfg.CONF, "proxy", version='0.1')


def _set_up_nova_objects():
    nova_rpc.init(cfg.CONF)
    block_db_access()
    set_up_nova_object_indirection()
    nova_objects.register_all()


def _disable_quotas():
    QUOTAS = quota.QUOTAS
    QUOTAS._driver_cls = quota.NoopQuotaDriver()


if __name__ == "__main__":
    _set_up_nova_objects()
    _disable_quotas()
    process_command_line_arguments()
    server = service.setup_server()
    server.start()
    server.wait()
