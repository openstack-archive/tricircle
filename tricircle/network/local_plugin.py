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

import six

from oslo_config import cfg
from oslo_log import log

import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions

from neutron.common import utils
from neutron.plugins.ml2 import plugin

from tricircle.common import client  # noqa
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
from tricircle.common.i18n import _
from tricircle.common import resource_handle
import tricircle.network.exceptions as t_exceptions
from tricircle.network import helper


tricircle_opts = [
    cfg.StrOpt('real_core_plugin', help=_('The core plugin the Tricircle '
                                          'local plugin will invoke.')),
    cfg.StrOpt('central_neutron_url', help=_('Central Neutron server url'))]

tricircle_opt_group = cfg.OptGroup('tricircle')
cfg.CONF.register_group(tricircle_opt_group)
cfg.CONF.register_opts(tricircle_opts, group=tricircle_opt_group)


LOG = log.getLogger(__name__)


class TricirclePlugin(plugin.Ml2Plugin):
    def __init__(self):
        super(TricirclePlugin, self).__init__()
        core_plugins_namespace = 'neutron.core_plugins'
        plugin_provider = cfg.CONF.tricircle.real_core_plugin
        plugin_class = utils.load_class_by_alias_or_classname(
            core_plugins_namespace, plugin_provider)
        self.core_plugin = plugin_class()
        self.neutron_handle = resource_handle.NeutronResourceHandle(
            cfg.CONF.client.auth_url)
        self.neutron_handle.endpoint_url = \
            cfg.CONF.tricircle.central_neutron_url

    @staticmethod
    def _adapt_network_body(network):
        network_type = network.get('provider:network_type')
        if network_type == t_constants.NT_LOCAL:
            for key in ['provider:network_type', 'provider:physical_network',
                        'provider:segmentation_id']:
                network.pop(key, None)
        elif network_type == t_constants.NT_SHARED_VLAN:
            network['provider:network_type'] = 'vlan'

    @staticmethod
    def _adapt_port_body_for_client(port):
        port.pop('port_security_enabled', None)
        port.pop('allowed_address_pairs', None)
        remove_keys = []
        for key, value in six.iteritems(port):
            if value is q_constants.ATTR_NOT_SPECIFIED:
                remove_keys.append(key)
        for key in remove_keys:
            port.pop(key)

    @staticmethod
    def _adapt_port_body_for_call(port):
        if 'mac_address' not in port:
            port['mac_address'] = q_constants.ATTR_NOT_SPECIFIED
        if 'fixed_ips' not in port:
            port['fixed_ips'] = q_constants.ATTR_NOT_SPECIFIED

    @staticmethod
    def _construct_params(filters, sorts, limit, marker, page_reverse):
        params = {}
        for key, value in six.iteritems(filters):
            params[key] = value
        if sorts:
            params['sort_key'] = [s[0] for s in sorts]
            if page_reverse:
                params['sort_dir'] = ['desc' if s[1] else 'asc' for s in sorts]
            else:
                params['sort_dir'] = ['asc' if s[1] else 'desc' for s in sorts]
        if limit:
            params['limit'] = limit
        if marker:
            params['marker'] = marker
        return params

    def _ensure_network_subnet(self, context, port):
        network_id = port['network_id']
        # get_network will create bottom network if it doesn't exist, also
        # create bottom subnets if they don't exist
        self.get_network(context, network_id)

    def _ensure_subnet(self, context, network, is_top=True):
        subnet_ids = network.get('subnets', [])
        if not is_top:
            if subnet_ids:
                return subnet_ids
            else:
                t_ctx = t_context.get_context_from_neutron_context(context)
                t_network = self.neutron_handle.handle_get(
                    t_ctx, 'network', network['id'])
                return self._ensure_subnet(context, t_network)
        if not subnet_ids:
            return []
        if len(subnet_ids) == 1:
            self.get_subnet(context, subnet_ids[0])
        else:
            self.get_subnets(context, filters={'id': subnet_ids})
        return subnet_ids

    def _ensure_subnet_dhcp_port(self, t_ctx, q_ctx, b_subnet):
        b_dhcp_ports = self.core_plugin.get_ports(
            q_ctx, filters={'network_id': [b_subnet['network_id']],
                            'device_owner': ['network:dhcp']})
        if b_dhcp_ports:
            return
        raw_client = self.neutron_handle._get_client(t_ctx)
        params = {'name': t_constants.dhcp_port_name % b_subnet['id']}
        t_ports = raw_client.list_ports(**params)['ports']
        if not t_ports:
            raise t_exceptions.DhcpPortNotFound(subnet_id=b_subnet['id'])

        dhcp_port_body = \
            helper.NetworkHelper._get_create_dhcp_port_body(
                b_subnet['tenant_id'], t_ports[0], b_subnet['id'],
                b_subnet['network_id'])
        dhcp_port_body['port']['id'] = t_ports[0]['id']
        self.core_plugin.create_port(q_ctx, dhcp_port_body)

    def get_network(self, context, _id, fields=None):
        try:
            b_network = self.core_plugin.get_network(context, _id, fields)
            subnet_ids = self._ensure_subnet(context, b_network, False)
        except q_exceptions.NotFound:
            t_ctx = t_context.get_context_from_neutron_context(context)
            t_network = self.neutron_handle.handle_get(t_ctx, 'network', _id)
            if not t_network:
                raise q_exceptions.NetworkNotFound(net_id=_id)
            self._adapt_network_body(t_network)
            b_network = self.core_plugin.create_network(context,
                                                        {'network': t_network})
            subnet_ids = self._ensure_subnet(context, t_network)
        if subnet_ids:
            b_network['subnets'] = subnet_ids
        return self._fields(b_network, fields)

    def get_networks(self, context, filters=None, fields=None,
                     sorts=None, limit=None, marker=None, page_reverse=False):
        # if id is not specified in the filter, we just return network data in
        # local Neutron server, otherwise id is specified, we need to retrieve
        # network data from central Neutron server and create network which
        # doesn't exist in local Neutron server.
        if not filters or 'id' not in filters:
            return self.core_plugin.get_networks(
                context, filters, fields, sorts, limit, marker, page_reverse)

        b_networks = self.core_plugin.get_networks(
            context, filters, fields, sorts, limit, marker, page_reverse)
        for b_network in b_networks:
            subnet_ids = self._ensure_subnet(context, b_network, False)
            if subnet_ids:
                b_network['subnets'] = subnet_ids

        if len(b_networks) == len(filters['id']):
            return b_networks

        t_ctx = t_context.get_context_from_neutron_context(context)
        raw_client = self.neutron_handle._get_client(t_ctx)
        params = self._construct_params(filters, sorts, limit, marker,
                                        page_reverse)
        t_networks = raw_client.list_networks(**params)['networks']

        t_id_set = set([network['id'] for network in t_networks])
        b_id_set = set([network['id'] for network in b_networks])
        missing_id_set = t_id_set - b_id_set
        if missing_id_set:
            missing_networks = [network for network in t_networks if (
                network['id'] in missing_id_set)]
            for network in missing_networks:
                self._adapt_network_body(network)
                b_network = self.core_plugin.create_network(
                    context, {'network': network})
                subnet_ids = self._ensure_subnet(context, network)
                if subnet_ids:
                    b_network['subnets'] = subnet_ids
                b_networks.append(self._fields(b_network, fields))
        return b_networks

    def get_subnet(self, context, _id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            b_subnet = self.core_plugin.get_subnet(context, _id, fields)
        except q_exceptions.NotFound:
            t_subnet = self.neutron_handle.handle_get(t_ctx, 'subnet', _id)
            if not t_subnet:
                raise q_exceptions.SubnetNotFound(subnet_id=_id)
            b_subnet = self.core_plugin.create_subnet(context,
                                                      {'subnet': t_subnet})
        if b_subnet['enable_dhcp']:
            self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)

        return self._fields(b_subnet, fields)

    def get_subnets(self, context, filters=None, fields=None, sorts=None,
                    limit=None, marker=None, page_reverse=False):
        # if id is not specified in the filter, we just return subnet data in
        # local Neutron server, otherwise id is specified, we need to retrieve
        # subnet data from central Neutron server and create subnet which
        # doesn't exist in local Neutron server.
        if not filters or 'id' not in filters:
            return self.core_plugin.get_subnets(
                context, filters, fields, sorts, limit, marker, page_reverse)

        t_ctx = t_context.get_context_from_neutron_context(context)
        b_subnets = self.core_plugin.get_subnets(
            context, filters, fields, sorts, limit, marker, page_reverse)
        for b_subnet in b_subnets:
            self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)
        if len(b_subnets) == len(filters['id']):
            return b_subnets

        raw_client = self.neutron_handle._get_client(t_ctx)
        params = self._construct_params(filters, sorts, limit, marker,
                                        page_reverse)
        t_subnets = raw_client.list_subnets(**params)['subnets']

        t_id_set = set([subnet['id'] for subnet in t_subnets])
        b_id_set = set([subnet['id'] for subnet in b_subnets])
        missing_id_set = t_id_set - b_id_set
        if missing_id_set:
            missing_subnets = [subnet for subnet in t_subnets if (
                subnet['id'] in missing_id_set)]
            for subnet in missing_subnets:
                b_subnet = self.core_plugin.create_subnet(
                    context, {'subnet': subnet})
                if b_subnet['enable_dhcp']:
                    self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)
                b_subnets.append(self._fields(b_subnet, fields))
        return b_subnets

    def create_port(self, context, port):
        port_body = port['port']
        network_id = port_body['network_id']
        # get_network will create bottom network if it doesn't exist
        self.get_network(context, network_id)

        t_ctx = t_context.get_context_from_neutron_context(context)
        raw_client = self.neutron_handle._get_client(t_ctx)

        if port_body['fixed_ips'] is not q_constants.ATTR_NOT_SPECIFIED:
            fixed_ip = port_body['fixed_ips'][0]
            ip_address = fixed_ip.get('ip_address')
            if not ip_address:
                # dhcp agent may request to create a dhcp port without
                # specifying ip address, we just raise an exception to reject
                # this request
                raise q_exceptions.InvalidIpForNetwork(ip_address='None')
            params = {'fixed_ips': 'ip_address=%s' % ip_address}
            t_ports = raw_client.list_ports(**params)['ports']
            if not t_ports:
                raise q_exceptions.InvalidIpForNetwork(
                    ip_address=fixed_ip['ip_address'])
            t_port = t_ports[0]
        else:
            self._adapt_port_body_for_client(port['port'])
            t_port = raw_client.create_port(port)['port']
        subnet_id = t_port['fixed_ips'][0]['subnet_id']
        # get_subnet will create bottom subnet if it doesn't exist
        self.get_subnet(context, subnet_id)
        b_port = self.core_plugin.create_port(context, {'port': t_port})
        return b_port

    def update_port(self, context, _id, port):
        if port['port'].get('device_owner', '').startswith('compute') and (
                port['port'].get('binding:host_id')):
            # we check both "device_owner" and "binding:host_id" to ensure the
            # request comes from nova. and ovs agent will not call update_port.
            # it updates port status via rpc and direct db operation
            region_name = cfg.CONF.nova.region_name
            update_dict = {'binding:profile': {
                t_constants.PROFILE_REGION: region_name}}
            t_ctx = t_context.get_context_from_neutron_context(context)
            self.neutron_handle.handle_update(t_ctx, 'port', _id,
                                              {'port': update_dict})
        return self.core_plugin.update_port(context, _id, port)

    def get_port(self, context, _id, fields=None):
        try:
            b_port = self.core_plugin.get_port(context, _id, fields)
        except q_exceptions.NotFound:
            t_ctx = t_context.get_context_from_neutron_context(context)
            t_port = self.neutron_handle.handle_get(t_ctx, 'port', _id)
            if not t_port:
                raise q_exceptions.PortNotFound(port_id=_id)
            self._ensure_network_subnet(context, t_port)
            self._adapt_port_body_for_call(t_port)
            b_port = self.core_plugin.create_port(context, {'port': t_port})
        return self._fields(b_port, fields)

    def get_ports(self, context, filters=None, fields=None, sorts=None,
                  limit=None, marker=None, page_reverse=False):
        # if id is not specified in the filter, we just return port data in
        # local Neutron server, otherwise id is specified, we need to retrieve
        # port data from central Neutron server and create port which doesn't
        # exist in local Neutron server.
        if not filters or 'id' not in filters:
            return self.core_plugin.get_ports(context, filters, fields, sorts,
                                              limit, marker, page_reverse)

        b_ports = self.core_plugin.get_ports(context, filters, fields, sorts,
                                             limit, marker, page_reverse)
        if len(b_ports) == len(filters['id']):
            return b_ports

        id_set = set(filters['id'])
        b_id_set = set([port['id'] for port in b_ports])
        missing_id_set = id_set - b_id_set
        t_ctx = t_context.get_context_from_neutron_context(context)
        raw_client = self.neutron_handle._get_client(t_ctx)
        t_ports = []
        for port_id in missing_id_set:
            # use list_port will cause infinite API call since central Neutron
            # server will also use list_port to retrieve port information from
            # local Neutron server, so we show_port one by one
            try:
                t_port = raw_client.show_port(port_id)['port']
                t_ports.append(t_port)
            except Exception:
                # user passes a nonexistent port id
                pass

        for port in t_ports:
            self._ensure_network_subnet(context, port)
            self._adapt_port_body_for_call(port)
            b_port = self.core_plugin.create_port(context,
                                                  {'port': port})
            b_ports.append(self._fields(b_port, fields))
        return b_ports

    def delete_port(self, context, _id, l3_port_check=True):
        t_ctx = t_context.get_context_from_neutron_context(context)
        self.neutron_handle.handle_delete(t_ctx, t_constants.RT_PORT, _id)
        self.core_plugin.delete_port(context, _id, l3_port_check)
