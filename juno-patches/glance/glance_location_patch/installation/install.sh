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

CURPATH=$(cd "$(dirname "$0")"; pwd)
_GLANCE_CONF_DIR="/etc/glance"
_GLANCE_API_CONF_FILE="glance-api.conf"
_PYTHON_INSTALL_DIR="/usr/lib64/python2.6/site-packages"
_GLANCE_DIR="${_PYTHON_INSTALL_DIR}/glance"

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="${CURPATH}/../glance"
_CONF_DIR="${CURPATH}/../etc"
_PATCH_DIR="${CURPATH}/.."
_BACKUP_DIR="${_GLANCE_DIR}/glance-installation-backup"

_SCRIPT_LOGFILE="/var/log/glance/installation/install.log"

api_config_option_list="sync_enabled=True sync_server_port=9595 sync_server_host=127.0.0.1"

export PS4='+{$LINENO:${FUNCNAME[0]}}'

ERRTRAP()
{
   echo "[LINE:$1] Error: Command or function exited with status $?"
}

function log()
{
    echo "$@"
    echo "`date -u +'%Y-%m-%d %T.%N'`: $@" >> $_SCRIPT_LOGFILE
}

trap 'ERRTRAP $LINENO' ERR

if [[ ${EUID} -ne 0 ]]; then
    log "Please run as root."
    exit 1
fi

if [ ! -d "/var/log/glance/installation" ]; then
    mkdir /var/log/glance/installation
    touch _SCRIPT_LOGFILE
fi

cd `dirname $0`

log "checking installation directories..."
if [ ! -d "${_GLANCE_DIR}" ] ; then
    log "Could not find the glance installation. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi
if [ ! -f "${_GLANCE_CONF_DIR}/${_GLANCE_API_CONF_FILE}" ] ; then
    log "Could not find glance-api config file. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi


log "checking previous installation..."
if [ -d "${_BACKUP_DIR}/glance" ] ; then
    log "It seems glance cascading has already been installed!"
    log "Please check README for solution if this is not true."
    exit 1
fi

log "backing up current files that might be overwritten..."
mkdir -p "${_BACKUP_DIR}/glance"
mkdir -p "${_BACKUP_DIR}/etc"
mkdir -p "${_BACKUP_DIR}/etc/glance"
cp -rf "${_GLANCE_CONF_DIR}/${_GLANCE_API_CONF_FILE}" "${_BACKUP_DIR}/etc/glance/"

if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/glance"
    rm -r "${_BACKUP_DIR}/etc"
    log "Error in config backup, aborted."
    exit 1
fi

log "copying in new files..."

cp -r "${_PATCH_DIR}/glance" `dirname ${_GLANCE_DIR}`

glanceEggDir=`ls ${_PYTHON_INSTALL_DIR} |grep -e glance- |grep -e egg-info `
if [ ! -d ${_PYTHON_INSTALL_DIR}/${glanceEggDir} ]; then
    log "glance install dir not exist. Pleas check manually."
    exit 1
fi
cp "${_PATCH_DIR}/glance-egg-info/entry_points.txt" "${_PYTHON_INSTALL_DIR}/${glanceEggDir}/"
if [ $? -ne 0 ] ; then
    log "Error in copying, aborted. Please install manually."
    exit 1
fi

log "Completed."
log "See README to get started."

exit 0
