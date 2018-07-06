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

from neutron.db import models_v2
from neutron_lib import exceptions
from sqlalchemy import sql

import tricircle.common.constants as t_constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models


def check_resource_not_in_deleting(context, dict_para):
    t_ctx = t_context.get_context_from_neutron_context(context)
    with t_ctx.session.begin():
        resource_filters = []
        for key in dict_para.keys():
            resource_filters.append({'key': key,
                                     'comparator': 'eq',
                                     'value': dict_para[key]})

        deleting_resource = core.query_resource(t_ctx,
                                                models.DeletingResources,
                                                resource_filters, [])

        if len(deleting_resource):
            if hasattr(context, "USER_AGENT") and \
                    context.USER_AGENT == t_constants.LOCAL:
                raise t_exceptions.ResourceNotFound(
                    models.DeletingResources, dict_para['resource_id'])
            else:
                raise t_exceptions.ResourceIsInDeleting()


def check_network_not_in_use(self, context, t_ctx, network_id):
    # use a different name to avoid override _ensure_entwork_not_in_use
    subnets = self._get_subnets_by_network(context, network_id)
    auto_delete_port_names = []

    for subnet in subnets:
        subnet_id = subnet['id']
        region_names = [e[0] for e in t_ctx.session.query(
            sql.distinct(models.Pod.region_name)).join(
            models.ResourceRouting,
            models.Pod.pod_id == models.ResourceRouting.pod_id).filter(
            models.ResourceRouting.top_id == subnet_id)]
        auto_delete_port_names.extend([t_constants.interface_port_name % (
            region_name, subnet_id) for region_name in region_names])
        dhcp_port_name = t_constants.dhcp_port_name % subnet_id
        snat_port_name = t_constants.snat_port_name % subnet_id
        auto_delete_port_names.append(dhcp_port_name)
        auto_delete_port_names.append(snat_port_name)

    if not auto_delete_port_names:
        # pre-created port not found, any ports left need to be deleted
        # before deleting network
        non_auto_delete_ports = context.session.query(
            models_v2.Port.id).filter_by(network_id=network_id)
        if non_auto_delete_ports.count():
            raise exceptions.NetworkInUse(net_id=network_id)
        return

    t_pod = db_api.get_top_pod(t_ctx)
    auto_delete_port_ids = [e[0] for e in t_ctx.session.query(
        models.ResourceRouting.bottom_id).filter_by(
        pod_id=t_pod['pod_id'], resource_type=t_constants.RT_PORT).filter(
        models.ResourceRouting.top_id.in_(auto_delete_port_names))]

    non_auto_delete_ports = context.session.query(
        models_v2.Port.id).filter_by(network_id=network_id).filter(
        ~models_v2.Port.id.in_(auto_delete_port_ids))
    if non_auto_delete_ports.count():
        raise exceptions.NetworkInUse(net_id=network_id)
