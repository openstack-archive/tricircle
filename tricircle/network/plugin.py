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


import oslo_log.helpers as log_helpers
from oslo_log import log

from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
from neutron.db import models_v2
from neutron.db import portbindings_db
from neutron.db import securitygroups_db
from neutron.db import sqlalchemyutils
from neutron.extensions import availability_zone as az_ext

from sqlalchemy import sql

import tricircle.common.client as t_client
import tricircle.common.context as t_context
from tricircle.common.i18n import _LI
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models


LOG = log.getLogger(__name__)


class TricirclePlugin(db_base_plugin_v2.NeutronDbPluginV2,
                      securitygroups_db.SecurityGroupDbMixin,
                      external_net_db.External_net_db_mixin,
                      portbindings_db.PortBindingMixin,
                      extradhcpopt_db.ExtraDhcpOptMixin):

    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    supported_extension_aliases = ["quotas",
                                   "extra_dhcp_opt",
                                   "binding",
                                   "security-group",
                                   "external-net",
                                   "network_availability_zone"]

    def __init__(self):
        super(TricirclePlugin, self).__init__()
        LOG.info(_LI("Starting Tricircle Neutron Plugin"))
        self.clients = {}
        self._setup_rpc()

    def _setup_rpc(self):
        self.endpoints = []

    def _get_client(self, pod_name):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    @log_helpers.log_method_call
    def start_rpc_listeners(self):
        pass
        # NOTE(zhiyuan) use later
        # self.topic = topics.PLUGIN
        # self.conn = n_rpc.create_connection(new=True)
        # self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        # return self.conn.consume_in_threads()

    @staticmethod
    def _validate_availability_zones(context, az_list):
        if not az_list:
            return
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin():
            pods = core.query_resource(t_ctx, models.PodMap, [], [])
            az_set = set(az_list)
            known_az_set = set([pod['pod_name'] for pod in pods])
            diff = az_set - known_az_set
            if diff:
                raise az_ext.AvailabilityZoneNotFound(
                    availability_zone=diff.pop())

    def create_network(self, context, network):
        net_data = network['network']
        if az_ext.AZ_HINTS in net_data:
            self._validate_availability_zones(context,
                                              net_data[az_ext.AZ_HINTS])
            az_hints = az_ext.convert_az_list_to_string(
                net_data[az_ext.AZ_HINTS])
            net_data[az_ext.AZ_HINTS] = az_hints
        return super(TricirclePlugin, self).create_network(context, network)

    def delete_network(self, context, network_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, network_id, 'network')
            for mapping in mappings:
                pod_name = mapping[0]['pod_name']
                bottom_network_id = mapping[1]
                self._get_client(pod_name).delete_networks(
                    t_ctx, bottom_network_id)
        except Exception:
            raise
        super(TricirclePlugin, self).delete_network(context, network_id)

    def update_network(self, context, network_id, network):
        return super(TricirclePlugin, self).update_network(
            context, network_id, network)

    def create_subnet(self, context, subnet):
        return super(TricirclePlugin, self).create_subnet(context, subnet)

    def delete_subnet(self, context, subnet_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, subnet_id, 'network')
            for mapping in mappings:
                pod_name = mapping[0]['pod_name']
                bottom_subnet_id = mapping[1]
                self._get_client(pod_name).delete_subnets(
                    t_ctx, bottom_subnet_id)
        except Exception:
            raise
        super(TricirclePlugin, self).delete_subnet(context, subnet_id)

    def update_subnet(self, context, subnet_id, subnet):
        return super(TricirclePlugin, self).update_network(
            context, subnet_id, subnet)

    def create_port(self, context, port):
        return super(TricirclePlugin, self).create_port(context, port)

    def delete_port(self, context, port_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(t_ctx,
                                                            port_id, 'port')
            if mappings:
                pod_name = mappings[0][0]['pod_name']
                bottom_port_id = mappings[0][1]
                self._get_client(pod_name).delete_ports(
                    t_ctx, bottom_port_id)
        except Exception:
            raise
        super(TricirclePlugin, self).delete_port(context, port_id)

    def update_port(self, context, port_id, port):
        return super(TricirclePlugin, self).update_port(
            context, port_id, port)

    def get_port(self, context, port_id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        mappings = db_api.get_bottom_mappings_by_top_id(t_ctx,
                                                        port_id, 'port')
        if mappings:
            pod_name = mappings[0][0]['pod_name']
            bottom_port_id = mappings[0][1]
            port = self._get_client(pod_name).get_ports(
                t_ctx, bottom_port_id)
            port['id'] = port_id
            if fields:
                port = dict(
                    [(k, v) for k, v in port.iteritems() if k in fields])
            if 'network_id' not in port and 'fixed_ips' not in port:
                return port

            bottom_top_map = {}
            with t_ctx.session.begin():
                for resource in ('subnet', 'network'):
                    route_filters = [{'key': 'resource_type',
                                      'comparator': 'eq',
                                      'value': resource}]
                    routes = core.query_resource(
                        t_ctx, models.ResourceRouting, route_filters, [])
                    for route in routes:
                        if route['bottom_id']:
                            bottom_top_map[
                                route['bottom_id']] = route['top_id']
            if 'network_id' in port and port['network_id'] in bottom_top_map:
                port['network_id'] = bottom_top_map[port['network_id']]
            if 'fixed_ips' in port:
                for ip in port['fixed_ips']:
                    if ip['subnet_id'] in bottom_top_map:
                        ip['subnet_id'] = bottom_top_map[ip['subnet_id']]

            return port
        else:
            return super(TricirclePlugin, self).get_port(context,
                                                         port_id, fields)

    @staticmethod
    def _apply_ports_filters(query, model, filters):
        if not filters:
            return query
        for key, value in filters.iteritems():
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
        query = sqlalchemyutils.paginate_query(
            query, models_v2.Port, search_step, [('id', False)],
            # create a dummy port object
            marker_obj=models_v2.Port(
                id=last_port_id) if last_port_id else None)
        total = 0
        ret = []
        for port in query:
            total += 1
            if port['id'] not in top_bottom_map:
                ret.append(port)
            if len(ret) == number:
                return ret
        # NOTE(zhiyuan) we have traverse all the ports
        if total < search_step:
            return ret
        else:
            ret.extend(self._get_ports_from_db_with_number(
                context, number - len(ret), ret[-1]['id'], top_bottom_map))

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
                    ret.append(port)
            return ret

    @staticmethod
    def _map_ports_from_bottom_to_top(res, bottom_top_map):
        # TODO(zhiyuan) judge if it's fine to remove unmapped port
        port_list = []
        for port in res['ports']:
            if port['id'] not in bottom_top_map:
                continue
            port['id'] = bottom_top_map[port['id']]
            if 'network_id' in port and port['network_id'] in bottom_top_map:
                port['network_id'] = bottom_top_map[port['network_id']]
            if 'fixed_ips' in port:
                for ip in port['fixed_ips']:
                    if ip['subnet_id'] in bottom_top_map:
                        ip['subnet_id'] = bottom_top_map[ip['subnet_id']]
            port_list.append(port)
        del res['ports']
        res['ports'] = port_list

    def _get_ports_from_pod_with_number(self, context,
                                        current_pod, number, last_port_id,
                                        bottom_top_map, top_bottom_map,
                                        filters=None):
        # NOTE(zhiyuan) last_port_id is top id, also id in returned port dict
        # also uses top id. when interacting with bottom pod, need to map
        # top to bottom in request and map bottom to top in response

        t_ctx = t_context.get_context_from_neutron_context(context)
        q_client = self._get_client(
            current_pod['pod_name']).get_native_client('port', t_ctx)
        params = {'limit': number}
        if filters:
            _filters = dict(filters)
            for key, value in _filters:
                if key == 'id' or key == 'network_id':
                    id_list = []
                    for _id in value:
                        if _id in top_bottom_map:
                            id_list.append(top_bottom_map[_id])
                        else:
                            id_list.append(_id)
                    _filters['id'] = id_list
            params.update(_filters)
        if last_port_id:
            # map top id to bottom id in request
            params['marker'] = top_bottom_map[last_port_id]
        res = q_client.get(q_client.ports_path, params=params)
        # map bottom id to top id in client response
        self._map_ports_from_bottom_to_top(res, bottom_top_map)

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
                    bottom_top_map, top_bottom_map, filters)
                next_res['ports'].extend(res['ports'])
                return next_res

    def get_ports(self, context, filters=None, fields=None, sorts=None,
                  limit=None, marker=None, page_reverse=False):
        t_ctx = t_context.get_context_from_neutron_context(context)
        with t_ctx.session.begin():
            bottom_top_map = {}
            top_bottom_map = {}
            for resource in ('port', 'subnet', 'network'):
                route_filters = [{'key': 'resource_type',
                                  'comparator': 'eq',
                                  'value': resource}]
                routes = core.query_resource(t_ctx, models.ResourceRouting,
                                             route_filters, [])

                for route in routes:
                    if route['bottom_id']:
                        bottom_top_map[route['bottom_id']] = route['top_id']
                        top_bottom_map[route['top_id']] = route['bottom_id']

        if limit:
            if marker:
                mappings = db_api.get_bottom_mappings_by_top_id(t_ctx,
                                                                marker, 'port')
                # NOTE(zhiyuan) if mapping exists, we retrieve port information
                # from bottom, otherwise from top
                if mappings:
                    pod_id = mappings[0][0]['pod_id']
                    current_pod = db_api.get_pod(t_ctx, pod_id)
                    res = self._get_ports_from_pod_with_number(
                        context, current_pod, limit, marker,
                        bottom_top_map, top_bottom_map, filters)
                else:
                    res = self._get_ports_from_top_with_number(
                        context, limit, marker, top_bottom_map, filters)

            else:
                current_pod = db_api.get_next_bottom_pod(t_ctx)
                # only top pod registered
                if current_pod:
                    res = self._get_ports_from_pod_with_number(
                        context, current_pod, limit, '',
                        bottom_top_map, top_bottom_map, filters)
                else:
                    res = self._get_ports_from_top_with_number(
                        context, limit, marker, top_bottom_map, filters)

            # NOTE(zhiyuan) we can safely return ports, neutron controller will
            # generate links for us so we do not need to worry about it.
            #
            # _get_ports_from_pod_with_number already traverses all the pods
            # to try to get ports equal to limit, so pod is transparent for
            # controller.
            return res['ports']
        else:
            ret = []
            pods = db_api.list_pods(t_ctx)
            for pod in pods:
                if not pod['az_name']:
                    continue
                _filters = []
                if filters:
                    for key, value in filters.iteritems():
                        if key == 'id' or key == 'network_id':
                            id_list = []
                            for _id in value:
                                if _id in top_bottom_map:
                                    id_list.append(top_bottom_map[_id])
                                else:
                                    id_list.append(_id)
                            _filters.append({'key': key,
                                             'comparator': 'eq',
                                             'value': id_list})
                        else:
                            _filters.append({'key': key,
                                             'comparator': 'eq',
                                             'value': value})
                client = self._get_client(pod['pod_name'])
                ret.extend(client.list_ports(t_ctx, filters=_filters))
            self._map_ports_from_bottom_to_top({'ports': ret}, bottom_top_map)
            ret.extend(self._get_ports_from_top(context, top_bottom_map,
                                                filters))
            return ret
