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

import copy

import six
from sqlalchemy.orm import attributes
from sqlalchemy.orm import exc
from sqlalchemy.sql import elements
import sqlalchemy.sql.expression as sql_expression
from sqlalchemy.sql import selectable

import neutron.objects.exceptions as q_obj_exceptions
import neutron_lib.context as q_context

from tricircle.common import constants


class ResourceStore(object):
    _resource_list = [('networks', constants.RT_NETWORK),
                      ('subnets', constants.RT_SUBNET),
                      ('ports', constants.RT_PORT),
                      ('routers', constants.RT_ROUTER),
                      ('routerports', None),
                      ('ipallocations', None),
                      ('subnetpools', None),
                      ('subnetpoolprefixes', None),
                      ('ml2_vlan_allocations', None),
                      ('ml2_vxlan_allocations', None),
                      ('ml2_flat_allocations', None),
                      ('networksegments', None),
                      ('externalnetworks', None),
                      ('floatingips', constants.RT_FIP),
                      ('securitygroups', constants.RT_SG),
                      ('securitygrouprules', None),
                      ('networkrbacs', None),
                      ('subnetroutes', None),
                      ('dnsnameservers', None),
                      ('trunks', 'trunk'),
                      ('subports', None),
                      ('agents', 'agent')]

    def __init__(self):
        self.store_list = []
        self.store_map = {}
        self.pod_store_map = {'top': {}, 'pod_1': {}, 'pod_2': {}}
        for prefix, pod in [('TOP', 'top'), ('BOTTOM1', 'pod_1'),
                            ('BOTTOM2', 'pod_2')]:
            for table, resource in self._resource_list:
                store_name = '%s_%s' % (prefix, table.upper())
                setattr(self, store_name, [])
                store = getattr(self, store_name)
                self.store_list.append(store)
                if prefix == 'TOP':
                    self.store_map[table] = store
                if resource:
                    self.pod_store_map[pod][resource] = store

    def clean(self):
        for store in self.store_list:
            del store[:]


TEST_TENANT_ID = 'test_tenant_id'
_RESOURCE_STORE = None


def get_resource_store():
    global _RESOURCE_STORE
    if not _RESOURCE_STORE:
        _RESOURCE_STORE = ResourceStore()
    return _RESOURCE_STORE


class DotDict(dict):
    def __init__(self, normal_dict=None):
        if normal_dict:
            for key, value in six.iteritems(normal_dict):
                self[key] = value

    def __getattr__(self, item):
        dummy_value_map = {
            'rbac_entries': [],
            'segment_host_mapping': []
        }
        if item in dummy_value_map:
            return dummy_value_map[item]
        return self.get(item)

    def to_dict(self):
        return self

    def __copy__(self):
        return DotDict(self)

    def bump_revision(self):
        pass

    def save(self, session=None):
        pass


class DotList(list):
    def all(self):
        return self


