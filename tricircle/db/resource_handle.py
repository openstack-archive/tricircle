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


import glanceclient as g_client
import glanceclient.exc as g_exceptions
from neutronclient.common import exceptions as q_exceptions
from neutronclient.neutron import client as q_client
from novaclient import client as n_client
from oslo_config import cfg
from requests import exceptions as r_exceptions

from tricircle.db import exception as exception

client_opts = [
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
    support_resource = ('image', )

    def _get_client(self, cxt):
        return g_client.Client('1',
                               token=cxt.auth_token,
                               auth_url=self.auth_url,
                               endpoint=self.endpoint_url,
                               timeout=cfg.CONF.client.glance_timeout)

    def handle_list(self, cxt, resource, filters):
        if resource not in self.support_resource:
            return []
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            return [res.to_dict() for res in getattr(
                client, collection).list(filters=_transform_filters(filters))]
        except g_exceptions.InvalidEndpoint:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable('glance',
                                                 client.http_client.endpoint)


class NeutronResourceHandle(ResourceHandle):
    service_type = 'neutron'
    support_resource = ('network', 'subnet', 'port', 'router',
                        'security_group', 'security_group_rule')

    def _get_client(self, cxt):
        return q_client.Client('2.0',
                               token=cxt.auth_token,
                               auth_url=self.auth_url,
                               endpoint_url=self.endpoint_url,
                               timeout=cfg.CONF.client.neutron_timeout)

    def handle_list(self, cxt, resource, filters):
        if resource not in self.support_resource:
            return []
        try:
            client = self._get_client(cxt)
            collection = '%ss' % resource
            search_opts = _transform_filters(filters)
            return [res for res in getattr(
                client, 'list_%s' % collection)(**search_opts)[collection]]
        except q_exceptions.ConnectionFailed:
            self.endpoint_url = None
            raise exception.EndpointNotAvailable(
                'neutron', client.httpclient.endpoint_url)


class NovaResourceHandle(ResourceHandle):
    service_type = 'nova'
    support_resource = ('flavor', 'server')

    def _get_client(self, cxt):
        cli = n_client.Client('2',
                              auth_token=cxt.auth_token,
                              auth_url=self.auth_url,
                              timeout=cfg.CONF.client.nova_timeout)
        cli.set_management_url(
            self.endpoint_url.replace('$(tenant_id)s', cxt.tenant))
        return cli

    def handle_list(self, cxt, resource, filters):
        if resource not in self.support_resource:
            return []
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
            raise exception.EndpointNotAvailable('nova',
                                                 client.client.management_url)
