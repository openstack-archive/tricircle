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
_CINDER_INSTALL_LOG="/var/log/cinder/cinder-proxy/installation/install.log"

# please set the option list set in cinder configure file
_CINDER_CONF_OPTION=("volume_manager=cinder.volume.cinder_proxy.CinderProxy volume_sync_interval=5 voltype_sync_interval=3600 periodic_interval=5 volume_sync_timestamp_flag=True cinder_tenant_name=admin cinder_tenant_id=1234 pagination_limit=50 cinder_username=admin cinder_password=1234 keystone_auth_url=http://10.67.148.210:5000/v2.0/ glance_cascading_flag=False cascading_glance_url=10.67.148.210:9292 cascaded_glance_url=http://10.67.148.201:9292 cascaded_cinder_url=http://10.67.148.201:8776/v2/%(project_id)s cascaded_region_name=Region_AZ1 cascaded_available_zone=AZ1")

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../cinder/"
_BACKUP_DIR="${_CINDER_DIR}/cinder-proxy-installation-backup"


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

log "checking previous installation..."
if [ -d "${_BACKUP_DIR}/cinder" ] ; then
    log "It seems cinder-proxy has already been installed!"
    log "Please check README for solution if this is not true."
    exit 1
fi

log "backing up current files that might be overwritten..."
mkdir -p "${_BACKUP_DIR}/cinder"
mkdir -p "${_BACKUP_DIR}/etc/cinder"
cp -r "${_CINDER_DIR}/volume" "${_BACKUP_DIR}/cinder/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/cinder"
    log "Error in code backup, aborted."
    exit 1
fi
cp "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}" "${_BACKUP_DIR}/etc/cinder/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/cinder"
    rm -r "${_BACKUP_DIR}/etc"
    log "Error in config backup, aborted."
    exit 1
fi

log "copying in new files..."
cp -r "${_CODE_DIR}" `dirname ${_CINDER_DIR}`
if [ $? -ne 0 ] ; then
    log "Error in copying, aborted."
    log "Recovering original files..."
    cp -r "${_BACKUP_DIR}/cinder" `dirname ${_CINDER_DIR}` && rm -r "${_BACKUP_DIR}/cinder"
    if [ $? -ne 0 ] ; then
        log "Recovering failed! Please install manually."
    fi
    exit 1
fi

log "updating config file..."
sed -i.backup -e "/volume_manager *=/d" "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}"
sed -i.backup -e "/periodic_interval *=/d" "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}"
for option in $_CINDER_CONF_OPTION
do
sed -i -e "/\[DEFAULT\]/a \\"$option  "${_CINDER_CONF_DIR}/${_CINDER_CONF_FILE}"
done

if [ $? -ne 0 ] ; then
    log "Error in updating, aborted."
    log "Recovering original files..."
    cp -r "${_BACKUP_DIR}/cinder" `dirname ${_CINDER_DIR}` && rm -r "${_BACKUP_DIR}/cinder"
    if [ $? -ne 0 ] ; then
        log "Recovering /cinder failed! Please install manually."
    fi
    cp "${_BACKUP_DIR}/etc/cinder/${_CINDER_CONF_FILE}" "${_CINDER_CONF_DIR}" && rm -r "${_BACKUP_DIR}/etc"
    if [ $? -ne 0 ] ; then
        log "Recovering config failed! Please install manually."
    fi
    exit 1
fi

log "restarting cinder proxy..."
service openstack-cinder-volume restart
if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart cinder proxy manually."
    exit 1
fi

log "Cinder proxy Completed."
log "See README to get started."

exit 0
