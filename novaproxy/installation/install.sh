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

_NOVA_CONF_DIR="/etc/nova"
_NOVA_CONF_FILE="nova.conf"
_NOVA_INSTALL="/usr/lib64/python2.6/site-packages"
_NOVA_DIR="${_NOVA_INSTALL}/nova"

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="../nova"
_BACKUP_DIR="${_NOVA_INSTALL}/.nova-proxy-installation-backup"

_SCRIPT_LOGFILE="/var/log/nova-proxy/installation/install.log"

config_option_list="nova_admin_username=nova nova_admin_password=openstack nova_admin_tenant_name=service proxy_region_name=AZ1 cascading_nova_url=http://cascading_host:8774/v2 cascaded_nova_url=http://cascaded_host:8774/v2 cascaded_neutron_url=http://cascaded_host:9696 cascaded_glance_flag=False cascaded_glance_url=http://cascaded_host:9292 os_region_name=Cascading_Openstack keystone_auth_url=http://cascading_host:5000/v2.0/ cinder_endpoint_template=http://cascading_host:8776/v1/%(project_id)s compute_manager=nova.compute.manager_proxy.ComputeManager image_copy_dest_location_url=file:///var/lib/glance/images image_copy_dest_host=cascaded_host image_copy_dest_user=glance image_copy_dest_password=openstack image_copy_source_location_url=file:///var/lib/glance/images image_copy_source_host=copy_image_host image_copy_source_user=glance image_copy_source_password=openstack"

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
if [ ! -f "${_NOVA_CONF_DIR}/${_NOVA_CONF_FILE}" ] ; then
    log "Could not find nova config file. Please check the variables in the beginning of the script."
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
mkdir -p "${_BACKUP_DIR}/nova"
mkdir -p "${_BACKUP_DIR}/etc/nova"
cp "${_NOVA_CONF_DIR}/${_NOVA_CONF_FILE}" "${_BACKUP_DIR}/etc/nova/"
if [ $? -ne 0 ] ; then
    rm -r "${_BACKUP_DIR}/nova"
    rm -r "${_BACKUP_DIR}/etc"
    log "Error in config backup, aborted."
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

log "updating config file..."
for option in $config_option_list
do
    option_key=`echo $option|awk -F "=" '{print $1}'`
    option_value=`echo $option|awk -F "=" '{print $2}'`
    sed -i.backup -e "/$option_key *=/d" "${_NOVA_CONF_DIR}/${_NOVA_CONF_FILE}"
    echo "$option_key,***************$option_value"
    echo $option_key=$option_value >> "${_NOVA_CONF_DIR}/${_NOVA_CONF_FILE}"

done

log "restarting nova compute..."
service openstack-nova-compute restart
if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart nova scheduler manually."
    exit 1
fi

log "Completed."
log "See README to get started."

exit 0
