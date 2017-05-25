# Copyright 2015 Huawei Technologies Co., Ltd.
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

import copy
import netaddr
import re
import six
from six.moves import xrange

from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
from neutron_lib import constants
import neutronclient.common.exceptions as q_cli_exceptions
from oslo_serialization import jsonutils

from tricircle.common import client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.common.lock_handle as t_lock
from tricircle.common import utils
import tricircle.db.api as db_api
import tricircle.network.exceptions as t_network_exc


# manually define these constants to avoid depending on neutron repos
# neutron.extensions.availability_zone.AZ_HINTS
AZ_HINTS = 'availability_zone_hints'
EXTERNAL = 'router:external'  # neutron.extensions.external_net.EXTERNAL
TYPE_VLAN = 'vlan'  # neutron.plugins.common.constants.TYPE_VLAN
TYPE_VXLAN = 'vxlan'  # neutron.plugins.common.constants.TYPE_VXLAN

OVS_AGENT_DATA_TEMPLATE = {
    'agent_type': None,
    'binary': 'neutron-openvswitch-agent',
    'host': None,
    'topic': constants.L2_AGENT_TOPIC,
    'configurations': {
        'ovs_hybrid_plug': False,
        'in_distributed_mode': False,
        'datapath_type': 'system',
        'arp_responder_enabled': False,
        'tunneling_ip': None,
        'vhostuser_socket_dir': '/var/run/openvswitch',
        'devices': 0,
        'ovs_capabilities': {
            'datapath_types': ['netdev', 'system'],
            'iface_types': ['geneve', 'gre', 'internal', 'ipsec_gre', 'lisp',
                            'patch', 'stt', 'system', 'tap', 'vxlan']},
        'log_agent_heartbeats': False,
        'l2_population': True,
        'tunnel_types': ['vxlan'],
        'extensions': [],
        'enable_distributed_routing': False,
        'bridge_mappings': {}}}

VIF_AGENT_TYPE_MAP = {
    portbindings.VIF_TYPE_OVS: constants.AGENT_TYPE_OVS}

AGENT_DATA_TEMPLATE_MAP = {
    constants.AGENT_TYPE_OVS: OVS_AGENT_DATA_TEMPLATE}

TUNNEL_IP_HANDLE_MAP = {
    constants.AGENT_TYPE_OVS: lambda agent: agent[
        'configurations']['tunneling_ip']}

MAC_PATTERN = re.compile('([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}')


