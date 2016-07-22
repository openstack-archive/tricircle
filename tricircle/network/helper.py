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

from neutron_lib import constants

from tricircle.common import client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.common.lock_handle as t_lock
from tricircle.common import utils
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models


# manually define these constants to avoid depending on neutron repos
EXTERNAL = 'router:external'  # neutron.extensions.external_net.EXTERNAL
TYPE_VLAN = 'vlan'  # neutron.plugins.common.constants.TYPE_VLAN


class NetworkHelper(object):
    def __init__(self, call_obj=None):
        self.clients = {}
        self.call_obj = call_obj

    @staticmethod
    def _transfer_network_type(network_type):
        network_type_map = {t_constants.NT_SHARED_VLAN: TYPE_VLAN}
        return network_type_map.get(network_type, network_type)

    def _get_client(self, pod_name=None):
        if not pod_name:
            if t_constants.TOP not in self.clients:
                self.clients[t_constants.TOP] = client.Client()
            return self.clients[t_constants.TOP]
        if pod_name not in self.clients:
            self.clients[pod_name] = client.Client(pod_name)
        return self.clients[pod_name]

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
                             t_net_id, b_router_id, b_port_id, is_ew):
        """Get or create top bridge interface

        :param t_ctx: tricircle context
        :param q_ctx: neutron context
        :param project_id: project id
        :param pod: dict of top pod
        :param t_net_id: top bridge network id
        :param b_router_id: bottom router id
        :param b_port_id: needed when creating bridge interface for south-
               north network, id of the internal port bound to floating ip
        :param is_ew: create the bridge interface for east-west network or
               south-north network
        :return: bridge interface id
        """
        if is_ew:
            port_name = t_constants.ew_bridge_port_name % (project_id,
                                                           b_router_id)
        else:
            port_name = t_constants.ns_bridge_port_name % (project_id,
                                                           b_router_id,
                                                           b_port_id)
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
            client = self._get_client(pod_['pod_name'])
            if _type_ == t_constants.RT_NETWORK:
                value = utils.get_bottom_network_name(ele_)
            else:
                value = ele_['id']
            return client.list_resources(_type_, t_ctx_,
                                         [{'key': 'name', 'comparator': 'eq',
                                           'value': value}])

        def create_resources(t_ctx_, q_ctx, pod_, body_, _type_):
            client = self._get_client(pod_['pod_name'])
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
        network_type = network.get('provider:network_type')
        if network_type == t_constants.NT_SHARED_VLAN:
            body['network']['provider:network_type'] = 'vlan'
            body['network']['provider:physical_network'] = network[
                'provider:physical_network']
            body['network']['provider:segmentation_id'] = network[
                'provider:segmentation_id']
        return body

    @staticmethod
    def get_create_subnet_body(project_id, t_subnet, b_net_id):
        """Get request body to create bottom subnet

        :param project_id: project id
        :param t_subnet: top subnet dict
        :param b_net_id: bottom network id
        :return: request body to create bottom subnet
        """
        body = {
            'subnet': {
                'network_id': b_net_id,
                'name': t_subnet['id'],
                'ip_version': t_subnet['ip_version'],
                'cidr': t_subnet['cidr'],
                'gateway_ip': t_subnet['gateway_ip'],
                'allocation_pools': t_subnet['allocation_pools'],
                'enable_dhcp': t_subnet['enable_dhcp'],
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
        :param security_group_ids: list of bottom security group id
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

    def prepare_bottom_network_subnets(self, t_ctx, project_id, pod,
                                       t_net, t_subnets):
        """Get or create bottom network, subnet and dhcp port

        :param t_ctx: tricircle context
        :param project_id: project id
        :param pod: dict of bottom pod
        :param t_net: dict of top network
        :param t_subnets: list of top subnet dict
        :return: bottom network id and a dict with top subnet id as key,
                 bottom subnet id as value
        """
        # network
        net_body = self.get_create_network_body(project_id, t_net)
        if net_body['network'].get('provider:network_type'):
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
        for subnet in t_subnets:
            subnet_body = self.get_create_subnet_body(
                project_id, subnet, b_net_id)
            _, b_subnet_id = self.prepare_bottom_element(
                t_ctx, project_id, pod, subnet, t_constants.RT_SUBNET,
                subnet_body)
            subnet_map[subnet['id']] = b_subnet_id

        # dhcp port
        for t_subnet_id, b_subnet_id in subnet_map.iteritems():
            self.prepare_dhcp_port(t_ctx, project_id, pod, t_net['id'],
                                   t_subnet_id, b_net_id, b_subnet_id)

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
            'provider:network_type': self._transfer_network_type(
                t_net['provider:network_type']),
            'provider:physical_network': t_net['provider:physical_network'],
            'provider:segmentation_id': t_net['provider:segmentation_id'],
            'admin_state_up': True}}
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
        # In the pod hosting external network, where ns bridge network is used
        # as an internal network, need to allocate ip address from .3 because
        # .2 is used by the router gateway port in the pod hosting servers,
        # where ns bridge network is used as an external network.
        # if t_subnet['name'].startswith('ns_bridge_') and not is_external:
        #     prefix = t_subnet['cidr'][:t_subnet['cidr'].rindex('.')]
        #     subnet_body['subnet']['allocation_pools'] = [
        #         {'start': prefix + '.3', 'end': prefix + '.254'}]
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
                'binding:profile': {},
                'device_id': 'reserved_dhcp_port',
                'device_owner': 'network:dhcp',
            }
        }
        return body

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
        t_client = self._get_client()
        b_client = self._get_client(b_pod['pod_name'])

        t_dhcp_name = t_constants.dhcp_port_name % t_subnet_id
        t_dhcp_port_body = {
            'port': {
                'tenant_id': project_id,
                'admin_state_up': True,
                'network_id': t_net_id,
                'name': t_dhcp_name,
                'binding:profile': {},
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
            ctx, None, project_id, db_api.get_top_pod(ctx),
            {'id': t_dhcp_name}, t_constants.RT_PORT, t_dhcp_port_body)
        t_dhcp_port = t_client.get_ports(ctx, t_dhcp_port_id)

        mappings = db_api.get_bottom_mappings_by_top_id(
            ctx, t_dhcp_port['id'], t_constants.RT_PORT)
        pod_list = [mapping[0]['pod_id'] for mapping in mappings]
        if b_pod['pod_id'] in pod_list:
            # mapping exists, skip this subnet
            return

        dhcp_port_filters = [
            {'key': 'device_owner', 'comparator': 'eq',
             'value': 'network:dhcp'},
            {'key': 'network_id', 'comparator': 'eq',
             'value': b_net_id},
        ]
        dhcp_port_body = self._get_create_dhcp_port_body(
            project_id, t_dhcp_port, b_subnet_id, b_net_id)
        t_dhcp_ip = t_dhcp_port['fixed_ips'][0]['ip_address']

        b_dhcp_port = None
        try:
            b_dhcp_port = b_client.create_ports(ctx, dhcp_port_body)
        except Exception:
            # examine if we conflicted with a dhcp port which was
            # automatically created by bottom pod
            b_dhcp_ports = b_client.list_ports(ctx,
                                               dhcp_port_filters)
            dhcp_port_match = False
            for dhcp_port in b_dhcp_ports:
                subnet_id = dhcp_port['fixed_ips'][0]['subnet_id']
                ip = dhcp_port['fixed_ips'][0]['ip_address']
                if b_subnet_id == subnet_id and t_dhcp_ip == ip:
                    with ctx.session.begin():
                        core.create_resource(
                            ctx, models.ResourceRouting,
                            {'top_id': t_dhcp_port['id'],
                             'bottom_id': dhcp_port['id'],
                             'pod_id': b_pod['pod_id'],
                             'project_id': project_id,
                             'resource_type': t_constants.RT_PORT})
                    dhcp_port_match = True
                    break
            if not dhcp_port_match:
                # so we didn't conflict with a dhcp port, raise exception
                raise

        if b_dhcp_port:
            with ctx.session.begin():
                core.create_resource(ctx, models.ResourceRouting,
                                     {'top_id': t_dhcp_port['id'],
                                      'bottom_id': b_dhcp_port['id'],
                                      'pod_id': b_pod['pod_id'],
                                      'project_id': project_id,
                                      'resource_type': t_constants.RT_PORT})
            # there is still one thing to do, there may be other dhcp ports
            # created by bottom pod, we need to delete them
            b_dhcp_ports = b_client.list_ports(ctx,
                                               dhcp_port_filters)
            remove_port_list = []
            for dhcp_port in b_dhcp_ports:
                subnet_id = dhcp_port['fixed_ips'][0]['subnet_id']
                ip = dhcp_port['fixed_ips'][0]['ip_address']
                if b_subnet_id == subnet_id and t_dhcp_ip != ip:
                    remove_port_list.append(dhcp_port['id'])
            for dhcp_port_id in remove_port_list:
                # NOTE(zhiyuan) dhcp agent will receive this port-delete
                # notification and re-configure dhcp so our newly created
                # dhcp port can be used
                b_client.delete_ports(ctx, dhcp_port_id)