class FakeQuery(object):
    pk_map = {'ports': 'id'}

    def __init__(self, records, table):
        self.records = records
        self.table = table
        self.index = 0

    def _handle_pagination_by_id(self, record_id):
        for i, record in enumerate(self.records):
            if record['id'] == record_id:
                if i + 1 < len(self.records):
                    return FakeQuery(self.records[i + 1:], self.table)
                else:
                    return FakeQuery([], self.table)
        return FakeQuery([], self.table)

    def _handle_filter(self, keys, values):
        filtered_list = []
        for record in self.records:
            selected = True
            for i, key in enumerate(keys):
                if key not in record or record[key] != values[i]:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def filter(self, *criteria):
        _filter = []
        keys = []
        values = []
        for e in criteria:
            if isinstance(e, sql_expression.BooleanClauseList):
                e = e.clauses[0]
            if not hasattr(e, 'right') and isinstance(e, elements.False_):
                # filter is a single False value, set key to a 'INVALID_FIELD'
                # then no records will be returned
                keys.append('INVALID_FIELD')
                values.append(False)
            elif hasattr(e, 'right') and not isinstance(e.right,
                                                        elements.Null):
                _filter.append(e)
            elif isinstance(e, selectable.Exists):
                # handle external network filter
                expression = e.element.element._whereclause
                if hasattr(expression, 'right') and (
                        expression.right.name == 'network_id'):
                    keys.append('router:external')
                    values.append(True)
        if not _filter:
            if not keys:
                return FakeQuery(self.records, self.table)
            else:
                return self._handle_filter(keys, values)
        if hasattr(_filter[0].right, 'value'):
            keys.extend([f.left.name for f in _filter])
            values.extend([f.right.value for f in _filter])
        else:
            keys.extend([f.expression.left.name for f in _filter])
            values.extend(
                [f.expression.right.element.clauses[0].value for f in _filter])
        if _filter[0].expression.operator.__name__ == 'lt':
            return self._handle_pagination_by_id(values[0])
        else:
            return self._handle_filter(keys, values)

    def filter_by(self, **kwargs):
        filtered_list = []
        for record in self.records:
            selected = True
            for key, value in six.iteritems(kwargs):
                if key not in record or record[key] != value:
                    selected = False
                    break
            if selected:
                filtered_list.append(record)
        return FakeQuery(filtered_list, self.table)

    def get(self, pk):
        pk_field = self.pk_map[self.table]
        for record in self.records:
            if record.get(pk_field) == pk:
                return record

    def delete(self, synchronize_session=False):
        pass

    def outerjoin(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

    def join(self, *props, **kwargs):
        return FakeQuery(self.records, self.table)

    def order_by(self, func):
        self.records.sort(key=lambda x: x['id'])
        return FakeQuery(self.records, self.table)

    def enable_eagerloads(self, value):
        return FakeQuery(self.records, self.table)

    def limit(self, limit):
        return FakeQuery(self.records[:limit], self.table)

    def next(self):
        if self.index >= len(self.records):
            raise StopIteration
        self.index += 1
        return self.records[self.index - 1]

    __next__ = next

    def one(self):
        if len(self.records) == 0:
            raise exc.NoResultFound()
        return self.records[0]

    def first(self):
        if len(self.records) == 0:
            return None
        else:
            return self.records[0]

    def update(self, values):
        for record in self.records:
            for key, value in six.iteritems(values):
                record[key] = value
        return len(self.records)

    def all(self):
        return self.records

    def count(self):
        return len(self.records)

    def __iter__(self):
        return self


def delete_model(res_list, model_obj, key=None):
    if not res_list:
        return
    if not key:
        key = 'id'
    if key not in res_list[0]:
        return
    index = -1
    for i, res in enumerate(res_list):
        if res[key] == model_obj[key]:
            index = i
            break
    if index != -1:
        del res_list[index]
        return


def link_models(model_obj, model_dict, foreign_table, foreign_key, table, key,
                link_prop):
    if model_obj.__tablename__ == foreign_table:
        for instance in get_resource_store().store_map[table]:
            if instance[key] == model_dict[foreign_key]:
                if link_prop not in instance:
                    instance[link_prop] = []
                instance[link_prop].append(model_dict)


def unlink_models(res_list, model_dict, foreign_key, key, link_prop,
                  link_ele_foreign_key, link_ele_key):
    if foreign_key not in model_dict:
        return
    for instance in res_list:
        if instance[key] == model_dict[foreign_key]:
            if link_prop not in instance:
                return
            index = -1
            for i, res in enumerate(instance[link_prop]):
                if res[link_ele_foreign_key] == model_dict[link_ele_key]:
                    index = i
                    break
            if index != -1:
                del instance[link_prop][index]
                return


class FakeSession(object):
    class WithWrapper(object):
        def __enter__(self):
            pass

        def __exit__(self, type, value, traceback):
            pass

    def __init__(self):
        self.info = {}
        self.resource_store = get_resource_store()

    def __getattr__(self, field):
        def dummy_method(*args, **kwargs):
            pass

        return dummy_method

    def __contains__(self, item):
        return False

    @property
    def is_active(self):
        return True

    def begin(self, subtransactions=False, nested=True):
        return FakeSession.WithWrapper()

    def begin_nested(self):
        return FakeSession.WithWrapper()

    def query(self, model):
        if isinstance(model, attributes.InstrumentedAttribute):
            model = model.class_
        if model.__tablename__ not in self.resource_store.store_map:
            return FakeQuery([], model.__tablename__)
        return FakeQuery(self.resource_store.store_map[model.__tablename__],
                         model.__tablename__)

    def _extend_standard_attr(self, model_dict):
        if 'standard_attr' in model_dict:
            for field in ('resource_type', 'description', 'revision_number',
                          'created_at', 'updated_at'):
                model_dict[field] = getattr(model_dict['standard_attr'], field)

    def add_hook(self, model_obj, model_dict):
        # hook for operations before adding the model_obj to the resource store
        pass

    def delete_hook(self, model_obj):
        # hook for operations before deleting the model_obj from the resource
        # store. the default key to find the target object is "id", return
        # non-None value if you would like specify other key
        return None

    def add(self, model_obj):
        if model_obj.__tablename__ not in self.resource_store.store_map:
            return
        model_dict = DotDict(model_obj._as_dict())
        if 'project_id' in model_dict:
            model_dict['tenant_id'] = model_dict['project_id']

        if model_obj.__tablename__ == 'networks':
            model_dict['subnets'] = []
        if model_obj.__tablename__ == 'ports':
            model_dict['dhcp_opts'] = []
            model_dict['security_groups'] = []
            model_dict['fixed_ips'] = []

        link_models(model_obj, model_dict,
                    'subnetpoolprefixes', 'subnetpool_id',
                    'subnetpools', 'id', 'prefixes')
        link_models(model_obj, model_dict,
                    'ipallocations', 'port_id',
                    'ports', 'id', 'fixed_ips')
        link_models(model_obj, model_dict,
                    'subnets', 'network_id', 'networks', 'id', 'subnets')
        link_models(model_obj, model_dict,
                    'securitygrouprules', 'security_group_id',
                    'securitygroups', 'id', 'security_group_rules')

        if model_obj.__tablename__ == 'routerports':
            for port in self.resource_store.TOP_PORTS:
                if port['id'] == model_dict['port_id']:
                    model_dict['port'] = port
                    port.update(model_dict)
                    break
        if model_obj.__tablename__ == 'externalnetworks':
            for net in self.resource_store.TOP_NETWORKS:
                if net['id'] == model_dict['network_id']:
                    net['external'] = True
                    net['router:external'] = True
                    break
        if model_obj.__tablename__ == 'networkrbacs':
            if (model_dict['action'] == 'access_as_shared' and
                    model_dict['target_tenant'] == '*'):
                for net in self.resource_store.TOP_NETWORKS:
                    if net['id'] == model_dict['object']:
                        net['shared'] = True
                        break

        link_models(model_obj, model_dict,
                    'routerports', 'router_id',
                    'routers', 'id', 'attached_ports')

        if model_obj.__tablename__ == 'subnetroutes':
            for subnet in self.resource_store.TOP_SUBNETS:
                if subnet['id'] != model_dict['subnet_id']:
                    continue
                host_route = {'nexthop': model_dict['nexthop'],
                              'destination': model_dict['destination']}
                subnet['host_routes'].append(host_route)
                break

        if model_obj.__tablename__ == 'dnsnameservers':
            for subnet in self.resource_store.TOP_SUBNETS:
                if subnet['id'] != model_dict['subnet_id']:
                    continue
                dnsnameservers = model_dict['address']
                subnet['dns_nameservers'].append(dnsnameservers)
                break

        if model_obj.__tablename__ == 'ml2_flat_allocations':
            for alloc in self.resource_store.TOP_ML2_FLAT_ALLOCATIONS:
                if alloc['physical_network'] == model_dict['physical_network']:
                    raise q_obj_exceptions.NeutronDbObjectDuplicateEntry(
                        model_obj.__class__,
                        DotDict({'columns': '', 'value': ''}))

        self._extend_standard_attr(model_dict)

        self.add_hook(model_obj, model_dict)
        self.resource_store.store_map[
            model_obj.__tablename__].append(model_dict)

    def _cascade_delete(self, model_dict, foreign_key, table, key):
        if key not in model_dict:
            return
        index = -1
        for i, instance in enumerate(self.resource_store.store_map[table]):
            if instance[foreign_key] == model_dict[key]:
                index = i
                break
        if index != -1:
            del self.resource_store.store_map[table][index]

    def delete(self, model_obj):
        unlink_models(self.resource_store.store_map['routers'], model_obj,
                      'router_id', 'id', 'attached_ports', 'port_id', 'id')
        self._cascade_delete(model_obj, 'port_id', 'ipallocations', 'id')
        key = self.delete_hook(model_obj)
        for res_list in self.resource_store.store_map.values():
            delete_model(res_list, model_obj, key)


class FakeNeutronContext(q_context.Context):
    def __init__(self):
        self._session = None
        self.is_admin = True
        self.is_advsvc = False
        self.tenant_id = TEST_TENANT_ID

    def session_class(self):
        return FakeSession

    @property
    def session(self):
        if not self._session:
            self._session = self.session_class()()
        return self._session

    def elevated(self):
        return self


def filter_resource(resource_list, params):
    if not params:
        return resource_list

    params_copy = copy.deepcopy(params)
    limit = params_copy.pop('limit', None)
    marker = params_copy.pop('marker', None)

    if params_copy:
        return_list = []
        for resource in resource_list:
            is_selected = True
            for key, value in six.iteritems(params_copy):
                if (key not in resource
                    or not resource[key]
                        or resource[key] not in value):
                    is_selected = False
                    break
            if is_selected:
                return_list.append(resource)
    else:
        return_list = resource_list

    if marker:
        sorted_list = sorted(return_list, key=lambda x: x['id'])
        for i, resource in enumerate(sorted_list):
            if resource['id'] == marker:
                return_list = sorted_list[i + 1:]

    if limit:
        sorted_list = sorted(return_list, key=lambda x: x['id'])
        if limit > len(sorted_list):
            last_index = len(sorted_list)
        else:
            last_index = limit
        return_list = sorted_list[0: last_index]
    return return_list


class FakeNeutronClient(object):
    # override this
    _resource = None

    def __init__(self, region_name):
        self.region_name = region_name
        self._res_map = get_resource_store().pod_store_map

    def get(self, path, params=None):
        if self.region_name in ['pod_1', 'pod_2', 'top']:
            res_list = self._res_map[self.region_name][self._resource]
            filtered_res_list = filter_resource(res_list, params)
            return_list = []
            for res in filtered_res_list:
                if self.region_name != 'top':
                    res = copy.copy(res)
                return_list.append(res)
            return {self._resource + 's': return_list}
        else:
            raise Exception()


class FakeClient(object):
    def __init__(self, region_name=None):
        if not region_name:
            self.region_name = 'top'
        else:
            self.region_name = region_name
        self._res_map = get_resource_store().pod_store_map

    def create_resources(self, _type, ctx, body):
        res_list = self._res_map[self.region_name][_type]
        res = dict(body[_type])
        res_list.append(res)
        return res

    def list_resources(self, _type, ctx, filters=None):
        res_list = self._res_map[self.region_name][_type]
        ret_list = []
        for res in res_list:
            is_selected = True
            for _filter in filters:
                if _filter['key'] not in res:
                    is_selected = False
                    break
                if _filter['value'] != res[_filter['key']]:
                    is_selected = False
                    break
            if is_selected:
                ret_list.append(res)
        return ret_list

    def get_resource(self, _type, ctx, _id):
        res = self.list_resources(
            _type, ctx, [{'key': 'id', 'comparator': 'eq', 'value': _id}])
        if res:
            return res[0]
        return None

    def delete_resources(self, _type, ctx, _id):
        index = -1
        res_list = self._res_map[self.region_name][_type]
        for i, res in enumerate(res_list):
            if res['id'] == _id:
                index = i
        if index != -1:
            del res_list[index]

    def update_resources(self, _type, ctx, _id, body):
        res_list = self._res_map[self.region_name][_type]
        updated = False
        for res in res_list:
            if res['id'] == _id:
                updated = True
                res.update(body[_type])
        return updated
