from oslo.config import cfg

sync_client_opts = [
    cfg.StrOpt('sync_client_protocol', default='http',
               help=_('The protocol to use for communication with the '
                      'sync server.  Either http or https.')),
    cfg.StrOpt('sync_client_key_file',
               help=_('The path to the key file to use in SSL connections '
                      'to the sync server.')),
    cfg.StrOpt('sync_client_cert_file',
               help=_('The path to the cert file to use in SSL connections '
                      'to the sync server.')),
    cfg.StrOpt('sync_client_ca_file',
               help=_('The path to the certifying authority cert file to '
                      'use in SSL connections to the sync server.')),
    cfg.BoolOpt('sync_client_insecure', default=False,
                help=_('When using SSL in connections to the sync server, '
                       'do not require validation via a certifying '
                       'authority.')),
    cfg.IntOpt('sync_client_timeout', default=600,
               help=_('The period of time, in seconds, that the API server '
                      'will wait for a sync request to complete. A '
                      'value of 0 implies no timeout.')),
]

sync_client_ctx_opts = [
    cfg.BoolOpt('sync_use_user_token', default=True,
                help=_('Whether to pass through the user token when '
                       'making requests to the sync.')),
    cfg.StrOpt('sync_admin_user', secret=True,
               help=_('The administrators user name.')),
    cfg.StrOpt('sync_admin_password', secret=True,
               help=_('The administrators password.')),
    cfg.StrOpt('sync_admin_tenant_name', secret=True,
               help=_('The tenant name of the administrative user.')),
    cfg.StrOpt('sync_auth_url',
               help=_('The URL to the keystone service.')),
    cfg.StrOpt('sync_auth_strategy', default='noauth',
               help=_('The strategy to use for authentication.')),
    cfg.StrOpt('sync_auth_region',
               help=_('The region for the authentication service.')),
]

CONF = cfg.CONF
CONF.register_opts(sync_client_opts)
CONF.register_opts(sync_client_ctx_opts)
