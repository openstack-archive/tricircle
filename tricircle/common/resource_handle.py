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


from cinderclient import client as c_client
from cinderclient import exceptions as c_exceptions
import glanceclient as g_client
import glanceclient.exc as g_exceptions
from neutronclient.common import exceptions as q_exceptions
from neutronclient.neutron import client as q_client
from novaclient import client as n_client
from novaclient import exceptions as n_exceptions
from oslo_config import cfg
from oslo_log import log as logging
from requests import exceptions as r_exceptions

from tricircle.common import exceptions

client_opts = [
    cfg.IntOpt('cinder_timeout',
               default=60,
               help='timeout for cinder client in seconds'),
    cfg.IntOpt('glance_timeout',
               default=60,
               help='timeout for glance client in seconds'),
    cfg.IntOpt('neutron_timeout',
               default=60,
               help='timeout for neutron client in seconds'),
    cfg.IntOpt('nova_timeout',
               default=60,
               help='timeout for nova client in seconds'),
]
cfg.CONF.register_opts(client_opts, group='client')


LIST, CREATE, DELETE, GET, ACTION = 1, 2, 4, 8, 16
operation_index_map = {'list': LIST, 'create': CREATE,
                       'delete': DELETE, 'get': GET, 'action': ACTION}

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

    def update_endpoint_url(self, url):
        self.endpoint_url = url


class GlanceResourceHandle(ResourceHandle):
    service_type = 'glance'
    support_resource = {'image': LIST}

    def _get_client(self, cxt):
        return g_client.Client('1',
                               token=cxt.auth_token,
                               auth_url=self.auth_url,
                               endpoint=self.endpoint_url,
                               timeout=cfg.CONF.client.glance_timeout)

    def handle_list(self, cxt, resource, filters):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return [res.to_dict() for res in getattr(
                client, collection).list(filters=_transform_filters(filters))]
        except g_exceptions.InvalidEndpoint:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('glance',
                                                  client.http_client.endpoint)


class NeutronResourceHandle(ResourceHandle):
    service_type = 'neutron'
    support_resource = {'network': LIST | DELETE,
                        'subnet': LIST | DELETE,
                        'port': LIST | DELETE | GET,
                        'router': LIST,
                        'security_group': LIST,
                        'security_group_rule': LIST}

    def _get_client(self, cxt):
        return q_client.Client('2.0',
                               token=cxt.auth_token,
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
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)

    def handle_get(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            return getattr(client, 'show_%s' % resource)(resource_id)[resource]
        except q_exceptions.ConnectionFailed:
            self.endpoint_url = None
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
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)
        except q_exceptions.NotFound:
            LOG.debug("Delete %(resource)s %(resource_id)s which not found",
                      {'resource': resource, 'resource_id': resource_id})


class NovaResourceHandle(ResourceHandle):
    service_type = 'nova'
    support_resource = {'flavor': LIST,
                        'server': LIST,
                        'aggregate': LIST | CREATE | DELETE | ACTION}

    def _get_client(self, cxt):
        cli = n_client.Client('2',
                              auth_token=cxt.auth_token,
                              auth_url=self.auth_url,
                              timeout=cfg.CONF.client.nova_timeout)
        cli.set_management_url(
            self.endpoint_url.replace('$(tenant_id)s', cxt.tenant))
        return cli

    def handle_list(self, cxt, resource, filters):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            # only server list supports filter
            if resource == 'server':
                search_opts = _transform_filters(filters)
                return [res.to_dict() for res in getattr(
                    client, collection).list(search_opts=search_opts)]
            else:
                return [res.to_dict() for res in getattr(client,
                                                         collection).list()]
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)

    def handle_create(self, cxt, resource, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).create(
                *args, **kwargs).to_dict()
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)

    def handle_delete(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).delete(resource_id)
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)
        except n_exceptions.NotFound:
            LOG.debug("Delete %(resource)s %(resource_id)s which not found",
                      {'resource': resource, 'resource_id': resource_id})

    def handle_action(self, cxt, resource, action, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            resource_manager = getattr(client, collection)
            getattr(resource_manager, action)(*args, **kwargs)
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)


class CinderResourceHandle(ResourceHandle):
    service_type = 'cinder'
    support_resource = {'volume': GET | ACTION,
                        'transfer': CREATE | ACTION}

    def _get_client(self, cxt):
        cli = c_client.Client('2',
                              auth_token=cxt.auth_token,
                              auth_url=self.auth_url,
                              timeout=cfg.CONF.client.cinder_timeout)
        cli.set_management_url(
            self.endpoint_url.replace('$(tenant_id)s', cxt.tenant))
        return cli

    def handle_get(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            res = getattr(client, collection).get(resource_id)
            info = {}
            info.update(res._info)
            return info
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('cinder',
                                                  client.client.management_url)

    def handle_delete(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).delete(resource_id)
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('cinder',
                                                  client.client.management_url)
        except c_exceptions.NotFound:
            LOG.debug("Delete %(resource)s %(resource_id)s which not found",
                      {'resource': resource, 'resource_id': resource_id})

    def handle_action(self, cxt, resource, action, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            resource_manager = getattr(client, collection)
            getattr(resource_manager, action)(*args, **kwargs)
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('cinder',
                                                  client.client.management_url)
