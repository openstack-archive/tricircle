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

from oslo.config import cfg

from keystoneclient.v2_0 import client as ksclient
import glance.openstack.common.log as logging
from glanceclient.v2 import client as gclient2


LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class Clients(object):

    def __init__(self, auth_token=None, tenant_id=None):
        self._keystone = None
        self._glance = None
        self._cxt_token = auth_token
        self._tenant_id = tenant_id
        self._ks_conf = cfg.CONF.keystone_authtoken

    @property
    def auth_token(self, token=None):
        return token or self.keystone().auth_token

    @property
    def ks_url(self):
        protocol = self._ks_conf.auth_protocol or 'http'
        auth_host = self._ks_conf.auth_host or '127.0.0.1'
        auth_port = self._ks_conf.auth_port or '35357'
        return protocol + '://' + auth_host + ':' + str(auth_port) + '/v2.0/'

    def url_for(self, **kwargs):
        return self.keystone().service_catalog.url_for(**kwargs)

    def get_urls(self, **kwargs):
        return self.keystone().service_catalog.get_urls(**kwargs)

    def keystone(self):
        if self._keystone:
            return self._keystone

        if self._cxt_token and self._tenant_id:
            creds = {'token': self._cxt_token,
                     'auth_url': self.ks_url,
                     'project_id': self._tenant_id
                     }
        else:
            creds = {'username': self._ks_conf.admin_user,
                     'password': self._ks_conf.admin_password,
                     'auth_url': self.ks_url,
                     'project_name': self._ks_conf.admin_tenant_name}
        try:
            self._keystone = ksclient.Client(**creds)
        except Exception as e:
            LOG.error(_('create keystone client error: reason: %s') % (e))
            return None

        return self._keystone

    def glance(self, auth_token=None, url=None):
        gclient = gclient2
        if gclient is None:
            return None
        if self._glance:
            return self._glance
        args = {
            'token': auth_token or self.auth_token,
            'endpoint': url or self.url_for(service_type='image')
        }
        self._glance = gclient.Client(**args)

        return self._glance
