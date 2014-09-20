# Copyright (c) 2014 OpenStack Foundation.
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
#
# @author: Jia Dong, HuaWei

import os

from oslo.config import cfg

from glance.common import exception
from glance.openstack.common import jsonutils
import glance.openstack.common.log as logging
from glance.sync.client.v1 import client

CONF = cfg.CONF
CONF.import_opt('sync_server_host', 'glance.common.config')
CONF.import_opt('sync_server_port', 'glance.common.config')

sync_client_ctx_opts = [
    cfg.BoolOpt('sync_send_identity_headers', default=False,
                help=_("Whether to pass through headers containing user "
                       "and tenant information when making requests to "
                       "the sync. This allows the sync to use the "
                       "context middleware without the keystoneclients' "
                       "auth_token middleware, removing calls to the keystone "
                       "auth service. It is recommended that when using this "
                       "option, secure communication between glance api and "
                       "glance sync is ensured by means other than "
                       "auth_token middleware.")),
]
CONF.register_opts(sync_client_ctx_opts)

_sync_client = 'glance.sync.client'
CONF.import_opt('sync_client_protocol', _sync_client)
CONF.import_opt('sync_client_key_file', _sync_client)
CONF.import_opt('sync_client_cert_file', _sync_client)
CONF.import_opt('sync_client_ca_file', _sync_client)
CONF.import_opt('sync_client_insecure', _sync_client)
CONF.import_opt('sync_client_timeout', _sync_client)
CONF.import_opt('sync_use_user_token', _sync_client)
CONF.import_opt('sync_admin_user', _sync_client)
CONF.import_opt('sync_admin_password', _sync_client)
CONF.import_opt('sync_admin_tenant_name', _sync_client)
CONF.import_opt('sync_auth_url', _sync_client)
CONF.import_opt('sync_auth_strategy', _sync_client)
CONF.import_opt('sync_auth_region', _sync_client)
CONF.import_opt('metadata_encryption_key', 'glance.common.config')

_CLIENT_CREDS = None
_CLIENT_HOST = None
_CLIENT_PORT = None
_CLIENT_KWARGS = {}


def get_sync_client(cxt):
    global _CLIENT_CREDS, _CLIENT_KWARGS, _CLIENT_HOST, _CLIENT_PORT
    kwargs = _CLIENT_KWARGS.copy()
    if CONF.sync_use_user_token:
        kwargs['auth_tok'] = cxt.auth_tok
    if _CLIENT_CREDS:
        kwargs['creds'] = _CLIENT_CREDS

    if CONF.sync_send_identity_headers:
        identity_headers = {
            'X-User-Id': cxt.user,
            'X-Tenant-Id': cxt.tenant,
            'X-Roles': ','.join(cxt.roles),
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': jsonutils.dumps(cxt.service_catalog),
        }
        kwargs['identity_headers'] = identity_headers
    return client.SyncClient(_CLIENT_HOST, _CLIENT_PORT, **kwargs)


def configure_sync_client():

    global _CLIENT_KWARGS, _CLIENT_HOST, _CLIENT_PORT
    host, port = CONF.sync_server_host, CONF.sync_server_port

    _CLIENT_HOST = host
    _CLIENT_PORT = port
    _METADATA_ENCRYPTION_KEY = CONF.metadata_encryption_key
    _CLIENT_KWARGS = {
        'use_ssl': CONF.sync_client_protocol.lower() == 'https',
        'key_file': CONF.sync_client_key_file,
        'cert_file': CONF.sync_client_cert_file,
        'ca_file': CONF.sync_client_ca_file,
        'insecure': CONF.sync_client_insecure,
        'timeout': CONF.sync_client_timeout,
    }

    if not CONF.sync_use_user_token:
        configure_sync_admin_creds()


def configure_sync_admin_creds():
    global _CLIENT_CREDS

    if CONF.sync_auth_url or os.getenv('OS_AUTH_URL'):
        strategy = 'keystone'
    else:
        strategy = CONF.sync_auth_strategy

    _CLIENT_CREDS = {
        'user': CONF.sync_admin_user,
        'password': CONF.sync_admin_password,
        'username': CONF.sync_admin_user,
        'tenant': CONF.sync_admin_tenant_name,
        'auth_url': CONF.sync_auth_url,
        'strategy': strategy,
        'region': CONF.sync_auth_region,
    }
