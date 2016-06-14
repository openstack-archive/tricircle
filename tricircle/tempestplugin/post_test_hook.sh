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

export DEST=${DEST:-/opt/stack/new}
export DEVSTACK_DIR=$DEST/tricircle/devstack
export TRICIRCLE_DIR=$DEST/tricircle
export TEMPEST_DIR=$DEST/tempest
export TEMPEST_CONF=$TEMPEST_DIR/etc/tempest.conf

# use admin role to create Tricircle top Pod and Pod1
source $DEVSTACK_DIR/admin-openrc.sh
token=$(openstack token issue | awk 'NR==5 {print $4}')
echo $token
curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'
curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

# preparation for the tests
cd $TEMPEST_DIR
testr init

# change the configruation to test Tricircle Cinder-APIGW
iniset $TEMPEST_CONF volume region RegionOne
iniset $TEMPEST_CONF volume catalog_type volumev2
iniset $TEMPEST_CONF volume endpoint_type publicURL
iniset $TEMPEST_CONF volume-feature-enabled api_v1 false

# Run functional test
echo "Running Tricircle functional test suite..."
ostestr --regex tempest.api.volume.test_volumes_list
ostestr --regex tempest.api.volume.test_volumes_get
