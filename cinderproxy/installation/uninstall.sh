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

_CINDER_CONF_DIR="/etc/cinder"
_CINDER_CONF_FILE="cinder.conf"
_CINDER_DIR="/usr/lib64/python2.6/site-packages/cinder"
_CINDER_CONF_OPTION=("volume_manager volume_sync_interval periodic_interval cinder_tenant_name cinder_username cinder_password keystone_auth_url glance_cascading_flag cascading_glance_url cascaded_glance_url cascaded_cinder_url cascaded_region_name cascaded_available_zone")

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../cinder"
_BACKUP_DIR="${_CINDER_DIR}/cinder-proxy-installation-backup"
_CINDER_INSTALL_LOG="/var/log/cinder/cinder-proxy/installation/install.log"

#_SCRIPT_NAME="${0##*/}"
#_SCRIPT_LOGFILE="/var/log/nova-solver-scheduler/installation/${_SCRIPT_NAME}.log"

function log()
{
    if [ ! -f "${_CINDER_INSTALL_LOG}" ] ; then
        mkdir -p `dirname ${_CINDER_INSTALL_LOG}`
        touch $_CINDER_INSTALL_LOG
        chmod 777 $_CINDER_INSTALL_LOG
    fi
    echo "$@"
    echo "`date -u +'%Y-%m-%d %T.%N'`: $@" >> $_CINDER_INSTALL_LOG
}

if [[ ${EUID} -ne 0 ]]; then
    log "Please run as root."
    exit 1
fi

cd `dirname $0`

log "checking installation directories..."
if [ ! -d "${_CINDER_DIR}" ] ; then
    log "Could not find the cinder installation. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi
if [ ! -f "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}" ] ; then
    log "Could not find cinder config file. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi

log "checking backup..."
if [ ! -d "${_BACKUP_DIR}/cinder" ] ; then
    log "Could not find backup files. It is possible that the cinder-proxy has been uninstalled."
    log "If this is not the case, then please uninstall manually."
    exit 1
fi

log "backing up current files that might be overwritten..."
if [ -d "${_BACKUP_DIR}/uninstall" ] ; then
    rm -r "${_BACKUP_DIR}/uninstall"
fi
mkdir -p "${_BACKUP_DIR}/uninstall/cinder"
mkdir -p "${_BACKUP_DIR}/uninstall/etc/cinder"
cp -r "${_CINDER_DIR}/volume" "${_BACKUP_DIR}/uninstall/cinder/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/uninstall/cinder"
    log "Error in code backup, aborted."
    exit 1
fi
cp "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}" "${_BACKUP_DIR}/uninstall/etc/cinder/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/uninstall/cinder"
    rm -r "${_BACKUP_DIR}/uninstall/etc"
    log "Error in config backup, aborted."
    exit 1
fi

log "restoring code to the status before installing cinder-proxy..."
cp -r "${_BACKUP_DIR}/cinder" `dirname ${_CINDER_DIR}`
if [ $? -ne 0 ] ; then
    log "Error in copying, aborted."
    log "Recovering current files..."
    cp -r "${_BACKUP_DIR}/uninstall/cinder" `dirname ${_CINDER_DIR}`
    if [ $? -ne 0 ] ; then
        log "Recovering failed! Please uninstall manually."
    fi
    exit 1
fi

log "updating config file..."
for option in $_CINDER_CONF_OPTION
do
sed -i.uninstall.backup -e "/"$option "*=/d" "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}"
done
if [ $? -ne 0 ] ; then
    log "Error in updating, aborted."
    log "Recovering current files..."
    cp "${_BACKUP_DIR}/uninstall/etc/cinder/${_CINDER_CONF_FILE}" "${_CINDER_CONF_DIR}"
    if [ $? -ne 0 ] ; then
        log "Recovering failed! Please uninstall manually."
    fi
    exit 1
fi

log "cleaning up backup files..."
rm -r "${_BACKUP_DIR}/cinder" && rm -r "${_BACKUP_DIR}/etc"
if [ $? -ne 0 ] ; then
    log "There was an error when cleaning up the backup files."
fi

log "restarting cinder volume..."
service openstack-cinder-volume restart
if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart cinder volume manually."
    exit 1
fi

log "Completed."

exit 0
