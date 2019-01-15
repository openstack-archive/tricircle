#!/bin/bash -xe

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script is executed inside post_test_hook function in devstack gate.

export DEST=$BASE/new
export DEVSTACK_DIR=$DEST/devstack
export TRICIRCLE_DIR=$DEST/tricircle
export TRICIRCLE_DEVSTACK_PLUGIN_DIR=$TRICIRCLE_DIR/devstack
export TRICIRCLE_TEMPEST_PLUGIN_DIR=$TRICIRCLE_DIR/tricircle/tempestplugin

# execute test only in the primary node(i.e, RegionOne)
if [ "$OS_REGION_NAME" -ne "RegionOne" ]; then
    return 0
fi

PRIMARY_NODE_IP=$(cat /etc/nodepool/primary_node_private)

# use admin role to create Tricircle top Pod and Pod1
source $DEVSTACK_DIR/openrc admin admin
unset OS_REGION_NAME
mytoken=$(openstack --os-region-name=RegionOne token issue | awk 'NR==5 {print $4}')
echo $mytoken

openstack multiregion networking pod create --region-name CentralRegion

openstack multiregion networking pod create --region-name RegionOne --availability-zone az1

if [ "$DEVSTACK_GATE_TOPOLOGY" == "multinode" ]; then
    openstack multiregion networking pod create --region-name RegionTwo --availability-zone az2
fi

# the usage of "nova flavor-create":
# nova flavor-create [--ephemeral <ephemeral>] [--swap <swap>]
#                    [--rxtx-factor <factor>] [--is-public <is-public>]
#                    <name> <id> <ram> <disk> <vcpus>
# the following command is to create a flavor with name='test',
# id=1, ram=1024MB, disk=10GB, vcpu=1
# nova flavor-create test 1 1024 10 1
image_id=$(openstack --os-region-name=RegionOne image list | awk 'NR==4 {print $2}')

# change the tempest configuration to test Tricircle
env | grep OS_

#Temporary comment smoke test due to ci environment problems
#if [ "$DEVSTACK_GATE_TOPOLOGY" == "multinode" ]; then
#    cd $TRICIRCLE_TEMPEST_PLUGIN_DIR
#    sudo BASE=$BASE bash smoke_test.sh
#fi
