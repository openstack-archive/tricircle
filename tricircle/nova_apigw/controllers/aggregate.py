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
from tricircle.common.i18n import _
from tricircle.common import utils
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
            return utils.format_nova_error(
                403, _("Policy doesn't allow os_compute_api:os-aggregates:"
                       "index to be performed."))
        try:
            with context.session.begin():
                core.get_resource(context, models.Aggregate, self.aggregate_id)
        except t_exc.ResourceNotFound:
            return utils.format_nova_error(
                404, _('Aggregate %s could not be found.') % self.aggregate_id)
        if 'add_host' in kw or 'remove_host' in kw:
            return utils.format_nova_error(
                400, _('Add and remove host action not supported'))
        # TODO(zhiyuan) handle aggregate metadata updating
        try:
            aggregate = az_ag.get_one_ag(context, self.aggregate_id)
            return {'aggregate': aggregate}
        except Exception:
            return utils.format_nova_error(
                500, _('Aggregate operation on %s failed') % self.aggregate_id)


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
            return utils.format_nova_error(
                403, _("Policy doesn't allow os_compute_api:os-aggregates:"
                       "index to be performed."))
        if 'aggregate' not in kw:
            return utils.format_nova_error(
                400, _('aggregate is not set'))

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
            return utils.format_nova_error(
                409, _('Aggregate %s already exists.') % name)
        except Exception:
            return utils.format_nova_error(
                500, _('Fail to create aggregate'))

        return {'aggregate': aggregate}

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                aggregate = az_ag.get_one_ag(context, _id)
                return {'aggregate': aggregate}
        except t_exc.ResourceNotFound:
            return utils.format_nova_error(
                404, _('Aggregate %s could not be found.') % _id)
        except Exception:
            return utils.format_nova_error(
                500, _('Fail to get aggregate %s') % _id)

    @expose(generic=True, template='json')
    def get_all(self):
        context = t_context.extract_context_from_environ()

        try:
            with context.session.begin():
                aggregates = az_ag.get_all_ag(context)
        except Exception:
            return utils.format_nova_error(500, _('Fail to list aggregates'))
        return {'aggregates': aggregates}

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()
        try:
            with context.session.begin():
                az_ag.delete_ag(context, _id)
                pecan.response.status = 200
        except t_exc.ResourceNotFound:
            return utils.format_nova_error(
                404, _('Aggregate %s could not be found.') % _id)
        except Exception:
            return utils.format_nova_error(
                500, _('Fail to delete aggregate %s') % _id)
