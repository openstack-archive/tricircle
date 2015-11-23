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

from nova.compute.manager import ComputeManager
from nova.virt.fake import FakeDriver

import nova.rpc as nova_rpc
from nova.service import Service
import nova.version as nova_version

from tricircle.common.utils import get_import_path

_REPORT_INTERVAL = 30
_REPORT_INTERVAL_MAX = 60


def _patch_nova_service():
    if nova_version.loaded:
        return

    nova_version.NOVA_PACKAGE = "tricircle"
    nova_rpc.TRANSPORT.conf.set_override('control_exchange', 'nova')
    nova_version.loaded = True


class NovaService(Service):
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


def _fix_compute_service_exchange(service):
    """Fix service exchange value for nova"""

    manager = service.manager
    for client in (
        manager.compute_rpcapi.client,
        manager.compute_task_api.conductor_compute_rpcapi.client,
        manager.consoleauth_rpcapi.client,
        # manager.scheduler_client.queryclient.scheduler_rpcapi.client,
    ):
        client.target.exchange = "nova"


class ComputeHostManager(object):
    def __init__(self, site_manager):
        self._compute_nodes = []

    def _create_compute_node_service(self, host):
        service = NovaService(
            host=host,
            binary="nova-compute",
            topic="compute",  # TODO(saggi): get from conf
            db_allowed=False,
            periodic_enable=True,
            report_interval=_REPORT_INTERVAL,
            periodic_interval_max=_REPORT_INTERVAL_MAX,
            manager=get_import_path(ComputeManager),
            # temporally use FakeDriver, new compute manager doesn't require
            # compute driver so this can be removed after new compute manager
            # is finished
            compute_driver=get_import_path(FakeDriver)
        )

        _fix_compute_service_exchange(service)

        return service

    def create_host_adapter(self, host):
        """Creates an adapter between the nova compute API and Site object"""
        service = self._create_compute_node_service(host)
        service.start()
        self._compute_nodes.append(service)
