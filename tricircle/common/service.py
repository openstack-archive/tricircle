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

from tricircle.common.nova_lib import rpc as nova_rpc
from tricircle.common.nova_lib import service as nova_service
from tricircle.common.nova_lib import version as nova_version


def fix_compute_service_exchange(service):
    """Fix service exchange value for nova"""

    _manager = service.manager

    client_paths = [
        ('compute_rpcapi', 'client'),
        ('compute_task_api', 'conductor_compute_rpcapi', 'client'),
        ('consoleauth_rpcapi', 'client'),
        ('scheduler_client', 'queryclient', 'scheduler_rpcapi', 'client'),
        ('proxy_client',),
        ('conductor_api', '_manager', 'client')
    ]
    for client_path in client_paths:
        if not hasattr(_manager, client_path[0]):
            continue
        obj = getattr(_manager, client_path[0])
        for part in client_path[1:]:
            obj = getattr(obj, part)
        obj.target.exchange = 'nova'


def _patch_nova_service():
    if nova_version.loaded:
        return

    nova_version.NOVA_PACKAGE = "tricircle"
    nova_rpc.TRANSPORT.conf.set_override('control_exchange', 'nova')
    nova_version.loaded = True


class NovaService(nova_service.Service):
    def __init__(self, *args, **kwargs):
        _patch_nova_service()
        self._conductor_api = None
        self._rpcserver = None
        super(NovaService, self).__init__(*args, **kwargs)

    @property
    def conductor_api(self):
        return self._conductor_api

    @conductor_api.setter
    def conductor_api(self, value):
        self._conductor_api = value
        for client in (
            self._conductor_api.base_rpcapi.client,
            self._conductor_api._manager.client,
        ):
            client.target.exchange = "nova"

    @property
    def rpcserver(self):
        return self._rpcserver

    @rpcserver.setter
    def rpcserver(self, value):
        self._rpcserver = value
        if value is not None:
            value.dispatcher._target.exchange = "nova"
