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
from novaclient import api_versions
from novaclient import client as n_client
from novaclient import exceptions as n_exceptions
from oslo_config import cfg
from oslo_log import log as logging
from requests import exceptions as r_exceptions

from tricircle.common import constants as cons
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

    def update_endpoint_url(self, url):
        self.endpoint_url = url


class GlanceResourceHandle(ResourceHandle):
    service_type = cons.ST_GLANCE
    support_resource = {'image': LIST | GET}

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

    def handle_get(self, cxt, resource, resource_id):
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).get(resource_id).to_dict()
        except g_exceptions.InvalidEndpoint:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('glance',
                                                  client.http_client.endpoint)
        except g_exceptions.HTTPNotFound:
            LOG.debug("%(resource)s %(resource_id)s not found",
                      {'resource': resource, 'resource_id': resource_id})


class NeutronResourceHandle(ResourceHandle):
    service_type = cons.ST_NEUTRON
    support_resource = {
        'network': LIST | CREATE | DELETE | GET,
        'subnet': LIST | CREATE | DELETE | GET | UPDATE,
        'port': LIST | CREATE | DELETE | GET,
        'router': LIST | CREATE | DELETE | ACTION | GET | UPDATE,
        'security_group': LIST | CREATE | GET,
        'security_group_rule': LIST | CREATE | DELETE,
        'floatingip': LIST | CREATE | UPDATE | DELETE}

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
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)

    def handle_update(self, cxt, resource, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            return getattr(client, 'update_%s' % resource)(
                *args, **kwargs)[resource]
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

    def handle_action(self, cxt, resource, action, *args, **kwargs):
        try:
            client = self._get_client(cxt)
            return getattr(client, '%s_%s' % (action, resource))(*args,
                                                                 **kwargs)
        except q_exceptions.ConnectionFailed:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)


def _convert_into_with_meta(item, resp):
    return resp, item


class NovaResourceHandle(ResourceHandle):
    service_type = cons.ST_NOVA
    support_resource = {'flavor': LIST,
                        'server': LIST | CREATE | DELETE | GET | ACTION,
                        'aggregate': LIST | CREATE | DELETE | ACTION,
                        'server_volume': ACTION}

    def _get_client(self, cxt):
        cli = n_client.Client(api_versions.APIVersion(cxt.nova_micro_version),
                              auth_token=cxt.auth_token,
                              auth_url=self.auth_url,
                              timeout=cfg.CONF.client.nova_timeout)
        cli.set_management_url(
            self.endpoint_url.replace('$(tenant_id)s', cxt.tenant))
        return cli

    def _adapt_resource(self, resource):
        if resource == 'server_volume':
            return 'volume'
        else:
            return resource

    def handle_list(self, cxt, resource, filters):
        try:
            resource = self._adapt_resource(resource)
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
            resource = self._adapt_resource(resource)
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).create(
                *args, **kwargs).to_dict()
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)

    def handle_get(self, cxt, resource, resource_id):
        try:
            resource = self._adapt_resource(resource)
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return getattr(client, collection).get(resource_id).to_dict()
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)
        except n_exceptions.NotFound:
            LOG.debug("%(resource)s %(resource_id)s not found",
                      {'resource': resource, 'resource_id': resource_id})

    def handle_delete(self, cxt, resource, resource_id):
        try:
            resource = self._adapt_resource(resource)
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
            resource = self._adapt_resource(resource)
            client = self._get_client(cxt)
            collection = '%ss' % resource
            resource_manager = getattr(client, collection)
            resource_manager.convert_into_with_meta = _convert_into_with_meta
            # NOTE(zhiyuan) yes, this is a dirty hack. but the original
            # implementation hides response object which is needed
            return getattr(resource_manager, action)(*args, **kwargs)
        except r_exceptions.ConnectTimeout:
            self.endpoint_url = None
            raise exceptions.EndpointNotAvailable('nova',
                                                  client.client.management_url)


class CinderResourceHandle(ResourceHandle):
    service_type = cons.ST_CINDER
    support_resource = {'volume': LIST | CREATE | DELETE | GET | ACTION,
                        'transfer': CREATE | ACTION}

    def _get_client(self, cxt):
        cli = c_client.Client('2',
                              auth_url=self.auth_url,
                              timeout=cfg.CONF.client.cinder_timeout)
        cli.client.set_management_url(
            self.endpoint_url.replace('$(tenant_id)s', cxt.tenant))
        cli.client.auth_token = cxt.auth_token
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
