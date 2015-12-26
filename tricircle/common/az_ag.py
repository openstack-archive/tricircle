# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from tricircle.db import core
from tricircle.db import models


def create_ag_az(context, ag_name, az_name):
    aggregate = core.create_resource(context, models.Aggregate,
                                     {'name': ag_name})
    core.create_resource(
        context, models.AggregateMetadata,
        {'key': 'availability_zone',
         'value': az_name,
         'aggregate_id': aggregate['id']})
    extra_fields = {
        'availability_zone': az_name,
        'metadata': {'availability_zone': az_name}
    }
    aggregate.update(extra_fields)
    return aggregate


def get_one_ag(context, aggregate_id):
    aggregate = core.get_resource(context, models.Aggregate, aggregate_id)
    metadatas = core.query_resource(
        context, models.AggregateMetadata,
        [{'key': 'key', 'comparator': 'eq',
          'value': 'availability_zone'},
         {'key': 'aggregate_id', 'comparator': 'eq',
          'value': aggregate['id']}], [])
    if metadatas:
        aggregate['availability_zone'] = metadatas[0]['value']
        aggregate['metadata'] = {
            'availability_zone': metadatas[0]['value']}
    else:
        aggregate['availability_zone'] = ''
        aggregate['metadata'] = {}
    return aggregate


def get_ag_by_name(context, ag_name):
    filters = [{'key': 'name',
                'comparator': 'eq',
                'value': ag_name}]
    aggregates = get_all_ag(context, filters)
    if aggregates is not None:
        if len(aggregates) == 1:
            return aggregates[0]

    return None


def delete_ag(context, aggregate_id):
    core.delete_resources(context, models.AggregateMetadata,
                          [{'key': 'aggregate_id',
                            'comparator': 'eq',
                            'value': aggregate_id}])
    core.delete_resource(context, models.Aggregate, aggregate_id)
    return


def get_all_ag(context, filters=None, sorts=None):
    aggregates = core.query_resource(context,
                                     models.Aggregate,
                                     filters or [],
                                     sorts or [])
    metadatas = core.query_resource(
        context, models.AggregateMetadata,
        [{'key': 'key',
          'comparator': 'eq',
          'value': 'availability_zone'}], [])

    agg_meta_map = {}
    for metadata in metadatas:
        agg_meta_map[metadata['aggregate_id']] = metadata
    for aggregate in aggregates:
        extra_fields = {
            'availability_zone': '',
            'metadata': {}
        }
        if aggregate['id'] in agg_meta_map:
            metadata = agg_meta_map[aggregate['id']]
            extra_fields['availability_zone'] = metadata['value']
            extra_fields['metadata'] = {
                'availability_zone': metadata['value']}
        aggregate.update(extra_fields)

    return aggregates
