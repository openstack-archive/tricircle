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

"""
Routines for configuring tricircle, largely copy from Neutron
"""

import sys

from oslo_config import cfg
import oslo_log.log as logging

from tricircle.common.i18n import _LI

# from tricircle import policy
from tricircle.common import rpc
from tricircle.common import version


LOG = logging.getLogger(__name__)


def init(opts, args, **kwargs):
    # Register the configuration options
    cfg.CONF.register_opts(opts)

    # ks_session.Session.register_conf_options(cfg.CONF)
    # auth.register_conf_options(cfg.CONF)
    logging.register_options(cfg.CONF)

    cfg.CONF(args=args, project='tricircle',
             version=version.version_info,
             **kwargs)

    _setup_logging()

    rpc.init(cfg.CONF)


def _setup_logging():
    """Sets up the logging options for a log with supplied name."""
    product_name = "tricircle"
    logging.setup(cfg.CONF, product_name)
    LOG.info(_LI("Logging enabled!"))
    LOG.info(_LI("%(prog)s version %(version)s"),
             {'prog': sys.argv[0],
              'version': version.version_info})
    LOG.debug("command line: %s", " ".join(sys.argv))


def reset_service():
    # Reset worker in case SIGHUP is called.
    # Note that this is called only in case a service is running in
    # daemon mode.
    _setup_logging()

    # TODO(zhiyuan) enforce policy later
    # policy.refresh()
