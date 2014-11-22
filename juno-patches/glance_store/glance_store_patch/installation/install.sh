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
_PYTHON_INSTALL_DIR="/usr/lib64/python2.6/site-packages"
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

cp -rf "${_CODE_DIR}" `dirname ${_PYTHON_INSTALL_DIR}`


log "Completed."
log "See README to get started."

exit 0
