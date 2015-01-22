#!/usr/bin/env python
# Copyright 2011 VMware, Inc.
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
# @author: Haojie Jia, Huawei

import hashlib
import signal
import sys
import time
import os
import socket
import select

from neutron import context as n_context
from neutron.common import constants as const

import eventlet
eventlet.monkey_patch()

import netaddr
from oslo.config import cfg
from six import moves

from neutron.agent import l2population_rpc
from neutron.agent.linux import ip_lib
from neutron.agent.linux import ovs_lib
from neutron.agent.linux import polling
from neutron.agent.linux import utils
from neutron.agent import rpc as agent_rpc
from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.api.rpc.handlers import dvr_rpc
from neutron.common import config as common_config
from neutron.common import constants as q_const
from neutron.common import exceptions
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.common import utils as q_utils
from neutron import context
from neutron.openstack.common import log as logging
from neutron.openstack.common import loopingcall
from neutron.openstack.common import jsonutils
from neutron.plugins.common import constants as p_const
from neutron.plugins.l2_proxy.common import config  # noqa
from neutron.plugins.l2_proxy.common import constants
from neutron.plugins.l2_proxy.agent import neutron_proxy_context
from neutron.plugins.l2_proxy.agent import clients
from neutron.openstack.common import timeutils
from neutronclient.common import exceptions
from neutron.openstack.common import excutils


LOG = logging.getLogger(__name__)

# A placeholder for dead vlans.
DEAD_VLAN_TAG = str(q_const.MAX_VLAN_TAG + 1)


class DeviceListRetrievalError(exceptions.NeutronException):
    message = _("Unable to retrieve port details for devices: %(devices)s "
                "because of error: %(error)s")


class QueryPortsInterface:

    cascaded_neutron_client = None

    def __init__(self):
        self.context = n_context.get_admin_context_without_session()

    def _get_cascaded_neutron_client(self):
        context = n_context.get_admin_context_without_session()
        keystone_auth_url = cfg.CONF.AGENT.keystone_auth_url
        kwargs = {'auth_token': None,
                  'username': cfg.CONF.AGENT.neutron_user_name,
                  'password': cfg.CONF.AGENT.neutron_password,
                  'aws_creds': None,
                  'tenant': cfg.CONF.AGENT.neutron_tenant_name,
                  'auth_url': keystone_auth_url,
                  'roles': context.roles,
                  'is_admin': context.is_admin,
                  'region_name': cfg.CONF.AGENT.os_region_name}
        reqCon = neutron_proxy_context.RequestContext(**kwargs)
        openStackClients = clients.OpenStackClients(reqCon)
        neutronClient = openStackClients.neutron()
        return neutronClient

    def _show_port(self, port_id):
        portResponse = None
        if(not QueryPortsFromCascadedNeutron.cascaded_neutron_client):
            QueryPortsFromCascadedNeutron.cascaded_neutron_client = \
            self._get_cascaded_neutron_client()
        retry = 0
        while(True):
            try:
                portResponse = QueryPortsFromCascadedNeutron.\
                cascaded_neutron_client.show_port(port_id)
                LOG.debug(_('show port, port_id=%s, Response:%s'), str(port_id),
                             str(portResponse))
                return portResponse
            except exceptions.Unauthorized:
                retry = retry + 1
                if(retry <= 3):
                    QueryPortsFromCascadedNeutron.cascaded_neutron_client = \
                        self._get_cascaded_neutron_client()
                    continue
                else:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_('ERR: Try 3 times,Unauthorized to list ports!'))
                        return None
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('ERR: show port %s failed!'), port_id)
                return None

    def _list_ports(self, since_time=None,
                    pagination_limit=None,
                    pagination_marker=None):
        filters = {'status': 'ACTIVE'}
        if(since_time):
            filters['changes_since'] = since_time
        if(pagination_limit):
            filters['limit'] = pagination_limit
            filters['page_reverse'] = 'False'
        if(pagination_marker):
            filters['marker'] = pagination_marker
        portResponse = None
        if(not QueryPortsFromCascadedNeutron.cascaded_neutron_client):
            QueryPortsFromCascadedNeutron.cascaded_neutron_client = \
                  self._get_cascaded_neutron_client()
        retry = 0
        while(True):
            try:
                portResponse = QueryPortsFromCascadedNeutron.\
                cascaded_neutron_client.get('/ports', params=filters)
                LOG.debug(_('list ports, filters:%s, since_time:%s, limit=%s, '
                            'marker=%s, Response:%s'), str(filters),
                             str(since_time), str(pagination_limit),
                             str(pagination_marker), str(portResponse))
                return portResponse
            except exceptions.Unauthorized:
                retry = retry + 1
                if(retry <= 3):
                    QueryPortsFromCascadedNeutron.cascaded_neutron_client = \
                        self._get_cascaded_neutron_client()
                    continue
                else:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_('ERR: Try 3 times,Unauthorized to list ports!'))
                        return None
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('ERR: list ports failed!'))
                return None

    def _get_ports_pagination(self, since_time=None):
        ports_info = {'ports': []}
        if cfg.CONF.AGENT.pagination_limit == -1:
            port_ret = self._list_ports(since_time)
            if port_ret:
                ports_info['ports'].extend(port_ret.get('ports', []))
            return ports_info
        else:
            pagination_limit = cfg.CONF.AGENT.pagination_limit
            first_page = self._list_ports(since_time, pagination_limit)
            if(not first_page):
                return ports_info
            ports_info['ports'].extend(first_page.get('ports', []))
            ports_links_list = first_page.get('ports_links', [])
            while(True):
                last_port_id = None
                current_page = None
                for pl in ports_links_list:
                    if (pl.get('rel', None) == 'next'):
                        port_count = len(ports_info['ports'])
                        last_port_id = ports_info['ports'][port_count - 1].get('id')
                if(last_port_id):
                    current_page = self._list_ports(since_time,
                                                    pagination_limit,
                                                    last_port_id)
                if(not current_page):
                    return ports_info
                ports_info['ports'].extend(current_page.get('ports', []))
                ports_links_list = current_page.get('ports_links', [])


