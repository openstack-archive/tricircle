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
_NEUTRON_CONF_DIR="/etc/neutron"
_NEUTRON_CONF_FILE='neutron.conf'
_NEUTRON_INSTALL="/usr/lib/python2.7/dist-packages"
_NEUTRON_DIR="${_NEUTRON_INSTALL}/neutron"
# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../neutron/"
_BACKUP_DIR="${_NEUTRON_INSTALL}/.neutron-cascaded-timestamp-patch-installation-backup"
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
if [ ! -f "${_NEUTRON_CONF_DIR}/${_NEUTRON_CONF_FILE}" ] ; then
    echo "Could not find neutron config file. Please check the variables in the beginning of the script."
    echo "aborted."
    exit 1
fi

echo "checking previous installation..."
if [ -d "${_BACKUP_DIR}/neutron" ] ; then
    echo "It seems neutron-server-cascaded-timestamp-patch has already been installed!"
    echo "Please check README for solution if this is not true."
    exit 1
fi

echo "backing up current files that might be overwritten..."
mkdir -p "${_BACKUP_DIR}"
cp -r "${_NEUTRON_DIR}/" "${_BACKUP_DIR}/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/neutron"
    echo "Error in code backup, aborted."
    exit 1
fi

echo "copying in new files..."
cp -r "${_CODE_DIR}" `dirname ${_NEUTRON_DIR}`
if [ $? -ne 0 ] ; then
    echo "Error in copying, aborted."
    echo "Recovering original files..."
    cp -r "${_BACKUP_DIR}/neutron" `dirname ${_NEUTRON_DIR}` && rm -r "${_BACKUP_DIR}/neutron"
    if [ $? -ne 0 ] ; then
        echo "Recovering failed! Please install manually."
    fi
    exit 1
fi

echo "upgrade DB for cascaded-timestamp-patch..."
neutron-db-manage --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/plugins/ml2/ml2_conf.ini upgrade head
if [ $? -ne 0 ] ; then
    echo "There was an error in upgrading DB for cascaded-timestamp-patch, please check cascacaded neutron server code manually."
    exit 1
fi

echo "restarting cascaded neutron server..."
service neutron-server restart
if [ $? -ne 0 ] ; then
    echo "There was an error in restarting the service, please restart cascaded neutron server manually."
    exit 1
fi

echo "restarting cascaded neutron-plugin-openvswitch-agent..."
service neutron-plugin-openvswitch-agent restart
if [ $? -ne 0 ] ; then
    echo "There was an error in restarting the service, please restart cascaded neutron-plugin-openvswitch-agent manually."
    exit 1
fi

echo "restarting cascaded neutron-l3-agent..."
service neutron-l3-agent restart
if [ $? -ne 0 ] ; then
    echo "There was an error in restarting the service, please restart cascaded neutron-l3-agent manually."
    exit 1
fi

echo "Completed."
echo "See README to get started."
exit 0
