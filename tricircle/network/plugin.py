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

from oslo_config import cfg
import oslo_log.helpers as log_helpers
from oslo_log import log
from oslo_utils import uuidutils

from neutron.api.v2 import attributes
from neutron.common import constants
from neutron.common import exceptions
from neutron.db import common_db_mixin
from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
# NOTE(zhiyuan) though not used, this import cannot be removed because Router
# relies on one table defined in l3_agentschedulers_db
from neutron.db import l3_agentschedulers_db  # noqa
from neutron.db import l3_db
from neutron.db import models_v2
from neutron.db import portbindings_db
from neutron.db import sqlalchemyutils
from neutron.extensions import availability_zone as az_ext
from neutron.extensions import external_net
from neutron.extensions import l3
from neutron.plugins.ml2.drivers import type_vlan
import neutron.plugins.ml2.models as ml2_models
import neutronclient.common.exceptions as q_cli_exceptions

from sqlalchemy import sql

from tricircle.common import az_ag
import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common.i18n import _LI
import tricircle.common.lock_handle as t_lock
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import security_groups


tricircle_opts = [
    cfg.StrOpt('bridge_physical_network',
               default='',
               help='name of l3 bridge physical network')
]
tricircle_opt_group = cfg.OptGroup('tricircle')
cfg.CONF.register_group(tricircle_opt_group)
cfg.CONF.register_opts(tricircle_opts, group=tricircle_opt_group)

LOG = log.getLogger(__name__)


class TricircleVlanTypeDriver(type_vlan.VlanTypeDriver):
    def __init__(self):
        super(TricircleVlanTypeDriver, self).__init__()

    # dump method
    def get_mtu(self, physical_network):
        return 0