class QueryPortsFromNovaproxy(QueryPortsInterface):

    ports_info = {'ports': {'add': [], 'del': []}}

    def __init__(self):
        self.context = n_context.get_admin_context_without_session()
        self.sock_path = None
        self.sock = None

    def listen_and_recv_port_info(self, sock_path):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            path = sock_path
            if os.path.exists(path):
                os.unlink(path)
            sock.bind(path)
            sock.listen(5)
            while(True):
                infds, outfds, errfds = select.select([sock,], [], [], 5)
                if len(infds) != 0:
                    con, addr = sock.accept()
                    recv_data = con.recv(1024)
                    self.process_recv_data(recv_data)
        except socket.error as e:
            LOG.warn(_('Error while connecting to socket: %s'), e)
            return {}
#         con.close()
#         sock.close()

    def process_recv_data(self, data):
        LOG.debug(_('process_recv_data begin! data:%s'), data)
        data_dict = jsonutils.loads(data)
        ports = data_dict.get('ports', None)
        if(ports):
            added_ports = ports.get('add', [])
            for port_id in added_ports:
                port_ret = self._show_port(port_id)
                if port_ret and port_ret.get('port', None):
                    QueryPortsFromNovaproxy.ports_info['ports']['add']. \
                                      append(port_ret.get('port'))
#             removed_ports = ports.get('delete', [])

    def get_update_net_port_info(self, since_time=None):
        if(since_time):
            ports_info = QueryPortsFromNovaproxy.ports_info['ports'].get('add', [])
            QueryPortsFromNovaproxy.ports_info['ports']['add'] = []
        else:
            all_ports = self._get_ports_pagination()
            ports_info = all_ports.get('ports', [])
        return ports_info


class QueryPortsFromCascadedNeutron(QueryPortsInterface):

    def __init__(self):
        self.context = n_context.get_admin_context_without_session()

    def get_update_net_port_info(self, since_time=None):
        if since_time:
            ports = self._get_ports_pagination(since_time)
        else:
            ports = self._get_ports_pagination()
        return ports.get("ports", [])

#     def get_update_port_info_since(self, since_time):
#         ports = self._get_ports_pagination(since_time)
#         return ports.get("ports", [])


class RemotePort:

    def __init__(self, port_id, port_name, mac, binding_profile, ips=None):
        self.port_id = port_id
        self.port_name = port_name
        self.mac = mac
        self.binding_profile = binding_profile
        if(ips is None):
            self.ip = set()
        else:
            self.ip = set(ips)


class LocalPort:

    def __init__(self, port_id, cascaded_port_id, mac, ips=None):
        self.port_id = port_id
        self.cascaded_port_id = cascaded_port_id
        self.mac = mac
        if(ips is None):
            self.ip = set()
        else:
            self.ip = set(ips)


# A class to represent a VIF (i.e., a port that has 'iface-id' and 'vif-mac'
# attributes set).
class LocalVLANMapping:
    def __init__(self, network_type, physical_network, segmentation_id,
                 cascaded_net_id, vif_ports=None):
        if vif_ports is None:
            self.vif_ports = {}
        else:
            self.vif_ports = vif_ports

        self.network_type = network_type
        self.physical_network = physical_network
        self.segmentation_id = segmentation_id
        self.remote_ports = {}
        self.cascaded_net_id = cascaded_net_id
        self.cascaded_subnet = {}

    def __str__(self):
        return ("lv-id = %s type = %s phys-net = %s phys-id = %s" %
                (self.vlan, self.network_type, self.physical_network,
                 self.segmentation_id))


class OVSPluginApi(agent_rpc.PluginApi,
                   dvr_rpc.DVRServerRpcApiMixin,
                   sg_rpc.SecurityGroupServerRpcApiMixin):
    pass


class OVSSecurityGroupAgent(sg_rpc.SecurityGroupAgentRpcMixin):
    def __init__(self, context, plugin_rpc, root_helper):
        self.context = context
        self.plugin_rpc = plugin_rpc
        self.root_helper = root_helper
        self.init_firewall(defer_refresh_firewall=True)


