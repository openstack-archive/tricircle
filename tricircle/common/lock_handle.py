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

import datetime
import eventlet

import oslo_db.exception as db_exc

from tricircle.db import core
from tricircle.db import models


def get_or_create_route(t_ctx, q_ctx,
                        project_id, pod, _id, _type, list_ele_method):
    # use configuration option later
    route_expire_threshold = 30

    with t_ctx.session.begin():
        routes = core.query_resource(
            t_ctx, models.ResourceRouting,
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
                    # NOTE(zhiyuan) cannot directly remove the route, we have
                    # a race here that other worker is updating this route, we
                    # need to check if the corresponding element has been
                    # created by other worker
                    eles = list_ele_method(t_ctx, q_ctx, pod, _id, _type)
                    if eles:
                        route['bottom_id'] = eles[0]['id']
                        core.update_resource(t_ctx,
                                             models.ResourceRouting,
                                             route['id'], route)
                        return route, False
                    try:
                        core.delete_resource(t_ctx,
                                             models.ResourceRouting,
                                             route['id'])
                    except db_exc.ResourceNotFound:
                        pass
    try:
        # NOTE(zhiyuan) try/except block inside a with block will cause
        # problem, so move them out of the block and manually handle the
        # session context
        t_ctx.session.begin()
        route = core.create_resource(t_ctx, models.ResourceRouting,
                                     {'top_id': _id,
                                      'pod_id': pod['pod_id'],
                                      'project_id': project_id,
                                      'resource_type': _type})
        t_ctx.session.commit()
        return route, True
    except db_exc.DBDuplicateEntry:
        t_ctx.session.rollback()
        return None, False
    finally:
        t_ctx.session.close()


def get_or_create_element(t_ctx, q_ctx,
                          project_id, pod, ele, _type, body,
                          list_ele_method, create_ele_method):
    # use configuration option later
    max_tries = 5
    for _ in xrange(max_tries):
        route, is_new = get_or_create_route(
            t_ctx, q_ctx, project_id, pod, ele['id'], _type, list_ele_method)
        if not route:
            eventlet.sleep(0)
            continue
        if not is_new and not route['bottom_id']:
            eventlet.sleep(0)
            continue
        if not is_new and route['bottom_id']:
            break
        if is_new:
            try:
                ele = create_ele_method(t_ctx, q_ctx, pod, body, _type)
            except Exception:
                with t_ctx.session.begin():
                    try:
                        core.delete_resource(t_ctx,
                                             models.ResourceRouting,
                                             route['id'])
                    except db_exc.ResourceNotFound:
                        # NOTE(zhiyuan) this is a rare case that other worker
                        # considers the route expires and delete it though it
                        # was just created, maybe caused by out-of-sync time
                        pass
                raise
            with t_ctx.session.begin():
                # NOTE(zhiyuan) it's safe to update route, the bottom network
                # has been successfully created, so other worker will not
                # delete this route
                route['bottom_id'] = ele['id']
                core.update_resource(t_ctx, models.ResourceRouting,
                                     route['id'], route)
                break
    if not route:
        raise Exception('Fail to create %s routing entry' % _type)
    if not route['bottom_id']:
        raise Exception('Fail to bind top and bottom %s' % _type)
    return is_new, route['bottom_id']
