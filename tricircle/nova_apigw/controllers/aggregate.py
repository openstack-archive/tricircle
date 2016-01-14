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

from tricircle.common import az_ag
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exc
from tricircle.db import core
from tricircle.db import models


class AggregateActionController(rest.RestController):

    def __init__(self, project_id, aggregate_id):
        self.project_id = project_id
        self.aggregate_id = aggregate_id

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            pecan.abort(400, 'Admin role required to operate aggregates')
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
        aggregate = az_ag.get_one_ag(context, self.aggregate_id)
        return {'aggregate': aggregate}


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
            pecan.abort(400, 'Admin role required to create aggregates')
            return
        if 'aggregate' not in kw:
            pecan.abort(400, 'Request body not found')
            return

        host_aggregate = kw['aggregate']
        name = host_aggregate['name'].strip()
        avail_zone = host_aggregate.get('availability_zone')
        if avail_zone:
            avail_zone = avail_zone.strip()

        try:
            with context.session.begin():
                aggregate = az_ag.create_ag_az(context,
                                               ag_name=name,
                                               az_name=avail_zone)
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
                aggregate = az_ag.get_one_ag(context, _id)
                return {'aggregate': aggregate}
        except t_exc.ResourceNotFound:
            pecan.abort(404, 'Aggregate not found')
            return

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()

        try:
            with context.session.begin():
                aggregates = az_ag.get_all_ag(context)
        except Exception:
            pecan.abort(500, 'Fail to get all host aggregates')
            return
        return {'aggregates': aggregates}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                az_ag.delete_ag(context, _id)
                pecan.response.status = 200
        except t_exc.ResourceNotFound:
            pecan.abort(404, 'Aggregate not found')
            return