class OVSNeutronAgent(n_rpc.RpcCallback,
                      sg_rpc.SecurityGroupAgentRpcCallbackMixin,
                      l2population_rpc.L2populationRpcCallBackTunnelMixin,
                      dvr_rpc.DVRAgentRpcCallbackMixin):
    '''Implements OVS-based tunneling, VLANs and flat networks.

    Two local bridges are created: an integration bridge (defaults to
    'br-int') and a tunneling bridge (defaults to 'br-tun'). An
    additional bridge is created for each physical network interface
    used for VLANs and/or flat networks.

    All VM VIFs are plugged into the integration bridge. VM VIFs on a
    given virtual network share a common "local" VLAN (i.e. not
    propagated externally). The VLAN id of this local VLAN is mapped
    to the physical networking details realizing that virtual network.

    For virtual networks realized as GRE tunnels, a Logical Switch
    (LS) identifier is used to differentiate tenant traffic on
    inter-HV tunnels. A mesh of tunnels is created to other
    Hypervisors in the cloud. These tunnels originate and terminate on
    the tunneling bridge of each hypervisor. Port patching is done to
    connect local VLANs on the integration bridge to inter-hypervisor
    tunnels on the tunnel bridge.

    For each virtual network realized as a VLAN or flat network, a
    veth or a pair of patch ports is used to connect the local VLAN on
    the integration bridge with the physical network bridge, with flow
    rules adding, modifying, or stripping VLAN tags as necessary.
    '''

    # history
    #   1.0 Initial version
    #   1.1 Support Security Group RPC
    #   1.2 Support DVR (Distributed Virtual Router) RPC
    RPC_API_VERSION = '1.2'

    def __init__(self, integ_br, tun_br, local_ip,
                 bridge_mappings, root_helper,
                 polling_interval, tunnel_types=None,
                 veth_mtu=None, l2_population=False,
                 enable_distributed_routing=False,
                 minimize_polling=False,
                 ovsdb_monitor_respawn_interval=(
                     constants.DEFAULT_OVSDBMON_RESPAWN),
                 arp_responder=False,
                 use_veth_interconnection=False):
        '''Constructor.

        :param integ_br: name of the integration bridge.
        :param tun_br: name of the tunnel bridge.
        :param local_ip: local IP address of this hypervisor.
        :param bridge_mappings: mappings from physical network name to bridge.
        :param root_helper: utility to use when running shell cmds.
        :param polling_interval: interval (secs) to poll DB.
        :param tunnel_types: A list of tunnel types to enable support for in
               the agent. If set, will automatically set enable_tunneling to
               True.
        :param veth_mtu: MTU size for veth interfaces.
        :param l2_population: Optional, whether L2 population is turned on
        :param minimize_polling: Optional, whether to minimize polling by
               monitoring ovsdb for interface changes.
        :param ovsdb_monitor_respawn_interval: Optional, when using polling
               minimization, the number of seconds to wait before respawning
               the ovsdb monitor.
        :param arp_responder: Optional, enable local ARP responder if it is
               supported.
        :param use_veth_interconnection: use veths instead of patch ports to
               interconnect the integration bridge to physical bridges.
        '''
        super(OVSNeutronAgent, self).__init__()
        self.use_veth_interconnection = use_veth_interconnection
        self.veth_mtu = veth_mtu
        self.root_helper = root_helper
        self.available_local_vlans = set(moves.xrange(q_const.MIN_VLAN_TAG,
                                                      q_const.MAX_VLAN_TAG))
        self.use_call = True
        self.tunnel_types = tunnel_types or []
        self.l2_pop = l2_population
        # TODO(ethuleau): Change ARP responder so it's not dependent on the
        #                 ML2 l2 population mechanism driver.
        self.enable_distributed_routing = enable_distributed_routing
        self.arp_responder_enabled = arp_responder and self.l2_pop
        self.agent_state = {
            'binary': 'neutron-openvswitch-agent',
            'host': cfg.CONF.host,
            'topic': q_const.L2_AGENT_TOPIC,
            'configurations': {'bridge_mappings': bridge_mappings,
                               'tunnel_types': self.tunnel_types,
                               'tunneling_ip': local_ip,
                               'l2_population': self.l2_pop,
                               'arp_responder_enabled':
                               self.arp_responder_enabled,
                               'enable_distributed_routing':
                               self.enable_distributed_routing},
            'agent_type': q_const.AGENT_TYPE_OVS,
            'start_flag': True}
        if(cfg.CONF.AGENT.query_ports_mode == 'cascaded_neutron'):
            self.query_ports_info_inter = QueryPortsFromCascadedNeutron()
        elif(cfg.CONF.AGENT.query_ports_mode == 'nova_proxy'):
            self.sock_path = cfg.CONF.AGENT.proxy_sock_path
            self.query_ports_info_inter = QueryPortsFromNovaproxy()
            eventlet.spawn_n(self.query_ports_info_inter.listen_and_recv_port_info,
                             self.sock_path)
        self.cascaded_port_info = {}
        self.cascaded_host_map = {}
        self.first_scan_flag = True

        # Keep track of int_br's device count for use by _report_state()
        self.int_br_device_count = 0

        self.int_br = ovs_lib.OVSBridge(integ_br, self.root_helper)
#         self.setup_integration_br()
        # Stores port update notifications for processing in main rpc loop
        self.updated_ports = set()
        self.setup_rpc()
        self.bridge_mappings = bridge_mappings
#         self.setup_physical_bridges(self.bridge_mappings)
        self.local_vlan_map = {}
        self.tun_br_ofports = {p_const.TYPE_GRE: {},
                               p_const.TYPE_VXLAN: {}}

        self.polling_interval = polling_interval
        self.minimize_polling = minimize_polling
        self.ovsdb_monitor_respawn_interval = ovsdb_monitor_respawn_interval

        if tunnel_types:
            self.enable_tunneling = True
        else:
            self.enable_tunneling = False
        self.local_ip = local_ip
        self.tunnel_count = 0
        self.vxlan_udp_port = cfg.CONF.AGENT.vxlan_udp_port
        self.dont_fragment = cfg.CONF.AGENT.dont_fragment
        self.tun_br = None
        self.patch_int_ofport = constants.OFPORT_INVALID
        self.patch_tun_ofport = constants.OFPORT_INVALID

