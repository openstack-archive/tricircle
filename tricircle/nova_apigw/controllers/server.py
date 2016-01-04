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

import datetime
import eventlet

import pecan
from pecan import expose
from pecan import rest

import oslo_db.exception as db_exc
from oslo_utils import uuidutils

import tricircle.common.client as t_client
import tricircle.common.context as t_context
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models


class ServerController(rest.RestController):

    def __init__(self, project_id):
        self.project_id = project_id
        self.clients = {'top': t_client.Client()}

    def _get_client(self, pod_name='top'):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    def _get_or_create_route(self, context, pod, _id, _type):
        # use configuration option later
        route_expire_threshold = 30

        with context.session.begin():
            routes = core.query_resource(
                context, models.ResourceRouting,
                [{'key': 'top_id', 'comparator': 'eq', 'value': _id},
                 {'key': 'pod_id', 'comparator': 'eq',
                  'value': pod['pod_id']}], [])
            if routes:
                route = routes[0]
                if route['bottom_id']:
                    return route, False
                else:
                    route_time = route['updated_at'] or route['created_at']
                    current_time = datetime.datetime.utcnow()
                    delta = current_time - route_time
                    if delta.seconds > route_expire_threshold:
                        # NOTE(zhiyuan) cannot directly remove the route, we
                        # have a race that other worker is updating this route
                        # with bottom id, we need to check if the bottom
                        # element has been created by other worker
                        client = self._get_client(pod['pod_name'])
                        bottom_eles = client.list_resources(
                            _type, context, [{'key': 'name',
                                              'comparator': 'eq',
                                              'value': _id}])
                        if bottom_eles:
                            route['bottom_id'] = bottom_eles[0]['id']
                            core.update_resource(context,
                                                 models.ResourceRouting,
                                                 route['id'], route)
                            return route, False
                        try:
                            core.delete_resource(context,
                                                 models.ResourceRouting,
                                                 route['id'])
                        except db_exc.ResourceNotFound:
                            pass
        try:
            # NOTE(zhiyuan) try/except block inside a with block will cause
            # problem, so move them out of the block and manually handle the
            # session context
            context.session.begin()
            route = core.create_resource(context, models.ResourceRouting,
                                         {'top_id': _id,
                                          'pod_id': pod['pod_id'],
                                          'project_id': self.project_id,
                                          'resource_type': _type})
            context.session.commit()
            return route, True
        except db_exc.DBDuplicateEntry:
            context.session.rollback()
            return None, False
        finally:
            context.session.close()

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

    def _get_create_port_body(self, port, subnet_map, bottom_net_id):
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
        client = self._get_client(pod['pod_name'])
        # use configuration option later
        max_tries = 5
        for _ in xrange(max_tries):
            route, is_new = self._get_or_create_route(context,
                                                      pod, ele['id'], _type)
            if not route:
                eventlet.sleep(0)
                continue
            if not is_new and not route['bottom_id']:
                eventlet.sleep(0)
                continue
            if is_new:
                try:
                    bottom_ele = client.create_resources(_type, context, body)
                except Exception:
                    with context.session.begin():
                        try:
                            core.delete_resource(context,
                                                 models.ResourceRouting,
                                                 route['id'])
                        except db_exc.ResourceNotFound:
                            # NOTE(zhiyuan) this is a rare case that other
                            # worker considers the route expires and delete it
                            # though it was just created, maybe caused by
                            # out-of-sync time
                            pass
                    raise
                with context.session.begin():
                    # NOTE(zhiyuan) it's safe to update route, the bottom
                    # network has been successfully created, so other worker
                    # will not delete this route
                    route['bottom_id'] = bottom_ele['id']
                    core.update_resource(context, models.ResourceRouting,
                                         route['id'], route)
                    break
        if not route:
            raise Exception('Fail to create %s routing entry' % _type)
        if not route['bottom_id']:
            raise Exception('Fail to bind top and bottom %s' % _type)
        return route['bottom_id']

    def _handle_network(self, context, pod, net, subnets, port=None):
        # network
        net_body = self._get_create_network_body(net)
        bottom_net_id = self._prepare_neutron_element(context, pod, net,
                                                      'network', net_body)

        # subnet
        subnet_map = {}
        for subnet in subnets:
            subnet_body = self._get_create_subnet_body(subnet, bottom_net_id)
            bottom_subnet_id = self._prepare_neutron_element(
                context, pod, subnet, 'subnet', subnet_body)
            subnet_map[subnet['id']] = bottom_subnet_id
        top_client = self._get_client()
        top_port_body = {'port': {'network_id': net['id'],
                                  'admin_state_up': True}}

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
                context, t_dhcp_port['id'], 'port')
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
                                 'resource_type': 'port'})
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
                                          'resource_type': 'port'})
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
        port_body = self._get_create_port_body(port, subnet_map, bottom_net_id)
        bottom_port_id = self._prepare_neutron_element(context, pod, port,
                                                       'port', port_body)
        return bottom_port_id

    def _handle_port(self, context, pod, port):
        mappings = db_api.get_bottom_mappings_by_top_id(context,
                                                        port['id'], 'port')
        if mappings:
            # TODO(zhiyuan) judge return or raise exception
            # NOTE(zhiyuan) user provides a port that already has mapped
            # bottom port, return bottom id or raise an exception?
            return mappings[0][1]
        top_client = self._get_client()
        # NOTE(zhiyuan) at this moment, bottom port has not been created,
        # neutron plugin directly retrieves information from top, so the
        # network id and subnet id in this port dict are safe to use
        net = top_client.get_networks(context, port['network_id'])
        subnets = []
        for fixed_ip in port['fixed_ips']:
            subnets.append(top_client.get_subnets(context,
                                                  fixed_ip['subnet_id']))
        return self._handle_network(context, pod, net, subnets, port)

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

    def _get_all(self, context):
        ret = []
        pods = db_api.list_pods(context)
        for pod in pods:
            if not pod['az_name']:
                continue
            client = self._get_client(pod['pod_name'])
            ret.extend(client.list_servers(context))
        return ret

    def _schedule_pod(self, context, az):
        with context.session.begin():
            pod_bindings = core.query_resource(
                context, models.PodBinding,
                [{'key': 'tenant_id',
                  'comparator': 'eq',
                  'value': self.project_id}], [])
            for pod_binding in pod_bindings:
                pod = core.get_resource(context, models.Pod,
                                        pod_binding['pod_id'])
                if pod['az_name'] == az:
                    pods = core.query_resource(
                        context, models.Pod,
                        [{'key': 'pod_name',
                          'comparator': 'eq',
                          'value': pod['pod_name']}], [])
                    return pods[0], pod['pod_az_name']
            # no proper pod found, try to schedule one
            pods = core.query_resource(
                context, models.Pod,
                [{'key': 'az_name',
                  'comparator': 'eq',
                  'value': az}], [])
            if pods:
                # dump schedule, just select the first map
                select_pod = pods[0]

                pods = core.query_resource(
                    context, models.Pod,
                    [{'key': 'pod_name',
                      'comparator': 'eq',
                      'value': select_pod['pod_name']}], [])
                core.create_resource(
                    context, models.PodBinding,
                    {'id': uuidutils.generate_uuid(),
                     'tenant_id': self.project_id,
                     'pod_id': select_pod['pod_id']})
                return pods[0], select_pod['pod_az_name']
            else:
                return None, None

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if _id == 'detail':
            return {'servers': self._get_all(context)}

        mappings = db_api.get_bottom_mappings_by_top_id(context, _id, 'server')
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

        pod, b_az = self._schedule_pod(context,
                                       kw['server']['availability_zone'])
        if not pod:
            pecan.abort(400, 'No pod bound to availability zone')
            return

        server_body = self._get_create_server_body(kw['server'], b_az)

        top_client = self._get_client()
        if 'networks' in kw['server']:
            server_body['networks'] = []
            for net_info in kw['server']['networks']:
                if 'uuid' in net_info:
                    network = top_client.get_networks(context,
                                                      net_info['uuid'])
                    if not network:
                        pecan.abort(400, 'Network not found')
                        return
                    subnets = top_client.list_subnets(
                        context, [{'key': 'network_id',
                                   'comparator': 'eq',
                                   'value': network['id']}])
                    if not subnets:
                        pecan.abort(400, 'Network not contain subnets')
                        return
                    bottom_port_id = self._handle_network(context, pod,
                                                          network, subnets)
                elif 'port' in net_info:
                    port = top_client.get_ports(context, net_info['port'])
                    if not port:
                        pecan.abort(400, 'Port not found')
                        return
                    bottom_port_id = self._handle_port(context, pod, port)
                server_body['networks'].append({'port': bottom_port_id})

        client = self._get_client(pod['pod_name'])
        nics = [
            {'port-id': _port['port']} for _port in server_body['networks']]
        server = client.create_servers(context,
                                       name=server_body['name'],
                                       image=server_body['imageRef'],
                                       flavor=server_body['flavorRef'],
                                       nics=nics)
        with context.session.begin():
            core.create_resource(context, models.ResourceRouting,
                                 {'top_id': server['id'],
                                  'bottom_id': server['id'],
                                  'pod_id': pod['pod_id'],
                                  'project_id': self.project_id,
                                  'resource_type': 'server'})
        return {'server': server}
