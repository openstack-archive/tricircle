#
#    (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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

import random

from sqlalchemy.orm import exc

from neutron.common import constants as q_const
from neutron.db import l3_agentschedulers_db as l3agent_sch_db
from neutron.db import l3_db
from neutron.db import l3_gwmode_db  # noqa
from neutron.extensions import l3agentscheduler
from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class L3_DVRsch_db_mixin(l3_db.L3_NAT_db_mixin,
                         l3agent_sch_db.L3AgentSchedulerDbMixin):
    """Mixin class for L3 DVR scheduler.

    @l3_db.L3_NAT_db_mixin db mixin class for L3
    @l3agent_sch_db.L3AgentSchedulerDbMixin
    """
    def dvr_update_router_addvm(self, context, port):
        ips = port['fixed_ips']
        for ip in ips:
            subnet = ip['subnet_id']
            filter_sub = {'fixed_ips': {'subnet_id': [subnet]},
                          'device_owner':
                          [q_const.DEVICE_OWNER_DVR_INTERFACE]}
            router_id = None
            ports = self._core_plugin.get_ports(context,
                                                filters=filter_sub)
            for port in ports:
                router_id = port['device_id']
                router_dict = self._get_router(context, router_id)
                if router_dict.get('distributed', False):
                    payload = {'subnet_id': subnet}
                    self.l3_rpc_notifier.routers_updated(
                        context, [router_id], None, payload)
                    break
        LOG.debug('DVR: dvr_update_router_addvm %s ', router_id)

    def get_dvrrouters_by_vmportid(self, context, port_id):
        """Gets the dvr routers on vmport subnets."""
        router_ids = set()
        port_dict = self._core_plugin._get_port(context, port_id)
        fixed_ips = port_dict['fixed_ips']
        for fixedip in fixed_ips:
            vm_subnet = fixedip['subnet_id']
            filter_sub = {'fixed_ips': {'subnet_id': [vm_subnet]},
                          'device_owner':
                          [q_const.DEVICE_OWNER_DVR_INTERFACE]}
            subnetports = self._core_plugin.get_ports(context,
                                                      filters=filter_sub)
            for subnetport in subnetports:
                routerid = subnetport['device_id']
                router_ids.add(routerid)
        return router_ids

    def get_subnetids_on_router(self, context, router_id):
        """Only get subnet IDs for interfaces that are
        attached to the given router.
        """
        subnet_ids = set()
        filter_rtr = {'device_id': [router_id]}
        int_ports = self._core_plugin.get_ports(context,
                                                filters=filter_rtr)
        for int_port in int_ports:
            int_ips = int_port['fixed_ips']
            int_subnet = int_ips[0]['subnet_id']
            subnet_ids.add(int_subnet)
        return subnet_ids

    def check_vm_exists_onsubnet(self, context, host, port_id, subnet_id):
        """Check if there is any vm exists on the subnet_id."""
        filter_sub = {'fixed_ips': {'subnet_id': [subnet_id]}}
        ports = self._core_plugin.get_ports(context,
                                            filters=filter_sub)
        for port in ports:
            if ("compute:" in port['device_owner']
                and port['status'] == 'ACTIVE'
                and port['binding:host_id'] == host
                and port['id'] != port_id
                ):
                LOG.debug('DVR- Vm exists for subnet %(subnet_id)s on host '
                          '%(host)s', {'subnet_id': subnet_id,
                                       'host': host})
                return True
        return False

    def delete_namespace_onhost(self, context, host, router_id):
        """Delete the given router namespace on the host."""
        agent = self._core_plugin._get_agent_by_type_and_host(
            context, q_const.AGENT_TYPE_L3, host)
        agent_id = str(agent.id)
        with context.session.begin(subtransactions=True):
            bindings = (context.session.
                        query(l3agent_sch_db.RouterL3AgentBinding).
                        filter_by(router_id=router_id))
            for bind in bindings:
                if bind.l3_agent_id == agent_id:
                    context.session.delete(bind)
                    break
        self.l3_rpc_notifier.router_removed_from_agent(context,
                                                       router_id,
                                                       host)
        LOG.debug('Deleted router %(router_id)s on agent.id %(id)s',
                  {'router_id': router_id,
                   'id': agent.id})

    def dvr_deletens_ifnovm(self, context, port_id):
        """Delete the DVR namespace if no VM exists."""
        router_ids = self.get_dvrrouters_by_vmportid(context, port_id)
        port_host = self._core_plugin.get_bindinghost_by_portid(port_id)
        if not router_ids:
            LOG.debug('No namespaces available for this port %(port)s '
                      'on host %(host)s', {'port': port_id,
                                           'host': port_host})
            return
        for router_id in router_ids:
            subnet_ids = self.get_subnetids_on_router(context, router_id)
            for subnet in subnet_ids:
                if self.check_vm_exists_onsubnet(context,
                                                 port_host,
                                                 port_id,
                                                 subnet):
                    return
            filter_rtr = {'device_id': [router_id],
                          'device_owner':
                          [q_const.DEVICE_OWNER_DVR_INTERFACE]}
            int_ports = self._core_plugin.get_ports(context,
                                                    filters=filter_rtr)
            for prt in int_ports:
                dvr_binding = (self._core_plugin.
                               get_dvr_port_binding_by_host(context,
                                                            prt['id'],
                                                            port_host))
                if dvr_binding:
                    # unbind this port from router
                    dvr_binding['router_id'] = None
                    dvr_binding.update(dvr_binding)
            self.delete_namespace_onhost(context, port_host, router_id)
            LOG.debug('Deleted router namespace %(router_id)s '
                      'on host %(host)s', {'router_id': router_id,
                                           'host': port_host})

    def bind_snat_router(self, context, router_id, chosen_agent):
        """Bind the router to the chosen l3 agent."""
        with context.session.begin(subtransactions=True):
            binding = l3agent_sch_db.CentralizedSnatL3AgentBinding()
            binding.l3_agent = chosen_agent
            binding.router_id = router_id
            context.session.add(binding)
            LOG.debug('SNAT Router %(router_id)s is scheduled to L3 agent '
                      '%(agent_id)s', {'router_id': router_id,
                                       'agent_id': chosen_agent.id})

    def bind_dvrrouter_servicenode(self, context, router_id,
                                   chosen_snat_agent):
        """Bind the IR router to service node if not already hosted."""
        query = (context.session.query(l3agent_sch_db.RouterL3AgentBinding).
                 filter_by(router_id=router_id))
        for bind in query:
            if bind.l3_agent_id == chosen_snat_agent.id:
                LOG.debug('Distributed Router %(router_id)s already hosted '
                          'on snat l3_agent %(id)s',
                          {'router_id': router_id, 'id': chosen_snat_agent.id})
                return

        LOG.debug('Binding the distributed router %(router_id)s to '
                  'the snat agent %(id)s',
                  {'router_id': router_id,
                   'id': chosen_snat_agent.id})
        self.bind_router(context, router_id, chosen_snat_agent)

    def bind_snat_servicenode(self, context, router_id, snat_candidates):
        """Bind the snat router to the chosen l3 service agent."""
        chosen_snat_agent = random.choice(snat_candidates)
        self.bind_snat_router(context, router_id, chosen_snat_agent)

    def unbind_snat_servicenode(self, context, router_id):
        """Unbind the snat router to the chosen l3 service agent."""
        vm_exists = False
        agent_id = None
        vm_ports = []
        host = None
        with context.session.begin(subtransactions=True):
            query = (context.session.
                     query(l3agent_sch_db.CentralizedSnatL3AgentBinding).
                     filter_by(router_id=router_id))
            try:
                binding = query.one()
            except exc.NoResultFound:
                LOG.debug('no snat router is binding entry found '
                          '%(router_id)s', {'router_id': router_id})
                return

            host = binding.l3_agent.host
            subnet_ids = self.get_subnetids_on_router(context, router_id)
            for subnet in subnet_ids:
                vm_ports = (
                    self._core_plugin.get_compute_ports_on_host_by_subnet(
                        context, host, subnet))
                if vm_ports:
                    vm_exists = True
                    LOG.debug('vm exists on the snat enabled l3_agent '
                              'host %(host)s and router_id '
                              '%(router_id)s', {'host': host,
                                                'router_id':
                                                router_id})
                    break
            agent_id = binding.l3_agent_id
            LOG.debug('Delete the binding the SNAT router %(router_id)s '
                      'from agent %(id)s', {'router_id': router_id,
                                            'id': agent_id})
            context.session.delete(binding)

            if not vm_exists:
                query = (context.session.
                         query(l3agent_sch_db.RouterL3AgentBinding).
                         filter_by(router_id=router_id))
                for bind in query:
                    if bind.l3_agent_id == agent_id:
                        context.session.delete(bind)
                        self.l3_rpc_notifier.router_removed_from_agent(
                            context, router_id, host)
                        LOG.debug('Removed the binding for router '
                                  '%(router_id)s from agent %(id)s',
                                  {'router_id': router_id, 'id': agent_id})
                        break

    def schedule_snat_router(self, plugin, context, router_id, gw_exists):
        """Schedule the snat router on l3 service agent."""
        sync_router = plugin.get_router(context, router_id)
        if gw_exists:
            query = (context.session.
                     query(l3agent_sch_db.CentralizedSnatL3AgentBinding).
                     filter_by(router_id=router_id))
            for bind in query:
                agt_id = bind.l3_agent_id
                LOG.debug('SNAT Router %(router_id)s has already been '
                          'hosted by L3 agent '
                          '%(agent_id)s', {'router_id': router_id,
                                           'agent_id': agt_id})
                self.bind_dvrrouter_servicenode(context,
                                                router_id,
                                                bind.l3_agent)
                return
            active_l3_agents = plugin.get_l3_agents(context, active=True)
            if not active_l3_agents:
                LOG.warn(_('No active L3 agents'))
                return
            snat_candidates = plugin.get_snat_candidates(sync_router,
                                                         active_l3_agents)
            if snat_candidates:
                self.bind_snat_servicenode(context, router_id, snat_candidates)
            else:
                raise (l3agentscheduler.
                       NoSnatEnabledL3Agent(router_id=router_id))
        else:
            self.unbind_snat_servicenode(context, router_id)
