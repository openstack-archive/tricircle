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
_PYTHON_INSTALL_DIR=${OPENSTACK_INSTALL_DIR}
if [ ! -n ${_PYTHON_INSTALL_DIR} ];then
    _PYTHON_INSTALL_DIR="/usr/lib/python2.7/dist-packages"
fi
_GLANCE_STORE_DIR="${_PYTHON_INSTALL_DIR}/glance_store"

# if you did not make changes to the installation files,
# please do not edit the following directories.
_CODE_DIR="${CURPATH}/../glance_store"

_SCRIPT_LOGFILE="/var/log/glance/installation/install_store.log"

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

function restart_services
{
    log "restarting glance ..."
    service glance-api restart
    service glance-registry restart
    process_stop "glance-sync"
    python /usr/bin/glance-sync --config-file=/etc/glance/glance-sync.conf &
}

trap 'ERRTRAP $LINENO' ERR

if [[ ${EUID} -ne 0 ]]; then
    log "Please run as root."
    exit 1
fi

if [ ! -d "/var/log/glance/installation" ]; then
    mkdir -p /var/log/glance/installation
    touch _SCRIPT_LOGFILE
fi

cd `dirname $0`

log "checking installation directories..."
if [ ! -d "${_GLANCE_STORE_DIR}" ] ; then
    log "Could not find the glance installation. Please check the variables in the beginning of the script."
    log "aborted."
    exit 1
fi


log "copying in new files..."

cp -rf "${_CODE_DIR}" ${_PYTHON_INSTALL_DIR}

restart_services
if [ $? -ne 0 ] ; then
    log "There was an error in restarting the service, please restart glance manually."
    exit 1
fi

log "Completed."
log "See README to get started."

exit 0