#         self.dvr_agent.setup_dvr_flows_on_integ_tun_br()

        # Security group agent support
        self.sg_agent = OVSSecurityGroupAgent(self.context,
                                              self.plugin_rpc,
                                              root_helper)
        # Initialize iteration counter
        self.iter_num = 0
        self.run_daemon_loop = True

    def _report_state(self):
        # How many devices are likely used by a VM
        self.agent_state.get('configurations')['devices'] = (
            self.int_br_device_count)
        try:
            self.state_rpc.report_state(self.context,
                                        self.agent_state,
                                        self.use_call)
            self.use_call = False
            self.agent_state.pop('start_flag', None)
        except Exception:
            LOG.exception(_("Failed reporting state!"))

    def setup_rpc(self):
        self.agent_id = 'ovs-agent-%s' % cfg.CONF.host
        self.topic = topics.AGENT
        self.plugin_rpc = OVSPluginApi(topics.PLUGIN)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)

        # RPC network init
        self.context = context.get_admin_context_without_session()
        # Handle updates from service
        self.endpoints = [self]
        # Define the listening consumers for the agent
        consumers = [[topics.PORT, topics.UPDATE],
                     [topics.NETWORK, topics.DELETE],
                     [constants.TUNNEL, topics.UPDATE],
                     [topics.SECURITY_GROUP, topics.UPDATE],
                     [topics.DVR, topics.UPDATE]]
        if self.l2_pop:
            consumers.append([topics.L2POPULATION,
                              topics.UPDATE, cfg.CONF.host])
        self.connection = agent_rpc.create_consumers(self.endpoints,
                                                     self.topic,
                                                     consumers)
        report_interval = cfg.CONF.AGENT.report_interval
        if report_interval:
            heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            heartbeat.start(interval=report_interval)

    def get_net_uuid(self, vif_id):
        for network_id, vlan_mapping in self.local_vlan_map.iteritems():
            if vif_id in vlan_mapping.vif_ports:
                return network_id

    def network_delete(self, context, **kwargs):
        LOG.debug(_("network_delete received"))
        network_id = kwargs.get('network_id')
        LOG.debug(_("Delete %s"), network_id)
        # The network may not be defined on this agent
        lvm = self.local_vlan_map.get(network_id)
        if lvm:
            self.reclaim_local_vlan(network_id)
        else:
            LOG.debug(_("Network %s not used on agent."), network_id)

    def port_update(self, context, **kwargs):
        port = kwargs.get('port')
        # Put the port identifier in the updated_ports set.
        # Even if full port details might be provided to this call,
        # they are not used since there is no guarantee the notifications
        # are processed in the same order as the relevant API requests
        self.updated_ports.add(port['id'])
        LOG.debug(_("port_update message processed for port %s"), port['id'])

    def tunnel_update(self, context, **kwargs):
        LOG.debug(_("tunnel_update received"))

    def _create_port(self, context, network_id, binding_profile, port_name,
                     mac_address, ips):
        if(not network_id):
            LOG.error(_("No network id is specified, cannot create port"))
            return
        neutronClient = self.get_cascaded_neutron_client()
        req_props = {'network_id': network_id,
                     'name': port_name,
                     'admin_state_up': True,
                     'fixed_ips': [{'ip_address': ip} for ip in ips],
                     'mac_address': mac_address,
                     'binding:profile': binding_profile,
                     'device_owner': 'compute:'
                     }
        bodyResponse = neutronClient.create_port({'port': req_props})
        LOG.debug(_('create port, Response:%s'), str(bodyResponse))
        return bodyResponse

    def _destroy_port(self, context, port_id):
        if(not port_id):
            LOG.error(_("No port id is specified, cannot destroy port"))
            return

        openStackClients = self.get_cascaded_neutron_client()
        neutronClient = openStackClients.neutron()
        bodyResponse = neutronClient.delete_port(port_id)
        LOG.debug(_('destroy port, Response:%s'), str(bodyResponse))
        return bodyResponse

    def fdb_add(self, context, fdb_entries):
        LOG.debug("fdb_add received")
        for lvm, agent_ports in self.get_agent_ports(fdb_entries,
                                                     self.local_vlan_map):
            cascaded_net_id = lvm.cascaded_net_id
            if not cascaded_net_id:
                continue

            agent_ports.pop(self.local_ip, None)
            if len(agent_ports):
                for agent_ip, ports in agent_ports.items():
                    binding_profile = {"port_key": "remote_port",
                                       "host_ip": agent_ip}
                    port_name = 'remote_port'
                    mac_ip_map = {}
                    for port in ports:
                        if(port == q_const.FLOODING_ENTRY):
                            continue
                        if(const.DEVICE_OWNER_DVR_INTERFACE in port[1]):
                            return
                        ips = mac_ip_map.get(port[0])
                        if(ips):
                            ips += port[2]
                            mac_ip_map[port[0]] = ips
                        else:
                            mac_ip_map[port[0]] = [port[2]]
                    for mac_address, ips in mac_ip_map.items():
                        if(lvm.remote_ports.get(mac_address) or
                           lvm.vif_ports.get(mac_address)):
                            continue
                        port_ret = self._create_port(context,
                                                     cascaded_net_id,
                                                     binding_profile,
                                                     port_name,
                                                     mac_address,
                                                     ips)
                        if(not port_ret or
                           (port_ret and (not port_ret.get('port')))):
                            LOG.debug(_("remote port created failed, "
                                        "binding_profile:%s, mac_address:%s"),
                                      str(binding_profile), mac_address)
                            return
                        port_id = port_ret['port'].get('id', None)
                        if not port_id:
                            LOG.debug(_("remote port created failed, "
                                        "port_name%s, mac_address:%s"),
                                      port_name, mac_address)
                            return
                        remote_port = RemotePort(port_id,
                                                 port_name,
                                                 mac_address,
                                                 binding_profile,
                                                 ips)
                        lvm.remote_ports[mac_address] = remote_port

    def fdb_remove(self, context, fdb_entries):
        LOG.debug("fdb_remove received")
        for lvm, agent_ports in self.get_agent_ports(fdb_entries,
                                                     self.local_vlan_map):
            agent_ports.pop(self.local_ip, None)
            if len(agent_ports):
                for agent_ip, ports in agent_ports.items():
                    for port in ports:
                        local_p = lvm.vif_ports.pop(port[0], None)
                        if(local_p and local_p.port_id):
                            self.cascaded_port_info.pop(local_p.port_id, None)
                            continue
                        remote_p = lvm.remote_ports.pop(port[0], None)
                        if not remote_p:
                            continue
                        self._destroy_port(context, remote_p.port_id)

    def add_fdb_flow(self, br, port_info, remote_ip, lvm, ofport):
        '''TODO can not delete, by jiahaojie
        if delete,it will raise TypeError:
        Can't instantiate abstract class OVSNeutronAgent with abstract 
        methods add_fdb_flow, cleanup_tunnel_port, del_fdb_flow,
        setup_entry_for_arp_reply, setup_tunnel_port  '''
        LOG.debug("add_fdb_flow received")

    def del_fdb_flow(self, br, port_info, remote_ip, lvm, ofport):
        '''TODO can not delete, by jiahaojie
        if delete,it will raise TypeError:
        Can't instantiate abstract class OVSNeutronAgent with abstract
        methods add_fdb_flow, cleanup_tunnel_port, del_fdb_flow,
        setup_entry_for_arp_reply, setup_tunnel_port  '''
        LOG.debug("del_fdb_flow received")

    def setup_entry_for_arp_reply(self, br, action, local_vid, mac_address,
                                  ip_address):
        '''TODO can not delete, by jiahaojie
        if delete,it will raise TypeError: 
        Can't instantiate abstract class OVSNeutronAgent with abstract
        methods add_fdb_flow, cleanup_tunnel_port, del_fdb_flow,
        setup_entry_for_arp_reply, setup_tunnel_port  '''
        LOG.debug("setup_entry_for_arp_reply is called!")

    def provision_local_vlan(self, net_uuid, network_type, physical_network,
                             segmentation_id, cascaded_net_id):
        '''Provisions a local VLAN.

        :param net_uuid: the uuid of the network associated with this vlan.
        :param network_type: the network type ('gre', 'vxlan', 'vlan', 'flat',
                                               'local')
        :param physical_network: the physical network for 'vlan' or 'flat'
        :param segmentation_id: the VID for 'vlan' or tunnel ID for 'tunnel'
        '''

        # On a restart or crash of OVS, the network associated with this VLAN
        # will already be assigned, so check for that here before assigning a
        # new one.
        lvm = self.local_vlan_map.get(net_uuid)
        if lvm:
            lvid = lvm.vlan
        else:
            if not self.available_local_vlans:
                LOG.error(_("No local VLAN available for net-id=%s"), net_uuid)
                return
            lvid = self.available_local_vlans.pop()
            self.local_vlan_map[net_uuid] = LocalVLANMapping(
                                                             network_type,
                                                             physical_network,
                                                             segmentation_id,
                                                             cascaded_net_id)

        LOG.info(_("Assigning %(vlan_id)s as local vlan for "
                   "net-id=%(net_uuid)s"),
                 {'vlan_id': lvid, 'net_uuid': net_uuid})

    def reclaim_local_vlan(self, net_uuid):
        '''Reclaim a local VLAN.

        :param net_uuid: the network uuid associated with this vlan.
        :param lvm: a LocalVLANMapping object that tracks (vlan, lsw_id,
            vif_ids) mapping.
        '''
        lvm = self.local_vlan_map.pop(net_uuid, None)
        if lvm is None:
            LOG.debug(_("Network %s not used on agent."), net_uuid)
            return

        LOG.info(_("Reclaiming vlan = %(vlan_id)s from net-id = %(net_uuid)s"),
                 {'vlan_id': lvm.vlan,
                  'net_uuid': net_uuid})

        if len(lvm.vif_ports) > 0 or len(lvm.remote_ports) > 0:
            # should clear ports and delete network of cascaded layer
            # by jiahaojie 00209498
            pass
        else:
            LOG.error(_("Cannot reclaim unknown network type "
                        "%(network_type)s for net-id=%(net_uuid)s"),
                      {'network_type': lvm.network_type,
                       'net_uuid': net_uuid})

        self.available_local_vlans.add(lvm.vlan)

    def port_bound(self, port, net_uuid,
                   network_type, physical_network,
                   segmentation_id, fixed_ips, device_owner,
                   cascaded_port_info,
                   ovs_restarted):
        '''Bind port to net_uuid/lsw_id and install flow for inbound traffic
        to vm.

        :param port: a ovslib.VifPort object.
        :param net_uuid: the net_uuid this port is to be associated with.
        :param network_type: the network type ('gre', 'vlan', 'flat', 'local')
        :param physical_network: the physical network for 'vlan' or 'flat'
        :param segmentation_id: the VID for 'vlan' or tunnel ID for 'tunnel'
        :param fixed_ips: the ip addresses assigned to this port
        :param device_owner: the string indicative of owner of this port
        :param ovs_restarted: indicates if this is called for an OVS restart.
        '''
        if net_uuid not in self.local_vlan_map or ovs_restarted:
            self.provision_local_vlan(net_uuid, network_type,
                                      physical_network, segmentation_id,
                                      cascaded_port_info['network_id'])
        lvm = self.local_vlan_map[net_uuid]
        lvm.vif_ports[cascaded_port_info['mac_address']] = \
            LocalPort(port,
                      cascaded_port_info['id'],
                      cascaded_port_info['mac_address'])

    def get_port_id_from_profile(self, profile):
        return profile.get('cascading_port_id', None)

    def analysis_ports_info(self, ports_info):
        cur_ports = set()
        LOG.debug(_('jiahaojie---ports_info: %s'), str(ports_info))
        for port in ports_info:
            LOG.debug(_('jiahaojie---port: %s'), str(port))
            profile = port['binding:profile']
            cascading_port_id = self.get_port_id_from_profile(profile)
            if(not cascading_port_id):
                continue
            self.cascaded_port_info[cascading_port_id] = port
            cur_ports.add(cascading_port_id)
        return cur_ports

    def scan_ports(self, registered_ports, updated_ports=None):
        if(self.first_scan_flag):
            ports_info = self.query_ports_info_inter.get_update_net_port_info()
            self.first_scan_flag = False
        else:
            pre_time = time.time() - self.polling_interval - 1
            since_time = time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.gmtime(pre_time))
            ports_info = self.query_ports_info_inter.get_update_net_port_info(
                                                            since_time)
        added_or_updated_ports = self.analysis_ports_info(ports_info)
        cur_ports = set(self.cascaded_port_info.keys()) | added_or_updated_ports
        self.int_br_device_count = len(cur_ports)
        port_info = {'current': cur_ports}
        if updated_ports is None:
            updated_ports = set()
        #updated_ports.update(self.check_changed_vlans(registered_ports))
        if updated_ports:
            # Some updated ports might have been removed in the
            # meanwhile, and therefore should not be processed.
            # In this case the updated port won't be found among
            # current ports.
            updated_ports &= cur_ports
            if updated_ports:
                port_info['updated'] = updated_ports

        # FIXME(salv-orlando): It's not really necessary to return early
        # if nothing has changed.
        if cur_ports == registered_ports:
            # No added or removed ports to set, just return here
            return port_info

        port_info['added'] = cur_ports - registered_ports
        # Remove all the known ports not found on the integration bridge
        port_info['removed'] = registered_ports - cur_ports
        return port_info

    def treat_vif_port(self, vif_port, port_id, network_id, network_type,
                       physical_network, segmentation_id, admin_state_up,
                       fixed_ips, device_owner, cascaded_port_info,
                       ovs_restarted):
        # When this function is called for a port, the port should have
        # an OVS ofport configured, as only these ports were considered
        # for being treated. If that does not happen, it is a potential
        # error condition of which operators should be aware

        if admin_state_up:
            self.port_bound(vif_port, network_id, network_type,
                            physical_network, segmentation_id,
                            fixed_ips, device_owner, cascaded_port_info,
                            ovs_restarted)

    def setup_tunnel_port(self, br, remote_ip, network_type):
        '''TODO can not delete, by jiahaojie
        if delete,it will raise TypeError: 
        Can't instantiate abstract class OVSNeutronAgent with abstract 
        methods add_fdb_flow, cleanup_tunnel_port, del_fdb_flow, 
        setup_entry_for_arp_reply, setup_tunnel_port  '''
        LOG.debug("cleanup_tunnel_port is called!")

    def cleanup_tunnel_port(self, br, tun_ofport, tunnel_type):
        '''TODO can not delete, by jiahaojie
        if delete,it will raise TypeError: 
        Can't instantiate abstract class OVSNeutronAgent with abstract 
        methods add_fdb_flow, cleanup_tunnel_port, del_fdb_flow, 
        setup_entry_for_arp_reply, setup_tunnel_port  '''
        LOG.debug("cleanup_tunnel_port is called!")

    def compare_port_info(self, details, cascaded_port_info):
        if details is None or cascaded_port_info is None:
            return False
        details_ips_set = set([ip['ip_address']
                               for ip in details['fixed_ips']])
        cascaded_ips_set = set([ip['ip_address']
                                for ip in cascaded_port_info['fixed_ips']])
        return details_ips_set == cascaded_ips_set

    def get_cascading_neutron_client(self):
        context = n_context.get_admin_context_without_session()
        keystone_auth_url = cfg.CONF.AGENT.cascading_auth_url
        kwargs = {'auth_token': None,
                  'username': cfg.CONF.AGENT.cascading_user_name,
                  'password': cfg.CONF.AGENT.cascading_password,
                  'aws_creds': None,
                  'tenant': cfg.CONF.AGENT.cascading_tenant_name,
                  # 'tenant_id':'e8f280855dbe42a189eebb0f3ecb94bb', #context.values['tenant'],
                  'auth_url': keystone_auth_url,
                  'roles': context.roles,
                  'is_admin': context.is_admin,
                  'region_name': cfg.CONF.AGENT.cascading_os_region_name}
        reqCon = neutron_proxy_context.RequestContext(**kwargs)
        openStackClients = clients.OpenStackClients(reqCon)
        neutronClient = openStackClients.neutron()
        return neutronClient

    def update_cascading_port_profile(self, cascaded_host_ip,
                                      cascaded_port_info, details):
        if(not cascaded_host_ip):
            return
        profile = {'host_ip': cascaded_host_ip,
                   'cascaded_net_id': {
                       details['network_id']: {}},
                   'cascaded_subnet_id': {}}
        net_map = profile['cascaded_net_id'][details['network_id']]
        net_map[cfg.CONF.host] = cascaded_port_info['network_id']
        subnet_map = profile['cascaded_subnet_id']
        for fi_ing in details['fixed_ips']:
            for fi_ed in cascaded_port_info['fixed_ips']:
                if (fi_ed['ip_address'] == fi_ing['ip_address']):
                    subnet_map[fi_ing['subnet_id']] = {}
                    subnet_map[fi_ing['subnet_id']][cfg.CONF.host] = \
                        fi_ed['subnet_id']
                    break
        neutron_client = self.get_cascading_neutron_client()
        req_props = {"binding:profile": profile}
        port_ret = neutron_client.update_port(details['port_id'],
                                              {'port': req_props})
        LOG.debug(_('update compute port, Response:%s'), str(port_ret))

    def get_cascaded_neutron_client(self):
        context = n_context.get_admin_context_without_session()
        keystone_auth_url = cfg.CONF.AGENT.keystone_auth_url
        kwargs = {'auth_token': None,
                  'username': cfg.CONF.AGENT.neutron_user_name,
                  'password': cfg.CONF.AGENT.neutron_password,
                  'aws_creds': None,
                  'tenant': cfg.CONF.AGENT.neutron_tenant_name,
                  # 'tenant_id':'e8f280855dbe42a189eebb0f3ecb94bb', #context.values['tenant'],
                  'auth_url': keystone_auth_url,
                  'roles': context.roles,
                  'is_admin': context.is_admin,
                  'region_name': cfg.CONF.AGENT.os_region_name}
        reqCon = neutron_proxy_context.RequestContext(**kwargs)
        openStackClients = clients.OpenStackClients(reqCon)
        neutronClient = openStackClients.neutron()
        return neutronClient

    def get_cascaded_host_ip(self, ed_host_id):
        host_ip = self.cascaded_host_map.get(ed_host_id)
        if(host_ip):
            return host_ip
        neutron_client = self.get_cascaded_neutron_client()
        agent_ret = neutron_client.list_agents(host=ed_host_id,
                                               agent_type='Open vSwitch agent')
        if(not agent_ret or
           (agent_ret and (not agent_ret.get('agents')))):
            LOG.debug(_("get agent failed, host_id:%s"), ed_host_id)
            return
        agent_config = agent_ret['agents'][0].get('configurations', None)
        # json.loads(agent_config)
        configuration = agent_config
        host_ip = configuration.get('tunneling_ip')
        if(host_ip):
            self.cascaded_host_map[ed_host_id] = host_ip
        return host_ip

    def treat_devices_added_or_updated(self, devices, ovs_restarted):
        skipped_devices = []
        try:
            devices_details_list = self.plugin_rpc.get_devices_details_list(
                self.context,
                devices,
                self.agent_id,
                cfg.CONF.host)
        except Exception as e:
            raise DeviceListRetrievalError(devices=devices, error=e)
        for details in devices_details_list:
            device = details['device']
            LOG.debug("Processing port: %s", device)

            if 'port_id' in details:
                cascaded_port_info = self.cascaded_port_info.get(device)
                if(not self.compare_port_info(details, cascaded_port_info)):
                    LOG.info(_("Port %(device)s can not updated. "
                               "Because port info in cascading and cascaded layer"
                               "are different, Details: %(details)s"),
                             {'device': device, 'details': details})
                    skipped_devices.append(device)
                    return skipped_devices
                LOG.info(_("Port %(device)s updated. Details: %(details)s"),
                         {'device': device, 'details': details})
                self.treat_vif_port(device, details['port_id'],
                                    details['network_id'],
                                    details['network_type'],
                                    details['physical_network'],
                                    details['segmentation_id'],
                                    details['admin_state_up'],
                                    details['fixed_ips'],
                                    details['device_owner'],
                                    cascaded_port_info,
                                    ovs_restarted)
                # update cascading port, modify binding:profile to add host_ip
                # and cascaded net_id/cascaded_subnet_id
                if('compute' in details['device_owner']):
                    ed_host_id = cascaded_port_info['binding:host_id']
                    cascaded_host_ip = self.get_cascaded_host_ip(ed_host_id)
                    self.update_cascading_port_profile(cascaded_host_ip,
                                                       cascaded_port_info,
                                                       details)
                # update plugin about port status
                # FIXME(salv-orlando): Failures while updating device status
                # must be handled appropriately. Otherwise this might prevent
                # neutron server from sending network-vif-* events to the nova
                # API server, thus possibly preventing instance spawn.
                if details.get('admin_state_up'):
                    LOG.debug(_("Setting status for %s to UP"), device)
                    self.plugin_rpc.update_device_up(
                        self.context, device, self.agent_id, cfg.CONF.host)
                else:
                    LOG.debug(_("Setting status for %s to DOWN"), device)
                    self.plugin_rpc.update_device_down(
                        self.context, device, self.agent_id, cfg.CONF.host)
                LOG.info(_("Configuration for device %s completed."), device)
