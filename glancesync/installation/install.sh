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
_GLANCE_SYNC_CMD_FILE="glance-sync"
_PYTHON_INSTALL_DIR="/usr/lib64/python2.6/site-packages"
_GLANCE_DIR="${_PYTHON_INSTALL_DIR}/glance"

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="${CURPATH}/../glance"
_CONF_DIR="${CURPATH}/../etc"
_BACKUP_DIR="${_GLANCE_DIR}/glance-sync-backup"

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


function process_stop
{
    PID=`ps -efw|grep "$1"|grep -v grep|awk '{print $2}'`
    echo "PID is: $PID">>$_SCRIPT_LOGFILE
    if [ "x${PID}" != "x" ]; then
        for kill_id in $PID
        do
            kill -9 ${kill_id}
            if [ $? -ne 0 ]; then
                echo "[[stop glance-sync]]$1 stop failed.">>$_SCRIPT_LOGFILE
                exit 1
            fi
        done
        echo "[[stop glance-sync]]$1 stop ok.">>$_SCRIPT_LOGFILE
    fi
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
if [ ! -f "${_CONF_DIR}/${_GLANCE_SYNC_CMD_FILE}" ]; then
    log "Could not find the glance-sync file. Please check the variables in the beginning of the script."
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
cp -r "${_CODE_DIR}" `dirname ${_GLANCE_DIR}`
cp -r "${_CONF_DIR}/glance" "/etc"
cp   "${_CONF_DIR}/${_GLANCE_SYNC_CMD_FILE}" "/usr/bin/"
if [ $? -ne 0 ] ; then
    log "Error in copying, aborted."
    log "Recovering original files..."
    cp -r "${_BACKUP_DIR}/glance" `dirname ${_GLANCE_DIR}` && rm -r "${_BACKUP_DIR}/glance"
    cp  "${_BACKUP_DIR}/etc/glance/*.conf" `dirname ${_GLANCE_CONF_DIR}` && rm -r "${_BACKUP_DIR}/etc"
    if [ $? -ne 0 ] ; then
        log "Recovering failed! Please install manually."
    fi
    exit 1
fi

log "updating config file..."
for option in $api_config_option_list
do
    sed -i -e "/$option/d" "${_GLANCE_CONF_DIR}/${_GLANCE_API_CONF_FILE}"
    sed -i -e "/DEFAULT/a $option" "${_GLANCE_CONF_DIR}/${_GLANCE_API_CONF_FILE}"
done


log "restarting glance ..."
service openstack-glance-api restart
service openstack-glance-registry restart
process_stop "glance-sync"
python /usr/bin/glance-sync --config-file=/etc/glance/glance-sync.conf &
if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart glance manually."
    exit 1
fi

log "Completed."
log "See README to get started."

exit 0
