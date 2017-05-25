#!/bin/bash -xe

DEST=$BASE/new
DEVSTACK_DIR=$DEST/devstack
source $DEVSTACK_DIR/openrc admin admin
unset OS_REGION_NAME

openstacktop="openstack --os-region-name CentralRegion"
openstackpod1="openstack --os-region-name RegionOne"
openstackpod2="openstack --os-region-name RegionTwo"

echo list networks before running
$openstacktop network list

echo create external network
$openstacktop network create --external --provider-network-type vlan \
    --provider-physical-network extern --availability-zone-hint RegionTwo ext-net

echo show networks after running
for id in $($openstacktop network list -c ID -f value)
    do $openstacktop network show $id
done

echo create external subnet
$openstacktop subnet create --subnet-range 163.3.124.0/24 --network ext-net \
    --no-dhcp ext-subnet

echo create router
router_id=$($openstacktop router create router -c id -f value)

echo attach router to external network
$openstacktop router set --external-gateway ext-net router

echo create network1
$openstacktop network create net1

echo create subnet1
$openstacktop subnet create --subnet-range 10.0.1.0/24 --network net1 \
    --allocation-pool start=10.0.1.10,end=10.0.1.90 subnet1

echo create network3
$openstacktop network create net3

echo create subnet3 that has same CIDR with subnet1
$openstacktop subnet create --subnet-range 10.0.1.0/24 --network net3 \
    --allocation-pool start=10.0.1.110,end=10.0.1.190 subnet3

echo create port1
port1_id=$($openstacktop port create --network net1 port1 -c id -f value)

echo attach subnet1 to router
$openstacktop router add subnet router subnet1

echo associate floating ip to port1
$openstacktop floating ip create --port $port1_id ext-net -c id -f value

image1_id=$($openstackpod1 image list -c ID -f value)

echo create server1
$openstackpod1 server create --flavor 1 --image $image1_id --nic port-id=$port1_id vm1

echo create network2
net2_id=$($openstacktop network create net2 -c id -f value)

echo create subnet2
$openstacktop subnet create --subnet-range 10.0.2.0/24 --network net2 subnet2

image2_id=$($openstackpod2 image list -c ID -f value)

echo create server2
$openstackpod2 server create --flavor 1 --image $image2_id --nic net-id=$net2_id vm2

echo attach subnet2 to router
$openstacktop router add subnet router subnet2

echo create network4
net4_id=$($openstacktop network create net4 -c id -f value)

echo create subnet4 that has no gateway
$openstacktop subnet create --subnet-range 10.0.4.0/24 --network net4 \
    --gateway None subnet4

echo create server3
$openstackpod1 server create --flavor 1 --image $image1_id --nic net-id=$net4_id vm3

sleep 20

TOP_DIR=$DEVSTACK_DIR
source $DEVSTACK_DIR/stackrc
source $DEVSTACK_DIR/inc/meta-config
extract_localrc_section $TOP_DIR/local.conf $TOP_DIR/localrc $TOP_DIR/.localrc.auto
source $DEVSTACK_DIR/functions-common
source $DEVSTACK_DIR/lib/database
initialize_database_backends

if [ "$DATABASE_TYPE" == "mysql" ]; then
    for i in $(seq 1 11); do
        if [ $i == 11 ]; then
            # we check fail job at the end to give fail job a chance to redo
            fail_result=$(mysql -u$DATABASE_USER -p$DATABASE_PASSWORD -h$DATABASE_HOST -Dtricircle -e 'SELECT COUNT(*) FROM async_jobs WHERE status = "0_Fail"')
            fail_count=$(echo $fail_result | grep -o "[0-9]\{1,\}")
            if [ $fail_count -ne 0 ]; then
                echo "Listing fail job"
                mysql -u$DATABASE_USER -p$DATABASE_PASSWORD -h$DATABASE_HOST -Dtricircle -e 'SELECT * FROM async_jobs WHERE status = "0_Fail";'
                die $LINENO "Smoke test fails, $fail_count job fail"
            fi
            die $LINENO "Smoke test fails, exceed max wait time for job"
        fi
        full_result=$(mysql -u$DATABASE_USER -p$DATABASE_PASSWORD -h$DATABASE_HOST -Dtricircle -e 'SELECT COUNT(*) FROM async_jobs;')
        full_count=$(echo $full_result | grep -o "[0-9]\{1,\}")
        if [ $full_count -ne 0 ]; then
            echo "Wait for job to finish"
            sleep 10
        else
            break
        fi
    done
else
    for i in $(seq 1 11); do
        if [ $i == 11 ]; then
            # we check fail job at the end to give fail job a chance to redo
            fail_result=$(psql -h$DATABASE_HOST -U$DATABASE_USER -dtricircle -c 'SELECT COUNT(*) FROM async_jobs WHERE status = "0_Fail"')
            fail_count=$(echo $fail_result | grep -o "[0-9]\{1,\}")
            if [ $fail_count -ne 0 ]; then
                echo "Listing fail job"
                psql -h$DATABASE_HOST -U$DATABASE_USER -dtricircle -c 'SELECT * FROM async_jobs WHERE status = "0_Fail";'
                die $LINENO "Smoke test fails, $fail_count job fail"
            fi
            die $LINENO "Smoke test fails, exceed max wait time for job"
        fi
        full_result=$(psql -h$DATABASE_HOST -U$DATABASE_USER -dtricircle -c 'SELECT COUNT(*) FROM async_jobs;')
        full_count=$(echo $full_result | grep -o "[0-9]\{1,\}")
        if [ $full_count -ne 0 ]; then
            echo "Wait for job to finish"
            sleep 10
        else
            break
        fi
    done
fi

$openstackpod1 server list -f json | python smoke_test_validation.py server 1
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in server of RegionOne"
fi
$openstackpod2 server list -f json | python smoke_test_validation.py server 2
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in server of RegionTwo"
fi
$openstackpod1 subnet list -f json | python smoke_test_validation.py subnet 1
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in subnet of RegionOne"
fi
$openstackpod2 subnet list -f json | python smoke_test_validation.py subnet 2
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in subnet of RegionTwo"
fi
$openstackpod1 port list --router $router_id -f json | python smoke_test_validation.py router_port 1
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in router port of RegionOne"
fi
$openstackpod2 port list --router $router_id -f json | python smoke_test_validation.py router_port 2
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in router port of RegionTwo"
fi
$openstackpod1 router show $router_id -c routes -f json | python smoke_test_validation.py router 1
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in router of RegionOne"
fi
$openstackpod2 router show $router_id -c routes -f json | python smoke_test_validation.py router 2
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in router of RegionTwo"
fi
