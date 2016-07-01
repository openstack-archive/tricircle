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

from neutron.extensions import external_net
import neutron.plugins.common.constants as p_constants

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.lock_handle as t_lock
from tricircle.common import utils


class NetworkHelper(object):
    def __init__(self, call_obj=None):
        self.clients = {}
        self.call_obj = call_obj

    @staticmethod
    def _transfer_network_type(network_type):
        network_type_map = {t_constants.NT_SHARED_VLAN: p_constants.TYPE_VLAN}
        return network_type_map.get(network_type, network_type)

    def _get_client(self, pod_name=None):
        if not pod_name:
            if t_constants.TOP not in self.clients:
                self.clients[t_constants.TOP] = t_client.Client()
            return self.clients[t_constants.TOP]
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
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

    def get_bottom_elements(self, t_ctx, project_id, pod,
                            t_net, t_subnet, t_port):
        """Get or create bottom network, subnet and port

        :param t_ctx: tricircle context
        :param project_id: project id
        :param pod: dict of bottom pod
        :param t_net: dict of top network
        :param t_subnet: dict of top subnet
        :param t_port: dict of top port
        :return: bottom port id
        """
        net_body = {
            'network': {
                'tenant_id': project_id,
                'name': utils.get_bottom_network_name(t_net),
                'admin_state_up': True
            }
        }
        _, net_id = self.prepare_bottom_element(
            t_ctx, project_id, pod, t_net, 'network', net_body)
        subnet_body = {
            'subnet': {
                'network_id': net_id,
                'name': t_subnet['id'],
                'ip_version': t_subnet['ip_version'],
                'cidr': t_subnet['cidr'],
                'gateway_ip': t_subnet['gateway_ip'],
                'allocation_pools': t_subnet['allocation_pools'],
                'enable_dhcp': t_subnet['enable_dhcp'],
                'tenant_id': project_id
            }
        }
        _, subnet_id = self.prepare_bottom_element(
            t_ctx, project_id, pod, t_subnet, 'subnet', subnet_body)
        port_body = {
            'port': {
                'network_id': net_id,
                'name': t_port['id'],
                'admin_state_up': True,
                'fixed_ips': [
                    {'subnet_id': subnet_id,
                     'ip_address': t_port['fixed_ips'][0]['ip_address']}],
                'mac_address': t_port['mac_address']
            }
        }
        _, port_id = self.prepare_bottom_element(
            t_ctx, project_id, pod, t_port, 'port', port_body)
        return port_id

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
        :return:
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
            net_body['network'][external_net.EXTERNAL] = True
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
