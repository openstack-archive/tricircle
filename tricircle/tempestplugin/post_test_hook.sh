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
export DEVSTACK_DIR=$DEST/tricircle/devstack
export TRICIRCLE_DIR=$DEST/tricircle
export TRICIRCLE_TEMPEST_PLUGIN_DIR=$TRICIRCLE_DIR/tricircle/tempestplugin
export TEMPEST_DIR=$DEST/tempest

# use admin role to create Tricircle top Pod and Pod1
source $BASE/new/devstack/openrc admin admin

token=$(openstack token issue | awk 'NR==5 {print $4}')
echo $token

curl -X POST http://127.0.0.1:19999/v1.0/pods \
    -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods \
    -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" \
    -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

# preparation for the tests
cd $TEMPEST_DIR
if [ -d .testrepository ]; then
  sudo rm -r .testrepository
fi
# sudo -H -u jenkins testr init

# Run the Compute Tempest tests
# cd $TRICIRCLE_TEMPEST_PLUGIN_DIR
# sudo BASE=$BASE ./tempest_compute.sh

# Run the Volume Tempest tests
cd $TRICIRCLE_TEMPEST_PLUGIN_DIR
sudo BASE=$BASE ./tempest_volume.sh

# Run the Network Tempest tests
# cd $TRICIRCLE_TEMPEST_PLUGIN_DIR
# sudo BASE=$BASE ./tempest_network.sh

# Run the Scenario Tempest tests
# cd $TRICIRCLE_TEMPEST_PLUGIN_DIR
# sudo BASE=$BASE ./tempest_scenario.sh
