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

import datetime


# service type
ST_NEUTRON = 'neutron'


# resource_type
RT_NETWORK = 'network'
RT_SD_NETWORK = 'shadow_network'
RT_SUBNET = 'subnet'
RT_SD_SUBNET = 'shadow_subnet'
RT_PORT = 'port'
RT_TRUNK = 'trunk'
RT_SD_PORT = 'shadow_port'
RT_ROUTER = 'router'
RT_NS_ROUTER = 'ns_router'
RT_SG = 'security_group'
RT_FIP = 'floatingip'

REAL_SHADOW_TYPE_MAP = {
    RT_NETWORK: RT_SD_NETWORK,
    RT_SUBNET: RT_SD_SUBNET,
    RT_PORT: RT_SD_PORT
}


# check whether the resource type is properly provisioned.
def is_valid_resource_type(resource_type):
    resource_type_table = [RT_NETWORK, RT_SUBNET, RT_PORT, RT_ROUTER, RT_SG]
    return resource_type in resource_type_table


# version list
NEUTRON_VERSION_V2 = 'v2'

# supported release
R_LIBERTY = 'liberty'
R_MITAKA = 'mitaka'

# l3 bridge networking elements
bridge_subnet_pool_name = 'bridge_subnet_pool'
bridge_net_name = 'bridge_net_%s'  # project_id
bridge_subnet_name = 'bridge_subnet_%s'  # project_id
bridge_port_name = 'bridge_port_%s_%s'  # project_id b_router_id

# for external gateway port: project_id b_router_id None
# for floating ip port: project_id None b_internal_port_id
ns_bridge_port_name = 'ns_bridge_port_%s_%s_%s'
ns_router_name = 'ns_router_%s'

shadow_port_name = 'shadow_port_%s'
dhcp_port_name = 'dhcp_port_%s'  # subnet_id
snat_port_name = 'snat_port_%s'  # subnet_id
interface_port_name = 'interface_%s_%s'  # b_region_name t_subnet_id
interface_port_device_id = 'reserved_gateway_port'

MAX_INT = 0x7FFFFFFF
DEFAULT_DESTINATION = '0.0.0.0/0'
expire_time = datetime.datetime(2000, 1, 1)

# job status
JS_New = '3_New'
JS_Running = '2_Running'
JS_Success = '1_Success'
JS_Fail = '0_Fail'

SP_EXTRA_ID = '00000000-0000-0000-0000-000000000000'
TOP = 'top'
POD_NOT_SPECIFIED = 'not_specified_pod'
PROFILE_REGION = 'region'
PROFILE_DEVICE = 'device'
PROFILE_HOST = 'host'
PROFILE_AGENT_TYPE = 'type'
PROFILE_TUNNEL_IP = 'tunnel_ip'
PROFILE_FORCE_UP = 'force_up'
PROFILE_LOCAL_TRUNK_ID = 'local_trunk_id'
DEVICE_OWNER_SHADOW = 'compute:shadow'
DEVICE_OWNER_SUBPORT = 'trunk:subport'

# job type
JT_CONFIGURE_ROUTE = 'configure_route'
JT_ROUTER_SETUP = 'router_setup'
JT_PORT_DELETE = 'port_delete'
JT_SEG_RULE_SETUP = 'seg_rule_setup'
JT_NETWORK_UPDATE = 'update_network'
JT_SUBNET_UPDATE = 'subnet_update'
JT_SHADOW_PORT_SETUP = 'shadow_port_setup'
JT_TRUNK_SYNC = 'trunk_sync'

# network type
NT_LOCAL = 'local'
NT_VLAN = 'vlan'
NT_VxLAN = 'vxlan'
NT_FLAT = 'flat'

# cross-pod VxLAN networking support mode
NM_P2P = 'p2p'
NM_L2GW = 'l2gw'
NM_NOOP = 'noop'

# map job type to its resource, each resource is denoted by
# (resource_type, resource_id), for the field necessary
# to run the job but resides outside of job resource, we
# denote its type by "None"
job_resource_map = {
    JT_CONFIGURE_ROUTE: [(RT_ROUTER, "router_id")],
    JT_ROUTER_SETUP: [(None, "pod_id"),
                      (RT_ROUTER, "router_id"),
                      (RT_NETWORK, "network_id")],
    JT_PORT_DELETE: [(None, "pod_id"),
                     (RT_PORT, "port_id")],
    JT_SEG_RULE_SETUP: [(None, "project_id")],
    JT_NETWORK_UPDATE: [(None, "pod_id"),
                        (RT_NETWORK, "network_id")],
    JT_TRUNK_SYNC: [(None, "pod_id"),
                    (RT_TRUNK, "trunk_id")],
    JT_SUBNET_UPDATE: [(None, "pod_id"),
                       (RT_SUBNET, "subnet_id")],
    JT_SHADOW_PORT_SETUP: [(None, "pod_id"),
                           (RT_NETWORK, "network_id")]
}

# map raw job status to more human readable job status
job_status_map = {
    JS_Fail: 'FAIL',
    JS_Success: 'SUCCESS',
    JS_Running: 'RUNNING',
    JS_New: 'NEW'
}

# filter jobs according to the job's attributes
JOB_LIST_SUPPORTED_FILTERS = ['project_id', 'type', 'status']

# map job type to corresponding job handler
job_handles = {
    JT_CONFIGURE_ROUTE: "configure_route",
    JT_ROUTER_SETUP: "setup_bottom_router",
    JT_PORT_DELETE: "delete_server_port",
    JT_SEG_RULE_SETUP: "configure_security_group_rules",
    JT_NETWORK_UPDATE: "update_network",
    JT_SUBNET_UPDATE: "update_subnet",
    JT_TRUNK_SYNC: "sync_trunk",
    JT_SHADOW_PORT_SETUP: "setup_shadow_ports"
}

# map job type to its primary resource and then we only validate the project_id
# of that resource. For JT_SEG_RULE_SETUP, as it has only one project_id
# parameter, there is no need to validate it.
job_primary_resource_map = {
    JT_CONFIGURE_ROUTE: (RT_ROUTER, "router_id"),
    JT_ROUTER_SETUP: (RT_ROUTER, "router_id"),
    JT_PORT_DELETE: (RT_PORT, "port_id"),
    JT_SEG_RULE_SETUP: (None, "project_id"),
    JT_NETWORK_UPDATE: (RT_NETWORK, "network_id"),
    JT_SUBNET_UPDATE: (RT_SUBNET, "subnet_id"),
    JT_TRUNK_SYNC: (RT_TRUNK, "trunk_id"),
    JT_SHADOW_PORT_SETUP: (RT_NETWORK, "network_id")
}
