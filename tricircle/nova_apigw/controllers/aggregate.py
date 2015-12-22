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

import pecan
from pecan import expose
from pecan import rest

import oslo_db.exception as db_exc

import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exc
from tricircle.db import core
from tricircle.db import models


def _get_one(context, aggregate_id):
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
    return {'aggregate': aggregate}


class AggregateActionController(rest.RestController):

    def __init__(self, project_id, aggregate_id):
        self.project_id = project_id
        self.aggregate_id = aggregate_id

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            pecan.abort(400, 'Admin role required to create sites')
            return
        try:
            with context.session.begin():
                core.get_resource(context, models.Aggregate, self.aggregate_id)
        except t_exc.ResourceNotFound:
            pecan.abort(400, 'Aggregate not found')
            return
        if 'add_host' in kw or 'remove_host' in kw:
            pecan.abort(400, 'Add and remove host action not supported')
            return
        # TODO(zhiyuan) handle aggregate metadata updating
        return _get_one(context, self.aggregate_id)


class AggregateController(rest.RestController):

    def __init__(self, project_id):
        self.project_id = project_id

    @pecan.expose()
    def _lookup(self, aggregate_id, action, *remainder):
        if action == 'action':
            return AggregateActionController(self.project_id,
                                             aggregate_id), remainder

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            pecan.abort(400, 'Admin role required to create sites')
            return
        if 'aggregate' not in kw:
            pecan.abort(400, 'Request body not found')
            return

        host_aggregate = kw['aggregate']
        name = host_aggregate['name'].strip()
        avail_zone = host_aggregate.get("availability_zone")
        if avail_zone:
            avail_zone = avail_zone.strip()

        try:
            with context.session.begin():
                aggregate = core.create_resource(context, models.Aggregate,
                                                 {'name': name})
                core.create_resource(
                    context, models.AggregateMetadata,
                    {'key': 'availability_zone',
                     'value': avail_zone,
                     'aggregate_id': aggregate['id']})
                extra_fields = {
                    'availability_zone': avail_zone,
                    'metadata': {'availability_zone': avail_zone}
                }
                aggregate.update(extra_fields)
        except db_exc.DBDuplicateEntry:
            pecan.abort(409, 'Aggregate already exists')
            return
        except Exception:
            pecan.abort(500, 'Fail to create host aggregate')
            return

        return {'aggregate': aggregate}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                return _get_one(context, _id)
        except t_exc.ResourceNotFound:
            pecan.abort(404, 'Aggregate not found')
            return

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()
        with context.session.begin():
            aggregates = core.query_resource(context, models.Aggregate, [], [])
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

        return {'aggregates': aggregates}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                core.delete_resources(context, models.AggregateMetadata,
                                      [{'key': 'aggregate_id',
                                        'comparator': 'eq',
                                        'value': _id}])
                core.delete_resource(context, models.Aggregate, _id)
                pecan.response.status = 202
        except t_exc.ResourceNotFound:
            pecan.abort(404, 'Aggregate not found')
            return
