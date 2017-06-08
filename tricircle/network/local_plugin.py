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

from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
from neutron_lib.api import validators
import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions
from neutron_lib.plugins import directory

from neutron.common import utils
from neutron.extensions import availability_zone as az_ext
import neutron.extensions.securitygroup as ext_sg
from neutron.plugins.ml2 import plugin

from tricircle.common import client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
from tricircle.common.i18n import _

from tricircle.common import resource_handle
import tricircle.common.utils as t_utils
import tricircle.network.exceptions as t_exceptions
from tricircle.network import helper


tricircle_opts = [
    cfg.StrOpt('real_core_plugin', help=_('The core plugin the Tricircle '
                                          'local plugin will invoke.')),
    cfg.StrOpt('local_region_name',
               help=_('Region the local Neutron belongs to, has high priority '
                      'than nova.region_name')),
    cfg.StrOpt('central_neutron_url', help=_('Central Neutron server url')),
    cfg.IPOpt('l2gw_tunnel_ip', help=_('Tunnel IP of L2 gateway, need to set '
                                       'when client.cross_pod_vxlan_mode is '
                                       'set to l2gw'))]

tricircle_opt_group = cfg.OptGroup('tricircle')
cfg.CONF.register_group(tricircle_opt_group)
cfg.CONF.register_opts(tricircle_opts, group=tricircle_opt_group)


LOG = log.getLogger(__name__)


