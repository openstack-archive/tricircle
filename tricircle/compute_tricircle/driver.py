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

from nova.virt import driver
from nova.virt.hardware import InstanceInfo
import nova.compute.power_state as power_state

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging

TRANSPORT = oslo_messaging.get_transport(cfg.CONF)

LOG = logging.getLogger(__name__)


class TricircleComputeDriver(driver.ComputeDriver):
    site_manager = None  # will be set later by the ComputeHostManager

    def __init__(self, virtapi):
        super(TricircleComputeDriver, self).__init__(virtapi)

    def init_host(self, host):
        self.host = host
        # NOTE(saggi) There is no way to pass arguments to the driver apart
        # from the host It's a bit convoluted and if you find a better way
        # please send a patch
        self._site = TricircleComputeDriver.site_manager.get_site(host)

    def get_available_nodes(self, refresh=False):
        return [node.hypervisor_hostname for node in self._site.get_nodes()]

    def get_available_resource(self, nodename):
        return self._site.get_node(nodename).get_available_resource()

    def get_num_instances(self):
        return self._site.get_num_instances()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        pass

    def get_info(self, instance):
        # TODO(saggi) will be redirected to cascade service
        return InstanceInfo(
            state=power_state.RUNNING,
            max_mem_kb=500,
            mem_kb=500,
            num_cpu=1,
            cpu_time_ns=100,
            id=instance.id,
        )
