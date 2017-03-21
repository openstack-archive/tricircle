# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
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

# Much of this module is based on the work of the Ironic team
# see http://git.openstack.org/cgit/openstack/ironic/tree/ironic/cmd/api.py

import eventlet

eventlet.monkey_patch()

import sys

from oslo_config import cfg
from oslo_log import log as logging

from tricircle.common import config

from tricircle.xjob import xservice

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def main():
    config.init(xservice.common_opts, sys.argv[1:])

    host = CONF.host
    workers = CONF.workers

    if workers < 1:
        LOG.warning("Wrong worker number, worker = %(workers)s", workers)
        workers = 1

    LOG.info("XJob Server on http://%(host)s with %(workers)s",
             {'host': host, 'workers': workers})

    xservice.serve(xservice.create_service(), workers)

    LOG.info("Configuration:")
    CONF.log_opt_values(LOG, logging.INFO)

    xservice.wait()

if __name__ == '__main__':
    main()