class TricirclePlugin(plugin.Ml2Plugin):

    __native_bulk_support = True

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
        self.on_trunk_create = {}
        self.on_subnet_delete = {}

    def start_rpc_listeners(self):
        return self.core_plugin.start_rpc_listeners()

    def start_rpc_state_reports_listener(self):
        return self.core_plugin.start_rpc_state_reports_listener()

    def rpc_workers_supported(self):
        return self.core_plugin.rpc_workers_supported()

    def rpc_state_report_workers_supported(self):
        return self.core_plugin.rpc_state_report_workers_supported()

    def _start_subnet_delete(self, context):
        if context.request_id:
            LOG.debug('subnet delete start for ' + context.request_id)
            self.on_subnet_delete[context.request_id] = True

    def _end_subnet_delete(self, context):
        if context.request_id:
            LOG.debug('subnet delete end for ' + context.request_id)
            self.on_subnet_delete.pop(context.request_id, None)

    def _in_subnet_delete(self, context):
        if context.request_id:
            LOG.debug('check subnet delete state for ' + context.request_id)
            return context.request_id in self.on_subnet_delete
        return False

    @staticmethod
    def _adapt_network_body(network):
        network_type = network.get(provider_net.NETWORK_TYPE)
        if network_type == t_constants.NT_LOCAL:
            for key in (provider_net.NETWORK_TYPE,
                        provider_net.PHYSICAL_NETWORK,
                        provider_net.SEGMENTATION_ID):
                network.pop(key, None)

        # remove az_hint from network
        network.pop('availability_zone_hints', None)

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

    @staticmethod
    def _skip_non_api_query(context):
        return not context.auth_token

    @staticmethod
    def _get_neutron_region():
        region_name = cfg.CONF.tricircle.local_region_name
        if not region_name:
            region_name = cfg.CONF.nova.region_name
        return region_name

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
                if self._skip_non_api_query(t_ctx):
                    return []
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
        if self._skip_non_api_query(t_ctx):
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

    def _ensure_gateway_port(self, t_ctx, t_subnet):
        region_name = self._get_neutron_region()
        gateway_port_name = t_constants.interface_port_name % (region_name,
                                                               t_subnet['id'])
        gateway_port_body = {
            'port': {'tenant_id': t_subnet['tenant_id'],
                     'admin_state_up': True,
                     'name': gateway_port_name,
                     'network_id': t_subnet['network_id'],
                     'device_id': t_constants.interface_port_device_id}}
        try:
            return self.neutron_handle.handle_create(
                t_ctx, t_constants.RT_PORT, gateway_port_body)
        except Exception:
            raw_client = self.neutron_handle._get_client(t_ctx)
            params = {'name': gateway_port_name}
            t_ports = raw_client.list_ports(**params)['ports']
            if not t_ports:
                raise t_exceptions.GatewayPortNotFound(
                    subnet_id=t_subnet['id'], region=region_name)
            return t_ports[0]

    def create_network(self, context, network):
        # this method is overwritten for bottom bridge network and external
        # network creation, for internal network, get_network and get_networks
        # will do the trick
        net_body = network['network']
        self._adapt_network_body(net_body)
        if net_body['name']:
            net_id = t_utils.get_id_from_name(t_constants.RT_NETWORK,
                                              net_body['name'])
            if net_id:
                net_body['id'] = net_id
        b_network = self.core_plugin.create_network(context,
                                                    {'network': net_body})
        return b_network

    def _is_network_located_in_region(self, t_network, region_name):
        az_hints = t_network.get(az_ext.AZ_HINTS)
        if not az_hints:
            return True
        return region_name in az_hints

    def get_network(self, context, _id, fields=None):
        try:
            b_network = self.core_plugin.get_network(context, _id)
            if not self._in_subnet_delete(context):
                subnet_ids = self._ensure_subnet(context, b_network, False)
            else:
                subnet_ids = []
        except q_exceptions.NotFound:
            if self._in_subnet_delete(context):
                raise
            t_ctx = t_context.get_context_from_neutron_context(context)
            if self._skip_non_api_query(t_ctx):
                raise q_exceptions.NetworkNotFound(net_id=_id)
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

        b_full_networks = self.core_plugin.get_networks(
            context, filters, None, sorts, limit, marker, page_reverse)
        b_networks = []
        for b_network in b_full_networks:
            subnet_ids = self._ensure_subnet(context, b_network, False)
            if subnet_ids:
                b_network['subnets'] = subnet_ids
            b_networks.append(self._fields(b_network, fields))

        if len(b_networks) == len(filters['id']):
            return b_networks

        t_ctx = t_context.get_context_from_neutron_context(context)
        if self._skip_non_api_query(t_ctx):
            return b_networks
        t_ctx.auth_token = client.Client.get_admin_token(context.project_id)
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
                region_name = self._get_neutron_region()
                located = self._is_network_located_in_region(network,
                                                             region_name)
                if not located:
                    LOG.error('network: %(net_id)s not located in current '
                              'region: %(region_name)s, '
                              'az_hints: %(az_hints)s',
                              {'net_id': network['id'],
                               'region_name': region_name,
                               'az_hints': network[az_ext.AZ_HINTS]})
                    continue

                self._adapt_network_body(network)
                b_network = self.core_plugin.create_network(
                    context, {'network': network})
                subnet_ids = self._ensure_subnet(context, network)
                if subnet_ids:
                    b_network['subnets'] = subnet_ids
                b_networks.append(self._fields(b_network, fields))
        return b_networks

    def create_subnet(self, context, subnet):
        # this method is overwritten for bottom bridge subnet and external
        # subnet creation, for internal subnet, get_subnet and get_subnets
        # will do the trick
        subnet_body = subnet['subnet']
        if subnet_body['name']:
            subnet_id = t_utils.get_id_from_name(t_constants.RT_SUBNET,
                                                 subnet_body['name'])
            if subnet_id:
                subnet_body['id'] = subnet_id
        b_subnet = self.core_plugin.create_subnet(context,
                                                  {'subnet': subnet_body})
        return b_subnet

    def _create_bottom_subnet(self, t_ctx, q_ctx, t_subnet):
        if t_subnet['gateway_ip']:
            gateway_port = self._ensure_gateway_port(t_ctx, t_subnet)
            b_gateway_ip = gateway_port['fixed_ips'][0]['ip_address']
        else:
            b_gateway_ip = None
        subnet_body = helper.NetworkHelper.get_create_subnet_body(
            t_subnet['tenant_id'], t_subnet, t_subnet['network_id'],
            b_gateway_ip)['subnet']
        t_subnet['gateway_ip'] = subnet_body['gateway_ip']
        t_subnet['allocation_pools'] = subnet_body['allocation_pools']

        b_subnet = self.core_plugin.create_subnet(q_ctx, {'subnet': t_subnet})
        return b_subnet

    def get_subnet(self, context, _id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            b_subnet = self.core_plugin.get_subnet(context, _id)
        except q_exceptions.NotFound:
            if self._skip_non_api_query(t_ctx):
                raise q_exceptions.SubnetNotFound(subnet_id=_id)
            t_subnet = self.neutron_handle.handle_get(t_ctx, 'subnet', _id)
            if not t_subnet:
                raise q_exceptions.SubnetNotFound(subnet_id=_id)
            b_subnet = self._create_bottom_subnet(t_ctx, context, t_subnet)
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
        b_full_subnets = self.core_plugin.get_subnets(
            context, filters, None, sorts, limit, marker, page_reverse)
        b_subnets = []
        for b_subnet in b_full_subnets:
            if b_subnet['enable_dhcp']:
                self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)
            b_subnets.append(self._fields(b_subnet, fields))
        if len(b_subnets) == len(filters['id']):
            return b_subnets

        if self._skip_non_api_query(t_ctx):
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
                b_subnet = self._create_bottom_subnet(t_ctx, context, subnet)
                if b_subnet['enable_dhcp']:
                    self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)
                b_subnets.append(self._fields(b_subnet, fields))
        return b_subnets

    def delete_subnet(self, context, _id):
        self._start_subnet_delete(context)
        try:
            self.core_plugin.delete_subnet(context, _id)
        except Exception:
            raise
        finally:
            self._end_subnet_delete(context)

    def update_subnet(self, context, _id, subnet):
        """update bottom subnet

        Can not directly use ML2 plugin's update_subnet function,
        because it will call local plugin's get_subnet in a transaction,
        the local plugin's get_subnet will create a dhcp port when subnet's
        enable_dhcp attribute is changed from False to True, but neutron
        doesn't allow calling create_port in a transaction and will raise an
        exception.

        :param context: neutron context
        :param _id: subnet_id
        :param subnet: update body
        :return: updated subnet
        """
        t_ctx = t_context.get_context_from_neutron_context(context)
        b_subnet = self.core_plugin.get_subnet(context, _id)
        origin_enable_dhcp = b_subnet['enable_dhcp']
        req_enable_dhcp = subnet['subnet'].get('enable_dhcp')
        # when request enable dhcp, and origin dhcp is disabled,
        # ensure subnet dhcp port is created
        if req_enable_dhcp and not origin_enable_dhcp:
            self._ensure_subnet_dhcp_port(t_ctx, context, b_subnet)
        res = self.core_plugin.update_subnet(context, _id, subnet)
        return res

    @staticmethod
    def _is_special_port(port):
        return port.get('device_owner') in (
            q_constants.DEVICE_OWNER_ROUTER_INTF,
            q_constants.DEVICE_OWNER_FLOATINGIP,
            q_constants.DEVICE_OWNER_ROUTER_GW,
            q_constants.DEVICE_OWNER_ROUTER_SNAT,
            q_constants.DEVICE_OWNER_DVR_INTERFACE)

    def _handle_dvr_snat_port(self, t_ctx, port):
        if port.get('device_owner') != q_constants.DEVICE_OWNER_ROUTER_SNAT:
            return
        subnet_id = port['fixed_ips'][0]['subnet_id']
        t_subnet = self.neutron_handle.handle_get(t_ctx, 'subnet', subnet_id)
        snat_port_name = t_constants.snat_port_name % t_subnet['id']
        raw_client = self.neutron_handle._get_client(t_ctx)
        params = {'name': snat_port_name}
        t_ports = raw_client.list_ports(**params)['ports']
        if not t_ports:
            raise t_exceptions.CentralizedSNATPortNotFound(
                subnet_id=t_subnet['id'])
        port['fixed_ips'][0][
            'ip_address'] = t_ports[0]['fixed_ips'][0]['ip_address']

    def create_port_bulk(self, context, ports):
        # NOTE(zhiyuan) currently this bulk operation is only for shadow port
        # and trunk subports creation optimization
        for port in ports['ports']:
            port_body = port['port']
            self.get_network(context, port_body['network_id'])
            if port_body['device_owner'] == t_constants.DEVICE_OWNER_SHADOW:
                port_body['id'] = port_body['name'].split('_')[-1]
                self._create_shadow_agent(context, port_body)
                helper.NetworkHelper.fill_binding_info(port_body)
                # clear binding profile set by xmanager
                port_body[portbindings.PROFILE] = {}
            elif (port_body['device_owner'] ==
                    t_constants.DEVICE_OWNER_SUBPORT):
                port_body['id'] = port_body['device_id']
                # need set port's device_id to empty, otherwise will raise
                # a exception because the device_id is bound to a device when
                # the trunk add this port as a subport
                port_body['device_owner'] = ''
                port_body['device_id'] = ''

        return self.core_plugin.create_port_bulk(context, ports)

    def create_port(self, context, port):
        port_body = port['port']
        network_id = port_body['network_id']
        # get_network will create bottom network if it doesn't exist
        self.get_network(context, network_id)

        t_ctx = t_context.get_context_from_neutron_context(context)
        raw_client = self.neutron_handle._get_client(t_ctx)

        def get_top_port_by_ip(ip):
            params = {'fixed_ips': 'ip_address=%s' % ip,
                      'network_id': network_id}
            t_ports = raw_client.list_ports(**params)['ports']
            if not t_ports:
                raise q_exceptions.InvalidIpForNetwork(
                    ip_address=fixed_ip['ip_address'])
            return t_ports[0]

        if port_body['fixed_ips'] is not q_constants.ATTR_NOT_SPECIFIED and (
            port_body.get('device_owner') != (
                q_constants.DEVICE_OWNER_LOADBALANCERV2)):
            if not self._is_special_port(port_body):
                fixed_ip = port_body['fixed_ips'][0]
                ip_address = fixed_ip.get('ip_address')
                if not ip_address:
                    # dhcp agent may request to create a dhcp port without
                    # specifying ip address, we just raise an exception to
                    # reject this request
                    raise q_exceptions.InvalidIpForNetwork(ip_address='None')
                t_port = get_top_port_by_ip(ip_address)
            elif helper.NetworkHelper.is_need_top_sync_port(
                    port_body, cfg.CONF.client.bridge_cidr):
                # for port that needs to be synced with top port, we keep ids
                # the same
                ip_address = port_body['fixed_ips'][0]['ip_address']
                port_body['id'] = get_top_port_by_ip(ip_address)['id']
                t_port = port_body
            else:
                self._handle_dvr_snat_port(t_ctx, port_body)
                t_port = port_body
        else:
            self._adapt_port_body_for_client(port['port'])
            t_port = raw_client.create_port(port)['port']

        if not self._is_special_port(port_body):
            subnet_id = t_port['fixed_ips'][0]['subnet_id']
            # get_subnet will create bottom subnet if it doesn't exist
            self.get_subnet(context, subnet_id)

        for field in ('name', 'device_id', 'device_owner', 'binding:host_id'):
            if port_body.get(field):
                t_port[field] = port_body[field]

        self._handle_security_group(t_ctx, context, t_port)
        self._create_shadow_agent(context, port_body)
        b_port = self.core_plugin.create_port(context, {'port': t_port})
        return b_port

    def _create_shadow_agent(self, context, port_body):
        """Create shadow agent before creating shadow port

        Called inside self.create_port function. Shadow port is created by xjob
        daemon. Xjob daemon will insert agent information(agent type, tunnel
        ip and host) in the binding profile of the request body. This function
        checks if the necessary information is in the request body, if so, it
        invokes real core plugin to create or update shadow agent. For other
        kinds of port creation requests, this function is called but does not
        take effect.

        :param context: neutron context
        :param port_body: port update body
        :return: None
        """
        if not utils.is_extension_supported(self.core_plugin, 'agent'):
            return
        profile_dict = port_body.get(portbindings.PROFILE, {})
        if not validators.is_attr_set(profile_dict):
            return
        if t_constants.PROFILE_TUNNEL_IP not in profile_dict:
            return
        agent_type = profile_dict[t_constants.PROFILE_AGENT_TYPE]
        tunnel_ip = profile_dict[t_constants.PROFILE_TUNNEL_IP]
        agent_host = port_body[portbindings.HOST_ID]
        agent_state = helper.NetworkHelper.construct_agent_data(
            agent_type, agent_host, tunnel_ip)
        self.core_plugin.create_or_update_agent(context, agent_state)

    def _fill_agent_info_in_profile(self, context, port_id, host,
                                    profile_dict):
        """Fill agent information in the binding profile

        Called inside self.update_port function. When local plugin handles
        port update request, it checks if host is in the body, if so, local
        plugin will send a port update request to central Neutron to tell
        central plugin that the port has been bound to a host. The information
        of the agent in the host is inserted in the update body by calling this
        function. So after central Neutron receives the request, it can save
        the agent information in the Tricircle shadow agent table.

        :param context: neutron object
        :param port_id: port uuid
        :param host: host the port is bound to
        :param profile_dict: binding profile dict in the port update body
        :return: None
        """
        if not utils.is_extension_supported(self.core_plugin, 'agent'):
            return
        if cfg.CONF.client.cross_pod_vxlan_mode == t_constants.NM_NOOP:
            return

        port = self.core_plugin.get_port(context, port_id)
        net = self.core_plugin.get_network(context, port['network_id'])
        if net[provider_net.NETWORK_TYPE] != t_constants.NT_VxLAN:
            return

        vif_type = port[portbindings.VIF_TYPE]
        agent_type = helper.NetworkHelper.get_agent_type_by_vif(vif_type)
        if not agent_type:
            return
        agents = self.core_plugin.get_agents(
            context, filters={'agent_type': [agent_type], 'host': [host]})
        if not agents:
            return

        if cfg.CONF.client.cross_pod_vxlan_mode == t_constants.NM_P2P:
            helper.NetworkHelper.fill_agent_data(agent_type, host, agents[0],
                                                 profile_dict)
        elif cfg.CONF.client.cross_pod_vxlan_mode == t_constants.NM_L2GW:
            if not cfg.CONF.tricircle.l2gw_tunnel_ip:
                LOG.error('Cross-pod VxLAN networking mode is set to l2gw '
                          'but L2 gateway tunnel ip is not configured')
                return
            l2gw_tunnel_ip = cfg.CONF.tricircle.l2gw_tunnel_ip
            helper.NetworkHelper.fill_agent_data(agent_type, host, agents[0],
                                                 profile_dict,
                                                 tunnel_ip=l2gw_tunnel_ip)

    @staticmethod
    def _need_top_update(port, update_body):
        if not update_body.get(portbindings.HOST_ID):
            # no need to update top port if host is not updated
            return False
        # only for those ports that are synced with top port, we need to
        # update top port
        return helper.NetworkHelper.is_need_top_sync_port(
            port, cfg.CONF.client.bridge_cidr)

    def update_port(self, context, _id, port):
        # ovs agent will not call update_port, it updates port status via rpc
        # and direct db operation
        profile_dict = port['port'].get(portbindings.PROFILE, {})
        if profile_dict.pop(t_constants.PROFILE_FORCE_UP, None):
            port['port']['status'] = q_constants.PORT_STATUS_ACTIVE
            port['port'][
                portbindings.VNIC_TYPE] = q_constants.ATTR_NOT_SPECIFIED
        b_port = self.core_plugin.update_port(context, _id, port)
        if self._need_top_update(b_port, port['port']):
            region_name = self._get_neutron_region()
            update_dict = {portbindings.PROFILE: {
                t_constants.PROFILE_REGION: region_name,
                t_constants.PROFILE_DEVICE: b_port['device_owner']}}
            self._fill_agent_info_in_profile(
                context, _id, port['port'][portbindings.HOST_ID],
                update_dict[portbindings.PROFILE])

            if directory.get_plugin('trunk'):
                trunk_details = b_port.get('trunk_details')
                if trunk_details:
                    update_dict['binding:profile'].update({
                        t_constants.PROFILE_LOCAL_TRUNK_ID:
                            trunk_details['trunk_id']})

            t_ctx = t_context.get_context_from_neutron_context(context)
            self.neutron_handle.handle_update(t_ctx, 'port', _id,
                                              {'port': update_dict})
        return b_port

    def _start_trunk_create(self, context):
        if context.request_id:
            LOG.debug('trunk create start for ' + context.request_id)
            self.on_trunk_create[context.request_id] = True

    def _end_trunk_create(self, context):
        if context.request_id:
            LOG.debug('trunk create end for ' + context.request_id)
            self.on_trunk_create.pop(context.request_id, None)

    def _in_trunk_create(self, context):
        if context.request_id:
            return context.request_id in self.on_trunk_create
        return False

    def _create_trunk(self, context, t_ctx, port_id):
        trunk_plugin = directory.get_plugin('trunk')
        if not trunk_plugin:
            return
        b_trunks = trunk_plugin.get_trunks(
            context, filters={'port_id': [port_id]})
        if b_trunks:
            return
        t_trunks = self.neutron_handle.handle_list(
            t_ctx, 'trunk', [{'key': 'port_id',
                              'comparator': 'eq',
                              'value': port_id}])
        if not t_trunks:
            return
        t_trunk = t_trunks[0]
        # sub_ports will be created in xjob, so set it to empty here
        t_trunk['sub_ports'] = []
        trunk_plugin.create_trunk(context, {'trunk': t_trunk})

    def _ensure_trunk(self, context, t_ctx, port_id):
        # avoid recursive calls: _ensure_trunk will call create_trunk,
        # create_trunk will call get_port, and get_port will call
        # _ensure_trunk again
        if not self._in_trunk_create(context):
            self._start_trunk_create(context)
            try:
                self._create_trunk(context, t_ctx, port_id)
            except Exception:
                raise
            finally:
                self._end_trunk_create(context)

    def get_port(self, context, _id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            b_port = self.core_plugin.get_port(context, _id, fields)
        except q_exceptions.NotFound:
            if self._skip_non_api_query(t_ctx):
                raise q_exceptions.PortNotFound(port_id=_id)
            t_port = self.neutron_handle.handle_get(t_ctx, 'port', _id)
            if not t_port:
                raise q_exceptions.PortNotFound(port_id=_id)
            self._ensure_network_subnet(context, t_port)
            self._adapt_port_body_for_call(t_port)
            self._handle_security_group(t_ctx, context, t_port)
            b_port = self.core_plugin.create_port(context, {'port': t_port})

        self._ensure_trunk(context, t_ctx, _id)
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
        if self._skip_non_api_query(t_ctx):
            return b_ports
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
            self._handle_security_group(t_ctx, context, port)
            b_port = self.core_plugin.create_port(context,
                                                  {'port': port})
            b_ports.append(self._fields(b_port, fields))
        return b_ports

    def delete_port(self, context, _id, l3_port_check=True):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            b_port = self.core_plugin.get_port(context, _id)
            # to support floating ip, we create a copy port if the target port
            # is not in the pod where the real external network is located. to
            # distinguish it from normal port, we name it with a prefix
            do_top_delete = b_port['device_owner'].startswith(
                q_constants.DEVICE_OWNER_COMPUTE_PREFIX)
            skip_top_delete = t_constants.RT_SD_PORT in b_port['name']
        except q_exceptions.NotFound:
            return
        if do_top_delete and not skip_top_delete:
            self.neutron_handle.handle_delete(t_ctx, t_constants.RT_PORT, _id)
        self.core_plugin.delete_port(context, _id, l3_port_check)

    def _handle_security_group(self, t_ctx, q_ctx, port):
        if 'security_groups' not in port:
            return
        if not port['security_groups']:
            raw_client = self.neutron_handle._get_client(t_ctx)
            params = {'name': 'default'}
            t_sgs = raw_client.list_security_groups(
                **params)['security_groups']
            if t_sgs:
                port['security_groups'] = [t_sgs[0]['id']]
        if port['security_groups'] is q_constants.ATTR_NOT_SPECIFIED:
            return
        for sg_id in port['security_groups']:
            self.get_security_group(q_ctx, sg_id)

    def get_security_group(self, context, _id, fields=None, tenant_id=None):
        try:
            return self.core_plugin.get_security_group(
                context, _id, fields, tenant_id)
        except q_exceptions.NotFound:
            t_ctx = t_context.get_context_from_neutron_context(context)
            t_sg = self.neutron_handle.handle_get(t_ctx,
                                                  'security_group', _id)
            if not t_sg:
                raise ext_sg.SecurityGroupNotFound(id=_id)
            self.core_plugin.create_security_group(context,
                                                   {'security_group': t_sg})
            return self.core_plugin.get_security_group(
                context, _id, fields, tenant_id)

    def get_security_groups(self, context, filters=None, fields=None,
                            sorts=None, limit=None, marker=None,
                            page_reverse=False, default_sg=False):
        # if id is not specified in the filter, we just return security group
        # data in local Neutron server, otherwise id is specified, we need to
        # retrieve network data from central Neutron server and create network
        # which doesn't exist in local Neutron server.
        if not filters or 'id' not in filters:
            return self.core_plugin.get_security_groups(
                context, filters, fields, sorts, limit, marker, page_reverse,
                default_sg)

        b_sgs = self.core_plugin.get_security_groups(
            context, filters, fields, sorts, limit, marker, page_reverse,
            default_sg)
        if len(b_sgs) == len(filters['id']):
            return b_sgs

        t_ctx = t_context.get_context_from_neutron_context(context)
        raw_client = self.neutron_handle._get_client(t_ctx)
        params = self._construct_params(filters, sorts, limit, marker,
                                        page_reverse)
        t_sgs = raw_client.list_security_groups(**params)['security_groups']

        t_id_set = set([sg['id'] for sg in t_sgs])
        b_id_set = set([sg['id'] for sg in b_sgs])
        missing_id_set = t_id_set - b_id_set
        if missing_id_set:
            missing_sgs = [sg for sg in t_sgs if (
                sg['id'] in missing_id_set)]
            for sg in missing_sgs:
                b_sg = self.core_plugin.create_security_group(
                    context, {'security_group': sg})
                b_sgs.append(self.core_plugin.get_security_group(
                    context, b_sg['id'], fields))
        return b_sgs