#             else:
#                 LOG.warn(_("Device %s not defined on plugin"), device)
#                 if (port and port.ofport != -1):
#                     self.port_dead(port)
        return skipped_devices

    def process_network_ports(self, port_info, ovs_restarted):
        resync_a = False
        resync_b = False
        # TODO(salv-orlando): consider a solution for ensuring notifications
        # are processed exactly in the same order in which they were
        # received. This is tricky because there are two notification
        # sources: the neutron server, and the ovs db monitor process
        # If there is an exception while processing security groups ports
        # will not be wired anyway, and a resync will be triggered
        # TODO(salv-orlando): Optimize avoiding applying filters unnecessarily
        # (eg: when there are no IP address changes)
        self.sg_agent.setup_port_filters(port_info.get('added', set()),
                                         port_info.get('updated', set()))
        # VIF wiring needs to be performed always for 'new' devices.
        # For updated ports, re-wiring is not needed in most cases, but needs
        # to be performed anyway when the admin state of a device is changed.
        # A device might be both in the 'added' and 'updated'
        # list at the same time; avoid processing it twice.
        devices_added_updated = (port_info.get('added', set()) |
                                 port_info.get('updated', set()))
        if devices_added_updated:
            start = time.time()
            try:
                skipped_devices = self.treat_devices_added_or_updated(
                    devices_added_updated, ovs_restarted)
                LOG.debug(_("process_network_ports - iteration:%(iter_num)d -"
                            "treat_devices_added_or_updated completed. "
                            "Skipped %(num_skipped)d devices of "
                            "%(num_current)d devices currently available. "
                            "Time elapsed: %(elapsed).3f"),
                          {'iter_num': self.iter_num,
                           'num_skipped': len(skipped_devices),
                           'num_current': len(port_info['current']),
                           'elapsed': time.time() - start})
                # Update the list of current ports storing only those which
                # have been actually processed.
                port_info['current'] = (port_info['current'] -
                                        set(skipped_devices))
            except DeviceListRetrievalError:
                # Need to resync as there was an error with server
                # communication.
                LOG.exception(_("process_network_ports - iteration:%d - "
                                "failure while retrieving port details "
                                "from server"), self.iter_num)
                resync_a = True
        if 'removed' in port_info:
            start = time.time()
            #resync_b = self.treat_devices_removed(port_info['removed'])
            LOG.debug(_("process_network_ports - iteration:%(iter_num)d -"
                        "treat_devices_removed completed in %(elapsed).3f"),
                      {'iter_num': self.iter_num,
                       'elapsed': time.time() - start})
        # If one of the above operations fails => resync with plugin
        return (resync_a | resync_b)

    def get_ip_in_hex(self, ip_address):
        try:
            return '%08x' % netaddr.IPAddress(ip_address, version=4)
        except Exception:
            LOG.warn(_("Unable to create tunnel port. Invalid remote IP: %s"),
                     ip_address)
            return

    def _port_info_has_changes(self, port_info):
        return (port_info.get('added') or
                port_info.get('removed') or
                port_info.get('updated'))

    def rpc_loop(self, polling_manager=None):
