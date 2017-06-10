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


import copy
import mock
from mock import patch
import netaddr
import six
from six.moves import xrange
import unittest

from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_lib_exc
from neutron_lib.plugins import directory

import neutron.conf.common as q_config
from neutron.db import _utils
from neutron.db import db_base_plugin_common
from neutron.db import db_base_plugin_v2
from neutron.db import ipam_pluggable_backend
from neutron.db import l3_db
from neutron.db import models_v2
from neutron.db import rbac_db_models as rbac_db

from neutron.extensions import availability_zone as az_ext

from neutron.ipam import driver
from neutron.ipam import exceptions as ipam_exc
from neutron.ipam import requests
import neutron.ipam.utils as ipam_utils

from neutron import manager
import neutronclient.common.exceptions as q_exceptions

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from tricircle.common import client
from tricircle.common import constants
from tricircle.common import context
from tricircle.common import exceptions as t_exceptions
from tricircle.common.i18n import _
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
import tricircle.network.central_plugin as plugin
from tricircle.network.drivers import type_flat
from tricircle.network.drivers import type_local
from tricircle.network.drivers import type_vlan
from tricircle.network.drivers import type_vxlan
from tricircle.network import helper
from tricircle.network import managers
from tricircle.tests.unit.network import test_security_groups
import tricircle.tests.unit.utils as test_utils
from tricircle.xjob import xmanager

_resource_store = test_utils.get_resource_store()
TOP_NETS = _resource_store.TOP_NETWORKS
TOP_SUBNETS = _resource_store.TOP_SUBNETS
TOP_PORTS = _resource_store.TOP_PORTS
TOP_ROUTERS = _resource_store.TOP_ROUTERS
TOP_ROUTERPORTS = _resource_store.TOP_ROUTERPORTS
TOP_IPALLOCATIONS = _resource_store.TOP_IPALLOCATIONS
TOP_VLANALLOCATIONS = _resource_store.TOP_ML2_VLAN_ALLOCATIONS
TOP_VXLANALLOCATIONS = _resource_store.TOP_ML2_VXLAN_ALLOCATIONS
TOP_FLATALLOCATIONS = _resource_store.TOP_ML2_FLAT_ALLOCATIONS
TOP_SEGMENTS = _resource_store.TOP_NETWORKSEGMENTS
TOP_FLOATINGIPS = _resource_store.TOP_FLOATINGIPS
TOP_SGS = _resource_store.TOP_SECURITYGROUPS
TOP_SG_RULES = _resource_store.TOP_SECURITYGROUPRULES
BOTTOM1_NETS = _resource_store.BOTTOM1_NETWORKS
BOTTOM1_SUBNETS = _resource_store.BOTTOM1_SUBNETS
BOTTOM1_PORTS = _resource_store.BOTTOM1_PORTS
BOTTOM1_SGS = _resource_store.BOTTOM1_SECURITYGROUPS
BOTTOM1_FIPS = _resource_store.BOTTOM1_FLOATINGIPS
BOTTOM1_ROUTERS = _resource_store.BOTTOM1_ROUTERS
BOTTOM2_NETS = _resource_store.BOTTOM2_NETWORKS
BOTTOM2_SUBNETS = _resource_store.BOTTOM2_SUBNETS
BOTTOM2_PORTS = _resource_store.BOTTOM2_PORTS
BOTTOM2_SGS = _resource_store.BOTTOM2_SECURITYGROUPS
BOTTOM2_FIPS = _resource_store.BOTTOM2_FLOATINGIPS
BOTTOM2_ROUTERS = _resource_store.BOTTOM2_ROUTERS
TEST_TENANT_ID = test_utils.TEST_TENANT_ID
FakeNeutronContext = test_utils.FakeNeutronContext


def _fill_external_gateway_info(router):
    if router.gw_port:
        ext_gw_info = {
            'network_id': router.gw_port['network_id'],
            'external_fixed_ips': [
                {'subnet_id': ip["subnet_id"],
                 'ip_address': ip["ip_address"]}
                for ip in router.gw_port['fixed_ips']]}
    else:
        ext_gw_info = None
    router['external_gateway_info'] = ext_gw_info
    return router


def _transform_az(network):
    az_hints_key = 'availability_zone_hints'
    if az_hints_key in network:
        ret = test_utils.DotDict(network)
        az_str = network[az_hints_key]
        ret[az_hints_key] = jsonutils.loads(az_str) if az_str else []
        return ret
    return network


class FakeIpamSubnet(driver.Subnet):
    def __init__(self, subnet):
        self._subnet = subnet

    def allocate(self, address_request):
        pass

    def deallocate(self, address):
        pass

    def get_details(self):
        return requests.SpecificSubnetRequest(self._subnet['tenant_id'],
                                              self._subnet['id'],
                                              self._subnet['cidr'],
                                              self._subnet['gateway'],
                                              self._subnet['pools'])


class FakeNetworkRBAC(object):
    def __init__(self, **kwargs):
        self.__tablename__ = 'networkrbacs'
        self.project_id = kwargs['tenant_id']
        self.id = uuidutils.generate_uuid()
        self.target_tenant = kwargs['target_tenant']
        self.action = kwargs['action']
        network = kwargs['network']
        self.object_id = network['id']

    def _as_dict(self):
        return {'porject_id': self.project_id,
                'id': self.id,
                'target_tenant': self.target_tenant,
                'action': self.action,
                'object': self.object_id}


class FakePool(driver.Pool):
    def allocate_subnet(self, subnet_request):
        if isinstance(subnet_request, requests.SpecificSubnetRequest):
            subnet_info = {'id': subnet_request.subnet_id,
                           'tenant_id': subnet_request.tenant_id,
                           'cidr': subnet_request.subnet_cidr,
                           'gateway': subnet_request.gateway_ip,
                           'pools': subnet_request.allocation_pools}
            return FakeIpamSubnet(subnet_info)
        prefix = self._subnetpool.prefixes[0]
        subnet = next(prefix.subnet(subnet_request.prefixlen))
        gateway = subnet.network + 1
        pools = ipam_utils.generate_pools(subnet.cidr,
                                          gateway)
        subnet_info = {'id': subnet_request.subnet_id,
                       'tenant_id': subnet_request.tenant_id,
                       'cidr': subnet.cidr,
                       'gateway': gateway,
                       'pools': pools}
        return FakeIpamSubnet(subnet_info)

    def get_subnet(self, subnet_id):
        for subnet in TOP_SUBNETS:
            if subnet['id'] == subnet_id:
                return FakeIpamSubnet(subnet)
        raise q_lib_exc.SubnetNotFound(subnet_id=id)

    def get_allocator(self, subnet_ids):
        return driver.SubnetGroup()

    def update_subnet(self, subnet_request):
        pools = []
        for subnet in TOP_SUBNETS:
            if subnet['id'] == subnet_request.subnet_id:
                for request_pool in subnet_request.allocation_pools:
                    pool = {'start': str(request_pool._start),
                            'end': str(request_pool._end)}
                    pools.append(pool)
                subnet['allocation_pools'] = pools
                return FakeIpamSubnet(subnet_request)

        raise ipam_exc.InvalidSubnetRequest(
            reason=_("updated subnet id not found"))

    def remove_subnet(self, subnet_id):
        pass


class FakeNeutronClient(test_utils.FakeNeutronClient):
    _resource = 'port'
    ports_path = ''


class FakeClient(test_utils.FakeClient):
    def __init__(self, region_name=None):
        super(FakeClient, self).__init__(region_name)
        self.client = FakeNeutronClient(self.region_name)

    def get_native_client(self, resource, ctx):
        return self.client

    def _get_connection(self):
        # only for mock purpose
        pass

    def _allocate_ip(self, port_body):
        subnet_list = self._res_map[self.region_name]['subnet']
        for subnet in subnet_list:
            if subnet['network_id'] == port_body['port']['network_id']:
                cidr = subnet['cidr']
                ip = cidr[:cidr.rindex('.')] + '.5'
                return {'subnet_id': subnet['id'],
                        'ip_address': ip}

    def create_resources(self, _type, ctx, body):
        self._get_connection()
        if _type == 'port':
            res_list = self._res_map[self.region_name][_type]
            subnet_ips_map = {}
            for res in res_list:
                fixed_ips = res.get('fixed_ips', [])
                for fixed_ip in fixed_ips:
                    if fixed_ip['subnet_id'] not in subnet_ips_map:
                        subnet_ips_map[fixed_ip['subnet_id']] = set()
                    subnet_ips_map[fixed_ip['subnet_id']].add(
                        fixed_ip['ip_address'])
            fixed_ips = body[_type].get('fixed_ips', [])
            for fixed_ip in fixed_ips:
                for subnet in self._res_map[self.region_name]['subnet']:
                    ip_range = netaddr.IPNetwork(subnet['cidr'])
                    ip = netaddr.IPAddress(fixed_ip['ip_address'])
                    if ip in ip_range:
                        fixed_ip['subnet_id'] = subnet['id']
                        break
                if 'subnet_id' not in fixed_ip:
                    # we still cannot find the proper subnet, that's because
                    # this is a copy port. local plugin will create the missing
                    # subnet for this port but FakeClient won't. we just skip
                    # the ip address check
                    continue
                if fixed_ip['ip_address'] in subnet_ips_map.get(
                        fixed_ip['subnet_id'], set()):
                    raise q_exceptions.IpAddressInUseClient()
            if 'device_id' not in body[_type]:
                body[_type]['device_id'] = ''
            if 'fixed_ips' not in body[_type]:
                body[_type]['fixed_ips'] = [self._allocate_ip(body)]
        if _type == 'subnet':
            if 'gateway_ip' not in body[_type]:
                cidr = body[_type]['cidr']
                body[_type]['gateway_ip'] = cidr[:cidr.rindex('.')] + '.1'
        if 'id' not in body[_type]:
            body[_type]['id'] = uuidutils.generate_uuid()
        return super(FakeClient, self).create_resources(_type, ctx, body)

    def list_networks(self, ctx, filters=None):
        networks = self.list_resources('network', ctx, filters)
        if self.region_name != 'top':
            return networks
        ret_list = []
        for network in networks:
            ret_list.append(_transform_az(network))
        return ret_list

    def get_networks(self, ctx, net_id):
        return self.get_resource(constants.RT_NETWORK, ctx, net_id)

    def delete_networks(self, ctx, net_id):
        self.delete_resources('network', ctx, net_id)

    def update_networks(self, ctx, net_id, network):
        self.update_resources('network', ctx, net_id, network)

    def list_subnets(self, ctx, filters=None):
        return self.list_resources('subnet', ctx, filters)

    def get_subnets(self, ctx, subnet_id):
        return self.get_resource(constants.RT_SUBNET, ctx, subnet_id)

    def delete_subnets(self, ctx, subnet_id):
        self.delete_resources('subnet', ctx, subnet_id)

    def update_ports(self, ctx, port_id, body):
        self.update_resources('port', ctx, port_id, body)

    def update_subnets(self, ctx, subnet_id, body):
        updated = self.update_resources('subnet', ctx, subnet_id, body)
        if not updated:
            raise ipam_exc.InvalidSubnetRequest(
                reason=_("updated subnet id not found"))

    def create_ports(self, ctx, body):
        if 'ports' in body:
            ret = []
            for port in body['ports']:
                ret.append(self.create_resources('port', ctx, {'port': port}))
            return ret
        return self.create_resources('port', ctx, body)

    def list_ports(self, ctx, filters=None):
        filter_dict = {}
        filters = filters or []
        for query_filter in filters:
            key = query_filter['key']
            # when querying ports, "fields" is passed in the query string to
            # ask the server to only return necessary fields, which can reduce
            # the data being transfered. in test, we just return all the fields
            # since there's no need to optimize
            if key != 'fields':
                value = query_filter['value']
                filter_dict[key] = value
        return self.client.get('', filter_dict)['ports']

    def get_ports(self, ctx, port_id):
        return self.client.get(
            '', params={'id': [port_id]})['ports'][0]

    def delete_ports(self, ctx, port_id):
        self.delete_resources('port', ctx, port_id)
        index = -1
        for i, allocation in enumerate(TOP_IPALLOCATIONS):
            if allocation['port_id'] == port_id:
                index = i
                break
        if index != -1:
            del TOP_IPALLOCATIONS[index]

    def add_gateway_routers(self, ctx, *args, **kwargs):
        router_id, body = args
        try:
            t_name = constants.bridge_port_name % (TEST_TENANT_ID, router_id)
            t_client = FakeClient()
            t_ports = t_client.list_ports(
                ctx, [{'key': 'name', 'comparator': 'eq', 'value': t_name}])
            b_id = t_ports[0]['id'] if t_ports else uuidutils.generate_uuid()
            host_id = 'host1' if self.region_name == 'pod_1' else 'host_2'
            self.create_ports(ctx, {'port': {
                'admin_state_up': True,
                'id': b_id,
                'name': '',
                'network_id': body['network_id'],
                'fixed_ips': body['external_fixed_ips'],
                'mac_address': '',
                'device_id': router_id,
                'device_owner': 'network:router_gateway',
                'binding:vif_type': portbindings.VIF_TYPE_OVS,
                'binding:host_id': host_id
            }})
        except q_exceptions.IpAddressInUseClient:
            # just skip if the gateway port is already there
            pass

    def add_interface_routers(self, ctx, *args, **kwargs):
        self._get_connection()

        router_id, body = args
        if 'port_id' in body:
            for port in self._res_map[self.region_name]['port']:
                if port['id'] == body['port_id']:
                    port['device_id'] = router_id
                    port['device_owner'] = 'network:router_interface'
        else:
            subnet_id = body['subnet_id']
            subnet = self.get_subnets(ctx, subnet_id)
            self.create_ports(ctx, {'port': {
                'tenant_id': subnet['tenant_id'],
                'admin_state_up': True,
                'id': uuidutils.generate_uuid(),
                'name': '',
                'network_id': subnet['network_id'],
                'fixed_ips': [
                    {'subnet_id': subnet_id,
                     'ip_address': subnet['gateway_ip']}
                ],
                'mac_address': '',
                'device_id': router_id,
                'device_owner': 'network:router_interface'
            }})

    def remove_interface_routers(self, ctx, *args, **kwargs):
        # only for mock purpose
        pass

    def get_routers(self, ctx, router_id):
        router = self.get_resource(constants.RT_ROUTER, ctx, router_id)
        return _fill_external_gateway_info(router)

    def delete_routers(self, ctx, router_id):
        self.delete_resources('router', ctx, router_id)

    def action_routers(self, ctx, action, *args, **kwargs):
        # divide into three functions for test purpose
        if action == 'add_interface':
            return self.add_interface_routers(ctx, *args, **kwargs)
        elif action == 'add_gateway':
            return self.add_gateway_routers(ctx, *args, **kwargs)
        elif action == 'remove_interface':
            return self.remove_interface_routers(ctx, *args, **kwargs)

    def _is_bridge_network_attached():
        pass

    def create_floatingips(self, ctx, body):
        fip = self.create_resources('floatingip', ctx, body)
        for key in ['fixed_port_id']:
            if key not in fip:
                fip[key] = None
        return fip

    def list_floatingips(self, ctx, filters=None):
        fips = self.list_resources('floatingip', ctx, filters)
        for fip in fips:
            if 'port_id' not in fip:
                fip['port_id'] = None
        return fips

    def update_floatingips(self, ctx, _id, body):
        pass

    def delete_floatingips(self, ctx, _id):
        self.delete_resources('floatingip', ctx, _id)

    def create_security_group_rules(self, ctx, body):
        sg_id = body['security_group_rule']['security_group_id']
        res_list = self._res_map[self.region_name]['security_group']
        for sg in res_list:
            if sg['id'] == sg_id:
                target_sg = sg
        new_rule = copy.copy(body['security_group_rule'])
        match_found = False
        for rule in target_sg['security_group_rules']:
            old_rule = copy.copy(rule)
            if new_rule == old_rule:
                match_found = True
                break
        if match_found:
            raise q_exceptions.Conflict()
        target_sg['security_group_rules'].append(body['security_group_rule'])

    def delete_security_group_rules(self, ctx, rule_id):
        res_list = self._res_map[self.region_name]['security_group']
        for sg in res_list:
            for rule in sg['security_group_rules']:
                if rule['id'] == rule_id:
                    sg['security_group_rules'].remove(rule)
                    return

    def get_security_groups(self, ctx, sg_id):
        sg = self.get_resource(constants.RT_SG, ctx, sg_id)
        # need to do a deep copy because we will traverse the security
        # group's 'security_group_rules' field and make change to the
        # group
        return copy.deepcopy(sg)

    def get_security_group(self, context, _id, fields=None, tenant_id=None):
        pass


