# Copyright (c) 2015 Huawei Tech. Co., Ltd.
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

import netaddr
import pecan
from pecan import expose
from pecan import rest
import six

import oslo_log.log as logging

import neutronclient.common.exceptions as q_exceptions

from tricircle.common import az_ag
import tricircle.common.client as t_client
from tricircle.common import constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
import tricircle.common.lock_handle as t_lock
from tricircle.common.quota import QUOTAS
from tricircle.common import utils
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models

LOG = logging.getLogger(__name__)

MAX_METADATA_KEY_LENGTH = 255
MAX_METADATA_VALUE_LENGTH = 255


class ServerController(rest.RestController):

    def __init__(self, project_id):
        self.project_id = project_id
        self.clients = {'top': t_client.Client()}

    def _get_client(self, pod_name='top'):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    def _get_all(self, context):
        ret = []
        pods = db_api.list_pods(context)
        for pod in pods:
            if not pod['az_name']:
                continue
            client = self._get_client(pod['pod_name'])
            servers = client.list_servers(context)
            self._remove_fip_info(servers)
            ret.extend(servers)
        return ret

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if _id == 'detail':
            return {'servers': self._get_all(context)}

        mappings = db_api.get_bottom_mappings_by_top_id(
            context, _id, constants.RT_SERVER)
        if not mappings:
            pecan.abort(404, 'Server not found')
            return
        pod, bottom_id = mappings[0]
        client = self._get_client(pod['pod_name'])
        server = client.get_servers(context, bottom_id)
        if not server:
            pecan.abort(404, 'Server not found')
            return
        else:
            return {'server': server}

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()
        return {'servers': self._get_all(context)}

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if 'server' not in kw:
            pecan.abort(400, 'Request body not found')
            return

        if 'availability_zone' not in kw['server']:
            pecan.abort(400, 'Availability zone not set')
            return

        pod, b_az = az_ag.get_pod_by_az_tenant(
            context, kw['server']['availability_zone'], self.project_id)
        if not pod:
            pecan.abort(400, 'No pod bound to availability zone')
            return

        t_server_dict = kw['server']
        self._process_metadata_quota(context, t_server_dict)
        self._process_injected_file_quota(context, t_server_dict)

        server_body = self._get_create_server_body(kw['server'], b_az)

        top_client = self._get_client()

        sg_filters = [{'key': 'tenant_id', 'comparator': 'eq',
                       'value': self.project_id}]
        top_sgs = top_client.list_security_groups(context, sg_filters)
        top_sg_map = dict((sg['name'], sg) for sg in top_sgs)

        if 'security_groups' not in kw['server']:
            security_groups = ['default']
        else:
            security_groups = []
            for sg in kw['server']['security_groups']:
                if 'name' not in sg:
                    pecan.abort(404, 'Security group name not specified')
                    return
                if sg['name'] not in top_sg_map:
                    pecan.abort(404,
                                'Security group %s not found' % sg['name'])
                    return
                security_groups.append(sg['name'])
        t_sg_ids, b_sg_ids, is_news = self._handle_security_group(
            context, pod, top_sg_map, security_groups)

        if 'networks' in kw['server']:
            server_body['networks'] = []
            for net_info in kw['server']['networks']:
                if 'uuid' in net_info:
                    network = top_client.get_networks(context,
                                                      net_info['uuid'])
                    if not network:
                        pecan.abort(400, 'Network not found')
                        return

                    if not self._check_network_server_the_same_az(
                            network, kw['server']['availability_zone']):
                        pecan.abort(400, 'Network and server not in the same '
                                         'availability zone')
                        return

                    subnets = top_client.list_subnets(
                        context, [{'key': 'network_id',
                                   'comparator': 'eq',
                                   'value': network['id']}])
                    if not subnets:
                        pecan.abort(400, 'Network not contain subnets')
                        return
                    t_port_id, b_port_id = self._handle_network(
                        context, pod, network, subnets,
                        top_sg_ids=t_sg_ids, bottom_sg_ids=b_sg_ids)
                elif 'port' in net_info:
                    port = top_client.get_ports(context, net_info['port'])
                    if not port:
                        pecan.abort(400, 'Port not found')
                        return
                    t_port_id, b_port_id = self._handle_port(
                        context, pod, port)
                server_body['networks'].append({'port': b_port_id})

        # only for security group first created in a pod, we invoke
        # _handle_sg_rule_for_new_group to initialize rules in that group, this
        # method removes all the rules in the new group then add new rules
        top_sg_id_map = dict((sg['id'], sg) for sg in top_sgs)
        new_top_sgs = []
        new_bottom_sg_ids = []
        default_sg = None
        for t_id, b_id, is_new in zip(t_sg_ids, b_sg_ids, is_news):
            sg_name = top_sg_id_map[t_id]['name']
            if sg_name == 'default':
                default_sg = top_sg_id_map[t_id]
                continue
            if not is_new:
                continue
            new_top_sgs.append(top_sg_id_map[t_id])
            new_bottom_sg_ids.append(b_id)
        self._handle_sg_rule_for_new_group(context, pod, new_top_sgs,
                                           new_bottom_sg_ids)
        if default_sg:
            self._handle_sg_rule_for_default_group(
                context, pod, default_sg, self.project_id)

        client = self._get_client(pod['pod_name'])
        nics = [
            {'port-id': _port['port']} for _port in server_body['networks']]

        server = client.create_servers(context,
                                       name=server_body['name'],
                                       image=server_body['imageRef'],
                                       flavor=server_body['flavorRef'],
                                       nics=nics,
                                       security_groups=b_sg_ids)
        with context.session.begin():
            core.create_resource(context, models.ResourceRouting,
                                 {'top_id': server['id'],
                                  'bottom_id': server['id'],
                                  'pod_id': pod['pod_id'],
                                  'project_id': self.project_id,
                                  'resource_type': constants.RT_SERVER})
        return {'server': server}

    def _get_or_create_route(self, context, pod, _id, _type):
        def list_resources(t_ctx, q_ctx, pod_, _id_, _type_):
            client = self._get_client(pod_['pod_name'])
            return client.list_resources(_type_, t_ctx, [{'key': 'name',
                                                          'comparator': 'eq',
                                                          'value': _id_}])

        return t_lock.get_or_create_route(context, None,
                                          self.project_id, pod, _id, _type,
                                          list_resources)

    def _get_create_network_body(self, network):
        body = {
            'network': {
                'tenant_id': self.project_id,
                'name': network['id'],
                'admin_state_up': True
            }
        }
        return body

    def _get_create_subnet_body(self, subnet, bottom_net_id):
        body = {
            'subnet': {
                'network_id': bottom_net_id,
                'name': subnet['id'],
                'ip_version': subnet['ip_version'],
                'cidr': subnet['cidr'],
                'gateway_ip': subnet['gateway_ip'],
                'allocation_pools': subnet['allocation_pools'],
                'enable_dhcp': subnet['enable_dhcp'],
                'tenant_id': self.project_id
            }
        }
        return body

    def _get_create_port_body(self, port, subnet_map, bottom_net_id,
                              security_group_ids=None):
        bottom_fixed_ips = []
        for ip in port['fixed_ips']:
            bottom_ip = {'subnet_id': subnet_map[ip['subnet_id']],
                         'ip_address': ip['ip_address']}
            bottom_fixed_ips.append(bottom_ip)
        body = {
            'port': {
                'tenant_id': self.project_id,
                'admin_state_up': True,
                'name': port['id'],
                'network_id': bottom_net_id,
                'mac_address': port['mac_address'],
                'fixed_ips': bottom_fixed_ips
            }
        }
        if security_group_ids:
            body['port']['security_groups'] = security_group_ids
        return body

    def _get_create_dhcp_port_body(self, port, bottom_subnet_id,
                                   bottom_net_id):
        body = {
            'port': {
                'tenant_id': self.project_id,
                'admin_state_up': True,
                'name': port['id'],
                'network_id': bottom_net_id,
                'fixed_ips': [
                    {'subnet_id': bottom_subnet_id,
                     'ip_address': port['fixed_ips'][0]['ip_address']}
                ],
                'mac_address': port['mac_address'],
                'binding:profile': {},
                'device_id': 'reserved_dhcp_port',
                'device_owner': 'network:dhcp',
            }
        }
        return body

    def _prepare_neutron_element(self, context, pod, ele, _type, body):
        def list_resources(t_ctx, q_ctx, pod_, _id_, _type_):
            client = self._get_client(pod_['pod_name'])
            return client.list_resources(_type_, t_ctx, [{'key': 'name',
                                                          'comparator': 'eq',
                                                          'value': _id_}])

        def create_resources(t_ctx, q_ctx, pod_, body_, _type_):
            client = self._get_client(pod_['pod_name'])
            return client.create_resources(_type_, t_ctx, body_)

        return t_lock.get_or_create_element(
            context, None,  # we don't need neutron context, so pass None
            self.project_id, pod, ele, _type, body,
            list_resources, create_resources)

    def _handle_network(self, context, pod, net, subnets, port=None,
                        top_sg_ids=None, bottom_sg_ids=None):
        # network
        net_body = self._get_create_network_body(net)
        _, bottom_net_id = self._prepare_neutron_element(context, pod, net,
                                                         'network', net_body)

        # subnet
        subnet_map = {}
        for subnet in subnets:
            subnet_body = self._get_create_subnet_body(subnet, bottom_net_id)
            _, bottom_subnet_id = self._prepare_neutron_element(
                context, pod, subnet, 'subnet', subnet_body)
            subnet_map[subnet['id']] = bottom_subnet_id
        top_client = self._get_client()
        top_port_body = {'port': {'network_id': net['id'],
                                  'admin_state_up': True}}
        if top_sg_ids:
            top_port_body['port']['security_groups'] = top_sg_ids

        # dhcp port
        client = self._get_client(pod['pod_name'])
        t_dhcp_port_filters = [
            {'key': 'device_owner', 'comparator': 'eq',
             'value': 'network:dhcp'},
            {'key': 'network_id', 'comparator': 'eq',
             'value': net['id']},
        ]
        b_dhcp_port_filters = [
            {'key': 'device_owner', 'comparator': 'eq',
             'value': 'network:dhcp'},
            {'key': 'network_id', 'comparator': 'eq',
             'value': bottom_net_id},
        ]
        top_dhcp_port_body = {
            'port': {
                'tenant_id': self.project_id,
                'admin_state_up': True,
                'name': 'dhcp_port',
                'network_id': net['id'],
                'binding:profile': {},
                'device_id': 'reserved_dhcp_port',
                'device_owner': 'network:dhcp',
            }
        }
        t_dhcp_ports = top_client.list_ports(context, t_dhcp_port_filters)
        t_subnet_dhcp_map = {}
        for dhcp_port in t_dhcp_ports:
            subnet_id = dhcp_port['fixed_ips'][0]['subnet_id']
            t_subnet_dhcp_map[subnet_id] = dhcp_port
        for t_subnet_id, b_subnet_id in subnet_map.iteritems():
            if t_subnet_id in t_subnet_dhcp_map:
                t_dhcp_port = t_subnet_dhcp_map[t_subnet_id]
            else:
                t_dhcp_port = top_client.create_ports(context,
                                                      top_dhcp_port_body)
            mappings = db_api.get_bottom_mappings_by_top_id(
                context, t_dhcp_port['id'], constants.RT_PORT)
            pod_list = [mapping[0]['pod_id'] for mapping in mappings]
            if pod['pod_id'] in pod_list:
                # mapping exists, skip this subnet
                continue

            dhcp_port_body = self._get_create_dhcp_port_body(
                t_dhcp_port, b_subnet_id, bottom_net_id)
            t_dhcp_ip = t_dhcp_port['fixed_ips'][0]['ip_address']

            b_dhcp_port = None
            try:
                b_dhcp_port = client.create_ports(context, dhcp_port_body)
            except Exception:
                # examine if we conflicted with a dhcp port which was
                # automatically created by bottom pod
                b_dhcp_ports = client.list_ports(context,
                                                 b_dhcp_port_filters)
                dhcp_port_match = False
                for dhcp_port in b_dhcp_ports:
                    subnet_id = dhcp_port['fixed_ips'][0]['subnet_id']
                    ip = dhcp_port['fixed_ips'][0]['ip_address']
                    if b_subnet_id == subnet_id and t_dhcp_ip == ip:
                        with context.session.begin():
                            core.create_resource(
                                context, models.ResourceRouting,
                                {'top_id': t_dhcp_port['id'],
                                 'bottom_id': dhcp_port['id'],
                                 'pod_id': pod['pod_id'],
                                 'project_id': self.project_id,
                                 'resource_type': constants.RT_PORT})
                        dhcp_port_match = True
                        break
                if not dhcp_port_match:
                    # so we didn't conflict with a dhcp port, raise exception
                    raise

            if b_dhcp_port:
                with context.session.begin():
                    core.create_resource(context, models.ResourceRouting,
                                         {'top_id': t_dhcp_port['id'],
                                          'bottom_id': b_dhcp_port['id'],
                                          'pod_id': pod['pod_id'],
                                          'project_id': self.project_id,
                                          'resource_type': constants.RT_PORT})
                # there is still one thing to do, there may be other dhcp ports
                # created by bottom pod, we need to delete them
                b_dhcp_ports = client.list_ports(context,
                                                 b_dhcp_port_filters)
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
                    client.delete_ports(context, dhcp_port_id)

        # port
        if not port:
            port = top_client.create_ports(context, top_port_body)
            port_body = self._get_create_port_body(
                port, subnet_map, bottom_net_id, bottom_sg_ids)
        else:
            port_body = self._get_create_port_body(port, subnet_map,
                                                   bottom_net_id)
        _, bottom_port_id = self._prepare_neutron_element(context, pod, port,
                                                          'port', port_body)
        return port['id'], bottom_port_id

    def _handle_port(self, context, pod, port):
        top_client = self._get_client()
        # NOTE(zhiyuan) at this moment, it is possible that the bottom port has
        # been created. if user creates a port and associate it with a floating
        # ip before booting a vm, tricircle plugin will create the bottom port
        # first in order to setup floating ip in bottom pod. but it is still
        # safe for us to use network id and subnet id in the returned port dict
        # since tricircle plugin will do id mapping and guarantee ids in the
        # dict are top id.
        net = top_client.get_networks(context, port['network_id'])
        subnets = []
        for fixed_ip in port['fixed_ips']:
            subnets.append(top_client.get_subnets(context,
                                                  fixed_ip['subnet_id']))
        return self._handle_network(context, pod, net, subnets, port=port)

    @staticmethod
    def _safe_create_security_group_rule(context, client, body):
        try:
            client.create_security_group_rules(context, body)
        except q_exceptions.Conflict:
            return

    @staticmethod
    def _safe_delete_security_group_rule(context, client, _id):
        try:
            client.delete_security_group_rules(context, _id)
        except q_exceptions.NotFound:
            return

    def _handle_security_group(self, context, pod, top_sg_map,
                               security_groups):
        t_sg_ids = []
        b_sg_ids = []
        is_news = []
        for sg_name in security_groups:
            t_sg = top_sg_map[sg_name]
            sg_body = {
                'security_group': {
                    'name': t_sg['id'],
                    'description': t_sg['description']}}
            is_new, b_sg_id = self._prepare_neutron_element(
                context, pod, t_sg, constants.RT_SG, sg_body)
            t_sg_ids.append(t_sg['id'])
            is_news.append(is_new)
            b_sg_ids.append(b_sg_id)

        return t_sg_ids, b_sg_ids, is_news

    @staticmethod
    def _construct_bottom_rule(rule, sg_id, ip=None):
        ip = ip or rule['remote_ip_prefix']
        # if ip is passed, this is a extended rule for remote group
        return {'remote_group_id': None,
                'direction': rule['direction'],
                'remote_ip_prefix': ip,
                'protocol': rule.get('protocol'),
                'ethertype': rule['ethertype'],
                'port_range_max': rule.get('port_range_max'),
                'port_range_min': rule.get('port_range_min'),
                'security_group_id': sg_id}

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key]:
                return False
        return True

    def _handle_sg_rule_for_default_group(self, context, pod, default_sg,
                                          project_id):
        top_client = self._get_client()
        new_b_rules = []
        for t_rule in default_sg['security_group_rules']:
            if not t_rule['remote_group_id']:
                # leave sg_id empty here
                new_b_rules.append(
                    self._construct_bottom_rule(t_rule, ''))
                continue
            if t_rule['ethertype'] != 'IPv4':
                continue
            subnets = top_client.list_subnets(
                context, [{'key': 'tenant_id', 'comparator': 'eq',
                           'value': project_id}])
            bridge_ip_net = netaddr.IPNetwork('100.0.0.0/8')
            for subnet in subnets:
                ip_net = netaddr.IPNetwork(subnet['cidr'])
                if ip_net in bridge_ip_net:
                    continue
                # leave sg_id empty here
                new_b_rules.append(
                    self._construct_bottom_rule(t_rule, '',
                                                subnet['cidr']))

        mappings = db_api.get_bottom_mappings_by_top_id(
            context, default_sg['id'], constants.RT_SG)
        for pod, b_sg_id in mappings:
            client = self._get_client(pod['pod_name'])
            b_sg = client.get_security_groups(context, b_sg_id)
            add_rules = []
            del_rules = []
            match_index = set()
            for b_rule in b_sg['security_group_rules']:
                match = False
                for i, rule in enumerate(new_b_rules):
                    if self._compare_rule(b_rule, rule):
                        match = True
                        match_index.add(i)
                        break
                if not match:
                    del_rules.append(b_rule)
            for i, rule in enumerate(new_b_rules):
                if i not in match_index:
                    add_rules.append(rule)

            for del_rule in del_rules:
                self._safe_delete_security_group_rule(
                    context, client, del_rule['id'])
            if add_rules:
                rule_body = {'security_group_rules': []}
                for add_rule in add_rules:
                    add_rule['security_group_id'] = b_sg_id
                    rule_body['security_group_rules'].append(add_rule)
                self._safe_create_security_group_rule(context,
                                                      client, rule_body)

    def _handle_sg_rule_for_new_group(self, context, pod, top_sgs,
                                      bottom_sg_ids):
        client = self._get_client(pod['pod_name'])
        for i, t_sg in enumerate(top_sgs):
            b_sg_id = bottom_sg_ids[i]
            new_b_rules = []
            for t_rule in t_sg['security_group_rules']:
                if t_rule['remote_group_id']:
                    # we do not handle remote group rule for non-default
                    # security group, actually tricircle plugin in neutron
                    # will reject such rule
                    # default security group is not passed with top_sgs so
                    # t_rule will not belong to default security group
                    continue
                new_b_rules.append(
                    self._construct_bottom_rule(t_rule, b_sg_id))
            try:
                b_sg = client.get_security_groups(context, b_sg_id)
                for b_rule in b_sg['security_group_rules']:
                    self._safe_delete_security_group_rule(
                        context, client, b_rule['id'])
                if new_b_rules:
                    rule_body = {'security_group_rules': new_b_rules}
                    self._safe_create_security_group_rule(context, client,
                                                          rule_body)
            except Exception:
                # if we fails when operating bottom security group rule, we
                # update the security group mapping to set bottom_id to None
                # and expire the mapping, so next time the security group rule
                # operations can be redone
                with context.session.begin():
                    routes = core.query_resource(
                        context, models.ResourceRouting,
                        [{'key': 'top_id', 'comparator': 'eq',
                          'value': t_sg['id']},
                         {'key': 'bottom_id', 'comparator': 'eq',
                          'value': b_sg_id}], [])
                    update_dict = {'bottom_id': None,
                                   'created_at': constants.expire_time,
                                   'updated_at': constants.expire_time}
                    core.update_resource(context, models.ResourceRouting,
                                         routes[0]['id'], update_dict)
                raise

    @staticmethod
    def _get_create_server_body(origin, bottom_az):
        body = {}
        copy_fields = ['name', 'imageRef', 'flavorRef',
                       'max_count', 'min_count']
        if bottom_az:
            body['availability_zone'] = bottom_az
        for field in copy_fields:
            if field in origin:
                body[field] = origin[field]
        return body

    @staticmethod
    def _remove_fip_info(servers):
        for server in servers:
            if 'addresses' not in server:
                continue
            for addresses in server['addresses'].values():
                remove_index = -1
                for i, address in enumerate(addresses):
                    if address.get('OS-EXT-IPS:type') == 'floating':
                        remove_index = i
                        break
                if remove_index >= 0:
                    del addresses[remove_index]

    @staticmethod
    def _check_network_server_the_same_az(network, server_az):
        az_hints = 'availability_zone_hints'
        # if neutron az not assigned, server az is used
        if not network.get(az_hints):
            return True
        # temporally not support cross-pod network
        if len(network[az_hints]) > 1:
            return False
        if network[az_hints][0] == server_az:
            return True
        else:
            return False

    def _process_injected_file_quota(self, context, t_server_dict):
        try:
            ctx = context.elevated()
            injected_files = t_server_dict.get('injected_files', None)
            self._check_injected_file_quota(ctx, injected_files)
        except (t_exceptions.OnsetFileLimitExceeded,
                t_exceptions.OnsetFilePathLimitExceeded,
                t_exceptions.OnsetFileContentLimitExceeded) as e:
            msg = str(e)
            LOG.exception(_LE('Quota exceeded %(msg)s'),
                          {'msg': msg})
            pecan.abort(400, _('Quota exceeded %s') % msg)

    def _check_injected_file_quota(self, context, injected_files):
        """Enforce quota limits on injected files.

        Raises a QuotaError if any limit is exceeded.

        """

        if injected_files is None:
            return

        # Check number of files first
        try:
            QUOTAS.limit_check(context,
                               injected_files=len(injected_files))
        except t_exceptions.OverQuota:
            raise t_exceptions.OnsetFileLimitExceeded()

        # OK, now count path and content lengths; we're looking for
        # the max...
        max_path = 0
        max_content = 0
        for path, content in injected_files:
            max_path = max(max_path, len(path))
            max_content = max(max_content, len(content))

        try:
            QUOTAS.limit_check(context,
                               injected_file_path_bytes=max_path,
                               injected_file_content_bytes=max_content)
        except t_exceptions.OverQuota as exc:
            # Favor path limit over content limit for reporting
            # purposes
            if 'injected_file_path_bytes' in exc.kwargs['overs']:
                raise t_exceptions.OnsetFilePathLimitExceeded()
            else:
                raise t_exceptions.OnsetFileContentLimitExceeded()

    def _process_metadata_quota(self, context, t_server_dict):
        try:
            ctx = context.elevated()
            metadata = t_server_dict.get('metadata', None)
            self._check_metadata_properties_quota(ctx, metadata)
        except t_exceptions.InvalidMetadata as e1:
            LOG.exception(_LE('Invalid metadata %(exception)s'),
                          {'exception': str(e1)})
            pecan.abort(400, _('Invalid metadata'))
        except t_exceptions.InvalidMetadataSize as e2:
            LOG.exception(_LE('Invalid metadata size %(exception)s'),
                          {'exception': str(e2)})
            pecan.abort(400, _('Invalid metadata size'))
        except t_exceptions.MetadataLimitExceeded as e3:
            LOG.exception(_LE('Quota exceeded %(exception)s'),
                          {'exception': str(e3)})
            pecan.abort(400, _('Quota exceeded in metadata'))

    def _check_metadata_properties_quota(self, context, metadata=None):
        """Enforce quota limits on metadata properties."""
        if not metadata:
            metadata = {}
        if not isinstance(metadata, dict):
            msg = (_("Metadata type should be dict."))
            raise t_exceptions.InvalidMetadata(reason=msg)
        num_metadata = len(metadata)
        try:
            QUOTAS.limit_check(context, metadata_items=num_metadata)
        except t_exceptions.OverQuota as exc:
            quota_metadata = exc.kwargs['quotas']['metadata_items']
            raise t_exceptions.MetadataLimitExceeded(allowed=quota_metadata)

        # Because metadata is processed in the bottom pod, we just do
        # parameter validation here to ensure quota management
        for k, v in six.iteritems(metadata):
            try:
                utils.check_string_length(v)
                utils.check_string_length(k, min_len=1)
            except t_exceptions.InvalidInput as e:
                raise t_exceptions.InvalidMetadata(reason=str(e))

            if len(k) > MAX_METADATA_KEY_LENGTH:
                msg = _("Metadata property key greater than 255 characters")
                raise t_exceptions.InvalidMetadataSize(reason=msg)
            if len(v) > MAX_METADATA_VALUE_LENGTH:
                msg = _("Metadata property value greater than 255 characters")
                raise t_exceptions.InvalidMetadataSize(reason=msg)
