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

import os
import sys

from oslo_config import cfg
from oslo_log import log as logging
from paste import deploy

from tricircle.i18n import _
from tricircle.i18n import _LI

# from tricircle import policy
from tricircle import version


LOG = logging.getLogger(__name__)

common_opts = [
    cfg.StrOpt('bind_host', default='0.0.0.0',
               help=_("The host IP to bind to")),
    cfg.IntOpt('bind_port', default=19999,
               help=_("The port to bind to")),
    cfg.IntOpt('api_workers', default=1,
               help=_("number of api workers")),
    cfg.StrOpt('api_paste_config', default="api-paste.ini",
               help=_("The API paste config file to use")),
    cfg.StrOpt('api_extensions_path', default="",
               help=_("The path for API extensions")),
    cfg.StrOpt('auth_strategy', default='keystone',
               help=_("The type of authentication to use")),
    cfg.BoolOpt('allow_bulk', default=True,
                help=_("Allow the usage of the bulk API")),
    cfg.BoolOpt('allow_pagination', default=False,
                help=_("Allow the usage of the pagination")),
    cfg.BoolOpt('allow_sorting', default=False,
                help=_("Allow the usage of the sorting")),
    cfg.StrOpt('pagination_max_limit', default="-1",
               help=_("The maximum number of items returned in a single "
                      "response, value was 'infinite' or negative integer "
                      "means no limit")),
]


def init(args, **kwargs):
    # Register the configuration options
    cfg.CONF.register_opts(common_opts)

    # ks_session.Session.register_conf_options(cfg.CONF)
    # auth.register_conf_options(cfg.CONF)
    logging.register_options(cfg.CONF)

    cfg.CONF(args=args, project='tricircle',
             version='%%(prog)s %s' % version.version_info.release_string(),
             **kwargs)


def setup_logging():
    """Sets up the logging options for a log with supplied name."""
    product_name = "tricircle"
    logging.setup(cfg.CONF, product_name)
    LOG.info(_LI("Logging enabled!"))
    LOG.info(_LI("%(prog)s version %(version)s"),
             {'prog': sys.argv[0],
              'version': version.version_info.release_string()})
    LOG.debug("command line: %s", " ".join(sys.argv))


def reset_service():
    # Reset worker in case SIGHUP is called.
    # Note that this is called only in case a service is running in
    # daemon mode.
    setup_logging()

    # (TODO) enforce policy later
    # policy.refresh()


def load_paste_app(app_name):
    """Builds and returns a WSGI app from a paste config file.

    :param app_name: Name of the application to load
    :raises ConfigFilesNotFoundError when config file cannot be located
    :raises RuntimeError when application cannot be loaded from config file
    """

    config_path = cfg.CONF.find_file(cfg.CONF.api_paste_config)
    if not config_path:
        raise cfg.ConfigFilesNotFoundError(
            config_files=[cfg.CONF.api_paste_config])
    config_path = os.path.abspath(config_path)
    LOG.info(_LI("Config paste file: %s"), config_path)

    try:
        app = deploy.loadapp("config:%s" % config_path, name=app_name)
    except (LookupError, ImportError):
        msg = (_("Unable to load %(app_name)s from "
                 "configuration file %(config_path)s.") %
               {'app_name': app_name,
                'config_path': config_path})
        LOG.exception(msg)
        raise RuntimeError(msg)
    return app