#         if not polling_manager:
#             polling_manager = polling.AlwaysPoll()

        sync = True
        ports = set()
        updated_ports_copy = set()
        ancillary_ports = set()
        ovs_restarted = False
        while self.run_daemon_loop:
            start = time.time()
            port_stats = {'regular': {'added': 0,
                                      'updated': 0,
                                      'removed': 0},
                          'ancillary': {'added': 0,
                                        'removed': 0}}
            LOG.debug(_("Agent rpc_loop - iteration:%d started"),
                      self.iter_num)
#             if sync:
#                 LOG.info(_("Agent out of sync with plugin!"))
#                 ports.clear()
#                 ancillary_ports.clear()
#                 sync = False
#                 polling_manager.force_polling()

#             if self._agent_has_updates(polling_manager) or ovs_restarted:
            if True:
                try:
                    LOG.debug(_("Agent rpc_loop - iteration:%(iter_num)d - "
                                "starting polling. Elapsed:%(elapsed).3f"),
                              {'iter_num': self.iter_num,
                               'elapsed': time.time() - start})
                    # Save updated ports dict to perform rollback in
                    # case resync would be needed, and then clear
                    # self.updated_ports. As the greenthread should not yield
                    # between these two statements, this will be thread-safe
                    updated_ports_copy = self.updated_ports
                    self.updated_ports = set()
                    reg_ports = (set() if ovs_restarted else ports)
                    #import pdb;pdb.set_trace()
                    port_info = self.scan_ports(reg_ports, updated_ports_copy)
                    LOG.debug(_("Agent rpc_loop - iteration:%(iter_num)d - "
                                "port information retrieved. "
                                "Elapsed:%(elapsed).3f"),
                              {'iter_num': self.iter_num,
                               'elapsed': time.time() - start})
                    # Secure and wire/unwire VIFs and update their status
                    # on Neutron server
                    if (self._port_info_has_changes(port_info) or
                        self.sg_agent.firewall_refresh_needed() or
                        ovs_restarted):
                        LOG.debug(_("Starting to process devices in:%s"),
                                  port_info)
                        # If treat devices fails - must resync with plugin
                        sync = self.process_network_ports(port_info,
                                                          ovs_restarted)
                        LOG.debug(_("Agent rpc_loop - iteration:%(iter_num)d -"
                                    "ports processed. Elapsed:%(elapsed).3f"),
                                  {'iter_num': self.iter_num,
                                   'elapsed': time.time() - start})
                        port_stats['regular']['added'] = (
                            len(port_info.get('added', [])))
                        port_stats['regular']['updated'] = (
                            len(port_info.get('updated', [])))
                        port_stats['regular']['removed'] = (
                            len(port_info.get('removed', [])))
                    ports = port_info['current']

