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
_NEUTRON_ML2_CONF_FILE='plugins/ml2/ml2_conf.ini'
_NEUTRON_L3_CONF_FILE='l3_agent.ini'
_NEUTRON_INSTALL="/usr/lib/python2.7/dist-packages"
_NEUTRON_DIR="${_NEUTRON_INSTALL}/neutron"


_CODE_DIR="../neutron/"
_BACKUP_DIR="${_NEUTRON_INSTALL}/.neutron-cascaded-server-installation-backup"


if [[ ${EUID} -ne 0 ]]; then
    echo "Please run as root."
    exit 1
fi

echo "checking previous installation..."
if [ ! -d "${_BACKUP_DIR}/neutron" ] ; then
    echo "Could not find the neutron backup. Please check the variables in the beginning of the script."
    echo "aborted."
    exit 1
fi

if [ ! -f "${_NEUTRON_CONF_DIR}/${_NEUTRON_ML2_CONF_FILE}.bk" ] ; then
    echo "Could not find bak for ml2 config file. Please check the variables in the beginning of the script."
    echo "aborted."
    exit 1
fi

if [ ! -f "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_CONF_FILE}.bk" ] ; then
    echo "Could not find bak for l3_agent config file. Please check the variables in the beginning of the script."
    echo "aborted."
    exit 1
fi

echo "starting uninstall cascaded ..."
rm -r "${_NEUTRON_INSTALL}/neutron/"
cp -r "${_BACKUP_DIR}/neutron/" "${_NEUTRON_INSTALL}"

echo "updating config file..."
cp "${_NEUTRON_CONF_DIR}/${_NEUTRON_ML2_CONF_FILE}.bk" "${_NEUTRON_CONF_DIR}/${_NEUTRON_ML2_CONF_FILE}" 
cp "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_CONF_FILE}.bk"  "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_CONF_FILE}" 


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
rm -rf $_BACKUP_DIR/*
echo "Completed."
echo "uninstall success."

exit 0