def update_floatingip(self, context, _id, floatingip):
    for fip in TOP_FLOATINGIPS:
        if fip['id'] != _id:
            continue
        update_dict = floatingip['floatingip']
        if not floatingip['floatingip']['port_id']:
            update_dict['fixed_port_id'] = None
            update_dict['fixed_ip_address'] = None
            update_dict['router_id'] = None
            fip.update(update_dict)
            return
        for port in TOP_PORTS:
            if port['id'] != floatingip['floatingip']['port_id']:
                continue
            update_dict['fixed_port_id'] = port['id']
            update_dict[
                'fixed_ip_address'] = port['fixed_ips'][0]['ip_address']
            for router_port in TOP_ROUTERPORTS:
                for _port in TOP_PORTS:
                    if _port['id'] != router_port['port_id']:
                        continue
                    if _port['network_id'] == port['network_id']:
                        update_dict['router_id'] = router_port['router_id']

        fip.update(update_dict)


class FakeBaseXManager(xmanager.XManager):
    def __init__(self, fake_plugin):
        self.clients = {constants.TOP: client.Client()}
        self.job_handles = {
            constants.JT_CONFIGURE_ROUTE: self.configure_route,
            constants.JT_ROUTER_SETUP: self.setup_bottom_router,
            constants.JT_PORT_DELETE: self.delete_server_port}
        self.helper = FakeHelper(fake_plugin)

    def _get_client(self, region_name=None):
        return FakeClient(region_name)

    def setup_bottom_router(self, ctx, payload):
        (b_pod_id,
         t_router_id, t_net_id) = payload[constants.JT_ROUTER_SETUP].split('#')

        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_net_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                resource_id = '%s#%s#%s' % (b_pod['pod_id'],
                                            t_router_id, t_net_id)
                _payload = {constants.JT_ROUTER_SETUP: resource_id}
                super(FakeBaseXManager,
                      self).setup_bottom_router(ctx, _payload)
        else:
            super(FakeBaseXManager, self).setup_bottom_router(ctx, payload)


class FakeXManager(FakeBaseXManager):
    def __init__(self, fake_plugin):
        super(FakeXManager, self).__init__(fake_plugin)
        self.xjob_handler = FakeBaseRPCAPI(fake_plugin)


class FakeBaseRPCAPI(object):
    def __init__(self, fake_plugin):
        self.xmanager = FakeBaseXManager(fake_plugin)

    def configure_route(self, ctxt, project_id, router_id):
        pass

    def update_network(self, ctxt, project_id, network_id, pod_id):
        combine_id = '%s#%s' % (pod_id, network_id)
        self.xmanager.update_network(
            ctxt, payload={constants.JT_NETWORK_UPDATE: combine_id})

    def update_subnet(self, ctxt, project_id, subnet_id, pod_id):
        combine_id = '%s#%s' % (pod_id, subnet_id)
        self.xmanager.update_subnet(
            ctxt, payload={constants.JT_SUBNET_UPDATE: combine_id})

    def configure_security_group_rules(self, ctxt, project_id):
        pass

    def setup_shadow_ports(self, ctxt, project_id, pod_id, net_id):
        pass


class FakeRPCAPI(FakeBaseRPCAPI):
    def __init__(self, fake_plugin):
        self.xmanager = FakeXManager(fake_plugin)

    def setup_bottom_router(self, ctxt, project_id, net_id, router_id, pod_id):
        combine_id = '%s#%s#%s' % (pod_id, router_id, net_id)
        self.xmanager.setup_bottom_router(
            ctxt, payload={constants.JT_ROUTER_SETUP: combine_id})

    def delete_server_port(self, ctxt, project_id, port_id, pod_id):
        pass

    def configure_security_group_rules(self, ctxt, project_id):
        pass

    def setup_shadow_ports(self, ctxt, project_id, pod_id, net_id):
        combine_id = '%s#%s' % (pod_id, net_id)
        self.xmanager.setup_shadow_ports(
            ctxt, payload={constants.JT_SHADOW_PORT_SETUP: combine_id})


class FakeExtension(object):
    def __init__(self, ext_obj):
        self.obj = ext_obj


class FakeHelper(helper.NetworkHelper):
    def _get_client(self, region_name=None):
        return FakeClient(region_name)

    def _prepare_top_element_by_call(self, t_ctx, q_ctx,
                                     project_id, pod, ele, _type, body):
        if not q_ctx:
            q_ctx = FakeNeutronContext()
        return super(FakeHelper, self)._prepare_top_element_by_call(
            t_ctx, q_ctx, project_id, pod, ele, _type, body)

    def _get_top_element(self, t_ctx, q_ctx, _type, _id):
        if not q_ctx:
            q_ctx = FakeNeutronContext()
        return super(FakeHelper, self)._get_top_element(
            t_ctx, q_ctx, _type, _id)


class FakeTypeManager(managers.TricircleTypeManager):
    def _register_types(self):
        local_driver = type_local.LocalTypeDriver()
        self.drivers[constants.NT_LOCAL] = FakeExtension(local_driver)
        vlan_driver = type_vlan.VLANTypeDriver()
        self.drivers[constants.NT_VLAN] = FakeExtension(vlan_driver)
        vxlan_driver = type_vxlan.VxLANTypeDriver()
        self.drivers[constants.NT_VxLAN] = FakeExtension(vxlan_driver)
        local_driver = type_flat.FlatTypeDriver()
        self.drivers[constants.NT_FLAT] = FakeExtension(local_driver)

    def extend_network_dict_provider(self, cxt, net):
        target_net = None
        for t_net in TOP_NETS:
            if t_net['id'] == net['id']:
                target_net = t_net
        if not target_net:
            return
        for segment in TOP_SEGMENTS:
            if target_net['id'] == segment['network_id']:
                target_net['provider:network_type'] = segment['network_type']
                target_net[
                    'provider:physical_network'] = segment['physical_network']
                target_net[
                    'provider:segmentation_id'] = segment['segmentation_id']
                break


class FakePlugin(plugin.TricirclePlugin):
    def __init__(self):
        self.set_ipam_backend()
        self.helper = FakeHelper(self)
        self.xjob_handler = FakeRPCAPI(self)
        self.type_manager = FakeTypeManager()

    def _get_client(self, region_name):
        return FakeClient(region_name)

    def create_network(self, context, network):
        # neutron has been updated to use the new enginefacade, we no longer
        # call update_network in TricirclePlugin.create_network to update AZ
        # info. new context manager will update AZ info after context exits,
        # but since we don't simulate such process, we override this method to
        # insert AZ info
        net = super(FakePlugin, self).create_network(context, network)
        if 'availability_zone_hints' not in network['network']:
            return net
        for _net in TOP_NETS:
            if _net['id'] == net['id']:
                _net['availability_zone_hints'] = jsonutils.dumps(
                    network['network']['availability_zone_hints'])
        return net

    def _make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
        network = _transform_az(network)
        if 'project_id' in network:
            network['tenant_id'] = network['project_id']
        return network

    def _make_subnet_dict(self, subnet, fields=None, context=None):
        return subnet

    def _make_port_dict(self, ori_port, fields=None, process_extensions=True):
        if not isinstance(ori_port, dict):
            port = ori_port._as_dict()
            port['fixed_ips'] = ori_port.get('fixed_ips')
        else:
            port = ori_port
        if 'project_id' in port:
            port['tenant_id'] = port['project_id']
        if port.get('fixed_ips'):
            if isinstance(port['fixed_ips'][0], dict):
                return port
            else:
                for i, fixed_ip in enumerate(port['fixed_ips']):
                    port['fixed_ips'][i] = {
                        'subnet_id': fixed_ip['subnet_id'],
                        'ip_address': fixed_ip['ip_address']}
                return port
        # if fixed_ips is empty, we try first to load it from ip allocation
        for allocation in TOP_IPALLOCATIONS:
            if allocation['port_id'] == port['id']:
                ret = {}
                for key, value in six.iteritems(port):
                    if key == 'fixed_ips':
                        ret[key] = [{'subnet_id': allocation['subnet_id'],
                                     'ip_address': allocation['ip_address']}]
                    else:
                        ret[key] = value
                if 'project_id' in ret:
                    ret['tenant_id'] = ret['project_id']
                return ret
        return port

    def _make_security_group_dict(self, security_group, fields=None):
        return security_group


def fake_get_context_from_neutron_context(q_context):
    return context.get_db_context()


def fake_get_client(self, region_name):
    return FakeClient(region_name)


def fake_make_network_dict(self, network, fields=None,
                           process_extensions=True, context=None):
    return network


def fake_make_subnet_dict(self, subnet, fields=None, context=None):
    return subnet


def fake_make_router_dict(self, router, fields=None, process_extensions=True):
    return _fill_external_gateway_info(router)


def fake_generate_ip(subnet):
    suffix = 1
    for allocation in TOP_IPALLOCATIONS:
        if allocation['subnet_id'] == subnet['id']:
            ip = allocation['ip_address']
            current_suffix = int(ip[ip.rindex('.') + 1:])
            if current_suffix >= suffix:
                suffix = current_suffix
    suffix += 1
    cidr = subnet['cidr']
    new_ip = cidr[:cidr.rindex('.') + 1] + ('%d' % suffix)
    return {'ip_address': new_ip, 'subnet_id': subnet['id']}


def fake_allocate_ips_for_port(self, context, port):
    if 'fixed_ips' in port['port'] and (
            port['port'][
                'fixed_ips'] is not q_constants.ATTR_NOT_SPECIFIED):
        return port['port']['fixed_ips']
    for subnet in TOP_SUBNETS:
        if subnet['network_id'] == port['port']['network_id']:
            allocation = fake_generate_ip(subnet)
            # save allocation so we can retrieve it in make_port_dict
            TOP_IPALLOCATIONS.append(models_v2.IPAllocation(
                network_id=subnet['network_id'],
                port_id=port['port']['id'],
                ip_address=allocation['ip_address'],
                subnet_id=allocation['subnet_id']))
            return [allocation]


def fake_update_ips_for_port(self, context, port, host,
                             original_ips, new_ips, mac):
    # NOTE: remove this mock after we support ip updating
    return ipam_pluggable_backend.IpamPluggableBackend.Changes(
        add=[], original=[], remove=[])


@classmethod
def fake_get_instance(cls, subnet_pool, context):
    return FakePool(subnet_pool, context)


def fake_get_plugin(alias=q_constants.CORE):
    return FakePlugin()


def fake_filter_non_model_columns(data, model):
    return data


class FakeTrunkPlugin(object):

    def get_trunk_subports(self, context, filters):
        return None


