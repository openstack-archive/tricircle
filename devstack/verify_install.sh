#!/bin/bash

# This script is to verify the installation of Tricircle


TEST_DIR=$(pwd)
echo "Test work directy is $TEST_DIR."
source $TEST_DIR/adminrc.sh
echo "******************************"
echo "*       Verify Endpoint      *"
echo "******************************"
openstack endpoint list

token=$(openstack token issue | awk 'NR==5 {print $4}')

echo $token

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

echo "******************************"
echo "*         Verify nova        *"
echo "******************************"


nova aggregate-list
nova flavor-create test 1 1024 10 1

echo "******************************"
echo "*       Verify Neutron       *"
echo "******************************"

neutron net-create net1
neutron subnet-create net1 10.0.0.0/24
glance image-list

image_id=$(glance image-list |awk 'NR==4 {print $2}')
net_id=$(neutron net-list|grep net1 |awk '{print $2}')

nova boot --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az1 vm1

echo "******************************"
echo "*        Verify Cinder       *"
echo "******************************"


cinder --debug create --availability-zone=az1 1
cinder --debug list
volume_id=$(cinder list |grep lvmdriver-1 | awk '{print $2}')
cinder --debug show $volume_id
cinder --debug delete $volume_id
cinder --debug list


