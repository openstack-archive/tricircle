# Copyright 2017 Huawei Technologies Co., Ltd.
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


import six

from oslo_log import log

from neutron.plugins.ml2 import config  # noqa
from neutron.services.trunk import exceptions as trunk_exc
from neutron.services.trunk import plugin
from neutron_lib.plugins import directory

import tricircle.common.client as t_client
import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.network import central_plugin
from tricircle.network import helper

LOG = log.getLogger(__name__)


class TricircleTrunkPlugin(plugin.TrunkPlugin):

    def __init__(self):
        super(TricircleTrunkPlugin, self).__init__()
        self.xjob_handler = xrpcapi.XJobAPI()
        self.helper = helper.NetworkHelper(self)
        self.clients = {}

    def is_rpc_enabled(self):
        return False

    def _get_client(self, region_name):
        if region_name not in self.clients:
            self.clients[region_name] = t_client.Client(region_name)
        return self.clients[region_name]

    def update_trunk(self, context, trunk_id, trunk):
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin():
            res = super(TricircleTrunkPlugin, self).update_trunk(
                context, trunk_id, trunk)
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, trunk_id, t_constants.RT_TRUNK)
            if mappings:
                b_pod = mappings[0][0]
                self.xjob_handler.sync_trunk(t_ctx, res['project_id'],
                                             trunk_id, b_pod['pod_id'])
        return res

    def delete_trunk(self, context, trunk_id):
        t_ctx = t_context.get_context_from_neutron_context(context)
        res = super(TricircleTrunkPlugin, self).get_trunk(context, trunk_id)
        with context.session.begin():
            super(TricircleTrunkPlugin, self).delete_trunk(context, trunk_id)
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, trunk_id, t_constants.RT_TRUNK)
            if mappings:
                b_pod = mappings[0][0]
                self.xjob_handler.sync_trunk(t_ctx, res['project_id'],
                                             trunk_id, b_pod['pod_id'])

    def get_trunk(self, context, trunk_id, fields=None):
        t_ctx = t_context.get_context_from_neutron_context(context)
        t_trunk = super(TricircleTrunkPlugin, self).get_trunk(context,
                                                              trunk_id, fields)
        if not fields or 'status' in fields:
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, trunk_id, t_constants.RT_TRUNK)
            if mappings:
                b_pod, b_trunk_id = mappings[0]
                b_region_name = b_pod['region_name']
                b_client = self._get_client(region_name=b_region_name)
                b_trunk = b_client.get_trunks(t_ctx, b_trunk_id)
                if not b_trunk:
                    LOG.error('trunk: %(trunk_id)s not found '
                              'pod name: %(name)s',
                              {'trunk_id': b_trunk_id, 'name': b_region_name})
                else:
                    t_trunk['status'] = b_trunk['status']

        return t_trunk

    def _get_trunks_from_top(self, context, top_bottom_map, filters):
        top_trunks = super(TricircleTrunkPlugin, self).get_trunks(
            context, filters)

        return [trunk for trunk in top_trunks if
                trunk['id'] not in top_bottom_map]

    def _get_min_search_step(self):
        # this method is for unit test mock purpose
        return 100

    def _get_trunks_from_top_with_limit(self, context, top_bottom_map,
                                        filters, limit, marker):

        ret = []
        total = 0
        # set step as two times of number to have better chance to obtain all
        # trunks we need
        search_step = limit * 2
        min_search_step = self._get_min_search_step()
        if search_step < min_search_step:
            search_step = min_search_step
        # None means sort direction is desc
        sorts = [('id', None)]
        top_trunks = super(TricircleTrunkPlugin, self).get_trunks(
            context, filters, sorts=sorts, limit=search_step, marker=marker)

        for trunk in top_trunks:
            total += 1
            if trunk['id'] not in top_bottom_map:
                ret.append(trunk)
            if len(ret) == limit:
                return ret
        # NOTE(xiulin) we have traversed all the trunks
        if total < search_step:
            return ret
        else:
            ret.extend(self._get_trunks_from_top_with_limit(
                context, top_bottom_map, filters, limit - len(ret),
                ret[-1]['id']))
            return ret

    def _get_trunks_from_pod_with_limit(self, context, current_pod,
                                        bottom_top_map, top_bottom_map,
                                        filters, limit, marker):

        ret = []
        t_ctx = t_context.get_context_from_neutron_context(context)
        q_client = self._get_client(
            current_pod['region_name']).get_native_client('trunk', t_ctx)

        params = {'limit': 0 if not limit else limit}
        if marker:
            b_marker = top_bottom_map[marker]
            params.update({'marker': b_marker})
        if filters:
            if 'id' in filters:
                map_ids = self._get_map_trunk_ids(filters['id'],
                                                  top_bottom_map)
                filters['id'] = map_ids
            params.update(filters)
        bottom_trunks = q_client.get(q_client.trunks_path,
                                     params=params)['trunks']
        for bottom_trunk in bottom_trunks:
            top_id = bottom_top_map.get(bottom_trunk['id'])
            # TODO(xiulin): handle unmapped trunk
            if top_id:
                bottom_trunk['id'] = top_id
                ret.append(bottom_trunk)
        if len(ret) == limit:
            return ret

        remainder = limit - len(ret)
        next_pod = db_api.get_next_bottom_pod(
            t_ctx, current_pod_id=current_pod['pod_id'])
        if next_pod:
            # get from next bottom pod
            next_ret = self._get_trunks_from_pod_with_limit(
                context, next_pod, bottom_top_map, top_bottom_map,
                filters, remainder, None)
            ret.extend(next_ret)
            return ret
        else:
            # get from top pod
            top_ret = self._get_trunks_from_top_with_limit(
                context, top_bottom_map, filters, remainder, None)
            ret.extend(top_ret)
            return ret

    def _map_trunks_from_bottom_to_top(self, trunks, bottom_top_map):
        trunk_list = []
        for trunk in trunks:
            # TODO(xiulin): handle unmapped trunk
            if trunk['id'] not in bottom_top_map:
                continue
            trunk['id'] = bottom_top_map[trunk['id']]
            trunk_list.append(trunk)
        return trunk_list

    def _get_map_trunk_ids(self, top_ids, top_bottom_map):
        b_trunk_ids = []
        for _id in top_ids:
            if _id in top_bottom_map:
                b_trunk_ids.append(top_bottom_map[_id])
            else:
                b_trunk_ids.append(_id)
        return b_trunk_ids

    def _transform_trunk_filters(self, filters, top_bottom_map):
        _filters = []
        if filters:
            for key, value in six.iteritems(filters):
                if key == 'id':
                    value = self._get_map_trunk_ids(value, top_bottom_map)
                _filters.append({'key': key,
                                 'comparator': 'eq',
                                 'value': value})
        return _filters

    def get_trunks(self, context, filters=None, fields=None,
                   sorts=None, limit=None, marker=None, page_reverse=False):
        ret = []
        bottom_top_map = {}
        top_bottom_map = {}
        t_ctx = t_context.get_context_from_neutron_context(context)

        route_filters = [{'key': 'resource_type',
                          'comparator': 'eq',
                          'value': t_constants.RT_TRUNK}]
        routes = db_api.list_resource_routings(t_ctx, route_filters)
        for route in routes:
            bottom_top_map[route['bottom_id']] = route['top_id']
            top_bottom_map[route['top_id']] = route['bottom_id']

        if limit:
            if marker:
                mappings = db_api.get_bottom_mappings_by_top_id(
                    t_ctx, marker, t_constants.RT_TRUNK)
                # if mapping exists, we retrieve trunk information
                # from bottom, otherwise from top
                if mappings:
                    pod_id = mappings[0][0]['pod_id']
                    current_pod = db_api.get_pod(t_ctx, pod_id)
                    ret = self._get_trunks_from_pod_with_limit(
                        context, current_pod, bottom_top_map, top_bottom_map,
                        filters, limit, marker)
                else:
                    ret = self._get_trunks_from_top_with_limit(
                        context, top_bottom_map, filters, limit, marker)
            else:
                current_pod = db_api.get_next_bottom_pod(t_ctx)
                # if current_pod exists, we retrieve trunk information
                # from bottom, otherwise from top
                if current_pod:
                    ret = self._get_trunks_from_pod_with_limit(
                        context, current_pod, bottom_top_map, top_bottom_map,
                        filters, limit, None)
                else:
                    ret = self._get_trunks_from_top_with_limit(
                        context, top_bottom_map, filters, limit, None)
        else:
            pods = db_api.list_pods(t_ctx)
            _filters = self._transform_trunk_filters(filters, top_bottom_map)
            for pod in pods:
                if not pod['az_name']:
                    continue
                client = self._get_client(pod['region_name'])
                pod_trunks = client.list_trunks(t_ctx, filters=_filters)
                ret.extend(pod_trunks)
            ret = self._map_trunks_from_bottom_to_top(ret, bottom_top_map)
            top_trunks = self._get_trunks_from_top(context,
                                                   top_bottom_map, filters)
            ret.extend(top_trunks)

        return [super(TricircleTrunkPlugin, self)._fields(trunk, fields)
                for trunk in ret]

    def get_trunk_subports(self, context, filters=None):
        ret = None
        if not filters or len(filters) != 2:
            return ret
        device_ids = filters.get('device_id', [])
        device_owners = filters.get('device_owner', [])
        if (len(device_owners) != 1
           or len(device_ids) != 1
           or device_owners[0] != t_constants.DEVICE_OWNER_SUBPORT):
            return ret
        try:
            super(TricircleTrunkPlugin, self).get_trunk(context, device_ids[0])
        except trunk_exc.TrunkNotFound:
            return ret

        core_plugin = directory.get_plugin()
        ret = super(central_plugin.TricirclePlugin, core_plugin).get_ports(
            context, filters)
        return ret

    def update_subports_device_id(self, context,
                                  subports, device_id, device_owner):
        if not subports['sub_ports']:
            return
        core_plugin = directory.get_plugin()
        body = {'port': {
            'device_id': device_id,
            'device_owner': device_owner}}
        for subport in subports['sub_ports']:
            super(central_plugin.TricirclePlugin, core_plugin).update_port(
                context, subport['port_id'], body)

    def add_subports(self, context, trunk_id, subports):
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin():
            res = super(TricircleTrunkPlugin, self).add_subports(
                context, trunk_id, subports)
            self.update_subports_device_id(context, subports, trunk_id,
                                           t_constants.DEVICE_OWNER_SUBPORT)
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, trunk_id, t_constants.RT_TRUNK)
            if mappings:
                b_pod = mappings[0][0]
                self.xjob_handler.sync_trunk(
                    t_ctx, res['project_id'], trunk_id, b_pod['pod_id'])

        return res

    def remove_subports(self, context, trunk_id, subports):
        t_ctx = t_context.get_context_from_neutron_context(context)
        with context.session.begin():
            res = super(TricircleTrunkPlugin, self).remove_subports(
                context, trunk_id, subports)
            self.update_subports_device_id(context, subports, '', '')
            mappings = db_api.get_bottom_mappings_by_top_id(
                t_ctx, trunk_id, t_constants.RT_TRUNK)
            if mappings:
                b_pod = mappings[0][0]
                self.xjob_handler.sync_trunk(
                    t_ctx, res['project_id'], trunk_id, b_pod['pod_id'])

        return res
