# Copyright (c) 2015 Huawei, Tech. Co,. Ltd.
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

from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_middleware import request_id
from oslo_service import service
import pecan

import tricircle.common.exceptions as t_exc
from tricircle.common.i18n import _


common_opts = [
    cfg.StrOpt('bind_host', default='0.0.0.0',
               help=_("The host IP to bind to")),
    cfg.IntOpt('bind_port', default=19999,
               help=_("The port to bind to")),
    cfg.IntOpt('api_workers', default=1,
               help=_("number of api workers")),
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


def setup_app(*args, **kwargs):
    config = {
        'server': {
            'port': cfg.CONF.bind_port,
            'host': cfg.CONF.bind_host
        },
        'app': {
            'root': 'tricircle.api.controllers.root.RootController',
            'modules': ['tricircle.api'],
            'errors': {
                400: '/error',
                '__force_dict__': True
            }
        }
    }
    pecan_config = pecan.configuration.conf_from_dict(config)

    # app_hooks = [], hook collection will be put here later

    app = pecan.make_app(
        pecan_config.app.root,
        debug=False,
        wrap_app=_wrap_app,
        force_canonical=False,
        hooks=[],
        guess_content_type_from_ext=True
    )

    return app


def _wrap_app(app):
    app = request_id.RequestId(app)

    if cfg.CONF.auth_strategy == 'noauth':
        pass
    elif cfg.CONF.auth_strategy == 'keystone':
        # NOTE(zhiyuan) pkg_resources will try to load tricircle to get module
        # version, passing "project" as empty string to bypass it
        app = auth_token.AuthProtocol(app, {'project': ''})
    else:
        raise t_exc.InvalidConfigurationOption(
            opt_name='auth_strategy', opt_value=cfg.CONF.auth_strategy)

    return app


_launcher = None


def serve(api_service, conf, workers=1):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = service.launch(conf, api_service, workers=workers)


def wait():
    _launcher.wait()