class NetworkHelper(object):
    def __init__(self, call_obj=None):
        self.clients = {}
        self.call_obj = call_obj

    @staticmethod
    def _transfer_network_type(network_type):
        network_type_map = {t_constants.NT_VLAN: TYPE_VLAN,
                            t_constants.NT_VxLAN: TYPE_VXLAN}
        return network_type_map.get(network_type, network_type)

    @staticmethod
    def _get_provider_info(t_net):
        ret = {
            provider_net.NETWORK_TYPE: NetworkHelper._transfer_network_type(
                t_net[provider_net.NETWORK_TYPE]),
            provider_net.SEGMENTATION_ID: t_net[provider_net.SEGMENTATION_ID]
        }
        if t_net[provider_net.NETWORK_TYPE] == t_constants.NT_VLAN:
            ret[provider_net.PHYSICAL_NETWORK] = t_net[
                provider_net.PHYSICAL_NETWORK]
        return ret

    def _get_client(self, region_name=None):
        if not region_name:
            if t_constants.TOP not in self.clients:
                self.clients[t_constants.TOP] = client.Client()
            return self.clients[t_constants.TOP]
        if region_name not in self.clients:
            self.clients[region_name] = client.Client(region_name)
        return self.clients[region_name]

    @staticmethod
    def _merge_ip_range(ip_range, ip):
        ip_set = netaddr.IPSet(ip_range)
        ip_set.add(ip)
        if ip_set.iscontiguous():
            return ip_set.iprange(), True
        else:
            return ip_range, False

    # operate top resource
    def _prepare_top_element_by_call(self, t_ctx, q_ctx,
                                     project_id, pod, ele, _type, body):
        def list_resources(t_ctx_, q_ctx_, pod_, ele_, _type_):
            return getattr(super(self.call_obj.__class__, self.call_obj),
                           'get_%ss' % _type_)(q_ctx_,
                                               filters={'name': [ele_['id']]})

        def create_resources(t_ctx_, q_ctx_, pod_, body_, _type_):
            if _type_ == t_constants.RT_NETWORK:
                # for network, we call TricirclePlugin's own create_network to
                # handle network segment
                return self.call_obj.create_network(q_ctx_, body_)
            else:
                return getattr(super(self.call_obj.__class__, self.call_obj),
                               'create_%s' % _type_)(q_ctx_, body_)

        return t_lock.get_or_create_element(
            t_ctx, q_ctx,
            project_id, pod, ele, _type, body,
            list_resources, create_resources)

    def _prepare_top_element_by_client(self, t_ctx, q_ctx,
                                       project_id, pod, ele, _type, body):
        def list_resources(t_ctx_, q_ctx_, pod_, ele_, _type_):
            client = self._get_client()
            return client.list_resources(_type_, t_ctx_,
                                         [{'key': 'name', 'comparator': 'eq',
                                           'value': ele_['id']}])

        def create_resources(t_ctx_, q_ctx_, pod_, body_, _type_):
            client = self._get_client()
            return client.create_resources(_type_, t_ctx_, body_)

        assert _type == 'port'
        # currently only top port is possible to be created via client, other
        # top resources should be created directly by plugin
        return t_lock.get_or_create_element(
            t_ctx, q_ctx,
            project_id, pod, ele, _type, body,
            list_resources, create_resources)

    def prepare_top_element(self, t_ctx, q_ctx,
                            project_id, pod, ele, _type, body):
        """Get or create shared top networking resource

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param pod: dict of top pod
        :param ele: dict with "id" as key and distinctive identifier as value
        :param _type: type of the resource
        :param body: request body to create resource
        :return: boolean value indicating whether the resource is newly
                 created or already exists and id of the resource
        """
        if self.call_obj:
            return self._prepare_top_element_by_call(
                t_ctx, q_ctx, project_id, pod, ele, _type, body)
        else:
            return self._prepare_top_element_by_client(
                t_ctx, q_ctx, project_id, pod, ele, _type, body)

    def get_bridge_interface(self, t_ctx, q_ctx, project_id, pod,
                             t_net_id, b_router_id, t_subnet=None):
        """Get or create top bridge interface

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param pod: dict of top pod
        :param t_net_id: top bridge network id
        :param b_router_id: bottom router id
        :param t_subnet: optional top bridge subnet dict
        :return: bridge interface id
        """
        port_name = t_constants.bridge_port_name % (project_id,
                                                    b_router_id)
        port_ele = {'id': port_name}
        port_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'name': port_name,
                'network_id': t_net_id,
                'device_id': '',
                'device_owner': ''
            }
        }
        if self.call_obj:
            port_body['port'].update(
                {'mac_address': constants.ATTR_NOT_SPECIFIED,
                 'fixed_ips': constants.ATTR_NOT_SPECIFIED})
        if t_subnet:
            port_body['port'].update(
                {'fixed_ips': [{'subnet_id': t_subnet['id'],
                                'ip_address': t_subnet['gateway_ip']}]})
        _, port_id = self.prepare_top_element(
            t_ctx, q_ctx, project_id, pod, port_ele, 'port', port_body)
        return port_id

    # operate bottom resource
    def prepare_bottom_element(self, t_ctx,
                               project_id, pod, ele, _type, body):
        """Get or create bottom networking resource based on top resource

        :param t_ctx: tricircle context
        :param project_id: project id
        :param pod: dict of bottom pod
        :param ele: dict of top resource
        :param _type: type of the resource
        :param body: request body to create resource
        :return: boolean value indicating whether the resource is newly
                 created or already exists and id of the resource
        """
        def list_resources(t_ctx_, q_ctx, pod_, ele_, _type_):
            client = self._get_client(pod_['region_name'])
            if _type_ == t_constants.RT_NS_ROUTER:
                _type_ = t_constants.RT_ROUTER
                value = t_constants.ns_router_name % ele_['id']
            elif _type_ == t_constants.RT_SD_PORT:
                _type_ = t_constants.RT_PORT
                value = t_constants.shadow_port_name % ele_['id']
            elif _type_ == t_constants.RT_NETWORK:
                value = utils.get_bottom_network_name(ele_)
            elif _type_ == t_constants.RT_SD_PORT:
                _type_ = t_constants.RT_PORT
                value = t_constants.shadow_port_name % ele_['id']
            else:
                value = ele_['id']
            return client.list_resources(_type_, t_ctx_,
                                         [{'key': 'name', 'comparator': 'eq',
                                           'value': value}])

        def create_resources(t_ctx_, q_ctx, pod_, body_, _type_):
            if _type_ == t_constants.RT_NS_ROUTER:
                _type_ = t_constants.RT_ROUTER
            elif _type_ == t_constants.RT_SD_PORT:
                _type_ = t_constants.RT_PORT
            client = self._get_client(pod_['region_name'])
            if _type_ == t_constants.RT_SD_PORT:
                _type_ = t_constants.RT_PORT
            return client.create_resources(_type_, t_ctx_, body_)

        return t_lock.get_or_create_element(
            t_ctx, None,  # we don't need neutron context, so pass None
            project_id, pod, ele, _type, body,
            list_resources, create_resources)

    @staticmethod
    def get_create_network_body(project_id, network):
        """Get request body to create bottom network

        :param project_id: project id
        :param network: top network dict
        :return: request body to create bottom network
        """
        body = {
            'network': {
                'tenant_id': project_id,
                'name': utils.get_bottom_network_name(network),
                'admin_state_up': True
            }
        }
        network_type = network.get(provider_net.NETWORK_TYPE)
        if network_type == t_constants.NT_VLAN:
            body['network'][provider_net.NETWORK_TYPE] = 'vlan'
            body['network'][provider_net.PHYSICAL_NETWORK] = network[
                provider_net.PHYSICAL_NETWORK]
            body['network'][provider_net.SEGMENTATION_ID] = network[
                provider_net.SEGMENTATION_ID]
        return body

    @staticmethod
    def _find_ip_range(pool, gateway_ip):
        ret_pools = []
        ip_range = netaddr.IPRange(pool['start'], pool['end'])
        ip_num = len(ip_range)
        for i, ip in enumerate(ip_range):
            if gateway_ip == ip:
                if i > 0:
                    ret_pools.append({'start': ip_range[0].format(),
                                      'end': ip_range[i - 1].format()})
                if i < ip_num - 1:
                    ret_pools.append(
                        {'start': ip_range[i + 1].format(),
                         'end': ip_range[ip_num - 1].format()})
                return ret_pools

    @staticmethod
    def _split_pools_by_bottom_gateway_ip(pools, gateway_ip):
        new_pools = []
        g_ip = netaddr.IPAddress(gateway_ip)
        ip_found = False
        for pool in pools:
            if ip_found:
                new_pools.append({'start': pool['start'],
                                  'end': pool['end']})
                continue
            ret_pools = NetworkHelper._find_ip_range(pool, g_ip)
            if ret_pools:
                ip_found = True
                new_pools.extend(ret_pools)
        if not ip_found:
            new_pools.extend(pools)
        return new_pools

    @staticmethod
    def _merge_pools_by_top_gateway_ip(pools, gateway_ip):
        new_ranges = []
        merged_set = netaddr.IPSet()
        for pool in pools:
            ip_range = netaddr.IPRange(pool['start'], pool['end'])
            ip_range, ip_merged = NetworkHelper._merge_ip_range(
                ip_range, gateway_ip)
            if not ip_merged:
                new_ranges.append(ip_range)
            else:
                # if range1 + gateway_ip is contiguous, range2 + gateway_ip is
                # contiguous, then range1 + range2 + gateway_ip is contiguous,
                # so we add them in the same ip set
                merged_set.add(ip_range)
        new_pools = []
        for new_range in new_ranges:
            new_pools.append({'start': new_range[0].format(),
                              'end': new_range[len(new_range) - 1].format()})
        if merged_set:
            merged_range = merged_set.iprange()
            new_pools.append(
                {'start': merged_range[0].format(),
                 'end': merged_range[len(merged_range) - 1].format()})
        else:
            new_pools.append({'start': gateway_ip, 'end': gateway_ip})
        return new_pools

    @staticmethod
    def get_bottom_subnet_pools(t_subnet, b_gateway_ip):
        """Get bottom subnet allocation pools

        :param t_subnet: top subnet
        :param b_gateway_ip: bottom subnet gateway ip
        :return: bottom subnet allocation pools
        """
        pools = t_subnet['allocation_pools']
        t_gateway_ip = t_subnet['gateway_ip']
        if not t_gateway_ip:
            # gateway is None, so we don't need to split allocation pools
            return pools
        new_pools = NetworkHelper._split_pools_by_bottom_gateway_ip(
            pools, b_gateway_ip)
        if t_gateway_ip == b_gateway_ip:
            return new_pools
        return NetworkHelper._merge_pools_by_top_gateway_ip(new_pools,
                                                            t_gateway_ip)

    @staticmethod
    def get_create_subnet_body(project_id, t_subnet, b_net_id, gateway_ip):
        """Get request body to create bottom subnet

        :param project_id: project id
        :param t_subnet: top subnet dict
        :param b_net_id: bottom network id
        :param gateway_ip: bottom gateway ip
        :return: request body to create bottom subnet
        """
        new_pools = NetworkHelper.get_bottom_subnet_pools(t_subnet, gateway_ip)
        body = {
            'subnet': {
                'network_id': b_net_id,
                'name': t_subnet['id'],
                'ip_version': t_subnet['ip_version'],
                'cidr': t_subnet['cidr'],
                'gateway_ip': gateway_ip,
                'allocation_pools': new_pools,
                'enable_dhcp': False,
                'tenant_id': project_id
            }
        }
        return body

    @staticmethod
    def get_create_port_body(project_id, t_port, subnet_map, b_net_id,
                             b_security_group_ids=None):
        """Get request body to create bottom port

        :param project_id: project id
        :param t_port: top port dict
        :param subnet_map: dict with top subnet id as key and bottom subnet
               id as value
        :param b_net_id: bottom network id
        :param b_security_group_ids: list of bottom security group id
        :return: request body to create bottom port
        """
        b_fixed_ips = []
        for ip in t_port['fixed_ips']:
            b_ip = {'subnet_id': subnet_map[ip['subnet_id']],
                    'ip_address': ip['ip_address']}
            b_fixed_ips.append(b_ip)
        body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'name': t_port['id'],
                'network_id': b_net_id,
                'mac_address': t_port['mac_address'],
                'fixed_ips': b_fixed_ips
            }
        }
        if b_security_group_ids:
            body['port']['security_groups'] = b_security_group_ids
        return body

    def get_create_interface_body(self, project_id, t_net_id, b_region_name,
                                  t_subnet_id):
        """Get request body to create top interface

        :param project_id: project id
        :param t_net_id: top network id
        :param b_region_name: bottom pod name
        :param t_subnet_id: top subnet id
        :return:
        """
        t_interface_name = t_constants.interface_port_name % (b_region_name,
                                                              t_subnet_id)
        t_interface_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'name': t_interface_name,
                'network_id': t_net_id,
                'device_id': '',
                'device_owner': 'network:router_interface',
            }
        }
        if self.call_obj:
            t_interface_body['port'].update(
                {'mac_address': constants.ATTR_NOT_SPECIFIED,
                 'fixed_ips': constants.ATTR_NOT_SPECIFIED})
        return t_interface_body

    def prepare_bottom_network_subnets(self, t_ctx, q_ctx, project_id, pod,
                                       t_net, t_subnets):
        """Get or create bottom network, subnet and dhcp port

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param pod: dict of bottom pod
        :param t_net: dict of top network
        :param t_subnets: list of top subnet dict
        :return: bottom network id and a dict with top subnet id as key,
                 bottom subnet id as value
        """
        # network
        net_body = self.get_create_network_body(project_id, t_net)
        if net_body['network'].get(provider_net.NETWORK_TYPE):
            # if network type specified, we need to switch to admin account
            admin_context = t_context.get_admin_context()

            _, b_net_id = self.prepare_bottom_element(
                admin_context, project_id, pod, t_net, t_constants.RT_NETWORK,
                net_body)
        else:
            _, b_net_id = self.prepare_bottom_element(
                t_ctx, project_id, pod, t_net, t_constants.RT_NETWORK,
                net_body)

        # subnet
        subnet_map = {}
        subnet_dhcp_map = {}

        for subnet in t_subnets:
            # gateway
            t_interface_name = t_constants.interface_port_name % (
                pod['region_name'], subnet['id'])

            t_interface_body = self.get_create_interface_body(
                project_id, t_net['id'], pod['region_name'], subnet['id'])

            _, t_interface_id = self.prepare_top_element(
                t_ctx, q_ctx, project_id, pod, {'id': t_interface_name},
                t_constants.RT_PORT, t_interface_body)
            t_interface = self._get_top_element(
                t_ctx, q_ctx, t_constants.RT_PORT, t_interface_id)
            gateway_ip = t_interface['fixed_ips'][0]['ip_address']

            subnet_body = self.get_create_subnet_body(
                project_id, subnet, b_net_id, gateway_ip)
            _, b_subnet_id = self.prepare_bottom_element(
                t_ctx, project_id, pod, subnet, t_constants.RT_SUBNET,
                subnet_body)
            subnet_map[subnet['id']] = b_subnet_id
            subnet_dhcp_map[subnet['id']] = subnet['enable_dhcp']

        # dhcp port
        for t_subnet_id, b_subnet_id in six.iteritems(subnet_map):
            if not subnet_dhcp_map[t_subnet_id]:
                continue
            self.prepare_dhcp_port(t_ctx, project_id, pod, t_net['id'],
                                   t_subnet_id, b_net_id, b_subnet_id)
            b_client = self._get_client(pod['region_name'])
            b_client.update_subnets(t_ctx, b_subnet_id,
                                    {'subnet': {'enable_dhcp': True}})

        return b_net_id, subnet_map

    def get_bottom_bridge_elements(self, t_ctx, project_id,
                                   pod, t_net, is_external, t_subnet, t_port):
        """Get or create bottom bridge port

        :param t_ctx: tricircle context
        :param project_id: project id
        :param pod: dict of bottom pod
        :param t_net: dict of top bridge network
        :param is_external: whether the bottom network should be created as
               an external network, this is True for south-north case
        :param t_subnet: dict of top bridge subnet
        :param t_port: dict of top bridge port
        :return: tuple (boolean value indicating whether the resource is newly
                 created or already exists, bottom port id, bottom subnet id,
                 bottom network id)
        """
        net_body = {'network': {
            'tenant_id': project_id,
            'name': t_net['id'],
            'admin_state_up': True}}
        net_body['network'].update(self._get_provider_info(t_net))
        if is_external:
            net_body['network'][EXTERNAL] = True
        _, b_net_id = self.prepare_bottom_element(
            t_ctx, project_id, pod, t_net, 'network', net_body)

        subnet_body = {'subnet': {'network_id': b_net_id,
                                  'name': t_subnet['id'],
                                  'ip_version': 4,
                                  'cidr': t_subnet['cidr'],
                                  'enable_dhcp': False,
                                  'tenant_id': project_id}}
        _, b_subnet_id = self.prepare_bottom_element(
            t_ctx, project_id, pod, t_subnet, 'subnet', subnet_body)

        if t_port:
            port_body = {
                'port': {
                    'tenant_id': project_id,
                    'admin_state_up': True,
                    'name': t_port['id'],
                    'network_id': b_net_id,
                    'fixed_ips': [
                        {'subnet_id': b_subnet_id,
                         'ip_address': t_port['fixed_ips'][0]['ip_address']}]
                }
            }
            is_new, b_port_id = self.prepare_bottom_element(
                t_ctx, project_id, pod, t_port, 'port', port_body)

            return is_new, b_port_id, b_subnet_id, b_net_id
        else:
            return None, None, b_subnet_id, b_net_id

    @staticmethod
    def _get_create_dhcp_port_body(project_id, port, b_subnet_id,
                                   b_net_id):
        body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'name': port['id'],
                'network_id': b_net_id,
                'fixed_ips': [
                    {'subnet_id': b_subnet_id,
                     'ip_address': port['fixed_ips'][0]['ip_address']}
                ],
                'mac_address': port['mac_address'],
                portbindings.PROFILE: {},
                'device_id': 'reserved_dhcp_port',
                'device_owner': 'network:dhcp',
            }
        }
        return body

    def prepare_top_snat_port(self, t_ctx, q_ctx, project_id, t_net_id,
                              t_subnet_id):
        """Create top centralized snat port

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param t_net_id: top network id
        :param t_subnet_id: top subnet id
        :return: top centralized snat port
        """
        t_snat_name = t_constants.snat_port_name % t_subnet_id
        t_snat_port_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'network_id': t_net_id,
                'name': t_snat_name,
                'binding:profile': {},
                'device_id': '',
                'device_owner': constants.DEVICE_OWNER_ROUTER_SNAT,
            }
        }
        if self.call_obj:
            t_snat_port_body['port'].update(
                {'mac_address': constants.ATTR_NOT_SPECIFIED,
                 'fixed_ips': constants.ATTR_NOT_SPECIFIED})

        # NOTE(zhiyuan) for one subnet in different pods, we just create one
        # centralized snat port. though snat port in different pods will have
        # the same IP, VM packets will only got to the local router namespace
        _, t_snat_port_id = self.prepare_top_element(
            t_ctx, q_ctx, project_id, db_api.get_top_pod(t_ctx),
            {'id': t_snat_name}, t_constants.RT_PORT, t_snat_port_body)
        return t_snat_port_id

    def prepare_top_dhcp_port(self, t_ctx, q_ctx, project_id, t_net_id,
                              t_subnet_id):
        """Create top dhcp port

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param t_net_id: top network id
        :param t_subnet_id: top subnet id
        :return: top dhcp port id
        """
        t_dhcp_name = t_constants.dhcp_port_name % t_subnet_id
        t_dhcp_port_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'network_id': t_net_id,
                'name': t_dhcp_name,
                portbindings.PROFILE: {},
                'device_id': 'reserved_dhcp_port',
                'device_owner': 'network:dhcp',
            }
        }
        if self.call_obj:
            t_dhcp_port_body['port'].update(
                {'mac_address': constants.ATTR_NOT_SPECIFIED,
                 'fixed_ips': constants.ATTR_NOT_SPECIFIED})

        # NOTE(zhiyuan) for one subnet in different pods, we just create
        # one dhcp port. though dhcp port in different pods will have
        # the same IP, each dnsmasq daemon only takes care of VM IPs in
        # its own pod, VM will not receive incorrect dhcp response
        _, t_dhcp_port_id = self.prepare_top_element(
            t_ctx, q_ctx, project_id, db_api.get_top_pod(t_ctx),
            {'id': t_dhcp_name}, t_constants.RT_PORT, t_dhcp_port_body)
        return t_dhcp_port_id

    def prepare_dhcp_port(self, ctx, project_id, b_pod, t_net_id, t_subnet_id,
                          b_net_id, b_subnet_id):
        """Create top dhcp port and map it to bottom dhcp port

        :param ctx: tricircle context
        :param project_id: project id
        :param b_pod: dict of bottom pod
        :param t_net_id: top network id
        :param t_subnet_id: top subnet id
        :param b_net_id: bottom network id
        :param b_subnet_id: bottom subnet id
        :return: None
        """
        t_dhcp_port_id = self.prepare_top_dhcp_port(ctx, None, project_id,
                                                    t_net_id, t_subnet_id)
        t_client = self._get_client()
        t_dhcp_port = t_client.get_ports(ctx, t_dhcp_port_id)
        dhcp_port_body = self._get_create_dhcp_port_body(
            project_id, t_dhcp_port, b_subnet_id, b_net_id)
        self.prepare_bottom_element(ctx, project_id, b_pod, t_dhcp_port,
                                    t_constants.RT_PORT, dhcp_port_body)

    @staticmethod
    def _safe_create_bottom_floatingip(t_ctx, pod, client, fip_net_id,
                                       fip_address, port_id):
        try:
            client.create_floatingips(
                t_ctx, {'floatingip': {'floating_network_id': fip_net_id,
                                       'floating_ip_address': fip_address,
                                       'port_id': port_id}})
        except q_cli_exceptions.IpAddressInUseClient:
            fips = client.list_floatingips(t_ctx,
                                           [{'key': 'floating_ip_address',
                                             'comparator': 'eq',
                                             'value': fip_address}])
            if not fips:
                # this is rare case that we got IpAddressInUseClient exception
                # a second ago but now the floating ip is missing
                raise t_network_exc.BottomPodOperationFailure(
                    resource='floating ip', region_name=pod['region_name'])
            associated_port_id = fips[0].get('port_id')
            if associated_port_id == port_id:
                # the internal port associated with the existing fip is what
                # we expect, just ignore this exception
                pass
            elif not associated_port_id:
                # the existing fip is not associated with any internal port,
                # update the fip to add association
                client.update_floatingips(t_ctx, fips[0]['id'],
                                          {'floatingip': {'port_id': port_id}})
            else:
                raise

    def _get_top_element(self, t_ctx, q_ctx, _type, _id):
        if self.call_obj:
            return getattr(self.call_obj, 'get_%s' % _type)(q_ctx, _id)
        else:
            return getattr(self._get_client(), 'get_%ss' % _type)(t_ctx, _id)

    @staticmethod
    def get_create_sg_rule_body(rule, sg_id, ip=None):
        ip = ip or rule['remote_ip_prefix']
        # if ip is passed, this is an extended rule for remote group
        return {'security_group_rule': {
            'tenant_id': rule['tenant_id'],
            'remote_group_id': None,
            'direction': rule['direction'],
            'remote_ip_prefix': ip,
            'protocol': rule.get('protocol'),
            'ethertype': rule['ethertype'],
            'port_range_max': rule.get('port_range_max'),
            'port_range_min': rule.get('port_range_min'),
            'security_group_id': sg_id}}

    @staticmethod
    def convert_az2region(t_ctx, az_hints):
        region_names = set()
        for az_hint in az_hints:
            pods = db_api.find_pods_by_az_or_region(t_ctx, az_hint)
            if not pods:
                continue
            for pod in pods:
                region_names.add(pod['region_name'])
        return list(region_names)

    @staticmethod
    def get_router_az_hints(router):
        # when called by api, availability_zone_hints included in
        # extra_attributes, but when called by xjob, it included in router
        # body directly.
        extra_attributes = router.get('extra_attributes')
        az_hints = router.get(AZ_HINTS)
        if extra_attributes:
            az_hints = extra_attributes.get(AZ_HINTS)
        if not az_hints:
            return None
        if not isinstance(az_hints, list):
            az_hints = jsonutils.loads(az_hints)
        return az_hints

    @staticmethod
    def is_local_router(t_ctx, router):
        router_az_hints = NetworkHelper.get_router_az_hints(router)
        if not router_az_hints:
            return False
        if len(router_az_hints) > 1:
            return False
        router_az_hint = router_az_hints[0]
        return bool(db_api.get_pod_by_name(t_ctx, router_az_hint))

    @staticmethod
    def is_local_network(t_ctx, net):
        if net[provider_net.NETWORK_TYPE] == t_constants.NT_LOCAL:
            return True
        net_az_hints = net.get(AZ_HINTS)
        if not net_az_hints:
            return False
        if len(net_az_hints) > 1:
            return False
        net_az_hint = net_az_hints[0]
        return bool(db_api.get_pod_by_name(t_ctx, net_az_hint))

    @staticmethod
    def get_agent_type_by_vif(vif_type):
        return VIF_AGENT_TYPE_MAP.get(vif_type)

    @staticmethod
    def is_need_top_sync_port(port, bridge_cidr):
        """Judge if the port needs to be synced with top port

        While synced with top port, shadow agent/port process is triggered

        :param port: port dict
        :param bridge_cidr: bridge subnet CIDR
        :return: True/False
        """
        device_owner = port.get('device_owner', '')
        if device_owner.startswith('compute:'):
            # sync with top port for instance port
            return True
        if device_owner not in (constants.DEVICE_OWNER_ROUTER_GW,
                                constants.DEVICE_OWNER_ROUTER_INTF):
            # no need to sync with top port if the port is NOT instance port
            # or router interface or router gateway. in DVR case, there are
            # another two router port types, router_interface_distributed and
            # router_centralized_snat, these two don't need to be synced wih
            # top port neither
            return False
        ip = port['fixed_ips'][0]['ip_address']
        # only sync with top port for bridge router port
        return netaddr.IPAddress(ip) in netaddr.IPNetwork(bridge_cidr)

    @staticmethod
    def construct_agent_data(agent_type, host, tunnel_ip):
        if agent_type not in AGENT_DATA_TEMPLATE_MAP:
            return {}
        data = copy.copy(AGENT_DATA_TEMPLATE_MAP[agent_type])
        data['agent_type'] = agent_type
        data['host'] = host
        data['configurations']['tunneling_ip'] = tunnel_ip
        return data

    @staticmethod
    def fill_agent_data(agent_type, host, agent, profile, tunnel_ip=None):
        _tunnel_ip = None
        if tunnel_ip:
            # explicitly specified tunnel IP has the highest priority
            _tunnel_ip = tunnel_ip
        elif agent_type in TUNNEL_IP_HANDLE_MAP:
            tunnel_handle = TUNNEL_IP_HANDLE_MAP[agent_type]
            _tunnel_ip = tunnel_handle(agent)
        if not _tunnel_ip:
            return
        profile[t_constants.PROFILE_HOST] = host
        profile[t_constants.PROFILE_AGENT_TYPE] = agent_type
        profile[t_constants.PROFILE_TUNNEL_IP] = _tunnel_ip

    @staticmethod
    def create_shadow_agent_if_needed(t_ctx, profile, pod):
        if t_constants.PROFILE_HOST not in profile:
            return
        agent_host = profile[t_constants.PROFILE_HOST]
        agent_type = profile[t_constants.PROFILE_AGENT_TYPE]
        agent_tunnel = profile[t_constants.PROFILE_TUNNEL_IP]
        db_api.ensure_agent_exists(t_ctx, pod['pod_id'], agent_host,
                                   agent_type, agent_tunnel)

    @staticmethod
    def fill_binding_info(port_body):
        agent_type = port_body[portbindings.PROFILE]
        # TODO(zhiyuan) support other agent types
        if agent_type == constants.AGENT_TYPE_OVS:
            port_body[portbindings.VIF_DETAILS] = {'port_filter': True,
                                                   'ovs_hybrid_plug': True}
            port_body[portbindings.VIF_TYPE] = portbindings.VIF_TYPE_OVS
            port_body[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL

    @staticmethod
    def prepare_ports_with_retry(ctx, client, req_create_bodys):
        create_body_map = dict(
            [(create_body['mac_address'],
              create_body) for create_body in req_create_bodys])
        max_tries = 10
        conflict_port_ids = []
        for i in xrange(max_tries):
            create_bodys = list(create_body_map.values())
            if not create_bodys:
                ret_ports = []
                break
            try:
                ret_ports = client.create_ports(ctx, {'ports': create_bodys})
                break
            except q_cli_exceptions.MacAddressInUseClient as e:
                if i == max_tries - 1:
                    # we fail in the last try, just raise exception
                    raise
                match = MAC_PATTERN.search(e.message)
                if match:
                    conflict_mac = match.group()
                    if conflict_mac not in create_body_map:
                        # rare case, we conflicted with an unrecognized mac
                        raise
                    conflict_port = create_body_map.pop(conflict_mac)
                    if (conflict_port['device_owner'] ==
                            t_constants.DEVICE_OWNER_SHADOW):
                        conflict_port_ids.append(
                            conflict_port['name'].split('_')[-1])
                    elif (conflict_port['device_owner'] ==
                            t_constants.DEVICE_OWNER_SUBPORT):
                        conflict_port_ids.append(conflict_port['device_id'])
                else:
                    # the exception no longer contains mac information
                    raise
        ret_port_ids = [ret_port['id'] for ret_port in ret_ports]
        ret_port_ids.extend(conflict_port_ids)
        return ret_port_ids

    def prepare_shadow_ports(self, ctx, project_id, target_pod, net_id,
                             port_bodys, agents, max_bulk_size):
        if not port_bodys:
            return []
        full_create_bodys = []
        for port_body, agent in zip(port_bodys, agents):
            host = port_body[portbindings.HOST_ID]
            create_body = {
                'port': {
                    'tenant_id': project_id,
                    'admin_state_up': True,
                    'name': t_constants.shadow_port_name % port_body['id'],
                    'network_id': net_id,
                    'fixed_ips': [{
                        'ip_address': port_body[
                            'fixed_ips'][0]['ip_address']}],
                    'mac_address': port_body['mac_address'],
                    'device_owner': t_constants.DEVICE_OWNER_SHADOW,
                    portbindings.HOST_ID: host
                }
            }
            if agent:
                create_body['port'].update(
                    {portbindings.PROFILE: {
                        t_constants.PROFILE_AGENT_TYPE: agent['type'],
                        t_constants.PROFILE_TUNNEL_IP: agent['tunnel_ip']}})
            full_create_bodys.append(create_body['port'])

        cursor = 0
        ret_port_ids = []
        client = self._get_client(target_pod['region_name'])
        while cursor < len(full_create_bodys):
            ret_port_ids.extend(self.prepare_ports_with_retry(
                ctx, client,
                full_create_bodys[cursor: cursor + max_bulk_size]))
            cursor += max_bulk_size
        return ret_port_ids

    def prepare_shadow_port(self, ctx, project_id, target_pod, net_id,
                            port_body, agent=None):
        host = port_body['binding:host_id']
        create_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'name': t_constants.shadow_port_name % port_body['id'],
                'network_id': net_id,
                'fixed_ips': [{
                    'ip_address': port_body['fixed_ips'][0]['ip_address']}],
                'device_owner': t_constants.DEVICE_OWNER_SHADOW,
                'binding:host_id': host
            }
        }
        if agent:
            create_body['port'].update(
                {'binding:profile': {
                    t_constants.PROFILE_AGENT_TYPE: agent['type'],
                    t_constants.PROFILE_TUNNEL_IP: agent['tunnel_ip']}})
        _, sw_port_id = self.prepare_bottom_element(
            ctx, project_id, target_pod, {'id': port_body['id']},
            t_constants.RT_SD_PORT, create_body)
        return sw_port_id

    @staticmethod
    def get_real_shadow_resource_iterator(t_ctx, res_type, res_id):
        shadow_res_type = t_constants.REAL_SHADOW_TYPE_MAP[res_type]
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, res_id, res_type)
        mappings.extend(db_api.get_bottom_mappings_by_top_id(
            t_ctx, res_id, shadow_res_type))

        processed_pod_set = set()
        for pod, bottom_res_id in mappings:
            region_name = pod['region_name']
            if region_name in processed_pod_set:
                continue
            processed_pod_set.add(region_name)
            yield pod, bottom_res_id

    @staticmethod
    def extract_resource_routing_entries(port):
        entries = []
        if not port:
            return entries
        for ip in port['fixed_ips']:
            entries.append((ip['subnet_id'], ip['subnet_id'],
                            t_constants.RT_SUBNET))
        entries.append((port['network_id'], port['network_id'],
                        t_constants.RT_NETWORK))
        entries.append((port['id'], port['id'],
                        t_constants.RT_PORT))
        if port['security_groups']:
            for sg_id in port['security_groups']:
                entries.append((sg_id, sg_id, t_constants.RT_SG))
        return entries

    @staticmethod
    def ensure_resource_mapping(t_ctx, project_id, pod, entries):
        """Ensure resource mapping

        :param t_ctx: tricircle context
        :param project_id: project id
        :param pod: bottom pod
        :param entries: a list of (top_id, bottom_id, resource_type) tuples.
        :return: None
        """
        for top_id, btm_id, resource_type in entries:
            if db_api.get_bottom_id_by_top_id_region_name(
                    t_ctx, top_id, pod['region_name'], resource_type):
                continue
            db_api.create_resource_mapping(t_ctx, top_id, btm_id,
                                           pod['pod_id'], project_id,
                                           resource_type)
