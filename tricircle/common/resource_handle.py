# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
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

import keystoneauth1.identity.generic as auth_identity
from keystoneauth1 import session

from neutronclient.common import exceptions as q_exceptions
from neutronclient.neutron import client as q_client
from oslo_config import cfg
from oslo_log import log as logging
from tricircle.common import constants as cons
from tricircle.common import exceptions

client_opts = [
    cfg.IntOpt('neutron_timeout',
               default=60,
               help='timeout for neutron client in seconds'),
]
cfg.CONF.register_opts(client_opts, group='client')


LIST, CREATE, DELETE, GET, ACTION, UPDATE = 1, 2, 4, 8, 16, 32
operation_index_map = {'list': LIST, 'create': CREATE, 'delete': DELETE,
                       'get': GET, 'action': ACTION, 'update': UPDATE}

LOG = logging.getLogger(__name__)


def _transform_filters(filters):
    filter_dict = {}
    for query_filter in filters:
        # only eq filter supported at first
        if query_filter['comparator'] != 'eq':
            continue
        key = query_filter['key']
        value = query_filter['value']
        filter_dict[key] = value
    return filter_dict


class ResourceHandle(object):
    def __init__(self, auth_url):
        self.auth_url = auth_url
        self.endpoint_url = None

    def is_endpoint_url_set(self):
        return self.endpoint_url is not None

    def clear_endpoint_url(self):
        self.endpoint_url = None

    def update_endpoint_url(self, url):
        self.endpoint_url = url

    @staticmethod
    def get_keystone_session(project_id=None):
        kwargs = {
            'auth_url': cfg.CONF.client.auth_url,
            'username': cfg.CONF.client.admin_username,
            'password': cfg.CONF.client.admin_password,
            'user_domain_name': cfg.CONF.client.admin_user_domain_name,
            'project_domain_name': cfg.CONF.client.admin_tenant_domain_name}
        if not project_id:
            kwargs['project_name'] = cfg.CONF.client.admin_tenant
        else:
            kwargs['project_id'] = project_id
        auth = auth_identity.Password(**kwargs)
        return session.Session(auth=auth)

    @staticmethod
    def get_admin_token(project_id=None):
        return ResourceHandle.get_keystone_session(project_id).get_token()


class NeutronResourceHandle(ResourceHandle):
    service_type = cons.ST_NEUTRON
    support_resource = {
        'network': LIST | CREATE | DELETE | GET | UPDATE,
        'subnet': LIST | CREATE | DELETE | GET | UPDATE,
        'port': LIST | CREATE | DELETE | GET | UPDATE,
        'router': LIST | CREATE | DELETE | ACTION | GET | UPDATE,
        'security_group': LIST | CREATE | GET,
        'security_group_rule': LIST | CREATE | DELETE,
        'floatingip': LIST | CREATE | UPDATE | DELETE,
        'trunk': LIST | CREATE | UPDATE | GET | DELETE | ACTION}

    def _get_client(self, cxt):
        token = cxt.auth_token
        if not token and cxt.is_admin:
            token = self.get_admin_token(cxt.tenant)
        return q_client.Client('2.0',
                               token=token,
                               auth_url=self.auth_url,
                               endpoint_url=self.endpoint_url,
                               timeout=cfg.CONF.client.neutron_timeout)

    def handle_list(self, cxt, resource, filters):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            search_opts = _transform_filters(filters)
            return [res for res in getattr(
                client, 'list_%s' % collection)(**search_opts)[collection]]
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)

    def handle_create(self, cxt, resource, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            ret = getattr(client, 'create_%s' % resource)(
                *args, **kwargs)
            if resource in ret:
                return ret[resource]
            else:
                return ret['%ss' % resource]
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)

    def handle_update(self, cxt, resource, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            return getattr(client, 'update_%s' % resource)(
                *args, **kwargs)[resource]
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)

    def handle_get(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            return getattr(client, 'show_%s' % resource)(resource_id)[resource]
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)
        except q_exceptions.NotFound:
            LOG.debug("%(resource)s %(resource_id)s not found",
                      {'resource': resource, 'resource_id': resource_id})

    def handle_delete(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            return getattr(client, 'delete_%s' % resource)(resource_id)
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)
        except q_exceptions.NotFound:
            LOG.debug("Delete %(resource)s %(resource_id)s which not found",
                      {'resource': resource, 'resource_id': resource_id})

    def handle_action(self, cxt, resource, action, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            func_name = '%s_%s' % (action, resource)
            if not hasattr(client, func_name):
                func_name = '%s_%s' % (resource, action)
            return getattr(client, func_name)(*args, **kwargs)
        except q_exceptions.ConnectionFailed:
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)


def _convert_into_with_meta(item, resp):
    return resp, item