#                     polling_manager.polling_completed()
                except Exception:
                    LOG.exception(_("Error while processing VIF ports"))
                    # Put the ports back in self.updated_port
                    self.updated_ports |= updated_ports_copy
                    sync = True

            # sleep till end of polling interval
            elapsed = (time.time() - start)
            LOG.debug(_("Agent rpc_loop - iteration:%(iter_num)d "
                        "completed. Processed ports statistics: "
                        "%(port_stats)s. Elapsed:%(elapsed).3f"),
                      {'iter_num': self.iter_num,
                       'port_stats': port_stats,
                       'elapsed': elapsed})
            if (elapsed < self.polling_interval):
                time.sleep(self.polling_interval - elapsed)
            else:
                LOG.debug(_("Loop iteration exceeded interval "
                            "(%(polling_interval)s vs. %(elapsed)s)!"),
                          {'polling_interval': self.polling_interval,
                           'elapsed': elapsed})
            self.iter_num = self.iter_num + 1

    def daemon_loop(self):
        with polling.get_polling_manager(
            self.minimize_polling) as pm:
            self.rpc_loop()
#         with polling.get_polling_manager(
#             self.minimize_polling,
#             self.root_helper,
#             self.ovsdb_monitor_respawn_interval) as pm:
#
#             self.rpc_loop(polling_manager=pm)

    def _handle_sigterm(self, signum, frame):
        LOG.debug("Agent caught SIGTERM, quitting daemon loop.")
        self.run_daemon_loop = False


