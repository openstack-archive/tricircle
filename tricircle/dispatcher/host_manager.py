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

import tricircle.common.service as t_service
from tricircle.common.utils import get_import_path
from tricircle.dispatcher.compute_manager import DispatcherComputeManager

_REPORT_INTERVAL = 30
_REPORT_INTERVAL_MAX = 60


class ComputeHostManager(object):
    def __init__(self, site_manager):
        self._compute_nodes = []
        self._site_manager = site_manager

    def _create_compute_node_service(self, host):
        service = t_service.NovaService(
            host=host,
            binary="nova-compute",
            topic="compute",  # TODO(saggi): get from conf
            db_allowed=False,
            periodic_enable=True,
            report_interval=_REPORT_INTERVAL,
            periodic_interval_max=_REPORT_INTERVAL_MAX,
            manager=get_import_path(DispatcherComputeManager),
            site_manager=self._site_manager
        )

        t_service.fix_compute_service_exchange(service)

        return service

    def create_host_adapter(self, host):
        """Creates an adapter between the nova compute API and Site object"""
        service = self._create_compute_node_service(host)
        service.start()
        self._compute_nodes.append(service)
