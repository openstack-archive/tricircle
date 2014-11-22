#!/bin/bash

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#    Copyright (c) 2014 Huawei Technologies.

CASCADING_CONTROL_IP=127.0.0.1
CASCADING_REGION_NAME=Cascading_Openstack
CASCADED_REGION_NAME=AZ1
USER_NAME=neutron
USER_PWD=openstack
TENANT_NAME=service

#For test path or the path is not standard
_PREFIX_DIR=""

_NEUTRON_CONF_DIR="${_PREFIX_DIR}/etc/neutron"
_NEUTRON_INSTALL="${_PREFIX_DIR}/usr/lib/python2.7/dist-packages"
_NEUTRON_DIR="${_NEUTRON_INSTALL}/neutron"
_NEUTRON_L3_PROXY_CONF_FILE='l3_proxy.ini'
_NEUTRON_L3_PROXY_CONF="${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
_NEUTRON_CONF="${_NEUTRON_CONF_DIR}/neutron.conf"

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CONF_DIR="../etc/neutron/"
_CONF_BACKUP_DIR="`dirname ${_NEUTRON_CONF_DIR}`/.neutron-cascading-l3proxy-installation-backup"
_CODE_DIR="../neutron/"
_BACKUP_DIR="${_NEUTRON_INSTALL}/.neutron-cascading-l3proxy-installation-backup"

#_SCRIPT_NAME="${0##*/}"
#_SCRIPT_LOGFILE="/var/log/neutron/installation/${_SCRIPT_NAME}.log"

if [[ ${EUID} -ne 0 ]]; then
    echo "Please run as root."
    exit 1
fi

##Redirecting output to logfile as well as stdout
#exec >  >(tee -a ${_SCRIPT_LOGFILE})
#exec 2> >(tee -a ${_SCRIPT_LOGFILE} >&2)

cd `dirname $0`
echo "checking installation directories..."
if [ ! -d "${_NEUTRON_DIR}" ] ; then
    echo "Could not find the neutron installation. Please check the variables in the beginning of the script."
    echo "aborted."
    exit 1
fi

#for test begin
#rm -rf "${_CONF_BACKUP_DIR}/neutron"
#rm -rf "${_BACKUP_DIR}/neutron"
#for test end


echo "checking previous installation..."
if [ -d "${_BACKUP_DIR}/neutron" -o -d "${_CONF_BACKUP_DIR}/neutron" ] ; then
    echo "It seems l3proxy has already been installed!"
    echo "Please check README for solution if this is not true."
    exit 1
fi

echo "backing up current files that might be overwritten..."
mkdir -p "${_CONF_BACKUP_DIR}"
cp -r "${_NEUTRON_CONF_DIR}/" "${_CONF_BACKUP_DIR}/"
if [ $? -ne 0 ] ; then
    rm -r "${_CONF_BACKUP_DIR}/neutron"
    echo "Error in code backup, aborted."
    exit 1
fi

mkdir -p "${_BACKUP_DIR}"
cp -r "${_NEUTRON_DIR}/" "${_BACKUP_DIR}/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/neutron"
    echo "Error in code backup, aborted."
    exit 1
fi

echo "copying in new code files..."
cp -r "${_CODE_DIR}" `dirname ${_NEUTRON_DIR}`
echo
if [ $? -ne 0 ] ; then
    echo "Error in copying new code files, aborted."
    exit 1
fi

echo "copying in new config files..."
cp -r "${_CONF_DIR}" `dirname ${_NEUTRON_CONF_DIR}`
if [ $? -ne 0 ] ; then
    echo "Error in copying config files, aborted."
    exit 1
fi

echo "updating config file..."
sed -i "s/CASCADING_CONTROL_IP/$CASCADING_CONTROL_IP/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
sed -i "s/CASCADING_REGION_NAME/$CASCADING_REGION_NAME/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
sed -i "s/CASCADED_REGION_NAME/$CASCADED_REGION_NAME/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
sed -i "s/USER_NAME/$USER_NAME/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
sed -i "s/USER_PWD/$USER_PWD/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"
sed -i "s/TENANT_NAME/$TENANT_NAME/g" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_PROXY_CONF_FILE}"

if [ $? -ne 0 ] ; then
    echo "Error in updating config file, aborted."
    exit 1
fi

echo "stoping l3-agent"
service neutron-l3-agent stop
ps -efw|grep l3_proxy.py|grep -v grep|awk '{print $2}'|xargs kill -9

echo "starting neutron l3-proxy..."
nohup   /usr/bin/python  ${_NEUTRON_DIR}/agent/l3_proxy.py --config-file ${_NEUTRON_CONF} --config-file ${_NEUTRON_L3_PROXY_CONF} >/dev/null 2>&1 &
if [ $? -ne 0 ] ; then
    echo "There was an error in starting the l3-proxy, please start neutron l3-proxy manually."
    exit 1
fi

echo "Completed."
echo "See README to get started."

exit 0