class PluginTest(unittest.TestCase,
                 test_security_groups.TricircleSecurityGroupTestMixin):
    def setUp(self):
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())
        cfg.CONF.register_opts(q_config.core_opts)
        cfg.CONF.register_opts(plugin.tricircle_opts)
        plugin_path = \
            'tricircle.tests.unit.network.test_central_plugin.FakePlugin'
        cfg.CONF.set_override('core_plugin', plugin_path)
        cfg.CONF.set_override('enable_api_gateway', True)
        self.context = context.Context()
        self.save_method = manager.NeutronManager._get_default_service_plugins
        manager.NeutronManager._get_default_service_plugins = mock.Mock()
        manager.NeutronManager._get_default_service_plugins.return_value = []
        xmanager.IN_TEST = True

        phynet = 'bridge'
        vlan_min, vlan_max = 2000, 2001
        vxlan_min, vxlan_max = 20001, 20002
        cfg.CONF.set_override('type_drivers', ['local', 'vlan'],
                              group='tricircle')
        cfg.CONF.set_override('tenant_network_types', ['local', 'vlan'],
                              group='tricircle')
        cfg.CONF.set_override('network_vlan_ranges',
                              ['%s:%d:%d' % (phynet, vlan_min, vlan_max)],
                              group='tricircle')
        cfg.CONF.set_override('bridge_network_type', 'vlan',
                              group='tricircle')
        cfg.CONF.set_override('default_region_for_external_network',
                              'pod_1', group='tricircle')
        for vlan in (vlan_min, vlan_max):
            TOP_VLANALLOCATIONS.append(
                test_utils.DotDict({'physical_network': phynet,
                                    'vlan_id': vlan, 'allocated': False}))
        for vxlan in (vxlan_min, vxlan_max):
            TOP_VXLANALLOCATIONS.append(
                test_utils.DotDict({'vxlan_vni': vxlan, 'allocated': False}))

        def fake_get_plugin(alias=q_constants.CORE):
            if alias == 'trunk':
                return FakeTrunkPlugin()
            return FakePlugin()
        from neutron_lib.plugins import directory
        directory.get_plugin = fake_get_plugin

    def _basic_pod_route_setup(self):
        pod1 = {'pod_id': 'pod_id_1',
                'region_name': 'pod_1',
                'az_name': 'az_name_1'}
        pod2 = {'pod_id': 'pod_id_2',
                'region_name': 'pod_2',
                'az_name': 'az_name_2'}
        pod3 = {'pod_id': 'pod_id_0',
                'region_name': 'top_pod',
                'az_name': ''}
        for pod in (pod1, pod2, pod3):
            db_api.create_pod(self.context, pod)
        route1 = {
            'top_id': 'top_id_1',
            'pod_id': 'pod_id_1',
            'bottom_id': 'bottom_id_1',
            'resource_type': 'port'}
        route2 = {
            'top_id': 'top_id_2',
            'pod_id': 'pod_id_2',
            'bottom_id': 'bottom_id_2',
            'resource_type': 'port'}
        with self.context.session.begin():
            core.create_resource(self.context, models.ResourceRouting, route1)
            core.create_resource(self.context, models.ResourceRouting, route2)

    def _basic_port_setup(self):
        TOP_PORTS.extend([{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [models_v2.IPAllocation(
                               port_id='top_id_0', ip_address='10.0.0.1',
                               subnet_id='top_subnet_id',
                               network_id='top_net_id')]},
                          {'id': 'top_id_1', 'name': 'top',
                           'tenant_id': 'project_id'},
                          {'id': 'top_id_2', 'name': 'top'},
                          {'id': 'top_id_3', 'name': 'top'}])
        BOTTOM1_PORTS.append({'id': 'bottom_id_1', 'name': 'bottom'})
        BOTTOM2_PORTS.append({'id': 'bottom_id_2', 'name': 'bottom'})

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port')
    def test_get_port(self, mock_plugin_method):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        fake_plugin.get_port(neutron_context, 'top_id_0')
        port1 = fake_plugin.get_port(neutron_context, 'top_id_1')
        port2 = fake_plugin.get_port(neutron_context, 'top_id_2')
        fake_plugin.get_port(neutron_context, 'top_id_3')

        self.assertEqual({'id': 'top_id_1', 'name': 'bottom'}, port1)
        self.assertEqual({'id': 'top_id_2', 'name': 'bottom'}, port2)
        calls = [mock.call(neutron_context, 'top_id_0', None),
                 mock.call(neutron_context, 'top_id_3', None)]
        mock_plugin_method.assert_has_calls(calls)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_pagination(self):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context, limit=1)
        ports2 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports1[-1]['id'])
        ports3 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports2[-1]['id'])
        ports4 = fake_plugin.get_ports(neutron_context, limit=1,
                                       marker=ports3[-1]['id'])
        ports = []
        expected_ports = [{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [{'subnet_id': 'top_subnet_id',
                                          'ip_address': '10.0.0.1'}]},
                          {'id': 'top_id_1', 'name': 'bottom'},
                          {'id': 'top_id_2', 'name': 'bottom'},
                          {'id': 'top_id_3', 'name': 'top'}]
        for _ports in (ports1, ports2, ports3, ports4):
            ports.extend(_ports)
        six.assertCountEqual(self, expected_ports, ports)

        ports = fake_plugin.get_ports(neutron_context)
        six.assertCountEqual(self, expected_ports, ports)

    @patch.object(context, 'get_context_from_neutron_context',
                  new=fake_get_context_from_neutron_context)
    @patch.object(plugin.TricirclePlugin, '_get_client',
                  new=fake_get_client)
    def test_get_ports_filters(self):
        self._basic_pod_route_setup()
        self._basic_port_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        ports1 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_0']})
        ports2 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_1']})
        ports3 = fake_plugin.get_ports(neutron_context,
                                       filters={'id': ['top_id_4']})
        self.assertEqual([{'id': 'top_id_0', 'name': 'top',
                           'fixed_ips': [{'subnet_id': 'top_subnet_id',
                                          'ip_address': '10.0.0.1'}]}], ports1)
        self.assertEqual([{'id': 'top_id_1', 'name': 'bottom'}], ports2)
        self.assertEqual([], ports3)

        TOP_ROUTERS.append({'id': 'router_id'})
        b_routers_list = [BOTTOM1_ROUTERS, BOTTOM2_ROUTERS]
        b_ports_list = [BOTTOM1_PORTS, BOTTOM2_PORTS]
        for i in xrange(1, 3):
            router_id = 'router_%d_id' % i
            b_routers_list[i - 1].append({'id': router_id})
            route = {
                'top_id': 'router_id',
                'pod_id': 'pod_id_%d' % i,
                'bottom_id': router_id,
                'resource_type': 'router'}
            with self.context.session.begin():
                core.create_resource(self.context,
                                     models.ResourceRouting, route)
            # find port and add device_id
            for port in b_ports_list[i - 1]:
                port_id = 'bottom_id_%d' % i
                if port['id'] == port_id:
                    port['device_id'] = router_id
        ports = fake_plugin.get_ports(neutron_context,
                                      filters={'device_id': ['router_id']})
        expected = [{'id': 'top_id_1', 'name': 'bottom',
                     'device_id': 'router_id'},
                    {'id': 'top_id_2', 'name': 'bottom',
                     'device_id': 'router_id'}]
        six.assertCountEqual(self, expected, ports)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'delete_port')
    @patch.object(FakeRPCAPI, 'delete_server_port')
    def test_delete_port(self, mock_client_method, mock_plugin_method,
                         mock_context_method):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context_method.return_value = tricircle_context
        project_id = 'project_id'

        (t_net_id, t_subnet_id,
         b_net_id, b_subnet_id) = self._prepare_network_subnet(
            project_id, tricircle_context, 'pod_1', 1)
        t_port_id1, _ = self._prepare_port_test(
            project_id, tricircle_context, 'pod_1', 1, t_net_id, b_net_id,
            t_subnet_id, b_subnet_id)
        t_port_id2, _ = self._prepare_port_test(
            project_id, tricircle_context, 'pod_1', 2, t_net_id, b_net_id,
            t_subnet_id, b_subnet_id)

        fake_plugin.delete_port(neutron_context, t_port_id1)
        fake_plugin.delete_port(neutron_context, t_port_id2)

        plugin_calls = [mock.call(neutron_context, t_port_id1),
                        mock.call(neutron_context, t_port_id2)]
        client_calls = [
            mock.call(tricircle_context, project_id, t_port_id1, 'pod_id_1'),
            mock.call(tricircle_context, project_id, t_port_id2, 'pod_id_1')]
        mock_plugin_method.assert_has_calls(plugin_calls)
        mock_client_method.assert_has_calls(client_calls)

    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'create_network')
    def test_network_az_region(self, mock_create, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        net_id = uuidutils.generate_uuid()
        network = {'network': {
            'id': net_id, 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': ['az_name_1', 'pod_2']}}
        mock_create.return_value = {'id': net_id, 'name': 'net_az'}
        ret_net = fake_plugin.create_network(neutron_context, network)
        self.assertEqual(['az_name_1', 'pod_2'],
                         ret_net['availability_zone_hints'])

        net_id = uuidutils.generate_uuid()
        err_network = {'network': {
            'id': 'net_id', 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'availability_zone_hints': ['az_name_1', 'az_name_3']}}
        mock_create.return_value = {'id': net_id, 'name': 'net_az'}
        self.assertRaises(az_ext.AvailabilityZoneNotFound,
                          fake_plugin.create_network,
                          neutron_context, err_network)

        net_id = uuidutils.generate_uuid()
        err_network = {'network': {
            'id': net_id, 'name': 'net_az', 'tenant_id': TEST_TENANT_ID,
            'availability_zone_hints': ['pod_1', 'pod_3']}}
        mock_create.return_value = {'id': net_id, 'name': 'net_az'}
        self.assertRaises(az_ext.AvailabilityZoneNotFound,
                          fake_plugin.create_network,
                          neutron_context, err_network)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        tricircle_context = context.get_db_context()
        mock_context.return_value = tricircle_context

        network = {'network': {
            'id': uuidutils.generate_uuid(), 'name': 'net_az',
            'tenant_id': TEST_TENANT_ID,
            'admin_state_up': True, 'shared': False,
            'availability_zone_hints': ['az_name_1', 'az_name_2']}}
        fake_plugin.create_network(neutron_context, network)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(rbac_db, 'NetworkRBAC', new=FakeNetworkRBAC)
    def test_convert_az2region_for_nets(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx

        az_hints = []
        region_names = []
        t_net_id, _, _, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1, az_hints=az_hints)
        net_filter = {'id': [t_net_id]}
        top_net = fake_plugin.get_networks(neutron_context, net_filter)
        six.assertCountEqual(self, top_net[0]['availability_zone_hints'],
                             region_names)

        az_hints = '["az_name_1", "az_name_2"]'
        region_names = ['pod_1', 'pod_2']
        t_net_id, _, _, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 2, az_hints=az_hints)
        net_filter = {'id': [t_net_id]}
        top_net = fake_plugin.get_networks(neutron_context, net_filter)
        six.assertCountEqual(self, top_net[0]['availability_zone_hints'],
                             region_names)

        az_hints = '["pod_1", "pod_2"]'
        region_names = ['pod_1', 'pod_2']
        t_net_id, _, _, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 3, az_hints=az_hints)
        net_filter = {'id': [t_net_id]}
        top_net = fake_plugin.get_networks(neutron_context, net_filter)
        six.assertCountEqual(self, top_net[0]['availability_zone_hints'],
                             region_names)

        az_hints = '["pod_1", "az_name_2"]'
        region_names = ['pod_1', 'pod_2']
        t_net_id, _, _, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 4, az_hints=az_hints)
        net_filter = {'id': [t_net_id]}
        top_net = fake_plugin.get_networks(neutron_context, net_filter)
        six.assertCountEqual(self, top_net[0]['availability_zone_hints'],
                             region_names)

        pod4 = {'pod_id': 'pod_id_4',
                'region_name': 'pod_4',
                'az_name': 'az_name_1'}
        db_api.create_pod(self.context, pod4)
        az_hints = '["pod_1", "az_name_1"]'
        region_names = ['pod_1', 'pod_4']
        t_net_id, _, _, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 5, az_hints=az_hints)
        net_filter = {'id': [t_net_id]}
        top_net = fake_plugin.get_networks(neutron_context, net_filter)
        six.assertCountEqual(self, top_net[0]['availability_zone_hints'],
                             region_names)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(rbac_db, 'NetworkRBAC', new=FakeNetworkRBAC)
    def test_update_network(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        t_net_id, _, b_net_id, _ = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1)
        fake_plugin = FakePlugin()
        fake_client = FakeClient('pod_1')
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx

        update_body = {
            'network': {
                'name': 'new_name',
                'description': 'new_description',
                'admin_state_up': True,
                'shared': True}
        }
        fake_plugin.update_network(neutron_context, t_net_id, update_body)

        top_net = fake_plugin.get_network(neutron_context, t_net_id)
        self.assertEqual(top_net['name'], update_body['network']['name'])
        self.assertEqual(top_net['description'],
                         update_body['network']['description'])
        self.assertEqual(top_net['admin_state_up'],
                         update_body['network']['admin_state_up'])
        self.assertEqual(top_net['shared'], True)

        bottom_net = fake_client.get_networks(t_ctx, b_net_id)
        # name is set to top resource id, which is used by lock_handle to
        # retrieve bottom/local resources that have been created but not
        # registered in the resource routing table, so it's not allowed to
        # be updated
        self.assertEqual(bottom_net['name'], t_net_id)
        self.assertEqual(bottom_net['description'],
                         update_body['network']['description'])
        self.assertEqual(bottom_net['admin_state_up'],
                         update_body['network']['admin_state_up'])
        self.assertEqual(bottom_net['shared'], True)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(rbac_db, 'NetworkRBAC', new=FakeNetworkRBAC)
    def test_update_network_external_attr(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        t_net_id, _, _, _ = self._prepare_network_subnet(tenant_id, t_ctx,
                                                         'pod_1', 1)
        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx

        update_body = {
            'network': {
                'router:external': True
            }
        }
        self.assertRaises(q_lib_exc.InvalidInput, fake_plugin.update_network,
                          neutron_context, t_net_id, update_body)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    @patch.object(rbac_db, 'NetworkRBAC', new=FakeNetworkRBAC)
    def test_update_network_provider_attrs(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        t_net_id, _, _, _ = self._prepare_network_subnet(tenant_id, t_ctx,
                                                         'pod_1', 1)
        fake_plugin = FakePlugin()
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx

        provider_attrs = {'provider:network_type': 'vlan',
                          'provider:physical_network': 'br-vlan',
                          'provider:segmentation_id': 1234}

        for key, value in provider_attrs.items():
            update_body = {
                'network': {
                    key: value
                }
            }
            self.assertRaises(q_lib_exc.InvalidInput,
                              fake_plugin.update_network,
                              neutron_context, t_net_id, update_body)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_prepare_element(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        for pod in db_api.list_pods(t_ctx):
            if not pod['az_name']:
                t_pod = pod
            else:
                b_pod = pod

        # test _prepare_top_element
        pool_id = fake_plugin._get_bridge_subnet_pool_id(
            t_ctx, q_ctx, 'project_id', t_pod)
        net, subnet = fake_plugin._get_bridge_network_subnet(
            t_ctx, q_ctx, 'project_id', t_pod, pool_id)
        port = fake_plugin._get_bridge_interface(t_ctx, q_ctx, 'project_id',
                                                 pod, net['id'], 'b_router_id')

        top_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': 'pod_id_0'}], []):
                top_entry_map[entry['resource_type']] = entry
        self.assertEqual(net['id'], subnet['network_id'])
        self.assertEqual(net['id'], port['network_id'])
        self.assertEqual(subnet['id'], port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(top_entry_map['network']['bottom_id'], net['id'])
        self.assertEqual(top_entry_map['subnet']['bottom_id'], subnet['id'])
        self.assertEqual(top_entry_map['port']['bottom_id'], port['id'])

        # test _prepare_bottom_element
        _, b_port_id, _, _ = fake_plugin._get_bottom_bridge_elements(
            q_ctx, 'project_id', b_pod, net, False, subnet, port)
        b_port = fake_plugin._get_client(b_pod['region_name']).get_ports(
            t_ctx, b_port_id)

        bottom_entry_map = {}
        with t_ctx.session.begin():
            for entry in core.query_resource(
                    t_ctx, models.ResourceRouting,
                    [{'key': 'pod_id', 'comparator': 'eq',
                      'value': b_pod['pod_id']}], []):
                bottom_entry_map[entry['resource_type']] = entry
        self.assertEqual(bottom_entry_map['network']['top_id'], net['id'])
        self.assertEqual(bottom_entry_map['network']['bottom_id'],
                         b_port['network_id'])
        self.assertEqual(bottom_entry_map['subnet']['top_id'], subnet['id'])
        self.assertEqual(bottom_entry_map['subnet']['bottom_id'],
                         b_port['fixed_ips'][0]['subnet_id'])
        self.assertEqual(bottom_entry_map['port']['top_id'], port['id'])
        self.assertEqual(bottom_entry_map['port']['bottom_id'], b_port_id)

    @staticmethod
    def _prepare_sg_test(project_id, ctx, pod_name):
        t_sg_id = uuidutils.generate_uuid()
        t_rule_id = uuidutils.generate_uuid()
        b_sg_id = uuidutils.generate_uuid()
        b_rule_id = uuidutils.generate_uuid()
        t_sg = {
            'id': t_sg_id,
            'name': 'default',
            'description': '',
            'tenant_id': project_id,
            'security_group_rules': [
                {'security_group_id': t_sg_id,
                 'id': t_rule_id,
                 'tenant_id': project_id,
                 'remote_group_id': t_sg_id,
                 'direction': 'ingress',
                 'remote_ip_prefix': '10.0.0.0/24',
                 'protocol': None,
                 'port_range_max': None,
                 'port_range_min': None,
                 'ethertype': 'IPv4'}
            ]
        }
        TOP_PORTS.append(test_utils.DotDict(t_sg))

        b_sg = {
            'id': b_sg_id,
            'name': 'default',
            'description': '',
            'tenant_id': project_id,
            'security_group_rules': [
                {'security_group_id': b_sg_id,
                 'id': b_rule_id,
                 'tenant_id': project_id,
                 'remote_group_id': b_sg_id,
                 'direction': 'ingress',
                 'remote_ip_prefix': '10.0.0.0/24',
                 'protocol': None,
                 'port_range_max': None,
                 'port_range_min': None,
                 'ethertype': 'IPv4'}
            ]
        }
        if pod_name == 'pod_1':
            BOTTOM1_PORTS.append(test_utils.DotDict(b_sg))
        else:
            BOTTOM2_PORTS.append(test_utils.DotDict(b_sg))

        pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_sg_id,
                              'bottom_id': b_sg_id,
                              'pod_id': pod_id,
                              'project_id': project_id,
                              'resource_type': constants.RT_SG})

        return t_sg_id, b_sg_id

    @staticmethod
    def _prepare_port_test(tenant_id, ctx, pod_name, index, t_net_id,
                           b_net_id, t_subnet_id, b_subnet_id, add_ip=True,
                           vif_type=portbindings.VIF_TYPE_UNBOUND,
                           device_onwer='compute:None'):
        t_port_id = uuidutils.generate_uuid()
        b_port_id = uuidutils.generate_uuid()

        if add_ip:
            ip_address = ''
            for subnet in TOP_SUBNETS:
                if subnet['id'] == t_subnet_id:
                    ip_address = subnet['cidr'].replace('.0/24',
                                                        '.%d' % (index + 4))

        t_port = {
            'id': t_port_id,
            'name': 'top_port_%d' % index,
            'description': 'old_top_description',
            'extra_dhcp_opts': [],
            'device_owner': device_onwer,
            'security_groups': [],
            'device_id': '68f46ee4-d66a-4c39-bb34-ac2e5eb85470',
            'admin_state_up': True,
            'network_id': t_net_id,
            'tenant_id': tenant_id,
            'mac_address': 'fa:16:3e:cd:76:40',
            'binding:vif_type': vif_type,
            'project_id': 'project_id',
            'binding:host_id': 'zhiyuan-5',
            'status': 'ACTIVE'
        }
        if add_ip:
            t_port.update({'fixed_ips': [{'subnet_id': t_subnet_id,
                                          'ip_address': ip_address}]})
        TOP_PORTS.append(test_utils.DotDict(t_port))

        b_port = {
            'id': b_port_id,
            'name': b_port_id,
            'description': 'old_bottom_description',
            'extra_dhcp_opts': [],
            'device_owner': device_onwer,
            'security_groups': [],
            'device_id': '68f46ee4-d66a-4c39-bb34-ac2e5eb85470',
            'admin_state_up': True,
            'network_id': b_net_id,
            'tenant_id': tenant_id,
            'device_owner': 'compute:None',
            'extra_dhcp_opts': [],
            'mac_address': 'fa:16:3e:cd:76:40',
            'binding:vif_type': vif_type,
            'project_id': 'tenant_id',
            'binding:host_id': 'zhiyuan-5',
            'status': 'ACTIVE'
        }
        if add_ip:
            b_port.update({'fixed_ips': [{'subnet_id': b_subnet_id,
                                          'ip_address': ip_address}]})

        if pod_name == 'pod_1':
            BOTTOM1_PORTS.append(test_utils.DotDict(b_port))
        else:
            BOTTOM2_PORTS.append(test_utils.DotDict(b_port))

        pod_id = 'pod_id_1' if pod_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_port_id,
                              'bottom_id': b_port_id,
                              'pod_id': pod_id,
                              'project_id': tenant_id,
                              'resource_type': constants.RT_PORT})

        return t_port_id, b_port_id

    @staticmethod
    def _prepare_network_subnet(project_id, ctx, region_name, index,
                                enable_dhcp=True, az_hints=None,
                                network_type=constants.NT_LOCAL):
        t_client = FakeClient()
        t_net_name = 'top_net_%d' % index
        t_nets = t_client.list_networks(ctx, [{'key': 'name',
                                               'comparator': 'eq',
                                               'value': t_net_name}])
        if not t_nets:
            t_net_id = uuidutils.generate_uuid()
            t_subnet_id = uuidutils.generate_uuid()
            t_net = {
                'id': t_net_id,
                'name': 'top_net_%d' % index,
                'tenant_id': project_id,
                'project_id': project_id,
                'description': 'description',
                'admin_state_up': False,
                'shared': False,
                'provider:network_type': network_type,
                'availability_zone_hints': az_hints
            }
            t_subnet = {
                'id': t_subnet_id,
                'network_id': t_net_id,
                'name': 'top_subnet_%d' % index,
                'ip_version': 4,
                'cidr': '10.0.%d.0/24' % index,
                'allocation_pools': [],
                'enable_dhcp': True,
                'gateway_ip': '10.0.%d.1' % index,
                'ipv6_address_mode': '',
                'ipv6_ra_mode': '',
                'tenant_id': project_id,
                'project_id': project_id,
                'description': 'description',
                'host_routes': [],
                'dns_nameservers': []
            }
            TOP_NETS.append(test_utils.DotDict(t_net))
            TOP_SUBNETS.append(test_utils.DotDict(t_subnet))
        else:
            t_net_id = t_nets[0]['id']
            t_subnet_name = 'top_subnet_%d' % index
            t_subnets = t_client.list_subnets(ctx, [{'key': 'name',
                                                     'comparator': 'eq',
                                                     'value': t_subnet_name}])
            t_subnet_id = t_subnets[0]['id']

        b_net_id = t_net_id
        b_subnet_id = t_subnet_id
        b_net = {
            'id': b_net_id,
            'name': t_net_id,
            'tenant_id': project_id,
            'project_id': project_id,
            'description': 'description',
            'admin_state_up': False,
            'shared': False,
            'tenant_id': project_id
        }
        b_subnet = {
            'id': b_subnet_id,
            'network_id': b_net_id,
            'name': t_subnet_id,
            'ip_version': 4,
            'cidr': '10.0.%d.0/24' % index,
            'allocation_pools': [],
            'enable_dhcp': enable_dhcp,
            'gateway_ip': '10.0.%d.25' % index,
            'ipv6_address_mode': '',
            'ipv6_ra_mode': '',
            'tenant_id': project_id,
            'project_id': project_id,
            'description': 'description',
            'host_routes': [],
            'dns_nameservers': []
        }
        if region_name == 'pod_1':
            BOTTOM1_NETS.append(test_utils.DotDict(b_net))
            BOTTOM1_SUBNETS.append(test_utils.DotDict(b_subnet))
        else:
            BOTTOM2_NETS.append(test_utils.DotDict(b_net))
            BOTTOM2_SUBNETS.append(test_utils.DotDict(b_subnet))

        pod_id = 'pod_id_1' if region_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_net_id,
                              'bottom_id': b_net_id,
                              'pod_id': pod_id,
                              'project_id': project_id,
                              'resource_type': constants.RT_NETWORK})
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_subnet_id,
                              'bottom_id': b_subnet_id,
                              'pod_id': pod_id,
                              'project_id': project_id,
                              'resource_type': constants.RT_SUBNET})
        return t_net_id, t_subnet_id, b_net_id, b_subnet_id

    @staticmethod
    def _prepare_port(project_id, ctx, region_name, index, extra_attrs={}):
        t_client = FakeClient()
        t_net_name = 'top_net_%d' % index
        t_nets = t_client.list_networks(ctx, [{'key': 'name',
                                               'comparator': 'eq',
                                               'value': t_net_name}])
        t_subnet_name = 'top_subnet_%d' % index
        t_subnets = t_client.list_subnets(ctx, [{'key': 'name',
                                                 'comparator': 'eq',
                                                 'value': t_subnet_name}])

        t_port_id = uuidutils.generate_uuid()
        b_port_id = t_port_id
        ip_suffix = index if region_name == 'pod_1' else 100 + index
        t_port = {
            'id': b_port_id,
            'network_id': t_nets[0]['id'],
            'device_id': 'vm%d_id' % index,
            'device_owner': 'compute:None',
            'fixed_ips': [{'subnet_id': t_subnets[0]['id'],
                           'ip_address': '10.0.%d.%d' % (index, ip_suffix)}],
            'mac_address': 'fa:16:3e:d4:%02x:%02x' % (index, ip_suffix),
            'security_groups': [],
            'tenant_id': project_id,
            'project_id': project_id
        }
        t_port.update(extra_attrs)
        # resource ids in top and bottom pod are the same
        b_port = {
            'id': t_port_id,
            'network_id': t_nets[0]['id'],
            'device_id': 'vm%d_id' % index,
            'device_owner': 'compute:None',
            'fixed_ips': [{'subnet_id': t_subnets[0]['id'],
                           'ip_address': '10.0.%d.%d' % (index, ip_suffix)}],
            'mac_address': 'fa:16:3e:d4:%02x:%02x' % (index, ip_suffix),
            'security_groups': [],
            'tenant_id': project_id,
            'project_id': project_id
        }
        b_port.update(extra_attrs)
        TOP_PORTS.append(test_utils.DotDict(t_port))
        if region_name == 'pod_1':
            BOTTOM1_PORTS.append(test_utils.DotDict(b_port))
        else:
            BOTTOM2_PORTS.append(test_utils.DotDict(b_port))

        pod_id = 'pod_id_1' if region_name == 'pod_1' else 'pod_id_2'
        core.create_resource(ctx, models.ResourceRouting,
                             {'top_id': t_port_id,
                              'bottom_id': t_port_id,
                              'pod_id': pod_id,
                              'project_id': project_id,
                              'resource_type': constants.RT_PORT})
        return t_port_id, b_port_id

    def _prepare_router(self, project_id, router_az_hints=None):
        t_router_id = uuidutils.generate_uuid()
        t_router = {
            'id': t_router_id,
            'name': 'top_router',
            'distributed': False,
            'tenant_id': project_id,
            'attached_ports': test_utils.DotList(),
            'extra_attributes': {
                'availability_zone_hints': router_az_hints
            }
        }
        TOP_ROUTERS.append(test_utils.DotDict(t_router))
        return t_router_id

    def _prepare_router_test(self, tenant_id, ctx, region_name, index,
                             router_az_hints=None, net_az_hints=None,
                             create_new_router=False,
                             network_type=constants.NT_LOCAL):
        (t_net_id, t_subnet_id, b_net_id,
         b_subnet_id) = self._prepare_network_subnet(
            tenant_id, ctx, region_name, index, az_hints=net_az_hints,
            network_type=network_type)
        if create_new_router or len(TOP_ROUTERS) == 0:
            t_router_id = self._prepare_router(tenant_id, router_az_hints)
        else:
            t_router_id = TOP_ROUTERS[0]['id']

        return t_net_id, t_subnet_id, t_router_id, b_net_id, b_subnet_id

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_subnet_clean(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = 'test_tenant_id'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        port_num = len(TOP_PORTS)
        pre_created_port_num = 0
        for port in TOP_PORTS:
            if port.get('name').startswith('dhcp_port_'):
                pre_created_port_num += 1
            elif port.get('name').startswith('interface_'):
                pre_created_port_num += 1
            elif port.get('device_owner') == 'network:router_interface':
                pre_created_port_num += 1

        fake_plugin.remove_router_interface(
            q_ctx, t_router_id, {'port_id': t_port_id})
        fake_plugin.delete_subnet(q_ctx, t_subnet_id)

        # check pre-created ports are all deleted
        self.assertEqual(port_num - pre_created_port_num, len(TOP_PORTS))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_subnet(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        neutron_context = FakeNeutronContext()
        t_ctx = context.get_db_context()
        _, t_subnet_id, _, b_subnet_id = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1)

        fake_plugin = FakePlugin()
        fake_client = FakeClient('pod_1')
        mock_context.return_value = t_ctx
        update_body = {
            'subnet':
                {'name': 'new_name',
                 'description': 'new_description',
                 'allocation_pools': [{"start": "10.0.1.10",
                                      "end": "10.0.1.254"}],
                 'gateway_ip': '10.0.1.2',
                 'host_routes': [{"nexthop": "10.1.0.1",
                                 "destination": "10.1.0.0/24"},
                                 {"nexthop": "10.2.0.1",
                                  "destination": "10.2.0.0/24"}],
                 'dns_nameservers': ['114.114.114.114', '8.8.8.8']}
        }
        body_copy = copy.deepcopy(update_body)
        fake_plugin.update_subnet(neutron_context, t_subnet_id, update_body)
        top_subnet = fake_plugin.get_subnet(neutron_context, t_subnet_id)
        self.assertEqual(top_subnet['name'], body_copy['subnet']['name'])
        self.assertEqual(top_subnet['description'],
                         body_copy['subnet']['description'])
        self.assertEqual(top_subnet['allocation_pools'],
                         body_copy['subnet']['allocation_pools'])
        six.assertCountEqual(self, top_subnet['host_routes'],
                             body_copy['subnet']['host_routes'])
        six.assertCountEqual(self, top_subnet['dns_nameservers'],
                             body_copy['subnet']['dns_nameservers'])
        self.assertEqual(top_subnet['gateway_ip'],
                         body_copy['subnet']['gateway_ip'])

        bottom_subnet = fake_client.get_subnets(t_ctx, b_subnet_id)
        # name is set to top resource id, which is used by lock_handle to
        # retrieve bottom/local resources that have been created but not
        # registered in the resource routing table, so it's not allowed
        # to be updated
        self.assertEqual(bottom_subnet['name'], b_subnet_id)
        self.assertEqual(bottom_subnet['description'],
                         body_copy['subnet']['description'])
        bottom_allocation_pools = [{'start': '10.0.1.2', 'end': '10.0.1.2'},
                                   {'start': '10.0.1.10', 'end': '10.0.1.24'},
                                   {'start': '10.0.1.26', 'end': '10.0.1.254'}]
        six.assertCountEqual(self,
                             bottom_subnet['allocation_pools'],
                             bottom_allocation_pools)
        six.assertCountEqual(self,
                             bottom_subnet['host_routes'],
                             body_copy['subnet']['host_routes'])
        six.assertCountEqual(self,
                             bottom_subnet['dns_nameservers'],
                             body_copy['subnet']['dns_nameservers'])
        # gateway ip is set to origin gateway ip ,because it is reserved
        # by top pod, so it's not allowed to be updated
        self.assertEqual(bottom_subnet['gateway_ip'], '10.0.1.25')

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_subnet_enable_disable_dhcp(self, mock_context):

        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        neutron_context = FakeNeutronContext()
        t_ctx = context.get_db_context()
        _, t_subnet_id, _, b_subnet_id = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1, enable_dhcp=False)

        fake_plugin = FakePlugin()
        fake_client = FakeClient('pod_1')
        mock_context.return_value = t_ctx

        self.assertEqual(0, len(TOP_PORTS))
        self.assertEqual(0, len(BOTTOM1_PORTS))

        update_body = {
            'subnet':
                {'enable_dhcp': 'True'}
        }
        body_copy = copy.deepcopy(update_body)
        # from disable dhcp to enable dhcp, create a new dhcp port
        fake_plugin.update_subnet(neutron_context, t_subnet_id, update_body)
        top_subnet = fake_plugin.get_subnet(neutron_context, t_subnet_id)
        self.assertEqual(top_subnet['enable_dhcp'],
                         body_copy['subnet']['enable_dhcp'])
        self.assertEqual(1, len(TOP_PORTS))

        bottom_subnet = fake_client.get_subnets(t_ctx, b_subnet_id)
        self.assertEqual(bottom_subnet['enable_dhcp'],
                         body_copy['subnet']['enable_dhcp'])

        update_body = {
            'subnet':
                {'enable_dhcp': 'False'}
        }
        body_copy = copy.deepcopy(update_body)
        # from enable dhcp to disable dhcp, reserved dhcp port
        # previously created
        fake_plugin.update_subnet(neutron_context, t_subnet_id, update_body)
        top_subnet = fake_plugin.get_subnet(neutron_context, t_subnet_id)
        self.assertEqual(top_subnet['enable_dhcp'],
                         body_copy['subnet']['enable_dhcp'])
        self.assertEqual(1, len(TOP_PORTS))

        bottom_subnet = fake_client.get_subnets(t_ctx, b_subnet_id)
        self.assertEqual(bottom_subnet['enable_dhcp'],
                         body_copy['subnet']['enable_dhcp'])

    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_update_ips_for_port', new=fake_update_ips_for_port)
    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(_utils, 'filter_non_model_columns',
                  new=fake_filter_non_model_columns)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_port(self, mock_context):
        project_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        neutron_context = FakeNeutronContext()
        t_ctx = context.get_db_context()
        (t_net_id, t_subnet_id,
         b_net_id, b_subnet_id) = self._prepare_network_subnet(
            project_id, t_ctx, 'pod_1', 1)
        t_port_id, b_port_id = self._prepare_port_test(
            project_id, t_ctx, 'pod_1', 1, t_net_id, b_net_id,
            t_subnet_id, b_subnet_id)
        t_sg_id, _ = self._prepare_sg_test(project_id, t_ctx, 'pod_1')

        fake_plugin = FakePlugin()
        fake_client = FakeClient('pod_1')
        mock_context.return_value = t_ctx

        update_body = {
            'port': {
                'description': 'new_description',
                'extra_dhcp_opts': [
                    {"opt_value": "123.123.123.45",
                     "opt_name": "server-ip-address"},
                    {"opt_value": "123.123.123.123",
                     "opt_name": "tftp-server"}
                ],
                'device_owner': 'compute:new',
                'device_id': 'new_device_id',
                'name': 'new_name',
                'admin_state_up': False,
                'mac_address': 'fa:16:3e:cd:76:bb',
                'security_groups': [t_sg_id],
                'allowed_address_pairs': [{"ip_address": "23.23.23.1",
                                           "mac_address": "fa:16:3e:c4:cd:3f"}]
            }

        }
        body_copy = copy.deepcopy(update_body)
        top_port = fake_plugin.update_port(
            neutron_context, t_port_id, update_body)
        self.assertEqual(top_port['name'], body_copy['port']['name'])
        self.assertEqual(top_port['description'],
                         body_copy['port']['description'])
        self.assertEqual(top_port['extra_dhcp_opts'],
                         body_copy['port']['extra_dhcp_opts'])
        self.assertEqual(top_port['device_owner'],
                         body_copy['port']['device_owner'])
        self.assertEqual(top_port['device_id'],
                         body_copy['port']['device_id'])
        self.assertEqual(top_port['admin_state_up'],
                         body_copy['port']['admin_state_up'])
        self.assertEqual(top_port['mac_address'],
                         body_copy['port']['mac_address'])
        self.assertEqual(top_port['security_groups'],
                         body_copy['port']['security_groups'])
        self.assertEqual(top_port['allowed_address_pairs'][0],
                         body_copy['port']['allowed_address_pairs'][0])

        bottom_port = fake_client.get_ports(t_ctx, b_port_id)
        # name is set to bottom resource id, which is used by lock_handle to
        # retrieve bottom/local resources that have been created but not
        # registered in the resource routing table, so it's not allowed
        # to be updated
        self.assertEqual(bottom_port['name'], b_port_id)
        self.assertEqual(bottom_port['description'],
                         body_copy['port']['description'])
        self.assertEqual(bottom_port['extra_dhcp_opts'],
                         body_copy['port']['extra_dhcp_opts'])
        self.assertEqual(bottom_port['device_owner'],
                         body_copy['port']['device_owner'])
        self.assertEqual(bottom_port['device_id'],
                         body_copy['port']['device_id'])
        self.assertEqual(bottom_port['admin_state_up'],
                         body_copy['port']['admin_state_up'])
        self.assertEqual(bottom_port['mac_address'],
                         body_copy['port']['mac_address'])
        self.assertEqual(bottom_port['security_groups'],
                         body_copy['port']['security_groups'])
        self.assertEqual(bottom_port['allowed_address_pairs'][0],
                         body_copy['port']['allowed_address_pairs'][0])

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(_utils, 'filter_non_model_columns',
                  new=fake_filter_non_model_columns)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_bound_port_mac(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        neutron_context = FakeNeutronContext()
        t_ctx = context.get_db_context()
        (t_net_id, t_subnet_id,
         b_net_id, b_subnet_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1)
        (t_port_id, b_port_id) = self._prepare_port_test(
            tenant_id, t_ctx, 'pod_1', 1, t_net_id, b_net_id,
            t_subnet_id, b_subnet_id,
            vif_type='ovs', device_onwer='compute:None')

        fake_plugin = FakePlugin()
        mock_context.return_value = t_ctx
        update_body = {
            'port': {
                'mac_address': 'fa:16:3e:cd:76:bb'
            }
        }

        self.assertRaises(q_lib_exc.PortBound, fake_plugin.update_port,
                          neutron_context, t_port_id, update_body)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(_utils, 'filter_non_model_columns',
                  new=fake_filter_non_model_columns)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_non_vm_port(self, mock_context):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx
        (t_net_id, t_subnet_id,
         b_net_id, b_subnet_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1)
        fake_plugin = FakePlugin()
        fake_client = FakeClient('pod_1')

        non_vm_port_types = [q_constants.DEVICE_OWNER_ROUTER_INTF,
                             q_constants.DEVICE_OWNER_ROUTER_GW,
                             q_constants.DEVICE_OWNER_DHCP]
        for port_type in non_vm_port_types:
            (t_port_id, b_port_id) = self._prepare_port_test(
                tenant_id, t_ctx, 'pod_1', 1, t_net_id, b_net_id,
                t_subnet_id, b_subnet_id, add_ip=False, device_onwer=port_type)
            update_body = {
                'port': {'binding:host_id': 'zhiyuan-6'}
            }
            body_copy = copy.deepcopy(update_body)
            top_port = fake_plugin.update_port(
                neutron_context, t_port_id, update_body)
            self.assertEqual(top_port['binding:host_id'],
                             body_copy['port']['binding:host_id'])
            # for router interface, router gw, dhcp port, not directly
            # update bottom, so bottom not changed
            bottom_port = fake_client.get_ports(t_ctx, b_port_id)
            self.assertEqual(bottom_port['binding:host_id'], 'zhiyuan-5')

    @patch.object(FakeRPCAPI, 'setup_shadow_ports')
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(_utils, 'filter_non_model_columns',
                  new=fake_filter_non_model_columns)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_vm_port(self, mock_context, mock_setup):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        t_ctx = context.get_db_context()
        neutron_context = FakeNeutronContext()
        mock_context.return_value = t_ctx
        (t_net_id, t_subnet_id,
         b_net_id, b_subnet_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1, network_type=constants.NT_LOCAL)
        fake_plugin = FakePlugin()

        (t_port_id, b_port_id) = self._prepare_port_test(
            tenant_id, t_ctx, 'pod_1', 1, t_net_id, b_net_id,
            t_subnet_id, b_subnet_id)
        update_body = {
            'port': {'binding:profile': {
                'region': 'pod_1',
                'host': 'fake_host',
                'type': 'Open vSwitch agent',
                'tunnel_ip': '192.168.1.101',
                'device': 'compute: None'
            }}
        }
        fake_plugin.update_port(
            neutron_context, t_port_id, update_body)
        agents = core.query_resource(t_ctx, models.ShadowAgent, [], [])
        # we only create shadow agent for vxlan network
        self.assertEqual(len(agents), 0)
        self.assertFalse(mock_setup.called)

        client = FakeClient()
        # in fact provider attribute is not allowed to be updated, but in test
        # we just change the network type for convenience
        client.update_networks(
            t_ctx, t_net_id,
            {'network': {'provider:network_type': constants.NT_VxLAN}})
        fake_plugin.update_port(
            neutron_context, t_port_id, update_body)
        agents = core.query_resource(t_ctx, models.ShadowAgent, [], [])
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]['type'], 'Open vSwitch agent')
        self.assertEqual(agents[0]['host'], 'fake_host')
        self.assertEqual(agents[0]['tunnel_ip'], '192.168.1.101')
        # we test the exact effect of setup_shadow_ports in
        # test_update_port_trigger_l2pop
        self.assertTrue(mock_setup.called)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'add_gateway_routers')
    @patch.object(FakeBaseRPCAPI, 'configure_route')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface(self, mock_context, mock_rpc, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        mock_rpc.assert_called_once_with(t_ctx, tenant_id, t_router_id)
        for b_net in BOTTOM1_NETS:
            if 'provider:segmentation_id' in b_net:
                self.assertIn(b_net['provider:segmentation_id'], (2000, 2001))
        # only one VLAN allocated since we just create one bridge network
        allocations = [
            allocation['allocated'] for allocation in TOP_VLANALLOCATIONS]
        six.assertCountEqual(self, [True, False], allocations)
        for segment in TOP_SEGMENTS:
            self.assertIn(segment['segmentation_id'], (2000, 2001))

        bridge_port_name = constants.bridge_port_name % (tenant_id,
                                                         b_router_id)
        _, t_bridge_port_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port_name, 'port')[0]
        for t_port in TOP_PORTS:
            if t_port['id'] == t_bridge_port_id:
                t_ns_bridge_net_id = t_port['network_id']
                t_ns_bridge_subnet_id = t_port['fixed_ips'][0]['subnet_id']
        b_ns_bridge_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_ns_bridge_net_id, 'pod_1', constants.RT_NETWORK)
        b_ns_bridge_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_ns_bridge_subnet_id, 'pod_1', constants.RT_SUBNET)

        (t_net_id, t_subnet_id, t_router_id,
         b_another_net_id, b_another_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 2)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_NS_ROUTER)
        # router for north-south networking is not created since no external
        # network created
        self.assertEqual(len(mappings), 0)

        device_ids = ['', '']
        for port in BOTTOM1_PORTS:
            if port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[0] = port['device_id']
            elif port['network_id'] == b_another_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[1] = port['device_id']

        self.assertEqual(device_ids, [b_router_id, b_router_id])
        call = mock.call(t_ctx, b_router_id,
                         {'network_id': b_ns_bridge_net_id,
                          'enable_snat': False,
                          'external_fixed_ips': [
                              {'subnet_id': b_ns_bridge_subnet_id,
                               'ip_address': '100.0.0.2'}]})
        # each router interface adding will call add_gateway once
        mock_action.assert_has_calls([call, call])

    @patch.object(context, 'get_context_from_neutron_context')
    def test_validation_router_net_location_match(self, mock_context):
        self._basic_pod_route_setup()
        pod4 = {'pod_id': 'pod_id_4',
                'region_name': 'pod_4',
                'az_name': 'az_name_2'}
        db_api.create_pod(self.context, pod4)

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        tenant_id = TEST_TENANT_ID

        router_az_hints = '["pod_1"]'
        net_az_hints = '["pod_2"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        self.assertRaises(t_exceptions.RouterNetworkLocationMismatch,
                          fake_plugin.validate_router_net_location_match,
                          t_ctx, router, net)

        router_az_hints = '["pod_1"]'
        net_az_hints = '["pod_1", "az_name_2"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 2, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        # for supporting multi-gateway l3 mode, we allow attaching a network
        # to a local router if the regions of the network include the region
        # of the router
        self.assertEqual(True, is_local_router)

        router_az_hints = '["az_name_1"]'
        net_az_hints = '["az_name_1", "pod_2"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 3, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        self.assertRaises(t_exceptions.RouterNetworkLocationMismatch,
                          fake_plugin.validate_router_net_location_match,
                          t_ctx, router, net)

        router_az_hints = '["pod_1"]'
        net_az_hints = None
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 4, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        # for supporting multi-gateway l3 mode, we allow attaching a network
        # to a local router if the regions of the network include the region
        # of the router
        self.assertEqual(True, is_local_router)

        router_az_hints = None
        net_az_hints = '["pod_1", "az_name_2"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 5, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, False)

        router_az_hints = None
        net_az_hints = None
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 6, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, False)

        router_az_hints = '["pod_1"]'
        net_az_hints = '["pod_1"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 7, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, True)

        router_az_hints = '["az_name_2"]'
        net_az_hints = '["az_name_2"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 8, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, False)

        router_az_hints = '["pod_1", "az_name_2"]'
        net_az_hints = '["az_name_2"]'
        t_ctx.is_admin = True
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 9, router_az_hints, net_az_hints, True)
        router = fake_plugin._get_router(q_ctx, t_router_id)
        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, False)

        net_az_hints = '["pod_1"]'
        t_ctx.is_admin = True
        (t_net_id, t_subnet_id, b_net_id,
         b_subnet_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 10, az_hints=net_az_hints)

        # add a use case: router's extra_attributes attr is not exist but
        # availability_zone_hints attr exist
        t_router = {
            'id': uuidutils.generate_uuid(),
            'name': 'top_router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': test_utils.DotList(),
            'availability_zone_hints': ['pod_1']
        }

        net = fake_plugin.get_network(q_ctx, t_net_id)
        is_local_router = helper.NetworkHelper.is_local_router(t_ctx, t_router)
        fake_plugin.validate_router_net_location_match(t_ctx, router, net)
        self.assertEqual(is_local_router, True)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakePlugin, '_get_bridge_network_subnet')
    @patch.object(FakeClient, 'add_gateway_routers')
    @patch.object(FakeBaseRPCAPI, 'configure_route')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_for_local_router(
            self, mock_context, mock_rpc, mock_action, mock_get_bridge_net):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        tenant_id = TEST_TENANT_ID

        router_az_hints = '["pod_1"]'
        net_az_hints = '["pod_1"]'
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1, router_az_hints, net_az_hints)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        (t_net_id, t_subnet_id, t_router_id,
         b_another_net_id, b_another_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 2, router_az_hints, net_az_hints)

        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        self.assertFalse(mock_rpc.called)
        self.assertFalse(mock_action.called)
        self.assertFalse(mock_get_bridge_net.called)

        device_ids = ['', '']
        for port in BOTTOM1_PORTS:
            if (port['network_id'] == b_net_id) and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[0] = port['device_id']
            elif port['network_id'] == b_another_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                device_ids[1] = port['device_id']

        self.assertEqual(device_ids, [b_router_id, b_router_id])

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            entry_num = len(entries)

        mock_action.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        self.assertEqual(0, len(TOP_ROUTERS[0]['attached_ports']))

        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # one new entry, for top bridge port
            self.assertEqual(entry_num + 1, len(entries))
        # top and bottom interface is deleted, only top bridge port left
        self.assertEqual(1, len(TOP_PORTS))
        self.assertEqual(0, len(BOTTOM1_PORTS))

        mock_action.side_effect = None
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id})
        # just bottom dhcp port, bottom interface is not created because
        # action_routers function is mocked
        self.assertEqual(1, len(BOTTOM1_PORTS))
        with t_ctx.session.begin():
            entries = core.query_resource(t_ctx, models.ResourceRouting,
                                          [{'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': 'port'}], [])
            # three more entries, for top and bottom dhcp ports, top interface
            self.assertEqual(entry_num + 1 + 3, len(entries))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, '_get_connection')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_exception_port_left(self, mock_context,
                                               mock_connect):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        mock_connect.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.add_router_interface,
                          q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        # top interface is removed
        self.assertEqual(0, len(TOP_ROUTERS[0]['attached_ports']))

        mock_connect.side_effect = None
        # test that we can success when bottom pod comes back
        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})
        # bottom dhcp port, bottom interface and bridge gateway port
        self.assertEqual(3, len(BOTTOM1_PORTS))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeBaseRPCAPI, 'configure_route')
    @patch.object(FakeClient, 'remove_interface_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_remove_interface(self, mock_context, mock_remove, mock_rpc):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1)
        t_port_id = fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']
        _, b_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_ROUTER)[0]

        for port in BOTTOM1_PORTS:
            if port['network_id'] == b_net_id and (
                    port['device_owner'] == 'network:router_interface'):
                b_interface_id = port['id']

        fake_plugin.remove_router_interface(
            q_ctx, t_router_id, {'port_id': t_port_id})

        mock_remove.assert_called_with(
            t_ctx, b_router_id, {'port_id': b_interface_id})
        mock_rpc.assert_called_with(t_ctx, tenant_id, t_router_id)

    def _prepare_interface_port(self, t_ctx, t_subnet_id, ip_suffix):
        t_client = FakeClient()
        t_subnet = t_client.get_subnets(t_ctx, t_subnet_id)
        t_net = t_client.get_networks(t_ctx, t_subnet['network_id'])
        t_port_id = uuidutils.generate_uuid()
        t_port = {
            'id': t_port_id,
            'network_id': t_net['id'],
            'device_id': '',
            'device_owner': '',
            'fixed_ips': [{'subnet_id': t_subnet['id'],
                           'ip_address': '%s%d' % (
                               t_subnet['cidr'][:-4], ip_suffix)}],
            'mac_address': 'fa:16:3e:d4:%02x:%02x' % (
                int(t_subnet['cidr'].split('.')[2]), ip_suffix),
            'security_groups': [],
            'tenant_id': t_subnet['tenant_id']
        }
        TOP_PORTS.append(test_utils.DotDict(t_port))
        return t_port_id

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(FakeClient, 'add_gateway_routers')
    @patch.object(FakeBaseRPCAPI, 'configure_route')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_east_west_gw_router(self, mock_context, mock_rpc, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        tenant_id = TEST_TENANT_ID

        # prepare three networks, net1 in pod1, net2 in pod2, net3 is in both
        # pod1 and pod2
        (t_net1_id, t_subnet1_id, b_net1_id,
         b_subnet1_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 1)
        (t_net2_id, t_subnet2_id, b_net2_id,
         b_subnet2_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_2', 2)
        (t_net3_id, t_subnet3_id, b_net3_id,
         b_subnet3_id) = self._prepare_network_subnet(
            tenant_id, t_ctx, 'pod_1', 3)
        self._prepare_network_subnet(tenant_id, t_ctx, 'pod_2', 3)
        t_subnet_ids = [t_subnet1_id, t_subnet2_id, t_subnet3_id]
        b_net_ids = [b_net1_id, b_net2_id, b_net3_id]

        # prepare three routers, router1 and router2 are local routers
        t_router1_id = self._prepare_router(tenant_id, ['pod_1'])
        t_router2_id = self._prepare_router(tenant_id, ['pod_2'])
        t_router3_id = self._prepare_router(tenant_id)
        t_router_ids = [t_router1_id, t_router2_id, t_router3_id]

        inf1_id = self._prepare_interface_port(t_ctx, t_subnet1_id, 5)
        inf2_id = self._prepare_interface_port(t_ctx, t_subnet2_id, 5)
        inf3_1_id = self._prepare_interface_port(t_ctx, t_subnet3_id, 5)
        inf3_2_id = self._prepare_interface_port(t_ctx, t_subnet3_id, 6)

        # attach router interface, net1 is attached to router1 and router3,
        # default gateway is on router1; net2 is attached to router2 and
        # router3, default gateway is on router2; net3 is attached to router1,
        # router2 and router3
        fake_plugin.add_router_interface(
            q_ctx, t_router1_id, {'subnet_id': t_subnet1_id})['port_id']
        fake_plugin.add_router_interface(
            q_ctx, t_router3_id, {'port_id': inf1_id})
        fake_plugin.add_router_interface(
            q_ctx, t_router2_id, {'subnet_id': t_subnet2_id})['port_id']
        fake_plugin.add_router_interface(
            q_ctx, t_router3_id, {'port_id': inf2_id})
        fake_plugin.add_router_interface(
            q_ctx, t_router1_id, {'subnet_id': t_subnet3_id})['port_id']
        fake_plugin.add_router_interface(
            q_ctx, t_router2_id, {'port_id': inf3_1_id})
        fake_plugin.add_router_interface(
            q_ctx, t_router3_id, {'port_id': inf3_2_id})

        b_router_id_map = {}
        for pod_idx, router_idx in [(1, 1), (2, 2), (1, 3), (2, 3)]:
            b_router_id = db_api.get_bottom_id_by_top_id_region_name(
                t_ctx, t_router_ids[router_idx - 1], 'pod_%d' % pod_idx,
                constants.RT_ROUTER)
            b_router_id_map[(pod_idx, router_idx)] = b_router_id

        actual_ips_map = {}
        for pod_idx, net_idx, router_idx in [
                (1, 1, 1), (1, 1, 3), (1, 3, 1), (1, 3, 3),
                (2, 2, 2), (2, 2, 3), (2, 3, 2), (2, 3, 3)]:
            b_router_id = b_router_id_map[(pod_idx, router_idx)]
            b_ports = BOTTOM1_PORTS if pod_idx == 1 else BOTTOM2_PORTS
            b_infs = [
                e for e in b_ports if e['device_id'] == b_router_id and (
                    e['network_id'] == b_net_ids[net_idx - 1])]
            inf_ip = b_infs[0]['fixed_ips'][0]['ip_address']
            actual_ips_map[(pod_idx, net_idx, router_idx)] = inf_ip

        t_infs_ip_map = {}
        for pod_idx, subnet_idx in [(1, 1), (1, 3), (2, 2), (2, 3)]:
            inf_name = 'interface_pod_%d_%s' % (pod_idx,
                                                t_subnet_ids[subnet_idx - 1])
            infs = [e for e in TOP_PORTS if e.get('name') == inf_name]
            t_infs_ip_map[(pod_idx, subnet_idx)] = infs[0][
                'fixed_ips'][0]['ip_address']

        t_client = FakeClient()
        t_subnet1 = t_client.get_subnets(t_ctx, t_subnet1_id)
        t_subnet2 = t_client.get_subnets(t_ctx, t_subnet2_id)
        t_subnet3 = t_client.get_subnets(t_ctx, t_subnet3_id)
        inf3_1 = t_client.get_ports(t_ctx, inf3_1_id)

        # tuple means (pod_idx, net_idx, router_idx)
        # (1, 1, 1) net1 attached to router1, subnet gateway is used as the
        #           interface ip
        # (1, 1, 3) net1 attached to router3, reserved gateway for non-local
        #           router is used as the interface ip
        # (1, 3, 1) net3 attached to router1, top and bottom interface ips
        #           are the same
        # (1, 3, 3) net3 attached to router3 in pod1, reserved gateway for
        #           non-local router is used as the interface ip
        # (2, 2, 2) net2 attached to router2, subnet gateway is used as the
        #           interface ip
        # (2, 2, 3) net2 attached to router3, reserved gateway for non-local
        #           router is used as the interface ip
        # (2, 3, 2) net3 attached to router2, top and bottom interface ips
        #           are the same
        # (2, 3, 3) net3 attached to router3 in pod2, reserved gateway for
        #           non-local router is used as the interface ip
        expect_ips_map = {
            (1, 1, 1): t_subnet1['gateway_ip'],
            (1, 1, 3): t_infs_ip_map[(1, 1)],
            (1, 3, 1): t_subnet3['gateway_ip'],
            (1, 3, 3): t_infs_ip_map[(1, 3)],
            (2, 2, 2): t_subnet2['gateway_ip'],
            (2, 2, 3): t_infs_ip_map[(2, 2)],
            (2, 3, 2): inf3_1['fixed_ips'][0]['ip_address'],
            (2, 3, 3): t_infs_ip_map[(2, 3)]
        }

        for key in actual_ips_map:
            self.assertEqual(expect_ips_map[key], actual_ips_map[key])

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_external_network_no_az_pod(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        # create external network without specifying az pod name
        body = {
            'network': {
                'name': 'ext-net',
                'admin_state_up': True,
                'shared': True,
                'tenant_id': TEST_TENANT_ID,
                'router:external': True,
            }
        }

        top_net = fake_plugin.create_network(q_ctx, body)
        for net in BOTTOM1_NETS:
            if net.get('router:external'):
                bottom_net = net
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, top_net['id'], constants.RT_NETWORK)
        self.assertEqual(mappings[0][1], bottom_net['id'])

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_external_network(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        body = {
            'network': {
                'name': 'ext-net',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': TEST_TENANT_ID,
                'router:external': True,
                'availability_zone_hints': ['pod_1']
            }
        }
        top_net = fake_plugin.create_network(q_ctx, body)
        for net in BOTTOM1_NETS:
            if net.get('router:external'):
                bottom_net = net
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, top_net['id'], constants.RT_NETWORK)
        self.assertEqual(mappings[0][1], bottom_net['id'])

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_flat_external_network(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        body = {
            'network': {
                'name': 'ext-net1',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': TEST_TENANT_ID,
                'router:external': True,
                'availability_zone_hints': ['pod_1'],
                provider_net.PHYSICAL_NETWORK: 'extern',
                provider_net.NETWORK_TYPE: 'flat'
            }
        }
        fake_plugin.create_network(q_ctx, body)
        body['network']['name'] = ['ext-net2']
        body['network']['availability_zone_hints'] = ['pod_2']
        fake_plugin.create_network(q_ctx, body)
        # we have ignore the FlatNetworkInUse exception, so only one allocation
        # record is created, and both pods have one external network
        self.assertEqual(1, len(TOP_FLATALLOCATIONS))
        self.assertEqual(1, len(BOTTOM1_NETS))
        self.assertEqual(1, len(BOTTOM2_NETS))

    def _prepare_external_net_router_test(self, q_ctx, fake_plugin,
                                          router_az_hints=None):

        tenant_id = TEST_TENANT_ID
        t_net_body = {
            'name': 'ext_net',
            'availability_zone_hints': ['pod_1'],
            'tenant_id': tenant_id,
            'router:external': True,
            'admin_state_up': True,
            'shared': False,
        }
        fake_plugin.create_network(q_ctx, {'network': t_net_body})
        t_net_id = TOP_NETS[0]['id']

        t_subnet_body = {
            'network_id': t_net_id,  # only one network created
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        fake_plugin.create_subnet(q_ctx, {'subnet': t_subnet_body})
        t_subnet_id = TOP_SUBNETS[0]['id']

        t_router_id = uuidutils.generate_uuid()
        t_router = {
            'id': t_router_id,
            'name': 'router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': test_utils.DotList(),
            'extra_attributes': {
                'availability_zone_hints': router_az_hints
            }
        }

        TOP_ROUTERS.append(test_utils.DotDict(t_router))
        return t_net_id, t_subnet_id, t_router_id,

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_set_gateway(self, mock_context, mock_action):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        t_net_id, t_subnet_id, t_router_id = (
            self._prepare_external_net_router_test(q_ctx, fake_plugin))

        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': TOP_NETS[0]['id'],
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': TOP_SUBNETS[0]['id'],
                                        'ip_address': '100.64.0.5'}]}}})

        b_ns_router_id = BOTTOM1_ROUTERS[0]['id']
        b_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_net_id, 'pod_1', constants.RT_NETWORK)
        b_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_subnet_id, 'pod_1', constants.RT_SUBNET)

        for subnet in TOP_SUBNETS:
            if subnet['name'].startswith('bridge_subnet'):
                t_bridge_subnet_id = subnet['id']
        b_bridge_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_bridge_subnet_id, 'pod_1', constants.RT_SUBNET)
        body = {'network_id': b_net_id,
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': b_subnet_id,
                                        'ip_address': '100.64.0.5'}]}
        calls = [mock.call(t_ctx, 'add_gateway', b_ns_router_id, body),
                 mock.call(t_ctx, 'add_interface', b_ns_router_id,
                           {'subnet_id': b_bridge_subnet_id})]
        mock_action.assert_has_calls(calls)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakePlugin, '_get_bridge_network_subnet')
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_set_gateway_for_local_router(self, mock_context, mock_action,
                                          mock_get_bridge_network):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        router_az_hints = '["pod_1"]'
        t_net_id, t_subnet_id, t_router_id = (
            self._prepare_external_net_router_test(q_ctx, fake_plugin,
                                                   router_az_hints))
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': TOP_NETS[0]['id'],
                'enable_snat': False,
                'external_fixed_ips':
                    [{'subnet_id': t_subnet_id,
                      'ip_address': '100.64.0.5'}]}}})

        b_router_id = BOTTOM1_ROUTERS[0]['id']
        b_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_net_id, 'pod_1', constants.RT_NETWORK)
        b_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_subnet_id, 'pod_1', constants.RT_SUBNET)

        body = {'network_id': b_net_id,
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': b_subnet_id,
                                        'ip_address': '100.64.0.5'}]}

        mock_action.assert_called_once_with(t_ctx, 'add_gateway',
                                            b_router_id, body)
        self.assertFalse(mock_get_bridge_network.called)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeClient, '_get_connection')
    @patch.object(FakeClient, 'action_routers')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_unset_gateway(self, mock_context, mock_action, mock_connect):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        tenant_id = TEST_TENANT_ID
        t_net_body = {
            'name': 'ext_net',
            'availability_zone_hints': ['pod_1'],
            'tenant_id': tenant_id,
            'router:external': True,
            'admin_state_up': True,
            'shared': False,
        }
        fake_plugin.create_network(q_ctx, {'network': t_net_body})
        t_net_id = TOP_NETS[0]['id']

        t_subnet_body = {
            'network_id': t_net_id,  # only one network created
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        fake_plugin.create_subnet(q_ctx, {'subnet': t_subnet_body})
        t_subnet_id = TOP_SUBNETS[0]['id']

        t_router_id = uuidutils.generate_uuid()
        t_router = {
            'id': t_router_id,
            'name': 'router',
            'distributed': False,
            'tenant_id': tenant_id,
            'attached_ports': test_utils.DotList()
        }

        TOP_ROUTERS.append(test_utils.DotDict(t_router))
        add_gw_body = {
            'router': {'external_gateway_info': {
                'network_id': t_net_id,
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': t_subnet_id,
                                        'ip_address': '100.64.0.5'}]}}}
        del_gw_body = {'router': {'external_gateway_info': {}}}

        # exception case, central router has been updated but local router has
        # not been created
        mock_connect.side_effect = q_exceptions.ConnectionFailed
        mock_action.side_effect = q_exceptions.ConnectionFailed
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.update_router, q_ctx, t_router_id,
                          copy.deepcopy(add_gw_body))
        mappings = db_api.get_bottom_mappings_by_top_id(t_ctx, t_router_id,
                                                        constants.RT_NS_ROUTER)
        self.assertEqual(0, len(mappings))
        # local router is not created, but we can still remove gateway. local
        # router is not touched, otherwise we will meet an exception here
        # because mock_action is assigned a side effect
        fake_plugin.update_router(q_ctx, t_router_id,
                                  copy.deepcopy(del_gw_body))

        # normal case
        mock_connect.side_effect = None
        mock_action.side_effect = None
        # first add router gateway
        fake_plugin.update_router(q_ctx, t_router_id, add_gw_body)
        _, b_ns_router_id = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_router_id, constants.RT_NS_ROUTER)[0]

        # then remove router gateway
        fake_plugin.update_router(q_ctx, t_router_id, del_gw_body)
        mock_action.assert_called_with(t_ctx, 'remove_gateway', b_ns_router_id)

    def _prepare_associate_floatingip_test(self, t_ctx, q_ctx, fake_plugin,
                                           router_az_hints=None,
                                           net_az_hints=None,
                                           js_net_az_hints=None):
        tenant_id = TEST_TENANT_ID
        self._basic_pod_route_setup()
        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1, router_az_hints, js_net_az_hints)
        if not net_az_hints:
            net_az_hints = ['pod_2']
        net_body = {
            'name': 'ext_net',
            'admin_state_up': True,
            'shared': False,
            'tenant_id': tenant_id,
            'router:external': True,
            'availability_zone_hints': net_az_hints
        }
        e_net = fake_plugin.create_network(q_ctx, {'network': net_body})
        subnet_body = {
            'network_id': e_net['id'],
            'name': 'ext_subnet',
            'ip_version': 4,
            'cidr': '100.64.0.0/24',
            'allocation_pools': [{'start': '100.64.0.2',
                                  'end': '100.64.0.254'}],
            'enable_dhcp': False,
            'gateway_ip': '100.64.0.1',
            'dns_nameservers': '',
            'host_routes': '',
            'tenant_id': tenant_id
        }
        e_subnet = fake_plugin.create_subnet(q_ctx, {'subnet': subnet_body})
        # set external gateway
        fake_plugin.update_router(
            q_ctx, t_router_id,
            {'router': {'external_gateway_info': {
                'network_id': e_net['id'],
                'enable_snat': False,
                'external_fixed_ips': [{'subnet_id': e_subnet['id'],
                                        'ip_address': '100.64.0.5'}]}}})
        # create floating ip
        fip_body = {'floating_network_id': e_net['id'],
                    'tenant_id': tenant_id}
        fip = fake_plugin.create_floatingip(q_ctx, {'floatingip': fip_body})
        # add router interface
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id})
        # create internal port
        t_port_id = uuidutils.generate_uuid()
        # now top id and bottom id are the same
        b_port_id = t_port_id
        t_port = {
            'id': t_port_id,
            'network_id': t_net_id,
            'mac_address': 'fa:16:3e:96:41:03',
            'fixed_ips': [{'subnet_id': t_subnet_id,
                          'ip_address': '10.0.0.4'}]
        }
        b_port = {
            'id': b_port_id,
            'name': t_port_id,
            'network_id': db_api.get_bottom_id_by_top_id_region_name(
                t_ctx, t_net_id, 'pod_1', constants.RT_NETWORK),
            'mac_address': 'fa:16:3e:96:41:03',
            'fixed_ips': [
                {'subnet_id': db_api.get_bottom_id_by_top_id_region_name(
                    t_ctx, t_subnet_id, 'pod_1', constants.RT_SUBNET),
                 'ip_address': '10.0.0.4'}],
            'binding:host_id': 'host_1',
            'binding:vif_type': 'ovs'
        }
        TOP_PORTS.append(t_port)
        BOTTOM1_PORTS.append(b_port)
        route = {'top_id': t_port_id,
                 'pod_id': 'pod_id_1',
                 'bottom_id': b_port_id,
                 'resource_type': constants.RT_PORT}
        with t_ctx.session.begin():
            core.create_resource(t_ctx, models.ResourceRouting, route)

        return t_port_id, b_port_id, fip, e_net

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'create_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_associate_floatingip(self, mock_context, mock_create):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)
        # here we attach a subnet in pod2 to the router to test if the two
        # bottom routers can be successfully created
        _, t_subnet_id2, t_router_id, _, _ = self._prepare_router_test(
            TEST_TENANT_ID, t_ctx, 'pod_2', 2)
        fake_plugin.add_router_interface(q_ctx, t_router_id,
                                         {'subnet_id': t_subnet_id2})

        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        b_ext_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, e_net['id'], 'pod_2', constants.RT_NETWORK)
        calls = [mock.call(t_ctx,
                           {'floatingip': {
                               'floating_network_id': b_ext_net_id,
                               'floating_ip_address': fip[
                                   'floating_ip_address'],
                               'port_id': b_port_id}})]
        mock_create.assert_has_calls(calls)
        # routers for east-west networking and north-south networking
        self.assertEqual(2, len(BOTTOM2_ROUTERS))

        # check routing entries for copied resources have been created
        fake_client = FakeClient()
        t_port = fake_client.get_ports(t_ctx, t_port_id)
        cp_port_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_port_id, constants.RT_SD_PORT)
        cp_subnet_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_port['fixed_ips'][0]['subnet_id'], constants.RT_SD_SUBNET)
        cp_network_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_port['network_id'], constants.RT_SD_NETWORK)
        # no resource routing entry for shadow port
        self.assertEqual(0, len(cp_port_mappings))
        self.assertEqual(1, len(cp_subnet_mappings))
        self.assertEqual(1, len(cp_network_mappings))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakePlugin, '_rollback_floatingip_data')
    @patch.object(FakeRPCAPI, 'setup_bottom_router')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_associate_floatingip_port_exception(
            self, mock_context, mock_setup, mock_rollback):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)

        # associate floating ip and exception occurs
        # actually we will not get this exception when calling
        # setup_bottom_router, we set this exception for test purpose
        mock_setup.side_effect = q_exceptions.ConnectionFailed
        fip_body = {'port_id': t_port_id}
        self.assertRaises(q_exceptions.ConnectionFailed,
                          fake_plugin.update_floatingip, q_ctx, fip['id'],
                          {'floatingip': fip_body})
        data = {'fixed_port_id': None,
                'fixed_ip_address': None,
                'router_id': None}
        mock_rollback.assert_called_once_with(q_ctx, fip['id'], data)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'delete_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_disassociate_floatingip(self, mock_context, mock_delete):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)

        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        # disassociate floating ip
        fip_body = {'port_id': None}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        fip_id = BOTTOM2_FIPS[0]['id']
        mock_delete.assert_called_once_with(t_ctx, fip_id)

        # check the association information is cleared
        self.assertIsNone(TOP_FLOATINGIPS[0]['fixed_port_id'])
        self.assertIsNone(TOP_FLOATINGIPS[0]['fixed_ip_address'])
        self.assertIsNone(TOP_FLOATINGIPS[0]['router_id'])

        # no resource routing entry for shadow port
        cp_port_mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_port_id, constants.RT_SD_PORT)
        self.assertEqual(0, len(cp_port_mappings))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(FakeClient, 'delete_floatingips')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_floatingip(self, mock_context, mock_delete):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)
        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        # disassociate floating ip
        fake_plugin.delete_floatingip(q_ctx, fip['id'])

        fip_id = BOTTOM2_FIPS[0]['id']
        mock_delete.assert_called_once_with(t_ctx, fip_id)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_router(self, mock_context):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        t_ctx.project_id = 'test_tenant_id'
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(t_ctx, q_ctx,
                                                               fake_plugin)
        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})
        # disassociate floating ip
        fip_body = {'port_id': None}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        t_router_id = TOP_ROUTERS[0]['id']
        for port in TOP_PORTS:
            if port['id'] == t_port_id:
                t_subnet_id = port['fixed_ips'][0]['subnet_id']
        fake_plugin.remove_router_interface(q_ctx, t_router_id,
                                            {'subnet_id': t_subnet_id})
        fake_plugin.update_router(q_ctx, t_router_id,
                                  {'router': {'external_gateway_info': {}}})

        top_res_sets = [TOP_NETS, TOP_SUBNETS, TOP_PORTS]
        top_res_nums = [len(top_res_set) for top_res_set in top_res_sets]
        top_pre_created_res_nums = [0, 0, 0]
        for i, top_res_set in enumerate(top_res_sets):
            for top_res in top_res_set:
                if top_res.get('name', '').find('bridge') != -1:
                    top_pre_created_res_nums[i] += 1
        fake_plugin.delete_router(q_ctx, t_router_id)

        # check pre-created networks, subnets and ports are all deleted
        for i, top_res_set in enumerate(top_res_sets):
            self.assertEqual(top_res_nums[i] - top_pre_created_res_nums[i],
                             len(top_res_set))

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, '_make_router_dict',
                  new=fake_make_router_dict)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(l3_db.L3_NAT_dbonly_mixin, 'update_floatingip',
                  new=update_floatingip)
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_local_router(self, mock_context):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        t_ctx.project_id = 'test_tenant_id'
        mock_context.return_value = t_ctx

        (t_port_id, b_port_id,
         fip, e_net) = self._prepare_associate_floatingip_test(
            t_ctx, q_ctx, fake_plugin, '["pod_1"]', ["pod_1"], '["pod_1"]')
        # associate floating ip
        fip_body = {'port_id': t_port_id}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})
        # disassociate floating ip
        fip_body = {'port_id': None}
        fake_plugin.update_floatingip(q_ctx, fip['id'],
                                      {'floatingip': fip_body})

        t_router_id = TOP_ROUTERS[0]['id']
        for port in TOP_PORTS:
            if port['id'] == t_port_id:
                t_subnet_id = port['fixed_ips'][0]['subnet_id']
        fake_plugin.remove_router_interface(q_ctx, t_router_id,
                                            {'subnet_id': t_subnet_id})
        fake_plugin.update_router(q_ctx, t_router_id,
                                  {'router': {'external_gateway_info': {}}})

        top_res_sets = [TOP_NETS, TOP_SUBNETS, TOP_PORTS]
        top_res_nums = [len(top_res_set) for top_res_set in top_res_sets]
        top_pre_created_res_nums = [0, 0, 0]
        for i, top_res_set in enumerate(top_res_sets):
            for top_res in top_res_set:
                if top_res.get('name', '').find('bridge') != -1:
                    top_pre_created_res_nums[i] += 1
        fake_plugin.delete_router(q_ctx, t_router_id)

        # check pre-created networks, subnets and ports are all deleted
        for i, top_res_set in enumerate(top_res_sets):
            self.assertEqual(top_res_nums[i] - top_pre_created_res_nums[i],
                             len(top_res_set))

    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_security_group_rule(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_create_security_group_rule(fake_plugin, q_ctx, t_ctx,
                                              'pod_id_1', TOP_SGS, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_security_group_rule(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_delete_security_group_rule(fake_plugin, q_ctx, t_ctx,
                                              'pod_id_1', TOP_SGS,
                                              TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_handle_remote_group_invalid_input(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_handle_remote_group_invalid_input(fake_plugin, q_ctx, t_ctx,
                                                     'pod_id_1', TOP_SGS,
                                                     TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(context, 'get_context_from_neutron_context')
    def test_handle_default_sg_invalid_input(self, mock_context):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx

        self._test_handle_default_sg_invalid_input(fake_plugin, q_ctx, t_ctx,
                                                   'pod_id_1', TOP_SGS,
                                                   TOP_SG_RULES, BOTTOM1_SGS)

    @patch.object(FakeClient, 'create_security_group_rules')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_create_security_group_rule_exception(self, mock_context,
                                                  mock_create):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        mock_create.side_effect = q_exceptions.ConnectionFailed

        self._test_create_security_group_rule_exception(
            fake_plugin, q_ctx, t_ctx, 'pod_id_1', TOP_SGS, BOTTOM1_SGS)

    @patch.object(FakeClient, 'delete_security_group_rules')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_delete_security_group_rule_exception(self, mock_context,
                                                  mock_delete):
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        mock_delete.side_effect = q_exceptions.ConnectionFailed

        self._test_delete_security_group_rule_exception(
            fake_plugin, q_ctx, t_ctx, 'pod_id_1', TOP_SGS, TOP_SG_RULES,
            BOTTOM1_SGS)

    @patch.object(FakeBaseRPCAPI, 'setup_shadow_ports')
    @patch.object(FakeClient, 'update_ports')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_update_port_trigger_l2pop(self, mock_context, mock_update,
                                       mock_setup):
        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        t_ctx.project_id = TEST_TENANT_ID
        mock_context.return_value = t_ctx

        self._basic_pod_route_setup()
        (t_net_id, _, _, _) = self._prepare_network_subnet(
            TEST_TENANT_ID, t_ctx, 'pod_1', 1, network_type=constants.NT_VxLAN)
        self._prepare_network_subnet(TEST_TENANT_ID, t_ctx, 'pod_2', 1,
                                     network_type=constants.NT_VxLAN)

        t_port_id1, b_port_id1 = self._prepare_port(
            TEST_TENANT_ID, t_ctx, 'pod_1', 1,
            {'binding:host_id': 'host1',
             'binding:vif_type': portbindings.VIF_TYPE_OVS})
        update_body = {'port': {
            'binding:profile': {
                constants.PROFILE_REGION: 'pod_1',
                constants.PROFILE_DEVICE: 'compute:None',
                constants.PROFILE_HOST: 'host1',
                constants.PROFILE_AGENT_TYPE: q_constants.AGENT_TYPE_OVS,
                constants.PROFILE_TUNNEL_IP: '192.168.1.101'}}}
        fake_plugin.update_port(q_ctx, t_port_id1, update_body)

        t_port_id2, b_port_id2 = self._prepare_port(
            TEST_TENANT_ID, t_ctx, 'pod_2', 1,
            {'binding:host_id': 'host2',
             'binding:vif_type': portbindings.VIF_TYPE_OVS})
        update_body = {'port': {
            'binding:profile': {
                constants.PROFILE_REGION: 'pod_2',
                constants.PROFILE_DEVICE: 'compute:None',
                constants.PROFILE_HOST: 'host2',
                constants.PROFILE_AGENT_TYPE: q_constants.AGENT_TYPE_OVS,
                constants.PROFILE_TUNNEL_IP: '192.168.1.102'}}}
        fake_plugin.update_port(q_ctx, t_port_id2, update_body)

        # shadow port is created
        client = FakeClient('pod_2')
        b_sd_port1 = client.list_ports(
            t_ctx, [{'key': 'name', 'comparator': 'eq',
                     'value': constants.shadow_port_name % t_port_id1}])[0]
        # shadow port is updated to active
        mock_update.assert_called_once_with(
            t_ctx, b_sd_port1['id'], {'port': {
                'binding:profile': {constants.PROFILE_FORCE_UP: 'True'}}})
        # asynchronous job in pod_1 is registered
        mock_setup.assert_called_once_with(t_ctx, TEST_TENANT_ID,
                                           'pod_id_1', t_net_id)

    @patch.object(directory, 'get_plugin', new=fake_get_plugin)
    @patch.object(driver.Pool, 'get_instance', new=fake_get_instance)
    @patch.object(ipam_pluggable_backend.IpamPluggableBackend,
                  '_allocate_ips_for_port', new=fake_allocate_ips_for_port)
    @patch.object(db_base_plugin_common.DbBasePluginCommon,
                  '_make_subnet_dict', new=fake_make_subnet_dict)
    @patch.object(FakeBaseRPCAPI, 'configure_route', new=mock.Mock)
    @patch.object(FakeBaseRPCAPI, 'setup_shadow_ports')
    @patch.object(context, 'get_context_from_neutron_context')
    def test_add_interface_trigger_l2pop(self, mock_context, mock_setup):
        cfg.CONF.set_override('bridge_network_type', 'vxlan',
                              group='tricircle')
        cfg.CONF.set_override('tenant_network_types', ['local', 'vxlan'],
                              group='tricircle')
        self._basic_pod_route_setup()

        fake_plugin = FakePlugin()
        q_ctx = FakeNeutronContext()
        t_ctx = context.get_db_context()
        mock_context.return_value = t_ctx
        tenant_id = TEST_TENANT_ID

        (t_net_id, t_subnet_id,
         t_router_id, b_net_id, b_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_1', 1, network_type=constants.NT_VxLAN)
        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        (t_net_id, t_subnet_id, t_router_id,
         b_another_net_id, b_another_subnet_id) = self._prepare_router_test(
            tenant_id, t_ctx, 'pod_2', 2, network_type=constants.NT_VxLAN)
        fake_plugin.add_router_interface(
            q_ctx, t_router_id, {'subnet_id': t_subnet_id})['port_id']

        b_router_id1 = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_router_id, 'pod_1', constants.RT_ROUTER)
        b_router_id2 = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, t_router_id, 'pod_2', constants.RT_ROUTER)
        t_bridge_port_name1 = constants.bridge_port_name % (TEST_TENANT_ID,
                                                            b_router_id1)
        t_bridge_port_name2 = constants.bridge_port_name % (TEST_TENANT_ID,
                                                            b_router_id2)
        t_bridge_port_id1 = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_name1, constants.RT_PORT)[0][1]
        t_bridge_port_id2 = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_bridge_port_name2, constants.RT_PORT)[0][1]
        update_body = {'port': {
            'binding:profile': {
                constants.PROFILE_REGION: 'pod_1',
                constants.PROFILE_DEVICE: 'network:router_gateway',
                constants.PROFILE_HOST: 'host1',
                constants.PROFILE_AGENT_TYPE: q_constants.AGENT_TYPE_OVS,
                constants.PROFILE_TUNNEL_IP: '192.168.1.101'}}}
        fake_plugin.update_port(q_ctx, t_bridge_port_id1, update_body)
        update_body = {'port': {
            'binding:profile': {
                constants.PROFILE_REGION: 'pod_2',
                constants.PROFILE_DEVICE: 'network:router_gateway',
                constants.PROFILE_HOST: 'host2',
                constants.PROFILE_AGENT_TYPE: q_constants.AGENT_TYPE_OVS,
                constants.PROFILE_TUNNEL_IP: '192.168.1.102'}}}
        fake_plugin.update_port(q_ctx, t_bridge_port_id2, update_body)

        client = FakeClient('pod_2')
        shadow_ports = client.list_ports(
            t_ctx, [{'key': 'name', 'comparator': 'eq',
                     'value': constants.shadow_port_name % t_bridge_port_id1}])
        # shadow port for bridge port is created
        self.assertEqual(len(shadow_ports), 1)
        # shadow port for bridge port is updated to active
        self.assertIn(constants.PROFILE_FORCE_UP,
                      shadow_ports[0]['binding:profile'])
        # asynchronous jobs are registered
        calls = [mock.call(t_ctx, tenant_id, 'pod_id_2',
                           shadow_ports[0]['network_id']),
                 mock.call(t_ctx, tenant_id, 'pod_id_1',
                           shadow_ports[0]['network_id'])]
        mock_setup.assert_has_calls(calls)

    def tearDown(self):
        core.ModelBase.metadata.drop_all(core.get_engine())
        test_utils.get_resource_store().clean()
        cfg.CONF.unregister_opts(q_config.core_opts)
        xmanager.IN_TEST = False