def create_agent_config_map(config):
    """Create a map of agent config parameters.

    :param config: an instance of cfg.CONF
    :returns: a map of agent configuration parameters
    """
    try:
        bridge_mappings = q_utils.parse_mappings(config.OVS.bridge_mappings)
    except ValueError as e:
        raise ValueError(_("Parsing bridge_mappings failed: %s.") % e)

    kwargs = dict(
        integ_br=config.OVS.integration_bridge,
        tun_br=config.OVS.tunnel_bridge,
        local_ip=config.OVS.local_ip,
        bridge_mappings=bridge_mappings,
        root_helper=config.AGENT.root_helper,
        polling_interval=config.AGENT.polling_interval,
        minimize_polling=config.AGENT.minimize_polling,
        tunnel_types=config.AGENT.tunnel_types,
        veth_mtu=config.AGENT.veth_mtu,
        enable_distributed_routing=config.AGENT.enable_distributed_routing,
        l2_population=config.AGENT.l2_population,
        arp_responder=config.AGENT.arp_responder,
        use_veth_interconnection=config.OVS.use_veth_interconnection,
    )

    # If enable_tunneling is TRUE, set tunnel_type to default to GRE
    if config.OVS.enable_tunneling and not kwargs['tunnel_types']:
        kwargs['tunnel_types'] = [p_const.TYPE_GRE]

    # Verify the tunnel_types specified are valid
    for tun in kwargs['tunnel_types']:
        if tun not in constants.TUNNEL_NETWORK_TYPES:
            msg = _('Invalid tunnel type specified: %s'), tun
            raise ValueError(msg)
        if not kwargs['local_ip']:
            msg = _('Tunneling cannot be enabled without a valid local_ip.')
            raise ValueError(msg)

    return kwargs


def main():
    cfg.CONF.register_opts(ip_lib.OPTS)
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    q_utils.log_opt_values(LOG)

    try:
        agent_config = create_agent_config_map(cfg.CONF)
    except ValueError as e:
        LOG.error(_('%s Agent terminated!'), e)
        sys.exit(1)

    is_xen_compute_host = 'rootwrap-xen-dom0' in agent_config['root_helper']
    if is_xen_compute_host:
        # Force ip_lib to always use the root helper to ensure that ip
        # commands target xen dom0 rather than domU.
        cfg.CONF.set_default('ip_lib_force_root', True)

    agent = OVSNeutronAgent(**agent_config)
    signal.signal(signal.SIGTERM, agent._handle_sigterm)

    # Start everything.
    LOG.info(_("Agent initialized successfully, now running... "))
    agent.daemon_loop()


if __name__ == "__main__":
    main()
