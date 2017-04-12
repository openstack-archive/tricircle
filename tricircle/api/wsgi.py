# Copyright (c) 2017 Huawei Tech. Co,. Ltd.
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

"""WSGI script for Tricircle API
WSGI handler for running Tricircle API under Apache2, nginx, gunicorn etc.

Community wide goal in Pike:
    https://governance.openstack.org/tc/goals/pike/deploy-api-in-wsgi.html
"""

import os
import os.path

from oslo_config import cfg
from oslo_log import log as logging

from tricircle.api import app
from tricircle.common import config

CONFIG_FILE = 'api.conf'

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _get_config_file(env=None):
    if env is None:
        env = os.environ

    dir_name = env.get('TRICIRCLE_CONF_DIR', '/etc/tricircle').strip()
    return os.path.join(dir_name, CONFIG_FILE)


def init_application():

    # initialize the config system
    conf_file = _get_config_file()
    config.init(app.common_opts, ['--config-file', conf_file])

    LOG.info("Configuration:")
    CONF.log_opt_values(LOG, logging.INFO)

    # return WSGI app
    return app.setup_app()
