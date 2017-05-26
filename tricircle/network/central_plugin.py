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

import collections
import copy
import re
import six

from oslo_config import cfg
from oslo_db.sqlalchemy import utils as sa_utils
import oslo_log.helpers as log_helpers
from oslo_log import log

from neutron.api.v2 import attributes
from neutron.callbacks import events
from neutron.callbacks import exceptions as callbacks_exc
from neutron.callbacks import registry
from neutron.callbacks import resources
import neutron.common.exceptions as ml2_exceptions
from neutron.db import _resource_extend as resource_extend
from neutron.db import api as q_db_api
from neutron.db.availability_zone import router as router_az
from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
# NOTE(zhiyuan) though not used, this import cannot be removed because Router
# relies on one table defined in l3_agentschedulers_db
from neutron.db import l3_agentschedulers_db  # noqa
from neutron.db import l3_db
from neutron.db import l3_dvr_db
# import l3_hamode_db to load l3_ha option
from neutron.db import l3_hamode_db  # noqa
from neutron.db import models_v2
from neutron.db import portbindings_db
from neutron.extensions import availability_zone as az_ext
from neutron.extensions import external_net
from neutron.extensions import l3
from neutron.extensions import providernet as provider
from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
from neutron_lib.api import validators
from neutron_lib import constants
from neutron_lib import exceptions
from neutron_lib.plugins import directory
import neutronclient.common.exceptions as q_cli_exceptions

from sqlalchemy import sql

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
import tricircle.network.exceptions as t_network_exc
from tricircle.network import helper
from tricircle.network import managers
from tricircle.network import security_groups


tricircle_opts = [
    cfg.ListOpt('type_drivers',
                default=['local,vxlan'],
                help=_('List of network type driver entry points to be loaded '
                       'from the tricircle.network.type_drivers namespace.')),
    cfg.ListOpt('tenant_network_types',
                default=['local,vxlan'],
                help=_('Ordered list of network_types to allocate as tenant '
                       'networks. The default value "local" is useful for '
                       'single pod connectivity.')),
    cfg.ListOpt('network_vlan_ranges',
                default=[],
                help=_('List of <physical_network>:<vlan_min>:<vlan_max> or '
                       '<physical_network> specifying physical_network names '
                       'usable for VLAN provider and tenant networks, as '
                       'well as ranges of VLAN tags on each available for '
                       'allocation to tenant networks.')),
    cfg.ListOpt('vni_ranges',
                default=[],
                help=_('Comma-separated list of <vni_min>:<vni_max> tuples '
                       'enumerating ranges of VXLAN VNI IDs that are '
                       'available for tenant network allocation.')),
    cfg.ListOpt('flat_networks',
                default='*',
                help=_("List of physical_network names with which flat "
                       "networks can be created. Use default '*' to allow "
                       "flat networks with arbitrary physical_network names. "
                       "Use an empty list to disable flat networks.")),
    cfg.StrOpt('bridge_network_type',
               default='vxlan',
               help=_('Type of l3 bridge network, this type should be enabled '
                      'in tenant_network_types and is not local type.')),
    cfg.StrOpt('default_region_for_external_network',
               default='RegionOne',
               help=_('Default Region where the external network belongs'
                      ' to.')),
    cfg.BoolOpt('enable_api_gateway',
                default=True,
                help=_('Whether the Nova API gateway is enabled'))
]

tricircle_opt_group = cfg.OptGroup('tricircle')
cfg.CONF.register_group(tricircle_opt_group)
cfg.CONF.register_opts(tricircle_opts, group=tricircle_opt_group)

LOG = log.getLogger(__name__)

NON_VM_PORT_TYPES = [constants.DEVICE_OWNER_ROUTER_INTF,
                     constants.DEVICE_OWNER_ROUTER_GW,
                     constants.DEVICE_OWNER_DHCP]


