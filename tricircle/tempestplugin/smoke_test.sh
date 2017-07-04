#!/bin/bash -xe

DEST=$BASE/new
DEVSTACK_DIR=$DEST/devstack
source $DEVSTACK_DIR/openrc admin admin
unset OS_REGION_NAME

python run_yaml_test.py single_gw_topology_test.yaml "$OS_AUTH_URL" "$OS_TENANT_NAME" "$OS_USERNAME" "$OS_PASSWORD"
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in single gateway topology test"
fi
python run_yaml_test.py multi_gw_topology_test.yaml "$OS_AUTH_URL" "$OS_TENANT_NAME" "$OS_USERNAME" "$OS_PASSWORD"
if [ $? != 0 ]; then
    die $LINENO "Smoke test fails, error in multi gateway topology test"
fi
