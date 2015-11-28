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

from oslo_config.cfg import CONF

import tricircle.common.service as t_service
from tricircle.common.utils import get_import_path
from tricircle.proxy.compute_manager import ProxyComputeManager

_REPORT_INTERVAL = 30
_REPORT_INTERVAL_MAX = 60


def setup_server():
    service = t_service.NovaService(
        host=CONF.host,
        # NOTE(zhiyuan) binary needs to start with "nova-"
        # if nova service is used
        binary="nova-proxy",
        topic="proxy",
        db_allowed=False,
        periodic_enable=True,
        report_interval=_REPORT_INTERVAL,
        periodic_interval_max=_REPORT_INTERVAL_MAX,
        manager=get_import_path(ProxyComputeManager),
    )

    t_service.fix_compute_service_exchange(service)

    return service
