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
# TODO(saggi) change to oslo before release
from oslo_serialization import jsonutils as json

from tricircle.common.singleton import Singleton
from tricircle.cascade_service.compute import ComputeHostManager


class Node(object):
    def __init__(self, name):
        self.vcpus = 20
        self.memory_mb = 1024 * 32  # 32 GB
        self.memory_mb_used = self.memory_mb * 0.1
        self.free_ram_mb = self.memory_mb - self.memory_mb_used
        self.local_gb = 1024 * 10  # 10 TB
        self.local_gb_used = self.local_gb * 0.3
        self.free_disk_gb = self.local_gb - self.local_gb_used
        self.vcpus_used = 0
        self.hypervisor_type = "Cascade Site"
        self.hypervisor_version = 1
        self.current_workload = 1
        self.hypervisor_hostname = name
        self.running_vms = 0
        self.cpu_info = ""
        self.disk_available_least = 1
        self.supported_instances = []
        self.metrics = None
        self.pci_stats = None
        self.extra_resources = None
        self.stats = json.dumps({})
        self.numa_topology = None

    def get_available_resource(self):
        return {
            "vcpus": self.vcpus,
            "memory_mb": self.memory_mb,
            "local_gb": self.local_gb,
            "vcpus_used": self.vcpus_used,
            "memory_mb_used": self.memory_mb_used,
            "local_gb_used": self.local_gb_used,
            "hypervisor_type": self.hypervisor_type,
            "hypervisor_version": self.hypervisor_version,
            "hypervisor_hostname": self.hypervisor_hostname,
            "free_ram_mb": self.free_ram_mb,
            "free_disk_gb": self.free_disk_gb,
            "current_workload": self.current_workload,
            "running_vms": self.running_vms,
            "cpu_info": self.cpu_info,
            "disk_available_least": self.disk_available_least,
            "supported_instances": self.supported_instances,
            "metrics": self.metrics,
            "pci_stats": self.pci_stats,
            "extra_resources": self.extra_resources,
            "stats": (self.stats),
            "numa_topology": (self.numa_topology),
        }


class Site(object):
    def __init__(self, name):
        self.name = name

        # We currently just hold one aggregate subnode representing the
        # resources owned by all the site's nodes.
        self._aggragate_node = Node("cascade_" + name)

        self._instance_launch_information = {}

    def get_nodes(self):
        return [self._aggragate_node]

    def get_node(self, name):
        return self._aggragate_node

    def get_num_instances(self):
        return 0

    def prepare_for_instance(self, request_spec, filter_properties):
        instance_uuid = request_spec[u'instance_properties']['uuid']
        self._instance_launch_information[instance_uuid] = (
            request_spec,
            filter_properties
        )


class _SiteManager(object):
    def __init__(self):
        self._sites = {}
        self.compute_host_manager = ComputeHostManager(self)

        # create fake data
        # NOTE(saggi) replace with DAL access when available
        self.create_site("Fake01")
        self.create_site("Fake02")

    def create_site(self, site_name):
        """creates a fake site, in reality the information about available
        sites should be pulled from the DAL and not created at will.
        """
        # TODO(saggi): thread safty
        if site_name in self._sites:
            raise RuntimeError("Site already exists in site map")

        self._sites[site_name] = Site(site_name)
        self.compute_host_manager.create_host_adapter(site_name)

    def get_site(self, site_name):
        return self._sites[site_name]

get_instance = Singleton(_SiteManager).get_instance