class TricirclePlugin(db_base_plugin_v2.NeutronDbPluginV2,
                      security_groups.TricircleSecurityGroupMixin,
                      external_net_db.External_net_db_mixin,
                      portbindings_db.PortBindingMixin,
                      extradhcpopt_db.ExtraDhcpOptMixin,
                      l3_db.L3_NAT_dbonly_mixin):

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
                                   "router"]

    def __init__(self):
        super(TricirclePlugin, self).__init__()
        LOG.info(_LI("Starting Tricircle Neutron Plugin"))
        self.clients = {}
        self.xjob_handler = xrpcapi.XJobAPI()
        self._setup_rpc()
        # use VlanTypeDriver to allocate VLAN for bridge network
        self.vlan_driver = TricircleVlanTypeDriver()
        self.vlan_driver.initialize()

    def _setup_rpc(self):
        self.endpoints = []

    def _get_client(self, pod_name):
        if pod_name not in self.clients:
            self.clients[pod_name] = t_client.Client(pod_name)
        return self.clients[pod_name]

    @log_helpers.log_method_call
    def start_rpc_listeners(self):
        return []
        # NOTE(zhiyuan) use later
        # self.topic = topics.PLUGIN
        # self.conn = n_rpc.create_connection(new=True)
        # self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        # return self.conn.consume_in_threads()

    @staticmethod
    def _validate_availability_zones(context, az_list, external):
        if not az_list:
            return
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin():
            pods = core.query_resource(t_ctx, models.Pod, [], [])
            az_set = set(az_list)
            if external:
                known_az_set = set([pod['pod_name'] for pod in pods])
            else:
                known_az_set = set([pod['az_name'] for pod in pods])
            diff = az_set - known_az_set
            if diff:
                if external:
                    raise t_exceptions.PodNotFound(pod_name=diff.pop())
                else:
                    raise az_ext.AvailabilityZoneNotFound(
                        availability_zone=diff.pop())

    @staticmethod
    def _extend_availability_zone(net_res, net_db):
        net_res[az_ext.AZ_HINTS] = az_ext.convert_az_string_to_list(
            net_db[az_ext.AZ_HINTS])

    common_db_mixin.CommonDbMixin.register_dict_extend_funcs(
        attributes.NETWORKS, ['_extend_availability_zone'])

    @staticmethod
    def _ensure_az_set_for_external_network(req_data):
        external = req_data.get(external_net.EXTERNAL)
        external_set = attributes.is_attr_set(external)
        if not external_set or not external:
            return False
        if az_ext.AZ_HINTS in req_data and req_data[az_ext.AZ_HINTS]:
            return True
        raise t_exceptions.ExternalNetPodNotSpecify()

    def _create_bottom_external_network(self, context, net, top_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        # use the first pod
        pod_name = net[az_ext.AZ_HINTS][0]
        pod = db_api.get_pod_by_name(t_ctx, pod_name)
        body = {
            'network': {
                'name': top_id,
                'tenant_id': net['tenant_id'],
                'admin_state_up': True,
                external_net.EXTERNAL: True
            }
        }
        provider_attrs = ('provider:network_type', 'provider:segmentation_id',
                          'provider:physical_network')
        for provider_attr in provider_attrs:
            if attributes.is_attr_set(net.get(provider_attr)):
                body['network'][provider_attr] = net[provider_attr]

        self._prepare_bottom_element(
            t_ctx, net['tenant_id'], pod, {'id': top_id},
            t_constants.RT_NETWORK, body)

    def _create_bottom_external_subnet(self, context, subnet, net, top_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        pod_name = net[az_ext.AZ_HINTS][0]
        pod = db_api.get_pod_by_name(t_ctx, pod_name)
        b_net_id = db_api.get_bottom_id_by_top_id_pod_name(
            t_ctx, net['id'], pod_name, t_constants.RT_NETWORK)
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
            if attributes.is_attr_set(subnet.get(attr)):
                body['subnet'][attr] = subnet[attr]
        self._prepare_bottom_element(
            t_ctx, subnet['tenant_id'], pod, {'id': top_id},
            t_constants.RT_SUBNET, body)

    @property
    def _core_plugin(self):
        return self

    def create_network(self, context, network):
        net_data = network['network']
        is_external = self._ensure_az_set_for_external_network(net_data)
        if az_ext.AZ_HINTS in net_data:
            self._validate_availability_zones(context,
                                              net_data[az_ext.AZ_HINTS],
                                              is_external)
        with context.session.begin(subtransactions=True):
            res = super(TricirclePlugin, self).create_network(context, network)
            if az_ext.AZ_HINTS in net_data:
                az_hints = az_ext.convert_az_list_to_string(
                    net_data[az_ext.AZ_HINTS])
                update_res = super(TricirclePlugin, self).update_network(
                    context, res['id'],
                    {'network': {az_ext.AZ_HINTS: az_hints}})
                res[az_ext.AZ_HINTS] = update_res[az_ext.AZ_HINTS]
            self._process_l3_create(context, res, net_data)
            # put inside a session so when bottom operations fails db can
            # rollback
            if is_external:
                self._create_bottom_external_network(
                    context, net_data, res['id'])
        return res

    def delete_network(self, context, network_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, network_id, t_constants.RT_NETWORK)
            for mapping in mappings:
                pod_name = mapping[0]['pod_name']
                bottom_network_id = mapping[1]
                self._get_client(pod_name).delete_networks(
                    t_ctx, bottom_network_id)
                with t_ctx.session.begin():
                    core.delete_resources(
                        t_ctx, models.ResourceRouting,
                        filters=[{'key': 'top_id', 'comparator': 'eq',
                                  'value': network_id},
                                 {'key': 'pod_id', 'comparator': 'eq',
                                  'value': mapping[0]['pod_id']}])
        except Exception:
            raise
        with t_ctx.session.begin():
            core.delete_resources(t_ctx, models.ResourceRouting,
                                  filters=[{'key': 'top_id',
                                            'comparator': 'eq',
                                            'value': network_id}])
        super(TricirclePlugin, self).delete_network(context, network_id)

    def update_network(self, context, network_id, network):
        return super(TricirclePlugin, self).update_network(
            context, network_id, network)

    def create_subnet(self, context, subnet):
        subnet_data = subnet['subnet']
        network = self.get_network(context, subnet_data['network_id'])
        with context.session.begin(subtransactions=True):
            res = super(TricirclePlugin, self).create_subnet(context, subnet)
            # put inside a session so when bottom operations fails db can
            # rollback
            if network.get(external_net.EXTERNAL):
                self._create_bottom_external_subnet(
                    context, res, network, res['id'])
        return res

    def delete_subnet(self, context, subnet_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, subnet_id, t_constants.RT_SUBNET)
            for mapping in mappings:
                pod_name = mapping[0]['pod_name']
                bottom_subnet_id = mapping[1]
                self._get_client(pod_name).delete_subnets(
                    t_ctx, bottom_subnet_id)
                with t_ctx.session.begin():
                    core.delete_resources(
                        t_ctx, models.ResourceRouting,
                        filters=[{'key': 'top_id', 'comparator': 'eq',
                                  'value': subnet_id},
                                 {'key': 'pod_id', 'comparator': 'eq',
                                  'value': mapping[0]['pod_id']}])
        except Exception:
            raise
        super(TricirclePlugin, self).delete_subnet(context, subnet_id)

    def update_subnet(self, context, subnet_id, subnet):
        return super(TricirclePlugin, self).update_network(
            context, subnet_id, subnet)

    def create_port(self, context, port):
        return super(TricirclePlugin, self).create_port(context, port)

    def update_port(self, context, port_id, port):
        # TODO(zhiyuan) handle bottom port update
        # be careful that l3_db will call update_port to update device_id of
        # router interface, we cannot directly update bottom port in this case,
        # otherwise we will fail when attaching bottom port to bottom router
        # because its device_id is not empty
        return super(TricirclePlugin, self).update_port(context, port_id, port)

    def delete_port(self, context, port_id, l3_port_check=True):
        t_ctx = t_context.get_context_from_neutron_context(context)
        try:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, port_id, t_constants.RT_PORT)
            if mappings:
                pod_name = mappings[0][0]['pod_name']
                bottom_port_id = mappings[0][1]
                self._get_client(pod_name).delete_ports(
                    t_ctx, bottom_port_id)
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
                ret.append(self._make_port_dict(port))
            if len(ret) == number:
                return ret
        # NOTE(zhiyuan) we have traversed all the ports
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
                id_list = self._get_map_filter_ids(
                    key, value, current_pod['pod_id'], top_bottom_map)
                if id_list:
                    _filters[key] = id_list
            params.update(_filters)
        if last_port_id:
            # map top id to bottom id in request
            params['marker'] = top_bottom_map[last_port_id]
        res = q_client.get(q_client.ports_path, params=params)
        # map bottom id to top id in client response
        mapped_port_list = self._map_ports_from_bottom_to_top(res['ports'],
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
                    bottom_top_map, top_bottom_map, filters)
                next_res['ports'].extend(res['ports'])
                return next_res

    def get_ports(self, context, filters=None, fields=None, sorts=None,
                  limit=None, marker=None, page_reverse=False):
        t_ctx = t_context.get_context_from_neutron_context(context)
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
                client = self._get_client(pod['pod_name'])
                ret.extend(client.list_ports(t_ctx, filters=_filters))
            ret = self._map_ports_from_bottom_to_top(ret, bottom_top_map)
            ret.extend(self._get_ports_from_top(context, top_bottom_map,
                                                filters))
            return ret

    def create_router(self, context, router):
        return super(TricirclePlugin, self).create_router(context, router)

    def delete_router(self, context, _id):
        super(TricirclePlugin, self).delete_router(context, _id)

    def _judge_network_across_pods(self, context, interface, add_by_port):
        if add_by_port:
            port = self.get_port(context, interface['port_id'])
            net_id = port['network_id']
        else:
            subnet = self.get_subnet(context, interface['subnet_id'])
            net_id = subnet['network_id']
        network = self.get_network(context, net_id)
        if len(network.get(az_ext.AZ_HINTS, [])) != 1:
            # Currently not support cross pods l3 networking so
            # raise an exception here
            raise Exception('Cross pods L3 networking not support')
        return network[az_ext.AZ_HINTS][0], network

    def _prepare_top_element(self, t_ctx, q_ctx,
                             project_id, pod, ele, _type, body):
        def list_resources(t_ctx_, q_ctx_, pod_, _id_, _type_):
            return getattr(self, 'get_%ss' % _type_)(
                q_ctx_, filters={'name': _id_})

        def create_resources(t_ctx_, q_ctx_, pod_, body_, _type_):
            return getattr(self, 'create_%s' % _type_)(q_ctx_, body_)

        return t_lock.get_or_create_element(
            t_ctx, q_ctx,
            project_id, pod, ele, _type, body,
            list_resources, create_resources)

    def _prepare_bottom_element(self, t_ctx,
                                project_id, pod, ele, _type, body):
        def list_resources(t_ctx_, q_ctx, pod_, _id_, _type_):
            client = self._get_client(pod_['pod_name'])
            return client.list_resources(_type_, t_ctx_, [{'key': 'name',
                                                           'comparator': 'eq',
                                                           'value': _id_}])

        def create_resources(t_ctx_, q_ctx, pod_, body_, _type_):
            client = self._get_client(pod_['pod_name'])
            return client.create_resources(_type_, t_ctx_, body_)

        return t_lock.get_or_create_element(
            t_ctx, None,  # we don't need neutron context, so pass None
            project_id, pod, ele, _type, body,
            list_resources, create_resources)

    def _get_bridge_subnet_pool_id(self, t_ctx, q_ctx, project_id, pod, is_ew):
        if is_ew:
            pool_name = t_constants.ew_bridge_subnet_pool_name
            pool_cidr = '100.0.0.0/9'
        else:
            pool_name = t_constants.ns_bridge_subnet_pool_name
            pool_cidr = '100.128.0.0/9'
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
                                   pool_id, is_ew):
        if is_ew:
            net_name = t_constants.ew_bridge_net_name % project_id
            net_ele = {'id': net_name}
            subnet_name = t_constants.ew_bridge_subnet_name % project_id
            subnet_ele = {'id': subnet_name}
        else:
            net_name = t_constants.ns_bridge_net_name % project_id
            net_ele = {'id': net_name}
            subnet_name = t_constants.ns_bridge_subnet_name % project_id
            subnet_ele = {'id': subnet_name}

        is_admin = q_ctx.is_admin
        q_ctx.is_admin = True

        net_body = {'network': {'tenant_id': project_id,
                                'name': net_name,
                                'shared': False,
                                'admin_state_up': True}}
        _, net_id = self._prepare_top_element(
            t_ctx, q_ctx, project_id, pod, net_ele, 'network', net_body)

        # allocate a VLAN id for bridge network
        phy_net = cfg.CONF.tricircle.bridge_physical_network
        with q_ctx.session.begin():
            query = q_ctx.session.query(ml2_models.NetworkSegment)
            query = query.filter_by(network_id=net_id)
            if not query.first():
                segment = self.vlan_driver.reserve_provider_segment(
                    q_ctx.session, {'physical_network': phy_net})
                record = ml2_models.NetworkSegment(
                    id=uuidutils.generate_uuid(),
                    network_id=net_id,
                    network_type='vlan',
                    physical_network=phy_net,
                    segmentation_id=segment['segmentation_id'],
                    segment_index=0,
                    is_dynamic=False
                )
                q_ctx.session.add(record)

        subnet_body = {
            'subnet': {
                'network_id': net_id,
                'name': subnet_name,
                'prefixlen': 24,
                'ip_version': 4,
                'allocation_pools': attributes.ATTR_NOT_SPECIFIED,
                'dns_nameservers': attributes.ATTR_NOT_SPECIFIED,
                'host_routes': attributes.ATTR_NOT_SPECIFIED,
                'cidr': attributes.ATTR_NOT_SPECIFIED,
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

    def _get_bottom_elements(self, t_ctx, project_id, pod,
                             t_net, t_subnet, t_port):
        net_body = {
            'network': {
                'tenant_id': project_id,
                'name': t_net['id'],
                'admin_state_up': True
            }
        }
        _, net_id = self._prepare_bottom_element(
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
        _, subnet_id = self._prepare_bottom_element(
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
        _, port_id = self._prepare_bottom_element(
            t_ctx, project_id, pod, t_port, 'port', port_body)
        return port_id

    def _get_bridge_interface(self, t_ctx, q_ctx, project_id, pod,
                              t_net_id, b_router_id, b_port_id, is_ew):
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
                'device_owner': '',
                'mac_address': attributes.ATTR_NOT_SPECIFIED,
                'fixed_ips': attributes.ATTR_NOT_SPECIFIED
            }
        }
        _, port_id = self._prepare_top_element(
            t_ctx, q_ctx, project_id, pod, port_ele, 'port', port_body)
        return self.get_port(q_ctx, port_id)

    def _get_bottom_bridge_elements(self, q_ctx, project_id,
                                    pod, t_net, is_external, t_subnet, t_port):
        t_ctx = t_context.get_context_from_neutron_context(q_ctx)

        phy_net = cfg.CONF.tricircle.bridge_physical_network
        with q_ctx.session.begin():
            query = q_ctx.session.query(ml2_models.NetworkSegment)
            query = query.filter_by(network_id=t_net['id'])
            vlan = query.first().segmentation_id

        net_body = {'network': {'tenant_id': project_id,
                                'name': t_net['id'],
                                'provider:network_type': 'vlan',
                                'provider:physical_network': phy_net,
                                'provider:segmentation_id': vlan,
                                'admin_state_up': True}}
        if is_external:
            net_body['network'][external_net.EXTERNAL] = True
        _, b_net_id = self._prepare_bottom_element(
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
        _, b_subnet_id = self._prepare_bottom_element(
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
            is_new, b_port_id = self._prepare_bottom_element(
                t_ctx, project_id, pod, t_port, 'port', port_body)

            return is_new, b_port_id, b_subnet_id, b_net_id
        else:
            return None, None, b_subnet_id, b_net_id

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

    def _unbound_top_interface(self, context, router_id, port_id):
        super(TricirclePlugin, self).update_port(
            context, port_id, {'port': {'device_id': '',
                                        'device_owner': ''}})
        with context.session.begin():
            query = context.session.query(l3_db.RouterPort)
            query.filter_by(port_id=port_id, router_id=router_id).delete()

    def _update_bottom_router_gateway(self, context, router_id, router_data):
        ext_net_id = router_data[l3.EXTERNAL_GW_INFO].get('network_id')
        if ext_net_id:
            # add router gateway
            t_ctx = t_context.get_context_from_neutron_context(context)
            network = self.get_network(context, ext_net_id)
            pod_name = network[az_ext.AZ_HINTS][0]
            pod = db_api.get_pod_by_name(t_ctx, pod_name)
            b_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                t_ctx, ext_net_id, pod_name, t_constants.RT_NETWORK)
            t_router = self._get_router(context, router_id)
            body = {'router': {'name': router_id,
                               'distributed': False}}
            _, b_router_id = self._prepare_bottom_element(
                t_ctx, t_router['tenant_id'], pod, t_router,
                t_constants.RT_ROUTER, body)
            b_client = self._get_client(pod_name)
            t_info = router_data[l3.EXTERNAL_GW_INFO]
            b_info = {'network_id': b_net_id}
            if 'enable_snat' in t_info:
                b_info['enable_snat'] = t_info['enable_snat']
            if 'external_fixed_ips' in t_info:
                fixed_ips = []
                for ip in t_info['external_fixed_ips']:
                    t_subnet_id = ip['subnet_id']
                    b_subnet_id = db_api.get_bottom_id_by_top_id_pod_name(
                        t_ctx, t_subnet_id, pod_name,
                        t_constants.RT_SUBNET)
                    fixed_ips.append({'subnet_id': b_subnet_id,
                                      'ip_address': ip['ip_address']})
                b_info['external_fixed_ips'] = fixed_ips
            b_client.action_routers(t_ctx, 'add_gateway', b_router_id, b_info)

            # create bridge network and attach to router
            t_pod = db_api.get_top_pod(t_ctx)
            project_id = t_router['tenant_id']
            admin_project_id = 'admin_project_id'
            pool_id = self._get_bridge_subnet_pool_id(
                t_ctx, context, admin_project_id, t_pod, False)
            t_bridge_net, t_bridge_subnet = self._get_bridge_network_subnet(
                t_ctx, context, project_id, t_pod, pool_id, False)
            (_, _, b_bridge_subnet_id,
             b_bridge_net_id) = self._get_bottom_bridge_elements(
                context, project_id, pod, t_bridge_net, False, t_bridge_subnet,
                None)
            is_attach = False
            interfaces = b_client.list_ports(t_ctx,
                                             filters=[{'key': 'device_id',
                                                       'comparator': 'eq',
                                                       'value': b_router_id}])
            for interface in interfaces:
                for fixed_ip in interface['fixed_ips']:
                    if fixed_ip['subnet_id'] == b_bridge_subnet_id:
                        is_attach = True
                        break
                if is_attach:
                    break
            if not is_attach:
                b_client.action_routers(t_ctx, 'add_interface', b_router_id,
                                        {'subnet_id': b_bridge_subnet_id})

    def update_router(self, context, router_id, router):
        router_data = router['router']
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
        if attributes.is_attr_set(router_data.get(l3.EXTERNAL_GW_INFO)):
            self._update_bottom_router_gateway(context, router_id, router_data)
        return super(TricirclePlugin, self).update_router(context, router_id,
                                                          router)

    def add_router_interface(self, context, router_id, interface_info):
        t_ctx = t_context.get_context_from_neutron_context(context)

        router = self._get_router(context, router_id)
        project_id = router['tenant_id']
        admin_project_id = 'admin_project_id'
        add_by_port, _ = self._validate_interface_info(interface_info)
        # make sure network not crosses pods
        # TODO(zhiyuan) support cross-pod tenant network
        az, t_net = self._judge_network_across_pods(
            context, interface_info, add_by_port)
        b_pod, b_az = az_ag.get_pod_by_az_tenant(t_ctx, az, project_id)
        t_pod = db_api.get_top_pod(t_ctx)
        assert t_pod

        router_body = {'router': {'name': router_id,
                                  'distributed': False}}
        _, b_router_id = self._prepare_bottom_element(
            t_ctx, project_id, b_pod, router, 'router', router_body)

        # bridge network for E-W networking
        pool_id = self._get_bridge_subnet_pool_id(
            t_ctx, context, admin_project_id, t_pod, True)
        t_bridge_net, t_bridge_subnet = self._get_bridge_network_subnet(
            t_ctx, context, project_id, t_pod, pool_id, True)
        t_bridge_port = self._get_bridge_interface(
            t_ctx, context, project_id, t_pod, t_bridge_net['id'],
            b_router_id, None, True)
        is_new, b_bridge_port_id, _, _ = self._get_bottom_bridge_elements(
            context, project_id, b_pod, t_bridge_net, False, t_bridge_subnet,
            t_bridge_port)

        # bridge network for N-S networking
        ext_nets = self.get_networks(context, {external_net.EXTERNAL: [True]})
        if not ext_nets:
            need_ns_bridge = False
        else:
            ext_net_pod_names = set(
                [ext_net[az_ext.AZ_HINTS][0] for ext_net in ext_nets])
            if b_pod['pod_name'] in ext_net_pod_names:
                need_ns_bridge = False
            else:
                need_ns_bridge = True
        if need_ns_bridge:
            pool_id = self._get_bridge_subnet_pool_id(
                t_ctx, context, admin_project_id, t_pod, False)
            t_bridge_net, t_bridge_subnet = self._get_bridge_network_subnet(
                t_ctx, context, project_id, t_pod, pool_id, False)
            (_, _, b_bridge_subnet_id,
             b_bridge_net_id) = self._get_bottom_bridge_elements(
                context, project_id, b_pod, t_bridge_net, True,
                t_bridge_subnet, None)

            ns_bridge_port = self._get_bridge_interface(
                t_ctx, context, project_id, t_pod, t_bridge_net['id'],
                b_router_id, None, False)

            client = self._get_client(b_pod['pod_name'])
            # add gateway is update operation, can run multiple times
            gateway_ip = ns_bridge_port['fixed_ips'][0]['ip_address']
            client.action_routers(
                t_ctx, 'add_gateway', b_router_id,
                {'network_id': b_bridge_net_id,
                 'external_fixed_ips': [{'subnet_id': b_bridge_subnet_id,
                                         'ip_address': gateway_ip}]})

        # NOTE(zhiyuan) subnet pool, network, subnet are reusable resource,
        # we decide not to remove them when operation fails, so before adding
        # router interface, no clearing is needed.
        is_success = False
        for _ in xrange(2):
            try:
                return_info = super(TricirclePlugin,
                                    self).add_router_interface(
                    context, router_id, interface_info)
                is_success = True
            except exceptions.PortInUse:
                # NOTE(zhiyuan) so top interface is already bound to top
                # router, we need to check if bottom interface is bound.

                # safe to get port_id since only adding interface by port will
                # get PortInUse exception
                t_port_id = interface_info['port_id']
                mappings = db_api.get_bottom_mappings_by_top_id(
                    t_ctx, t_port_id, t_constants.RT_PORT)
                if not mappings:
                    # bottom interface does not exists, ignore this exception
                    # and continue to create bottom interface
                    self._unbound_top_interface(context, router_id, t_port_id)
                else:
                    pod, b_port_id = mappings[0]
                    b_port = self._get_client(pod['pod_name']).get_ports(
                        t_ctx, b_port_id)
                    if not b_port['device_id']:
                        # bottom interface exists but is not bound, ignore this
                        # exception and continue to bind bottom interface
                        self._unbound_top_interface(context, router_id,
                                                    t_port_id)
                    else:
                        # bottom interface already bound, re-raise exception
                        raise
            if is_success:
                break

        if not is_success:
            raise Exception()

        t_port_id = return_info['port_id']
        t_port = self.get_port(context, t_port_id)
        t_subnet = self.get_subnet(context,
                                   t_port['fixed_ips'][0]['subnet_id'])

        try:
            b_port_id = self._get_bottom_elements(
                t_ctx, project_id, b_pod, t_net, t_subnet, t_port)
        except Exception:
            # NOTE(zhiyuan) remove_router_interface will delete top interface.
            # if mapping is already built between top and bottom interface,
            # bottom interface and resource routing entry will also be deleted.
            #
            # but remove_router_interface may fail when deleting bottom
            # interface, in this case, top and bottom interfaces are both left,
            # user needs to manually delete top interface.
            super(TricirclePlugin, self).remove_router_interface(
                context, router_id, interface_info)
            raise

        client = self._get_client(b_pod['pod_name'])
        try:
            if is_new:
                # only attach bridge port the first time
                client.action_routers(t_ctx, 'add_interface', b_router_id,
                                      {'port_id': b_bridge_port_id})
            else:
                # still need to check if the bridge port is bound
                port = client.get_ports(t_ctx, b_bridge_port_id)
                if not port.get('device_id'):
                    client.action_routers(t_ctx, 'add_interface', b_router_id,
                                          {'port_id': b_bridge_port_id})
            client.action_routers(t_ctx, 'add_interface', b_router_id,
                                  {'port_id': b_port_id})
        except Exception:
            super(TricirclePlugin, self).remove_router_interface(
                context, router_id, interface_info)
            raise

        # TODO(zhiyuan) improve reliability
        # this is a casting rpc, so no guarantee that this operation will
        # success, find out a way to improve reliability, like introducing
        # job mechanism for async operations
        self.xjob_handler.configure_extra_routes(t_ctx, router_id)
        return return_info

    def create_floatingip(self, context, floatingip):
        # create bottom fip when associating fixed ip
        return super(TricirclePlugin, self).create_floatingip(
            context, floatingip,
            initial_status=constants.FLOATINGIP_STATUS_DOWN)

    @staticmethod
    def _safe_create_bottom_floatingip(t_ctx, client, fip_net_id,
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
            # fip is what we expect, just ignore this exception
            if fips[0].get('port_id') == port_id:
                pass
            else:
                raise

    @staticmethod
    def _disassociate_floatingip(context, _id):
        with context.session.begin():
            fip_qry = context.session.query(l3_db.FloatingIP)
            floating_ips = fip_qry.filter_by(id=_id)
            for floating_ip in floating_ips:
                floating_ip.update({'fixed_port_id': None,
                                    'fixed_ip_address': None,
                                    'router_id': None})

    def update_floatingip(self, context, _id, floatingip):
        res = super(TricirclePlugin, self).update_floatingip(
            context, _id, floatingip)

        try:
            t_ctx = t_context.get_context_from_neutron_context(context)

            fip = floatingip['floatingip']
            floatingip_db = self._get_floatingip(context, _id)
            int_port_id = fip['port_id']
            project_id = floatingip_db['tenant_id']
            fip_address = floatingip_db['floating_ip_address']
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, int_port_id, t_constants.RT_PORT)
            if not mappings:
                int_port = self.get_port(context, int_port_id)
                int_network = self.get_network(context, int_port['network_id'])
                if az_ext.AZ_HINTS not in int_network:
                    raise Exception('Cross pods L3 networking not support')
                self._validate_availability_zones(
                    context, int_network[az_ext.AZ_HINTS], False)
                int_net_pod, _ = az_ag.get_pod_by_az_tenant(
                    t_ctx, int_network[az_ext.AZ_HINTS][0], project_id)
                b_int_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                    t_ctx, int_network['id'], int_net_pod['pod_name'],
                    t_constants.RT_NETWORK)
                b_int_port_body = {
                    'port': {
                        'tenant_id': project_id,
                        'admin_state_up': True,
                        'name': int_port['id'],
                        'network_id': b_int_net_id,
                        'mac_address': int_port['mac_address'],
                        'fixed_ips': [{'ip_address': int_port['fixed_ips'][0][
                            'ip_address']}]
                    }
                }
                # TODO(zhiyuan) handle DHCP port ip address conflict problem
                _, b_int_port_id = self._prepare_bottom_element(
                    t_ctx, project_id, int_net_pod, int_port,
                    t_constants.RT_PORT, b_int_port_body)
            else:
                int_net_pod, b_int_port_id = mappings[0]
            ext_net_id = floatingip_db['floating_network_id']
            ext_net = self.get_network(context, ext_net_id)
            ext_net_pod = db_api.get_pod_by_name(t_ctx,
                                                 ext_net[az_ext.AZ_HINTS][0])

            # external network and internal network are in the same pod, no
            # need to use bridge network.
            if int_net_pod['pod_name'] == ext_net_pod['pod_name']:
                client = self._get_client(int_net_pod['pod_name'])
                b_ext_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                    t_ctx, ext_net_id, ext_net_pod['pod_name'],
                    t_constants.RT_NETWORK)
                self._safe_create_bottom_floatingip(
                    t_ctx, client, b_ext_net_id, fip_address, b_int_port_id)

                return res

            # below handle the case that external network and internal network
            # are in different pods
            int_client = self._get_client(int_net_pod['pod_name'])
            ext_client = self._get_client(ext_net_pod['pod_name'])
            ns_bridge_net_name = t_constants.ns_bridge_net_name % project_id
            ns_bridge_net = self.get_networks(
                context, {'name': [ns_bridge_net_name]})[0]
            int_bridge_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                t_ctx, ns_bridge_net['id'], int_net_pod['pod_name'],
                t_constants.RT_NETWORK)
            ext_bridge_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                t_ctx, ns_bridge_net['id'], ext_net_pod['pod_name'],
                t_constants.RT_NETWORK)

            t_pod = db_api.get_top_pod(t_ctx)
            t_ns_bridge_port = self._get_bridge_interface(
                t_ctx, context, project_id, t_pod, ns_bridge_net['id'],
                None, b_int_port_id, False)
            port_body = {
                'port': {
                    'tenant_id': project_id,
                    'admin_state_up': True,
                    'name': 'ns_bridge_port',
                    'network_id': ext_bridge_net_id,
                    'fixed_ips': [{'ip_address': t_ns_bridge_port[
                        'fixed_ips'][0]['ip_address']}]
                }
            }
            _, b_ns_bridge_port_id = self._prepare_bottom_element(
                t_ctx, project_id, ext_net_pod, t_ns_bridge_port,
                t_constants.RT_PORT, port_body)
            b_ext_net_id = db_api.get_bottom_id_by_top_id_pod_name(
                t_ctx, ext_net_id, ext_net_pod['pod_name'],
                t_constants.RT_NETWORK)
            self._safe_create_bottom_floatingip(
                t_ctx, ext_client, b_ext_net_id, fip_address,
                b_ns_bridge_port_id)
            self._safe_create_bottom_floatingip(
                t_ctx, int_client, int_bridge_net_id,
                t_ns_bridge_port['fixed_ips'][0]['ip_address'], b_int_port_id)

            return res
        except Exception:
            # NOTE(zhiyuan) currently we just handle floating ip association
            # in this function, so when exception occurs, we update floating
            # ip object to unset fixed_port_id, fixed_ip_address, router_id
            self._disassociate_floatingip(context, _id)
            raise
