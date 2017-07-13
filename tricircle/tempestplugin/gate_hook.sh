#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script is executed inside gate_hook function in devstack gate.

set -ex

GATE_DEST=$BASE/new

# _setup_tricircle_multinode() - Set up two regions test environment
# in devstack multinode job. Tricircle API, central Neutron and RegionOne
# services will be enabled in primary node, RegionTwo servies will be
# enabled in the subnode. Currently only two nodes are supported in the
# test environment.

function _setup_tricircle_multinode {

    export PROJECTS="openstack/networking-sfc $PROJECTS"
    PRIMARY_NODE_IP=$(cat /etc/nodepool/primary_node_private)
    SUBNODE_IP=$(head -n1 /etc/nodepool/sub_nodes_private)

    export OVERRIDE_ENABLED_SERVICES="c-api,c-bak,c-sch,c-vol,cinder,"
    export OVERRIDE_ENABLED_SERVICES+="g-api,g-reg,key,"
    export OVERRIDE_ENABLED_SERVICES+="n-api,n-cauth,n-cond,n-cpu,n-crt,"
    export OVERRIDE_ENABLED_SERVICES+="n-novnc,n-obj,n-sch,"
    export OVERRIDE_ENABLED_SERVICES+="placement-api,placement-client,"
    export OVERRIDE_ENABLED_SERVICES+="q-agt,q-dhcp,q-l3,q-meta,"
    export OVERRIDE_ENABLED_SERVICES+="q-metering,q-svc,"
    export OVERRIDE_ENABLED_SERVICES+="dstat,peakmem_tracker,rabbit,mysql"

    ENABLE_TRICIRCLE="enable_plugin tricircle https://git.openstack.org/openstack/tricircle/"
    ENABLE_SFC="enable_plugin networking-sfc https://git.openstack.org/openstack/networking-sfc/"

    # Configure primary node
    export DEVSTACK_LOCAL_CONFIG="$ENABLE_TRICIRCLE"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"$ENABLE_SFC"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"TRICIRCLE_START_SERVICES=True"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"TRICIRCLE_ENABLE_TRUNK=True"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"TRICIRCLE_ENABLE_SFC=True"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"REGION_NAME=RegionOne"
    export DEVSTACK_LOCAL_CONFIG+=$'\n'"HOST_IP=$PRIMARY_NODE_IP"

    ML2_CONFIG=$'\n'"ML2_L3_PLUGIN=tricircle.network.local_l3_plugin.TricircleL3Plugin"
    ML2_CONFIG+=$'\n'"[[post-config|/"'$Q_PLUGIN_CONF_FILE]]'
    ML2_CONFIG+=$'\n'"[ml2]"
    ML2_CONFIG+=$'\n'"mechanism_drivers = openvswitch,linuxbridge,l2population"
    ML2_CONFIG+=$'\n'"[agent]"
    ML2_CONFIG+=$'\n'"extensions=sfc"
    ML2_CONFIG+=$'\n'"arp_responder=True"
    ML2_CONFIG+=$'\n'"tunnel_types=vxlan"
    ML2_CONFIG+=$'\n'"l2_population=True"

    export DEVSTACK_LOCAL_CONFIG+=$ML2_CONFIG

    # Configure sub-node
    export DEVSTACK_SUBNODE_CONFIG="$ENABLE_TRICIRCLE"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"$ENABLE_SFC"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"TRICIRCLE_START_SERVICES=False"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"TRICIRCLE_ENABLE_TRUNK=True"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"TRICIRCLE_ENABLE_SFC=True"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"REGION_NAME=RegionTwo"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"HOST_IP=$SUBNODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"KEYSTONE_REGION_NAME=RegionOne"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"KEYSTONE_SERVICE_HOST=$PRIMARY_NODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"KEYSTONE_AUTH_HOST=$PRIMARY_NODE_IP"

    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"SERVICE_HOST=$SUBNODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"RABBIT_HOST=$SUBNODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"QPID_HOST=$SUBNODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"DATABASE_HOST=$SUBNODE_IP"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"GLANCE_HOSTPORT=$SUBNODE_IP:9292"
    export DEVSTACK_SUBNODE_CONFIG+=$'\n'"Q_HOST=$SUBNODE_IP"

    export DEVSTACK_SUBNODE_CONFIG+=$ML2_CONFIG
}

if [ "$DEVSTACK_GATE_TOPOLOGY" == "multinode" ]; then
    _setup_tricircle_multinode
    $GATE_DEST/devstack-gate/devstack-vm-gate.sh
fi
