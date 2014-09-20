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

_MYSQL_PASS="Galax8800"
_NEUTRON_CONF_DIR="/etc/neutron"
_NEUTRON_CONF_FILE='neutron.conf'
_NEUTRON_INSTALL="/usr/lib64/python2.6/site-packages"
_NEUTRON_DIR="${_NEUTRON_INSTALL}/neutron"

_NEUTRON_L2_CONFIG_FILE='/plugins/openvswitch/ovs_neutron_plugin.ini'
_NEUTRON_L3_CONFIG_FILE='l3_agent.ini'
# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../neutron/"
_BACKUP_DIR="${_NEUTRON_INSTALL}/.neutron-dvr-code-installation-backup"

l2_config_option_list="\[AGENT\]:firewall_driver=neutron.agent.firewall.NoopFirewallDriver \[SECURITYGROUP\]:enable_distributed_routing=True"
l3_config_option_list="\[DEFAULT\]:distributed_agent=True"

#_SCRIPT_NAME="${0##*/}"
#_SCRIPT_LOGFILE="/var/log/neutron-dvr-code/installation/${_SCRIPT_NAME}.log"

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
    echo "It seems neutron-dvr-code-cascaded has already been installed!"
    echo "Please check README for solution if this is not true."
    exit 1
fi

echo "backing up current code files that might be overwritten..."
mkdir -p "${_BACKUP_DIR}"
cp -r "${_NEUTRON_DIR}/" "${_BACKUP_DIR}/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/neutron"
    echo "Error in code backup code files, aborted."
    exit 1
fi

echo "backing up current config code files that might be overwritten..."
mkdir -p "${_BACKUP_DIR}/etc"
cp -r "${_NEUTRON_CONF_DIR}/" "${_BACKUP_DIR}/etc"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/etc"
    echo "Error in code backup config files, aborted."
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

if [ -d "${_NEUTRON_DIR}/openstack/common/db/rpc" ] ; then
    rm -r "${_NEUTRON_DIR}/openstack/common/db/rpc"
fi

echo "updating l2 config file..."
for option in $l2_config_option_list
do
    option_branch=`echo $option|awk -F ":" '{print $1}'`
    option_config=`echo $option|awk -F ":" '{print $2}'`
    option_key=`echo $option_config|awk -F "=" '{print $1}'`
    option_value=`echo $option_config|awk -F "=" '{print $2}'`
    sed -i.backup -e "/$option_key *=/d" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L2_CONFIG_FILE}"
    echo "$option_key,***************$option_value"
    sed  -i "/$option_branch/a\\$option_key=$option_value" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L2_CONFIG_FILE}"

done
echo "updating l3 config file..."
for option in $l3_config_option_list
do
    option_branch=`echo $option|awk -F ":" '{print $1}'`
    option_config=`echo $option|awk -F ":" '{print $2}'`
    option_key=`echo $option_config|awk -F "=" '{print $1}'`
    option_value=`echo $option_config|awk -F "=" '{print $2}'`
    sed -i.backup -e "/$option_key *=/d" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_CONFIG_FILE}"
    echo "$option_key,***************$option_value"
    sed  -i "/$option_branch/a\\$option_key=$option_value" "${_NEUTRON_CONF_DIR}/${_NEUTRON_L3_CONFIG_FILE}"

done


echo "create neutron db..."
exec_sql_str="DROP DATABASE if exists neutron;CREATE DATABASE neutron;GRANT ALL PRIVILEGES ON neutron.* TO 'neutron'@'%' IDENTIFIED BY \"$_MYSQL_PASS\";GRANT ALL PRIVILEGES ON *.* TO 'neutron'@'%'IDENTIFIED BY \"$_MYSQL_PASS\";"
mysql -u root -p$_MYSQL_PASS -e "$exec_sql_str"
echo "syc neutron db..."
neutron-db-manage --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/plugins/ml2/ml2_conf.ini upgrade head

if [ $? -ne 0 ] ; then
    log "There was an error in sync neutron db, please sync neutron db manually."
    exit 1
fi

#echo "restarting neutron server..."
#service openstack-neutron stop

#if [ $? -ne 0 ] ; then
#    echo "There was an error in restarting the service, please restart neutron server manually."
#    exit 1
#fi

echo "Completed."
echo "See README to get started."

exit 0