class TricirclePlugin(db_base_plugin_v2.NeutronDbPluginV2,
                      security_groups.TricircleSecurityGroupMixin,
                      external_net_db.External_net_db_mixin,
                      portbindings_db.PortBindingMixin,
                      extradhcpopt_db.ExtraDhcpOptMixin,
                      l3_db.L3_NAT_dbonly_mixin,
                      router_az.RouterAvailabilityZoneMixin):

    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    # NOTE(zhiyuan) we don't support "agent" and "availability_zone" extensions
    # and also it's no need for us to support, but "network_availability_zone"
    # depends on these two extensions so we need to register them
    supported_extension_aliases = ["agent",
                                   "quotas",
                                   "extra_dhcp_opt",
                                   "binding",
                                   "security-group",
                                   "external-net",
                                   "availability_zone",
                                   "provider",
                                   "network_availability_zone",
                                   "dvr",
                                   "router",
                                   "router_availability_zone",
                                   "allowed-address-pairs"]

    def __new__(cls, *args, **kwargs):
        n = super(TricirclePlugin, cls).__new__(cls, *args, **kwargs)
        registry.subscribe(n._set_distributed_flag,
                           resources.ROUTER, events.PRECOMMIT_CREATE)
        return n

    def __init__(self):
        super(TricirclePlugin, self).__init__()
        LOG.info("Starting Tricircle Neutron Plugin")
        self.clients = {}
        self.xjob_handler = xrpcapi.XJobAPI()
        self._setup_rpc()
        self.type_manager = managers.TricircleTypeManager()
        self.type_manager.initialize()
        self.helper = helper.NetworkHelper(self)

    def _setup_rpc(self):
        self.endpoints = []

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    @log_helpers.log_method_call
    def start_rpc_listeners(self):
        return []
        # NOTE(zhiyuan) use later
        # self.topic = topics.PLUGIN
        # self.conn = n_rpc.create_connection(new=True)
        # self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        # return self.conn.consume_in_threads()

    def _set_distributed_flag(self, resource, event, trigger, context,
                              router, router_db, **kwargs):
        """Event handler to set distributed flag on creation."""
        dist = l3_dvr_db.is_distributed_router(router)
        router['distributed'] = dist
        self.set_extra_attr_value(context, router_db, 'distributed', dist)

    def validate_availability_zones(self, context, resource_type,
                                    availability_zones):
        self._validate_availability_zones(context, availability_zones)

    def get_router_availability_zones(self, router_db):
        return router_db.get(az_ext.AZ_HINTS)

    @staticmethod
    def _validate_availability_zones(context, az_list):
        if not az_list:
            return
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin(subtransactions=True):
            pods = core.query_resource(t_ctx, models.Pod, [], [])
            az_set = set(az_list)

            known_az_set = set([pod['az_name'] for pod in pods])
            known_az_set = known_az_set | set(
                [pod['region_name'] for pod in pods])

            diff = az_set - known_az_set
            if diff:
                raise az_ext.AvailabilityZoneNotFound(
                    availability_zone=diff.pop())

    @staticmethod
    @resource_extend.extends([attributes.NETWORKS])
    def _extend_availability_zone(net_res, net_db):
        net_res[az_ext.AZ_HINTS] = az_ext.convert_az_string_to_list(
            net_db[az_ext.AZ_HINTS])

    @staticmethod
    def _ensure_az_set_for_external_network(context, req_data):
        external = req_data.get(external_net.EXTERNAL)
        external_set = validators.is_attr_set(external)
        if not external_set or not external:
            return False
        if az_ext.AZ_HINTS in req_data and req_data[az_ext.AZ_HINTS]:
            return True
        # if no az_hints are specified, we will use default region_name
        req_data[az_ext.AZ_HINTS] = \
            [cfg.CONF.tricircle.default_region_for_external_network]
        return True

    @staticmethod
    def _fill_provider_info(from_net, to_net):
        provider_attrs = provider_net.ATTRIBUTES
        for provider_attr in provider_attrs:
            if validators.is_attr_set(from_net.get(provider_attr)):
                to_net[provider_attr] = from_net[provider_attr]

    def _create_bottom_external_network(self, context, net, top_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        # use the first pod
        az_name = net[az_ext.AZ_HINTS][0]
        pod = db_api.find_pod_by_az_or_region(t_ctx, az_name)
        body = {
            'network': {
                'name': top_id,
                'tenant_id': net['tenant_id'],
                'admin_state_up': True,
                external_net.EXTERNAL: True
            }
        }
        self._fill_provider_info(net, body['network'])
        self._prepare_bottom_element(
            t_ctx, net['tenant_id'], pod, {'id': top_id},
            t_constants.RT_NETWORK, body)

    def _create_bottom_external_subnet(self, context, subnet, net, top_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        region_name = net[az_ext.AZ_HINTS][0]
        pod = db_api.get_pod_by_name(t_ctx, region_name)
        b_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, net['id'], region_name, t_constants.RT_NETWORK)
        body = {
            'subnet': {
                'name': top_id,
                'network_id': b_net_id,
                'tenant_id': subnet['tenant_id']
            }
        }
        attrs = ('ip_version', 'cidr', 'gateway_ip', 'allocation_pools',
                 'enable_dhcp')
        for attr in attrs:
            if validators.is_attr_set(subnet.get(attr)):
                body['subnet'][attr] = subnet[attr]
        self._prepare_bottom_element(
            t_ctx, subnet['tenant_id'], pod, {'id': top_id},
            t_constants.RT_SUBNET, body)

    @property
    def _core_plugin(self):
        return self

    def create_network(self, context, network):
        net_data = network[attributes.NETWORK]
        tenant_id = net_data['tenant_id']
        is_external = self._ensure_az_set_for_external_network(context,
                                                               net_data)
        if az_ext.AZ_HINTS in net_data:
            self._validate_availability_zones(context,
                                              net_data[az_ext.AZ_HINTS])
        with q_db_api.context_manager.writer.using(context):
            net_db = self.create_network_db(context, network)
            res = self._make_network_dict(net_db, process_extensions=False,
                                          context=context)
            self._process_l3_create(context, res, net_data)
            net_data['id'] = res['id']
            self.type_manager.create_network_segments(context, net_data,
                                                      tenant_id)
            self.type_manager.extend_network_dict_provider(context, res)
            if az_ext.AZ_HINTS in net_data:
                az_hints = az_ext.convert_az_list_to_string(
                    net_data[az_ext.AZ_HINTS])
                net_db[az_ext.AZ_HINTS] = az_hints
                res[az_ext.AZ_HINTS] = net_data[az_ext.AZ_HINTS]
            # put inside a session so when bottom operations fails db can
            # rollback
            if is_external:
                self._fill_provider_info(res, net_data)
                try:
                    self._create_bottom_external_network(
                        context, net_data, res['id'])
                except q_cli_exceptions.Conflict as e:
                    pattern = re.compile('Physical network (.*) is in use')
                    match = pattern.search(e.message)
                    if not match:
                        raise
                    else:
                        raise ml2_exceptions.FlatNetworkInUse(
                            physical_network=match.groups()[0])
        return res

    def delete_network(self, context, network_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            for pod, bottom_network_id in (
                    self.helper.get_real_shadow_resource_iterator(
                        t_ctx, t_constants.RT_NETWORK, network_id)):
                self._get_client(pod['region_name']).delete_networks(
                    t_ctx, bottom_network_id)
                # we do not specify resource_type when deleting routing entries
                # so if both "network" and "shadow_network" type entries exist
                # in one pod(this is possible for cross-pod network), we delete
                # them at the same time
                with t_ctx.session.begin():
                    core.delete_resources(
                        t_ctx, models.ResourceRouting,
                        filters=[{'key': 'top_id', 'comparator': 'eq',
                                  'value': network_id},
                                 {'key': 'pod_id', 'comparator': 'eq',
                                  'value': pod['pod_id']}])
        except Exception:
            raise
        with t_ctx.session.begin():
            core.delete_resources(t_ctx, models.ResourceRouting,
                                  filters=[{'key': 'top_id',
                                            'comparator': 'eq',
                                            'value': network_id}])

        with context.session.begin(subtransactions=True):
            self.type_manager.release_network_segments(context, network_id)
            super(TricirclePlugin, self).delete_network(context, network_id)

    def _raise_if_updates_external_attribute(self, attrs):
        """Raise exception if external attributes are present.

        This method is used for plugins that do not support
        updating external attributes.
        """
        if validators.is_attr_set(attrs.get(external_net.EXTERNAL)):
            msg = _("Plugin does not support updating network's "
                    "router:external attribute")
            raise exceptions.InvalidInput(error_message=msg)

    def update_network(self, context, network_id, network):
        """update top network

        update top network and trigger asynchronous job via RPC to update
        bottom network

        :param context: neutron context
        :param network_id: top network id
        :param network: updated body
        :return: updated network
        """
        net_data = network[attributes.NETWORK]
        provider._raise_if_updates_provider_attributes(net_data)
        self._raise_if_updates_external_attribute(net_data)

        with context.session.begin():
            net = super(TricirclePlugin, self).update_network(context,
                                                              network_id,
                                                              network)
            t_ctx = t_context.get_context_from_neutron_context(context)
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, network_id, t_constants.RT_NETWORK)
            if mappings:
                self.xjob_handler.update_network(
                    t_ctx, net['tenant_id'], network_id,
                    t_constants.POD_NOT_SPECIFIED)

            self.type_manager.extend_network_dict_provider(context, net)
            return net

    def _convert_az2region_for_nets(self, context, nets):
        for net in nets:
            self._convert_az2region_for_net(context, net)

    def _convert_az2region_for_net(self, context, net):
        az_hints = net.get(az_ext.AZ_HINTS)
        if context.is_admin and az_hints:
            t_ctx = t_context.get_context_from_neutron_context(context)
            net[az_ext.AZ_HINTS] = self._convert_az2region(t_ctx, az_hints)

    def _convert_az2region(self, t_ctx, az_hints):
        return self.helper.convert_az2region(t_ctx, az_hints)

    def get_network(self, context, network_id, fields=None):
        net = super(TricirclePlugin, self).get_network(context, network_id,
                                                       fields)
        if not fields or 'id' in fields:
            self.type_manager.extend_network_dict_provider(context, net)

        self._convert_az2region_for_net(context, net)

        return net

    def get_networks(self, context, filters=None, fields=None,
                     sorts=None, limit=None, marker=None, page_reverse=False):
        nets = super(TricirclePlugin,
                     self).get_networks(context, filters, fields, sorts,
                                        limit, marker, page_reverse)
        if not fields or 'id' in fields:
            self.type_manager.extend_networks_dict_provider(context, nets)

        self._convert_az2region_for_nets(context, nets)
        return nets

    def create_subnet(self, context, subnet):
        subnet_data = subnet['subnet']
        network = self.get_network(context, subnet_data['network_id'])
        is_external = network.get(external_net.EXTERNAL)
        with context.session.begin(subtransactions=True):
            res = super(TricirclePlugin, self).create_subnet(context, subnet)
            # put inside a session so when bottom operations fails db can
            # rollback
            if is_external:
                self._create_bottom_external_subnet(
                    context, res, network, res['id'])
        snat_port_id = None
        try:
            t_ctx = t_context.get_context_from_neutron_context(context)
            if not subnet_data['name'].startswith(
                    t_constants.bridge_subnet_name[:-3]) and not is_external:
                # do not reserve snat port for bridge and external subnet
                snat_port_id = self.helper.prepare_top_snat_port(
                    t_ctx, context, res['tenant_id'], network['id'], res['id'])
            if res['enable_dhcp']:
                self.helper.prepare_top_dhcp_port(
                    t_ctx, context, res['tenant_id'], network['id'], res['id'])
        except Exception:
            if snat_port_id:
                super(TricirclePlugin, self).delete_port(context, snat_port_id)
            self.delete_subnet(context, res['id'])
            raise
        return res

    def _delete_pre_created_port(self, t_ctx, q_ctx, port_name):
        ports = super(TricirclePlugin, self).get_ports(
            q_ctx, {'name': [port_name]})
        if ports:
            super(TricirclePlugin, self).delete_port(q_ctx, ports[0]['id'])
        db_api.delete_pre_created_resource_mapping(t_ctx, port_name)

    def delete_subnet(self, context, subnet_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            for pod, bottom_subnet_id in (
                    self.helper.get_real_shadow_resource_iterator(
                        t_ctx, t_constants.RT_SUBNET, subnet_id)):
                region_name = pod['region_name']
                self._get_client(region_name).delete_subnets(
                    t_ctx, bottom_subnet_id)
                interface_name = t_constants.interface_port_name % (
                    region_name, subnet_id)
                self._delete_pre_created_port(t_ctx, context, interface_name)
                # we do not specify resource_type when deleting routing entries
                # so if both "subnet" and "shadow_subnet" type entries exist in
                # one pod(this is possible for cross-pod network), we delete
                # them at the same time
                with t_ctx.session.begin():
                    core.delete_resources(
                        t_ctx, models.ResourceRouting,
                        filters=[{'key': 'top_id', 'comparator': 'eq',
                                  'value': subnet_id},
                                 {'key': 'pod_id', 'comparator': 'eq',
                                  'value': pod['pod_id']}])
        except Exception:
            raise
        dhcp_port_name = t_constants.dhcp_port_name % subnet_id
        self._delete_pre_created_port(t_ctx, context, dhcp_port_name)
        snat_port_name = t_constants.snat_port_name % subnet_id
        self._delete_pre_created_port(t_ctx, context, snat_port_name)
        super(TricirclePlugin, self).delete_subnet(context, subnet_id)

    def update_subnet(self, context, subnet_id, subnet):
        """update top subnet

        update top subnet and trigger asynchronous job via RPC to update
        bottom subnet.
        :param context: neutron context
        :param subnet_id: top subnet id
        :param subnet: updated subnet body
        :return: updated subnet
        """
        with context.session.begin():
            subnet_data = subnet[attributes.SUBNET]
            t_ctx = t_context.get_context_from_neutron_context(context)
            # update top subnet
            result = super(TricirclePlugin, self).update_subnet(
                context, subnet_id, subnet)
            # prepare top dhcp port if user enables dhcp,
            # the top pre-created dhcp port will not be deleted even
            # "enable_dhcp" is updated from True to False
            enable_dhcp = subnet_data.get('enable_dhcp', False)
            if enable_dhcp:
                subnet = super(TricirclePlugin, self).get_subnet(
                    context, subnet_id)
                self.helper.prepare_top_dhcp_port(t_ctx, context,
                                                  t_ctx.project_id,
                                                  subnet['network_id'],
                                                  subnet_id)
            # update bottom pod subnet if exist
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, subnet_id, t_constants.RT_SUBNET)
            if mappings:
                self.xjob_handler.update_subnet(t_ctx, result['tenant_id'],
                                                subnet_id,
                                                t_constants.POD_NOT_SPECIFIED)
            return result

    def create_port(self, context, port):
        port_body = port['port']
        if port_body['device_id'] == t_constants.interface_port_device_id:
            _, region_name, subnet_id = port_body['name'].split('_')
            gateway_port_body = self.helper.get_create_interface_body(
                port_body['tenant_id'], port_body['network_id'], region_name,
                subnet_id)
            t_ctx = t_context.get_context_from_neutron_context(context)
            pod = db_api.get_pod_by_name(t_ctx, region_name)
            _, t_gateway_id = self.helper.prepare_top_element(
                t_ctx, context, port_body['tenant_id'], pod,
                {'id': port_body['name']}, t_constants.RT_PORT,
                gateway_port_body)
            return super(TricirclePlugin, self).get_port(context, t_gateway_id)
        db_port = super(TricirclePlugin, self).create_port_db(context, port)
        self._ensure_default_security_group_on_port(context, port)
        sgids = self._get_security_groups_on_port(context, port)
        result = self._make_port_dict(db_port)
        self._process_port_create_security_group(context, result, sgids)
        return result

    def _check_mac_update_allowed(self, orig_port, port):
        unplugged_types = (portbindings.VIF_TYPE_BINDING_FAILED,
                           portbindings.VIF_TYPE_UNBOUND)
        new_mac = port.get('mac_address')
        mac_change = (new_mac is not None and
                      orig_port['mac_address'] != new_mac)

        if mac_change and (
                orig_port[portbindings.VIF_TYPE] not in unplugged_types):
            raise exceptions.PortBound(
                port_id=orig_port['id'],
                vif_type=orig_port[portbindings.VIF_TYPE],
                old_mac=orig_port['mac_address'],
                new_mac=port['mac_address'])

    def _filter_unsupported_attrs(self, port_data):
        unsupported_attrs = ['fixed_ips', 'qos_policy']
        remove_keys = [key for key in port_data.keys() if (
            key in unsupported_attrs)]
        for key in remove_keys:
            port_data.pop(key)

    def _log_update_port_sensitive_attrs(self, port_id, port):
        sensitive_attrs = ['device_id', 'device_owner', portbindings.VNIC_TYPE,
                           portbindings.PROFILE, portbindings.HOST_ID]
        request_body = port['port']
        updated_sens_attrs = []

        for key in request_body.keys():
            if key in sensitive_attrs:
                updated_sens_attrs.append('%s = %s' % (key, request_body[key]))

        warning_attrs = ', '.join(updated_sens_attrs)
        LOG.warning('update port: %(port_id)s , %(warning_attrs)s',
                    {'port_id': port_id, 'warning_attrs': warning_attrs})

    def _handle_bottom_security_group(self, t_ctx, top_sg, bottom_pod):
        if top_sg:
            b_region_name = bottom_pod['region_name']
            for sg_id in top_sg:
                b_client = self._get_client(region_name=b_region_name)
                b_client.get_security_groups(t_ctx, sg_id)
                if db_api.get_bottom_id_by_top_id_region_name(
                        t_ctx, sg_id, b_region_name, t_constants.RT_SG):
                    continue
                db_api.create_resource_mapping(
                    t_ctx, sg_id, sg_id, bottom_pod['pod_id'], t_ctx.tenant,
                    t_constants.RT_SG)

    def _create_mapping_for_vm_port(self, t_ctx, port_body, pod):
        entries = self.helper.extract_resource_routing_entries(port_body)
        self.helper.ensure_resource_mapping(t_ctx, port_body['project_id'],
                                            pod, entries)

    def _process_trunk_port(self, ctx, t_ctx, port_body, pod, profile_dict):
        trunk_plugin = directory.get_plugin('trunk')
        trunk_details = port_body.get('trunk_details')
        if trunk_plugin and trunk_details:
            t_trunk_id = trunk_details['trunk_id']
            b_trunk_id = profile_dict.get(
                t_constants.PROFILE_LOCAL_TRUNK_ID)
            entries = [(t_trunk_id, b_trunk_id, t_constants.RT_TRUNK)]
            trunk_plugin.update_subports_device_id(
                ctx, trunk_details, t_trunk_id,
                t_constants.DEVICE_OWNER_SUBPORT)
            t_trunk = trunk_plugin.get_trunk(ctx, t_trunk_id)
            self.helper.ensure_resource_mapping(t_ctx, t_trunk['project_id'],
                                                pod, entries)
            if trunk_details['sub_ports']:
                self.xjob_handler.sync_trunk(t_ctx, t_trunk['project_id'],
                                             t_trunk_id, pod['pod_id'])

    def _trigger_router_xjob_for_vm_port(self, context, port_body, pod):
        interfaces = super(TricirclePlugin, self).get_ports(
            context,
            {'network_id': [port_body['network_id']],
             'device_owner': [constants.DEVICE_OWNER_ROUTER_INTF]},
            fields=['device_id'])
        router_ids = [
            inf['device_id'] for inf in interfaces if inf['device_id']]
        if router_ids:
            # request may be come from service, we use an admin context
            # to run the xjob
            LOG.debug('Update port: network %s has been attached to the '
                      'following routers: %s, xjob triggered',
                      port_body['network_id'], router_ids)
            admin_context = t_context.get_admin_context()
            t_ctx = t_context.get_context_from_neutron_context(context)

            for router_id in router_ids:
                router = self.get_router(context, router_id)
                if not self.helper.is_local_router(t_ctx, router):
                    # for local router, job will be triggered after router
                    # interface attachment.
                    self.xjob_handler.setup_bottom_router(
                        admin_context, router['tenant_id'],
                        port_body['network_id'], router_id, pod['pod_id'])
                    # network will be attached to only one non-local router,
                    # so we break here
                    break
        else:
            LOG.debug('Update port: no interfaces found, xjob not'
                      'triggered')

    def update_port(self, context, port_id, port):
        t_ctx = t_context.get_context_from_neutron_context(context)
        top_port = super(TricirclePlugin, self).get_port(context, port_id)

        # be careful that l3_db will call update_port to update device_id of
        # router interface, we cannot directly update bottom port in this case,
        # otherwise we will fail when attaching bottom port to bottom router
        # because its device_id is not empty
        if t_constants.PROFILE_REGION in port['port'].get(
                'binding:profile', {}):
            # this update request comes from local Neutron
            res = super(TricirclePlugin, self).update_port(context, port_id,
                                                           port)
            profile_dict = port['port']['binding:profile']
            region_name = profile_dict[t_constants.PROFILE_REGION]
            device_name = profile_dict[t_constants.PROFILE_DEVICE]
            t_ctx = t_context.get_context_from_neutron_context(context)
            pod = db_api.get_pod_by_name(t_ctx, region_name)

            net = self.get_network(context, res['network_id'])
            is_vxlan_network = (
                net[provider_net.NETWORK_TYPE] == t_constants.NT_VxLAN)
            if is_vxlan_network:
                # if a local type network happens to be a vxlan network, local
                # plugin will still send agent info, so we double check here
                self.helper.create_shadow_agent_if_needed(t_ctx,
                                                          profile_dict, pod)
            if device_name.startswith('compute:'):
                # local plugin will also update region information for bridge
                # gateway port, but we only need to create resource routing
                # entries, trigger xjob and configure security group rules for
                # instance port
                self._create_mapping_for_vm_port(t_ctx, res, pod)
                self._process_trunk_port(context, t_ctx,
                                         res, pod, profile_dict)
                # only trigger setup_bottom_router job
                self._trigger_router_xjob_for_vm_port(context, res, pod)
                self.xjob_handler.configure_security_group_rules(
                    t_ctx, res['tenant_id'])

            if is_vxlan_network and (
                    cfg.CONF.client.cross_pod_vxlan_mode in (
                        t_constants.NM_P2P, t_constants.NM_L2GW)):
                self.xjob_handler.setup_shadow_ports(t_ctx, res['tenant_id'],
                                                     pod['pod_id'],
                                                     res['network_id'])
        # for vm port or port with empty device_owner, update top port and
        # bottom port
        elif top_port.get('device_owner') not in NON_VM_PORT_TYPES:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, port_id, t_constants.RT_PORT)
            request_body = port[attributes.PORT]
            if mappings:
                with context.session.begin():
                    b_pod, b_port_id = mappings[0]
                    b_region_name = b_pod['region_name']
                    b_client = self._get_client(region_name=b_region_name)
                    b_port = b_client.get_ports(context, b_port_id)
                    self._check_mac_update_allowed(b_port, request_body)
                    self._filter_unsupported_attrs(request_body)
                    request_body = port[attributes.PORT]
                    if request_body.get('security_groups', None):
                        self._handle_bottom_security_group(
                            t_ctx, request_body['security_groups'], b_pod)

                    res = super(TricirclePlugin, self).update_port(
                        context, port_id, port)
                    # name is not allowed to be updated, because it is used by
                    # lock_handle to retrieve bottom/local resources that have
                    # been created but not registered in the resource routing
                    # table
                    request_body.pop('name', None)

                    try:
                        b_client.update_ports(t_ctx, b_port_id, port)
                    except q_cli_exceptions.NotFound:
                        LOG.error(
                            ('port: %(port_id)s not found, '
                             'region name: %(name)s'),
                            {'port_id': b_port_id, 'name': b_region_name})

                    if request_body.get('security_groups', None):
                        self.xjob_handler.configure_security_group_rules(
                            t_ctx, res['tenant_id'])
            else:
                self._filter_unsupported_attrs(request_body)
                res = super(TricirclePlugin, self).update_port(
                    context, port_id, port)
        else:
            # for router interface, router gw, dhcp port, not directly
            # update bottom port
            res = super(TricirclePlugin, self).update_port(
                context, port_id, port)
        self._log_update_port_sensitive_attrs(port_id, port)
        return res

    def _pre_delete_port(self, context, port_id, port_check):
        """Do some preliminary operations before deleting the port."""
        LOG.debug("Deleting port %s", port_id)
        try:
            # notify interested parties of imminent port deletion;
            # a failure here prevents the operation from happening
            kwargs = {
                'context': context,
                'port_id': port_id,
                'port_check': port_check
            }
            registry.notify(
                resources.PORT, events.BEFORE_DELETE, self, **kwargs)
        except callbacks_exc.CallbackFailure as e:
            # NOTE(xiulin): preserve old check's behavior
            if len(e.errors) == 1:
                raise e.errors[0].error
            raise exceptions.ServicePortInUse(port_id=port_id, reason=e)

    def delete_port(self, context, port_id, l3_port_check=True):
        t_ctx = t_context.get_context_from_neutron_context(context)
        port = super(TricirclePlugin, self).get_port(context, port_id)
        # NOTE(zhiyuan) the deletion of non vm ports like router interfaces
        # and dhcp ports is handled by "setup_bottom_router" job, this job
        # will issue request to delete central ports, local ports and routing
        # entries, so here we just remove database records for central ports.
        # the deletion of vm ports is different since both users and nova are
        # involved. nova may delete vm ports via local neutron so local neutron
        # needs to send request to central neutron to delete the corresponding
        # central ports; users may delete a pre-created vm ports via central
        # neutron so central neutron needs to send request to local neutron to
        # delete the corresponding local ports. to avoid infinite api calls,
        # we use a "delete_server_port" job to delete the local ports.
        if port.get('device_owner') not in NON_VM_PORT_TYPES:
            self._pre_delete_port(context, port_id, False)
            try:
                # since we don't create resource routing entries for shadow
                # ports, we traverse pods where the network is located to
                # delete ports
                for pod, _id in self.helper.get_real_shadow_resource_iterator(
                        t_ctx, t_constants.RT_NETWORK, port['network_id']):
                    self.xjob_handler.delete_server_port(
                        t_ctx, port['tenant_id'], port_id, pod['pod_id'])
            except Exception:
                raise
            with t_ctx.session.begin():
                core.delete_resources(t_ctx, models.ResourceRouting,
                                      filters=[{'key': 'top_id',
                                                'comparator': 'eq',
                                                'value': port_id}])
        super(TricirclePlugin, self).delete_port(context, port_id)

    def get_port(self, context, port_id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, port_id, t_constants.RT_PORT)
        if mappings:
            region_name = mappings[0][0]['region_name']
            bottom_port_id = mappings[0][1]
            port = self._get_client(region_name).get_ports(
                t_ctx, bottom_port_id)
            # TODO(zhiyuan) handle the case that bottom port does not exist
            port['id'] = port_id
            if fields:
                port = dict(
                    [(k, v) for k, v in six.iteritems(port) if k in fields])
            if 'network_id' not in port and 'fixed_ips' not in port:
                return port

            bottom_top_map = {}
            with t_ctx.session.begin():
                for resource in (t_constants.RT_SUBNET, t_constants.RT_NETWORK,
                                 t_constants.RT_ROUTER):
                    route_filters = [{'key': 'resource_type',
                                      'comparator': 'eq',
                                      'value': resource}]
                    routes = core.query_resource(
                        t_ctx, models.ResourceRouting, route_filters, [])
                    for route in routes:
                        if route['bottom_id']:
                            bottom_top_map[
                                route['bottom_id']] = route['top_id']
            self._map_port_from_bottom_to_top(port, bottom_top_map)
            return port
        else:
            return super(TricirclePlugin, self).get_port(context,
                                                         port_id, fields)

    @staticmethod
    def _apply_ports_filters(query, model, filters):
        if not filters:
            return query

        fixed_ips = filters.pop('fixed_ips', {})
        ip_addresses = fixed_ips.get('ip_address')
        subnet_ids = fixed_ips.get('subnet_id')
        if ip_addresses or subnet_ids:
            query = query.join(models_v2.Port.fixed_ips)
        if ip_addresses:
            query = query.filter(
                models_v2.IPAllocation.ip_address.in_(ip_addresses))
        if subnet_ids:
            query = query.filter(
                models_v2.IPAllocation.subnet_id.in_(subnet_ids))

        for key, value in six.iteritems(filters):
            column = getattr(model, key, None)
            if column is not None:
                if not value:
                    query = query.filter(sql.false())
                    return query
                query = query.filter(column.in_(value))
        return query

    def _get_ports_from_db_with_number(self, context,
                                       number, last_port_id, top_bottom_map,
                                       filters=None):
        query = context.session.query(models_v2.Port)
        # set step as two times of number to have better chance to obtain all
        # ports we need
        search_step = number * 2
        if search_step < 100:
            search_step = 100
        query = self._apply_ports_filters(query, models_v2.Port, filters)
        query = sa_utils.paginate_query(
            query, models_v2.Port, search_step,
            # create a dummy port object
            marker=models_v2.Port(
                id=last_port_id) if last_port_id else None,
            sort_keys=['id'],
            sort_dirs=['desc-nullsfirst'])
        total = 0
        ret = []
        for port in query:
            total += 1
            if port['id'] not in top_bottom_map:
                ret.append(self._make_port_dict(port))
            if len(ret) == number:
                return ret
        # NOTE(zhiyuan) we have traversed all the ports
        if total < search_step:
            return ret
        else:
            ret.extend(self._get_ports_from_db_with_number(
                context, number - len(ret), ret[-1]['id'], top_bottom_map))
            return ret

    def _get_ports_from_top_with_number(self, context,
                                        number, last_port_id, top_bottom_map,
                                        filters=None):
        with context.session.begin():
            ret = self._get_ports_from_db_with_number(
                context, number, last_port_id, top_bottom_map, filters)
            return {'ports': ret}

    def _get_ports_from_top(self, context, top_bottom_map, filters=None):
        with context.session.begin():
            ret = []
            query = context.session.query(models_v2.Port)
            query = self._apply_ports_filters(query, models_v2.Port, filters)
            for port in query:
                if port['id'] not in top_bottom_map:
                    ret.append(self._make_port_dict(port))
            return ret

    @staticmethod
    def _map_port_from_bottom_to_top(port, bottom_top_map):
        if 'network_id' in port and port['network_id'] in bottom_top_map:
            port['network_id'] = bottom_top_map[port['network_id']]
        if 'fixed_ips' in port:
            for ip in port['fixed_ips']:
                if ip['subnet_id'] in bottom_top_map:
                    ip['subnet_id'] = bottom_top_map[ip['subnet_id']]
        if 'device_id' in port and port['device_id'] in bottom_top_map:
            port['device_id'] = bottom_top_map[port['device_id']]

    @staticmethod
    def _map_ports_from_bottom_to_top(ports, bottom_top_map):
        # TODO(zhiyuan) judge if it's fine to remove unmapped port
        port_list = []
        for port in ports:
            if port['id'] not in bottom_top_map:
                continue
            if port.get('device_owner') in NON_VM_PORT_TYPES:
                continue
            port['id'] = bottom_top_map[port['id']]
            TricirclePlugin._map_port_from_bottom_to_top(port, bottom_top_map)
            port_list.append(port)
        return port_list

    @staticmethod
    def _get_map_filter_ids(key, value, pod_id, top_bottom_map):
        if key in ('id', 'network_id', 'device_id'):
            id_list = []
            for _id in value:
                key = '%s_%s' % (pod_id, _id)
                if _id in top_bottom_map:
                    id_list.append(top_bottom_map[_id])
                elif key in top_bottom_map:
                    id_list.append(top_bottom_map[key])
                else:
                    id_list.append(_id)
            return id_list

    @staticmethod
    def _filter_shadow_port(ports, pod_id, port_pod_map):
        port_list = []
        for port in ports:
            if pod_id not in port_pod_map[port['id']]:
                port_list.append(port)
        return port_list

    def _get_ports_from_pod_with_number(self, context,
                                        current_pod, number, last_port_id,
                                        bottom_top_map, top_bottom_map,
                                        port_pod_map, filters=None):
        # NOTE(zhiyuan) last_port_id is top id, also id in returned port dict
        # also uses top id. when interacting with bottom pod, need to map
        # top to bottom in request and map bottom to top in response

        t_ctx = t_context.get_context_from_neutron_context(context)
        q_client = self._get_client(
            current_pod['region_name']).get_native_client('port', t_ctx)
        params = {'limit': number}
        if filters:
            _filters = dict(filters)
            for key, value in _filters:
                if key == 'fixed_ips':
                    if 'ip_address' in value:
                        _filters[key] = 'ip_address=%s' % value[
                            'ip_address'][0]
                    continue
                id_list = self._get_map_filter_ids(
                    key, value, current_pod['pod_id'], top_bottom_map)
                if id_list:
                    _filters[key] = id_list
            params.update(_filters)
        if last_port_id:
            # map top id to bottom id in request
            params['marker'] = top_bottom_map[last_port_id]
        res = q_client.get(q_client.ports_path, params=params)
        ports = self._filter_shadow_port(res['ports'], current_pod['pod_id'],
                                         port_pod_map)
        # map bottom id to top id in client response
        mapped_port_list = self._map_ports_from_bottom_to_top(ports,
                                                              bottom_top_map)
        del res['ports']
        res['ports'] = mapped_port_list

        if len(res['ports']) == number:
            return res
        else:
            next_pod = db_api.get_next_bottom_pod(
                t_ctx, current_pod_id=current_pod['pod_id'])
            if not next_pod:
                # _get_ports_from_top_with_number uses top id, no need to map
                next_res = self._get_ports_from_top_with_number(
                    context, number - len(res['ports']), '', top_bottom_map,
                    filters)
                next_res['ports'].extend(res['ports'])
                return next_res
            else:
                # _get_ports_from_pod_with_number itself returns top id, no
                # need to map
                next_res = self._get_ports_from_pod_with_number(
                    context, next_pod, number - len(res['ports']), '',
                    bottom_top_map, top_bottom_map, port_pod_map, filters)
                next_res['ports'].extend(res['ports'])
                return next_res

    def get_ports(self, context, filters=None, fields=None, sorts=None,
                  limit=None, marker=None, page_reverse=False):
        # Directly sending list request with "id" filter to local Neutron
        # server will cause problems. Because when local Neutron server
        # receives list request with "id" filter, it will query central
        # Neutron server and try to create the port. Here we introduce a
        # special handle for "id" filter

        trunk_plugin = directory.get_plugin('trunk')
        if trunk_plugin:
            res = trunk_plugin.get_trunk_subports(context, filters)
            if res is not None:
                return res

        if not filters or 'id' not in filters:
            # if filter is empty or "id" is not in the filter, no special
            # handle is required
            return self._get_ports(context, filters, fields, sorts, limit,
                                   marker, page_reverse)
        if len(filters) == 1:
            # only "id" is in the filter, we use get_port to get all the ports
            ports = []
            for port_id in filters['id']:
                try:
                    ports.append(self.get_port(context, port_id, fields))
                except exceptions.PortNotFound:
                    continue
            return ports
        else:
            # other filters are also specified, we first get the ports with
            # other filters, then filter the ports again with "id"
            id_filters = filters.pop('id')
            ports = self._get_ports(context, filters, None, sorts, limit,
                                    marker, page_reverse)
            return [super(TricirclePlugin,
                          self)._fields(
                p, fields) for p in ports if p['id'] in id_filters]

    def _get_ports(self, context, filters=None, fields=None, sorts=None,
                   limit=None, marker=None, page_reverse=False):
        t_ctx = t_context.get_context_from_neutron_context(context)

        non_vm_ports = super(TricirclePlugin, self).get_ports(
            context, {'device_owner': NON_VM_PORT_TYPES}, ['id'])
        non_vm_port_ids = set([port['id'] for port in non_vm_ports])

        with t_ctx.session.begin():
            bottom_top_map = {}
            top_bottom_map = {}
            for resource in (t_constants.RT_PORT, t_constants.RT_SUBNET,
                             t_constants.RT_NETWORK, t_constants.RT_ROUTER):
                route_filters = [{'key': 'resource_type',
                                  'comparator': 'eq',
                                  'value': resource}]
                routes = core.query_resource(t_ctx, models.ResourceRouting,
                                             route_filters, [])

                for route in routes:
                    if route['top_id'] in non_vm_port_ids:
                        continue
                    if route['bottom_id']:
                        bottom_top_map[route['bottom_id']] = route['top_id']
                        if route['resource_type'] == t_constants.RT_PORT:
                            key = route['top_id']
                        else:
                            # for non port resource, one top resource is
                            # possible to be mapped to more than one bottom
                            # resource
                            key = '%s_%s' % (route['pod_id'], route['top_id'])
                        top_bottom_map[key] = route['bottom_id']

            port_pod_map = collections.defaultdict(set)
            route_filters = [{'key': 'resource_type',
                              'comparator': 'eq',
                              'value': t_constants.RT_SD_PORT}]
            routes = core.query_resource(t_ctx, models.ResourceRouting,
                                         route_filters, [])
            for route in routes:
                if route['bottom_id']:
                    port_pod_map[route['bottom_id']].add(route['pod_id'])

        if limit:
            if marker:
                mappings = db_api.get_bottom_mappings_by_top_id(
                    t_ctx, marker, t_constants.RT_PORT)
                # NOTE(zhiyuan) if mapping exists, we retrieve port information
                # from bottom, otherwise from top
                if mappings:
                    pod_id = mappings[0][0]['pod_id']
                    current_pod = db_api.get_pod(t_ctx, pod_id)
                    res = self._get_ports_from_pod_with_number(
                        context, current_pod, limit, marker,
                        bottom_top_map, top_bottom_map, port_pod_map, filters)
                else:
                    res = self._get_ports_from_top_with_number(
                        context, limit, marker, top_bottom_map, filters)

            else:
                current_pod = db_api.get_next_bottom_pod(t_ctx)
                # only top pod registered
                if current_pod:
                    res = self._get_ports_from_pod_with_number(
                        context, current_pod, limit, '',
                        bottom_top_map, top_bottom_map, port_pod_map, filters)
                else:
                    res = self._get_ports_from_top_with_number(
                        context, limit, marker, top_bottom_map, filters)

            # NOTE(zhiyuan) we can safely return ports, neutron controller will
            # generate links for us so we do not need to worry about it.
            #
            # _get_ports_from_pod_with_number already traverses all the pods
            # to try to get ports equal to limit, so pod is transparent for
            # controller.
            return [super(TricirclePlugin,
                          self)._fields(p, fields) for p in res['ports']]
        else:
            ret = []
            pods = db_api.list_pods(t_ctx)
            for pod in pods:
                if not pod['az_name']:
                    continue
                _filters = []
                if filters:
                    for key, value in six.iteritems(filters):
                        if key == 'fixed_ips':
                            if 'ip_address' in value:
                                _filters.append(
                                    {'key': key, 'comparator': 'eq',
                                     'value': 'ip_address=%s' % value[
                                         'ip_address'][0]})
                            continue
                        id_list = self._get_map_filter_ids(
                            key, value, pod['pod_id'], top_bottom_map)
                        if id_list:
                            _filters.append({'key': key,
                                             'comparator': 'eq',
                                             'value': id_list})
                        else:
                            _filters.append({'key': key,
                                             'comparator': 'eq',
                                             'value': value})
                client = self._get_client(pod['region_name'])
                ports = client.list_ports(t_ctx, filters=_filters)
                ret.extend(self._filter_shadow_port(ports, pod['pod_id'],
                                                    port_pod_map))
            ret = self._map_ports_from_bottom_to_top(ret, bottom_top_map)
            ret.extend(self._get_ports_from_top(context, top_bottom_map,
                                                filters))
            return [super(TricirclePlugin,
                          self)._fields(p, fields) for p in ret]

    def create_router(self, context, router):
        with context.session.begin(subtransactions=True):
            router_db = super(TricirclePlugin, self).create_router(
                context, router)

        return router_db

    def _delete_top_bridge_resource(self, t_ctx, q_ctx, resource_type,
                                    resource_id, resource_name):
        # first we update the routing entry to clear bottom_id and expire the
        # entry, if we succeed to delete the bridge resource next, we continue
        # to delete this expired entry; otherwise, we fail to delete the bridge
        # resource, then when the resource is accessed via lock_handle module,
        # that module will find the resource and update the entry
        with t_ctx.session.begin():
            core.update_resources(
                t_ctx, models.ResourceRouting,
                [{'key': 'bottom_id', 'comparator': 'eq',
                  'value': resource_id},
                 {'key': 'top_id', 'comparator': 'eq',
                  'value': resource_name}],
                {'bottom_id': None,
                 'created_at': t_constants.expire_time,
                 'updated_at': t_constants.expire_time})
        if resource_type == t_constants.RT_PORT:
            getattr(super(TricirclePlugin, self), 'delete_%s' % resource_type)(
                q_ctx, resource_id)
        else:
            getattr(self, 'delete_%s' % resource_type)(q_ctx, resource_id)
        with t_ctx.session.begin():
            core.delete_resources(t_ctx, models.ResourceRouting,
                                  [{'key': 'top_id',
                                    'comparator': 'eq',
                                    'value': resource_name}])

    def _delete_top_bridge_network_subnet(self, t_ctx, q_ctx):
        project_id = t_ctx.project_id
        bridge_subnet_name = t_constants.bridge_subnet_name % project_id
        bridge_subnets = super(TricirclePlugin, self).get_subnets(
            q_ctx, {'name': [bridge_subnet_name]})
        if bridge_subnets:
            self._delete_top_bridge_resource(
                t_ctx, q_ctx, t_constants.RT_SUBNET,
                bridge_subnets[0]['id'], bridge_subnet_name)
        bridge_net_name = t_constants.bridge_net_name % project_id
        bridge_nets = super(TricirclePlugin, self).get_networks(
            q_ctx, {'name': [bridge_net_name]})
        if bridge_nets:
            self._delete_top_bridge_resource(
                t_ctx, q_ctx, t_constants.RT_NETWORK, bridge_nets[0]['id'],
                bridge_net_name)

    def _delete_top_bridge_port(self, t_ctx, q_ctx, bridge_port_id,
                                bridge_port_name):
        self._delete_top_bridge_resource(t_ctx, q_ctx, t_constants.RT_PORT,
                                         bridge_port_id, bridge_port_name)

    def _delete_shadow_bridge_port(self, t_ctx, bridge_port):
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, bridge_port['network_id'], t_constants.RT_NETWORK)
        for pod, _id in mappings:
            region_name = pod['region_name']
            self._get_client(region_name).delete_ports(t_ctx,
                                                       bridge_port['id'])

    def delete_router(self, context, _id):
        router = super(TricirclePlugin,
                       self)._ensure_router_not_in_use(context, _id)
        project_id = router['tenant_id']
        t_ctx = t_context.get_context_from_neutron_context(context)
        is_local_router = self.helper.is_local_router(t_ctx, router)

        mappings = [
            (m[0], m[1], False) for m in db_api.get_bottom_mappings_by_top_id(
                t_ctx, _id, t_constants.RT_ROUTER)]
        mappings.extend(
            [(m[0], m[1], True) for m in db_api.get_bottom_mappings_by_top_id(
                t_ctx, _id, t_constants.RT_NS_ROUTER)])

        for pod, b_router_id, is_ns in mappings:
            b_client = self._get_client(pod['region_name'])
            bridge_port_name = t_constants.bridge_port_name % (project_id,
                                                               b_router_id)
            bridge_ports = super(TricirclePlugin, self).get_ports(
                context, {'name': [bridge_port_name]}, limit=1)
            if bridge_ports:
                # we will not create bridge ports for local router, so here no
                # need to check "is_local_router" again
                t_bridge_port = bridge_ports[0]
                t_bridge_port_id = t_bridge_port['id']

                if not is_ns:
                    b_client.action_routers(t_ctx, 'remove_gateway',
                                            b_router_id)
                else:
                    b_ns_port_id = t_bridge_port_id
                    request_body = {'port_id': b_ns_port_id}
                    try:
                        b_client.action_routers(t_ctx, 'remove_interface',
                                                b_router_id, request_body)
                    except Exception as e:
                        if e.status_code == 404:
                            # 404 error means that the router interface has
                            # been already detached, skip this exception
                            pass
                        raise

                self._delete_shadow_bridge_port(t_ctx, t_bridge_port)
                self._delete_top_bridge_port(t_ctx, context, t_bridge_port_id,
                                             bridge_port_name)
            b_client.delete_routers(t_ctx, b_router_id)
            db_api.delete_mappings_by_bottom_id(t_ctx, b_router_id)

        if not is_local_router:
            routers = super(TricirclePlugin, self).get_routers(
                context, {'tenant_id': [project_id]})
            if len(routers) <= 1:
                self._delete_top_bridge_network_subnet(t_ctx, context)

        super(TricirclePlugin, self).delete_router(context, _id)

    def _prepare_top_element(self, t_ctx, q_ctx,
                             project_id, pod, ele, _type, body):
        return self.helper.prepare_top_element(
            t_ctx, q_ctx, project_id, pod, ele, _type, body)

    def _prepare_bottom_element(self, t_ctx,
                                project_id, pod, ele, _type, body):
        return self.helper.prepare_bottom_element(
            t_ctx, project_id, pod, ele, _type, body)

    def _get_bridge_subnet_pool_id(self, t_ctx, q_ctx, project_id, pod):
        pool_name = t_constants.bridge_subnet_pool_name
        pool_cidr = cfg.CONF.client.bridge_cidr
        pool_ele = {'id': pool_name}
        body = {'subnetpool': {'tenant_id': project_id,
                               'name': pool_name,
                               'shared': True,
                               'is_default': False,
                               'prefixes': [pool_cidr]}}

        is_admin = q_ctx.is_admin
        q_ctx.is_admin = True
        _, pool_id = self._prepare_top_element(t_ctx, q_ctx, project_id, pod,
                                               pool_ele, 'subnetpool', body)
        q_ctx.is_admin = is_admin

        return pool_id

    def _get_bridge_network_subnet(self, t_ctx, q_ctx, project_id, pod,
                                   pool_id):
        net_name = t_constants.bridge_net_name % project_id
        net_ele = {'id': net_name}
        subnet_name = t_constants.bridge_subnet_name % project_id
        subnet_ele = {'id': subnet_name}

        is_admin = q_ctx.is_admin
        q_ctx.is_admin = True

        net_body = {'network': {
            'tenant_id': project_id,
            'name': net_name,
            'shared': False,
            'admin_state_up': True,
            provider_net.NETWORK_TYPE: cfg.CONF.tricircle.bridge_network_type}}
        _, net_id = self._prepare_top_element(
            t_ctx, q_ctx, project_id, pod, net_ele, 'network', net_body)

        subnet_body = {
            'subnet': {
                'network_id': net_id,
                'name': subnet_name,
                'prefixlen': 24,
                'ip_version': 4,
                'allocation_pools': constants.ATTR_NOT_SPECIFIED,
                'dns_nameservers': constants.ATTR_NOT_SPECIFIED,
                'host_routes': constants.ATTR_NOT_SPECIFIED,
                'cidr': constants.ATTR_NOT_SPECIFIED,
                'subnetpool_id': pool_id,
                'enable_dhcp': False,
                'tenant_id': project_id
            }
        }
        _, subnet_id = self._prepare_top_element(
            t_ctx, q_ctx,
            project_id, pod, subnet_ele, 'subnet', subnet_body)

        q_ctx.is_admin = is_admin

        net = self.get_network(q_ctx, net_id)
        subnet = self.get_subnet(q_ctx, subnet_id)

        return net, subnet

    def _get_bridge_interface(self, t_ctx, q_ctx, project_id, pod,
                              t_net_id, b_router_id, t_subnet=None):
        port_id = self.helper.get_bridge_interface(
            t_ctx, q_ctx, project_id, pod, t_net_id, b_router_id, t_subnet)
        return super(TricirclePlugin, self).get_port(q_ctx, port_id)

    def _get_bottom_bridge_elements(self, q_ctx, project_id,
                                    pod, t_net, is_external, t_subnet, t_port):
        t_ctx = t_context.get_context_from_neutron_context(q_ctx)
        return self.helper.get_bottom_bridge_elements(
            t_ctx, project_id, pod, t_net, is_external, t_subnet, t_port)

    def _get_net_id_by_interface_info(self, q_ctx, add_by_port,
                                      interface_info):
        if add_by_port:
            port = self.get_port(q_ctx, interface_info['port_id'])
            net_id = port['network_id']
        else:
            subnet = self.get_subnet(q_ctx, interface_info['subnet_id'])
            net_id = subnet['network_id']
        return net_id

    def _get_subnet_id_by_interface_info(self, q_ctx, add_by_port,
                                         interface_info):
        if add_by_port:
            port = self.get_port(q_ctx, interface_info['port_id'])
            # here we assume the port has an IP
            return port['fixed_ips'][0]['subnet_id']
        else:
            return interface_info['subnet_id']

    def _get_net_pods_by_interface_info(self, t_ctx, q_ctx, add_by_port,
                                        interface_info):
        net_id = self._get_net_id_by_interface_info(q_ctx, add_by_port,
                                                    interface_info)
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, net_id, t_constants.RT_NETWORK)
        return net_id, [mapping[0] for mapping in mappings]

    # NOTE(zhiyuan) the origin implementation in l3_db uses port returned from
    # get_port in core plugin to check, change it to base plugin, since only
    # top port information should be checked.
    def _check_router_port(self, context, port_id, device_id):
        port = super(TricirclePlugin, self).get_port(context, port_id)
        if port['device_id'] != device_id:
            raise exceptions.PortInUse(net_id=port['network_id'],
                                       port_id=port['id'],
                                       device_id=port['device_id'])
        if not port['fixed_ips']:
            msg = _('Router port must have at least one fixed IP')
            raise exceptions.BadRequest(resource='router', msg=msg)
        return port

    def _add_router_gateway(self, context, router_id, router_data):
        # get top external network information
        ext_net_id = router_data[l3.EXTERNAL_GW_INFO].get('network_id')
        t_ctx = t_context.get_context_from_neutron_context(context)
        network = self.get_network(context, ext_net_id)

        # when creating external network in top pod, pod name is passed via
        # az hint parameter, so tricircle plugin knows where to create the
        # corresponding bottom external network. here we get bottom external
        # network ID from resource routing table.
        if not network.get(az_ext.AZ_HINTS):
            raise t_exceptions.ExternalNetPodNotSpecify()

        t_router = self._get_router(context, router_id)
        self.validate_router_net_location_match(t_ctx, t_router, network)
        is_local_router = self.helper.is_local_router(t_ctx, t_router)

        region_name = network[az_ext.AZ_HINTS][0]
        pod = db_api.get_pod_by_name(t_ctx, region_name)
        b_net_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, ext_net_id, region_name, t_constants.RT_NETWORK)

        # create corresponding bottom router in the pod where external network
        # is located.
        if is_local_router:
            # if router is a local router, we will use RT_ROUTER to attach
            # external network, else use RT_NS_ROUTER
            router_type = t_constants.RT_ROUTER
            is_distributed = t_router.get('distributed', False)
            body = {'router': {'name': t_router['id'],
                               'distributed': is_distributed}}

        else:
            # TODO(zhiyuan) decide router is distributed or not from pod table
            # currently "distributed" is set to False, should add a metadata
            # field to pod table, and decide distributed or not from the
            # metadata later
            router_type = t_constants.RT_NS_ROUTER
            body = {'router': {'name': t_constants.ns_router_name % router_id,
                               'distributed': False}}

        _, b_router_id = self._prepare_bottom_element(
            t_ctx, t_router['tenant_id'], pod, t_router, router_type, body)

        # both router and external network in bottom pod are ready, attach
        # external network to router in bottom pod.
        b_client = self._get_client(region_name)
        t_info = router_data[l3.EXTERNAL_GW_INFO]
        b_info = {'network_id': b_net_id}
        if 'enable_snat' in t_info:
            b_info['enable_snat'] = t_info['enable_snat']
        if 'external_fixed_ips' in t_info:
            fixed_ips = []
            for ip in t_info['external_fixed_ips']:
                t_subnet_id = ip['subnet_id']
                b_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
                    t_ctx, t_subnet_id, region_name,
                    t_constants.RT_SUBNET)
                fixed_ips.append({'subnet_id': b_subnet_id,
                                  'ip_address': ip['ip_address']})
            b_info['external_fixed_ips'] = fixed_ips
        b_client.action_routers(t_ctx, 'add_gateway', b_router_id, b_info)

        if is_local_router:
            return

        # when internal network(providing fixed ip) and external network
        # (providing floating ip) are in different bottom pods, we utilize a
        # bridge network to connect these two networks. here we create the
        # bridge network.
        t_pod = db_api.get_top_pod(t_ctx)
        project_id = t_router['tenant_id']
        pool_id = self._get_bridge_subnet_pool_id(t_ctx, context, None, t_pod)
        t_bridge_net, t_bridge_subnet = self._get_bridge_network_subnet(
            t_ctx, context, project_id, t_pod, pool_id)
        (_, _, b_bridge_subnet_id,
         b_bridge_net_id) = self._get_bottom_bridge_elements(
            context, project_id, pod, t_bridge_net, True, t_bridge_subnet,
            None)

        # here we attach the bridge network to the router in bottom pod. to
        # make this method reentrant, we check if the interface is already
        # attached before attaching the interface.
        def _is_bridge_network_attached():
            interfaces = b_client.list_ports(t_ctx,
                                             filters=[{'key': 'device_id',
                                                       'comparator': 'eq',
                                                       'value': b_router_id}])
            for interface in interfaces:
                for fixed_ip in interface['fixed_ips']:
                    if fixed_ip['subnet_id'] == b_bridge_subnet_id:
                        return True
            return False

        is_attach = _is_bridge_network_attached()
        if not is_attach:
            # though no need to explicitly create the top bridge port since the
            # ip reserved for router interface will be used, we still create it
            # for shadow port creation purpose
            self._get_bridge_interface(
                t_ctx, context, project_id, t_pod, t_bridge_net['id'],
                b_router_id, t_bridge_subnet)
            b_client.action_routers(t_ctx, 'add_interface', b_router_id,
                                    {'subnet_id': b_bridge_subnet_id})

    def _remove_router_gateway(self, context, router_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        t_router = self._get_router(context, router_id)
        gw_port = t_router.gw_port
        if not gw_port:
            return
        ext_net_id = gw_port['network_id']
        t_network = self.get_network(context, ext_net_id)
        if az_ext.AZ_HINTS not in t_network:
            raise t_exceptions.ExternalNetPodNotSpecify()
        if not t_network[az_ext.AZ_HINTS]:
            raise t_exceptions.ExternalNetPodNotSpecify()

        region_name = t_network[az_ext.AZ_HINTS][0]
        is_local_router = self.helper.is_local_router(t_ctx, t_router)

        b_router_id = db_api.get_bottom_id_by_top_id_region_name(
            t_ctx, router_id, region_name,
            t_constants.RT_ROUTER if is_local_router
            else t_constants.RT_NS_ROUTER)

        if not b_router_id:
            # local router doesn't exist, skip local gateway deletion
            return

        b_client = self._get_client(region_name)
        b_client.action_routers(t_ctx, 'remove_gateway', b_router_id)

    def update_router(self, context, router_id, router):
        # TODO(zhiyuan) handle the case that SNAT is disabled
        # and check if bridge network solution works with IPv6
        router_data = copy.deepcopy(router['router'])
        need_update_bottom = False
        is_add = False
        if validators.is_attr_set(router_data.get(l3.EXTERNAL_GW_INFO)):
            need_update_bottom = True
            ext_net_id = router_data[l3.EXTERNAL_GW_INFO].get('network_id')
            if ext_net_id:
                is_add = True
        # TODO(zhiyuan) solve ip address conflict issue
        # if user creates floating ip before set router gateway, we may trigger
        # ip address conflict here. let's say external cidr is 163.3.124.0/24,
        # creating floating ip before setting router gateway, the gateway ip
        # will be 163.3.124.3 since 163.3.124.2 is used by floating ip, however
        # in the bottom pod floating ip is not created when creating floating
        # ip on top, so the gateway ip in the bottom pod is still 163.3.124.2,
        # thus conflict may occur.
        #
        # before this issue is solved, user should set router gateway before
        # create floating ip.
        if not need_update_bottom:
            return super(TricirclePlugin, self).update_router(
                context, router_id, router)
        if is_add:
            ret = super(TricirclePlugin, self).update_router(
                context, router_id, router)
            router_data[l3.EXTERNAL_GW_INFO].update(ret[l3.EXTERNAL_GW_INFO])
            self._add_router_gateway(context, router_id, router_data)
        else:
            self._remove_router_gateway(context, router_id)
            ret = super(TricirclePlugin, self).update_router(
                context, router_id, router)
        t_ctx = t_context.get_context_from_neutron_context(context)
        is_local_router = self.helper.is_local_router(t_ctx, router)
        if not is_local_router:
            self.xjob_handler.configure_route(
                t_ctx, ret['tenant_id'], router_id)
        return ret

    def validate_router_net_location_match(self, t_ctx, router, net):
        is_local_router = self.helper.is_local_router(t_ctx, router)
        router_az_hints = self.helper.get_router_az_hints(router)
        if not router_az_hints:
            return
        router_region_names = self._convert_az2region(t_ctx, router_az_hints)
        router_region_set = set(router_region_names)

        net_az_hints = net.get(az_ext.AZ_HINTS)
        if not net_az_hints:
            if is_local_router:
                # network az hints parameter is not specified, meaning that
                # this network can be located in any pod, such network is
                # allowed to be attached to a local router, for supporting
                # multi-gateway l3 mode
                return
            raise t_exceptions.RouterNetworkLocationMismatch(
                router_az_hints=router_region_names,
                net_az_hints=['All Region'])

        # net_az_hints already convert to region name when user is admin
        if t_ctx.is_admin:
            net_region_names = net_az_hints
        else:
            net_region_names = self._convert_az2region(t_ctx, net_az_hints)
        net_region_set = set(net_region_names)

        if is_local_router:
            if router_region_set <= net_region_set:
                # pods that this network can be located include the pod of the
                # local router, this attachment is allowed, for supporting
                # multi-gateway l3 mode
                return
            raise t_exceptions.RouterNetworkLocationMismatch(
                router_az_hints=router_region_names,
                net_az_hints=net_region_names)

        diff = net_region_set - router_region_set
        if diff:
            raise t_exceptions.RouterNetworkLocationMismatch(
                router_az_hints=router_region_names,
                net_az_hints=net_region_names)

    def add_router_interface(self, context, router_id, interface_info):
        t_ctx = t_context.get_context_from_neutron_context(context)

        router = self._get_router(context, router_id)
        project_id = router['tenant_id']
        add_by_port, _ = self._validate_interface_info(interface_info)
        net_id = self._get_net_id_by_interface_info(
            context, add_by_port, interface_info)
        subnet_id = self._get_subnet_id_by_interface_info(
            context, add_by_port, interface_info)
        net = self.get_network(context, net_id)
        subnet = self.get_subnet(context, subnet_id)
        self.validate_router_net_location_match(t_ctx, router, net)
        is_local_router = self.helper.is_local_router(t_ctx, router)

        if is_local_router:
            other_infs = super(TricirclePlugin, self).get_ports(
                context, filters={
                    'network_id': [net_id],
                    'device_owner': [constants.DEVICE_OWNER_ROUTER_INTF]})
            for other_inf in other_infs:
                if not other_inf['device_id']:
                    continue
                other_ip = other_inf['fixed_ips'][0]['ip_address']
                other_router = super(
                    TricirclePlugin, self).get_router(context,
                                                      other_inf['device_id'])
                if not self.helper.is_local_router(t_ctx, other_router) and (
                        other_ip == subnet['gateway_ip']):
                    # this network has already been attached to a non-local
                    # router and the gateway port is on that router, in this
                    # case, we don't allow this network to be attached other
                    # local routers
                    raise t_network_exc.NetAttachedToNonLocalRouter(
                        network_id=net_id, router_id=other_inf['device_id'])

        t_pod = db_api.get_top_pod(t_ctx)
        assert t_pod

        if not is_local_router:
            # for single external network, need bridge network for
            # E-W and N-S networking
            pool_id = self._get_bridge_subnet_pool_id(
                t_ctx, context, None, t_pod)
            self._get_bridge_network_subnet(
                t_ctx, context, project_id, t_pod, pool_id)

        if is_local_router:
            if self.helper.is_local_network(t_ctx, net):
                router_region = self.helper.get_router_az_hints(router)[0]
                b_client = self._get_client(router_region)
                b_pod = db_api.get_pod_by_name(t_ctx, router_region)
                # get bottom network will create bottom network and subnet
                b_client.get_networks(t_ctx, net_id)
                # create resource mapping so job will be triggered
                db_api.create_resource_mapping(
                    t_ctx, net_id, net_id, b_pod['pod_id'], net['project_id'],
                    t_constants.RT_NETWORK)
                db_api.create_resource_mapping(
                    t_ctx, subnet_id, subnet_id, b_pod['pod_id'],
                    subnet['project_id'], t_constants.RT_SUBNET)

        return_info = super(TricirclePlugin, self).add_router_interface(
            context, router_id, interface_info)

        _, b_pods = self._get_net_pods_by_interface_info(
            t_ctx, context, add_by_port, interface_info)
        if not b_pods:
            LOG.debug('Add router interface: no interfaces found, xjob not'
                      'triggered')
            return return_info
        try:
            if len(b_pods) == 1:
                self.xjob_handler.setup_bottom_router(
                    t_ctx, project_id, net_id, router_id, b_pods[0]['pod_id'])
            else:
                self.xjob_handler.setup_bottom_router(
                    t_ctx, project_id, net_id, router_id,
                    t_constants.POD_NOT_SPECIFIED)
        except Exception:
            # NOTE(zhiyuan) we fail to submit the job, so bottom router
            # operations are not started, it's safe for us to remove the top
            # router interface
            super(TricirclePlugin, self).remove_router_interface(
                context, router_id, interface_info)
            raise
        return return_info

    def create_floatingip(self, context, floatingip):
        # create bottom fip when associating fixed ip
        return super(TricirclePlugin, self).create_floatingip(
            context, floatingip,
            initial_status=constants.FLOATINGIP_STATUS_DOWN)

    def remove_router_interface(self, context, router_id, interface_info):
        t_ctx = t_context.get_context_from_neutron_context(context)

        add_by_port, _ = self._validate_interface_info(interface_info,
                                                       for_removal=True)
        net_id, b_pods = self._get_net_pods_by_interface_info(
            t_ctx, context, add_by_port, interface_info)

        return_info = super(TricirclePlugin, self).remove_router_interface(
            context, router_id, interface_info)

        router = self._get_router(context, router_id)

        if not b_pods:
            return return_info
        try:
            if len(b_pods) == 1:
                self.xjob_handler.setup_bottom_router(
                    t_ctx, router['tenant_id'], net_id,
                    router_id, b_pods[0]['pod_id'])
            else:
                self.xjob_handler.setup_bottom_router(
                    t_ctx, router['tenant_id'], net_id,
                    router_id, t_constants.POD_NOT_SPECIFIED)
        except Exception:
            # NOTE(zhiyuan) we fail to submit the job, so if bottom router
            # interface exists, it would not be deleted, then after we add
            # the top interface again, the bottom router setup job will reuse
            # the existing bottom interface.
            #
            # we don't create a routing entry between top interface and bottom
            # interface, instead, when we create bottom subnet, we specify the
            # ip of the top interface as the gateway ip of the bottom subnet.
            # later when we attach the bottom subnet to bottom router, neutron
            # server in bottom pod will create the bottom interface using the
            # gateway ip automatically.
            interface_info = {'subnet_id': return_info['subnet_id']}
            super(TricirclePlugin, self).add_router_interface(
                context, router_id, interface_info)
            raise
        return return_info

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
            # NOTE(zhiyuan) if the internal port associated with the existing
            # fip is what we expect, just ignore this exception; or if the
            # existing fip is not associated with any internal port, update the
            # fip to add association
            if not fips:
                # this is rare case that we got IpAddressInUseClient exception
                # a second ago but now the floating ip is missing
                raise t_network_exc.BottomPodOperationFailure(
                    resource='floating ip', region_name=pod['region_name'])
            associated_port_id = fips[0].get('port_id')
            if associated_port_id == port_id:
                pass
            elif not associated_port_id:
                client.update_floatingips(t_ctx, fips[0]['id'],
                                          {'floatingip': {'port_id': port_id}})
            else:
                raise

    @staticmethod
    def _rollback_floatingip_data(context, _id, org_data):
        """Rollback the data of floating ip object to the original one

        :param context: request context
        :param _id: ID of the floating ip
        :param org_data: data of floating ip we rollback to
        :return: None
        """
        try:
            with context.session.begin():
                fip_qry = context.session.query(l3_db.FloatingIP)
                floating_ips = fip_qry.filter_by(id=_id)
                for floating_ip in floating_ips:
                    floating_ip.update(org_data)
        except Exception as e:
            # log the exception and re-raise it
            LOG.exception('Fail to rollback floating ip data, reason: '
                          '%(reason)s' % {'reason': e.message})
            raise

    def update_floatingip(self, context, _id, floatingip):
        """Update floating ip object in top and bottom pods

        :param context: request context
        :param _id: ID of the floating ip
        :param floatingip: data of floating ip we update to
        :return: updated floating ip object
        """
        org_floatingip_dict = self._make_floatingip_dict(
            self._get_floatingip(context, _id))

        res = super(TricirclePlugin, self).update_floatingip(
            context, _id, floatingip)
        try:
            if floatingip['floatingip']['port_id']:
                self._associate_floatingip(context, _id, floatingip)
            else:
                self._disassociate_floatingip(context, org_floatingip_dict)
            return res
        except Exception as e:
            # NOTE(zhiyuan) when exception occurs, we update floating ip object
            # to rollback fixed_port_id, fixed_ip_address, router_id
            LOG.exception(
                'Fail to update floating ip, reason: '
                '%(reason)s, rollback floating ip data' %
                {'reason': e.message})
            org_data = {
                'fixed_port_id': org_floatingip_dict['port_id'],
                'fixed_ip_address': org_floatingip_dict['fixed_ip_address'],
                'router_id': org_floatingip_dict['router_id']}
            self._rollback_floatingip_data(context, _id, org_data)
            raise

    def _associate_floatingip(self, context, _id, floatingip):
        t_ctx = t_context.get_context_from_neutron_context(context)

        fip = floatingip['floatingip']
        floatingip_db = self._get_floatingip(context, _id)
        int_port_id = fip['port_id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, int_port_id, t_constants.RT_PORT)
        if not mappings:
            # mapping does not exist, meaning that the bottom port has not
            # been created, we just return and leave the work to setup bottom
            # floating ip to nova api gateway
            return

        int_net_pod, b_int_port_id = mappings[0]
        int_port = self.get_port(context, int_port_id)
        net_id = int_port['network_id']
        router_id = floatingip_db['router_id']
        router = self._get_router(context, router_id)
        self.xjob_handler.setup_bottom_router(
            t_ctx, router['tenant_id'], net_id,
            floatingip_db['router_id'], int_net_pod['pod_id'])

    def _disassociate_floatingip(self, context, ori_floatingip_db):
        if not ori_floatingip_db['port_id']:
            # floating ip has not been associated with fixed ip, no
            # operation in bottom pod needed
            return

        t_ctx = t_context.get_context_from_neutron_context(context)

        t_int_port_id = ori_floatingip_db['port_id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_ctx, t_int_port_id, t_constants.RT_PORT)
        if not mappings:
            # floating ip in top pod is associated but no mapping between
            # top and bottom internal port, this is an inconsistent state,
            # but since bottom internal port does not exist, no operation
            # in bottom pod is required
            LOG.warning('Internal port associated with floating ip '
                        'does not exist in bottom pod.')
            return

        b_int_net_pod, b_int_port_id = mappings[0]
        int_port = self.get_port(context, t_int_port_id)
        net_id = int_port['network_id']
        router_id = ori_floatingip_db['router_id']
        router = self._get_router(context, router_id)
        self.xjob_handler.setup_bottom_router(
            t_ctx, router['tenant_id'], net_id,
            ori_floatingip_db['router_id'], b_int_net_pod['pod_id'])

    def delete_floatingip(self, context, _id):
        """Disassociate floating ip if needed then delete it

        :param context: request context
        :param _id: ID of the floating ip
        :return: None
        """
        self.update_floatingip(context, _id, {'floatingip': {'port_id': None}})
        super(TricirclePlugin, self).delete_floatingip(context, _id)
