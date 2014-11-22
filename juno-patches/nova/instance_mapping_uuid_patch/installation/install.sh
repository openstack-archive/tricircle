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

_MYSQL_PASS="1234"
_NOVA_INSTALL="/usr/lib64/python2.6/site-packages"
_NOVA_DIR="${_NOVA_INSTALL}/nova"
# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../nova"
_BACKUP_DIR="${_NOVA_INSTALL}/.instance_mapping_uuid_patch-installation-backup"

_SCRIPT_LOGFILE="/var/log/instance_mapping_uuid_patch/installation/install.log"

function log()
{
    log_path=`dirname ${_SCRIPT_LOGFILE}`
    if [ ! -d $log_path ] ; then
        mkdir -p $log_path
    fi
    echo "$@"
    echo "`date -u +'%Y-%m-%d %T.%N'`: $@" >> $_SCRIPT_LOGFILE
}

if [[ ${EUID} -ne 0 ]]; then
    log "Please run as root."
    exit 1
fi


cd `dirname $0`

log "checking installation directories..."
if [ ! -d "${_NOVA_DIR}" ] ; then
    log "Could not find the nova installation. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi

log "checking previous installation..."
if [ -d "${_BACKUP_DIR}/nova" ] ; then
    log "It seems nova-proxy has already been installed!"
    log "Please check README for solution if this is not true."
    exit 1
fi

log "backing up current files that might be overwritten..."
cp -r "${_NOVA_DIR}/" "${_BACKUP_DIR}/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/nova"
    echo "Error in code backup, aborted."
    exit 1
fi

log "copying in new files..."
cp -r "${_CODE_DIR}" `dirname ${_NOVA_DIR}`
if [ $? -ne 0 ] ; then
    log "Error in copying, aborted."
    log "Recovering original files..."
    cp -r "${_BACKUP_DIR}/nova" `dirname ${_NOVA_DIR}` && rm -r "${_BACKUP_DIR}/nova"
    if [ $? -ne 0 ] ; then
        log "Recovering failed! Please install manually."
    fi
    exit 1
fi

log "syc nova db..."
mysql -u root -p$_MYSQL_PASS -e "DROP DATABASE if exists nova;CREATE DATABASE nova;GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'%' IDENTIFIED BY 'Galax8800';GRANT ALL PRIVILEGES ON *.* TO 'nova'@'%'IDENTIFIED BY 'Galax8800';"

nova-manage db sync

if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart nova scheduler manually."
    exit 1
fi

log "Completed."
log "See README to get started."
exit 0

