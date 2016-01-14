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


from tricircle.db import core
from tricircle.db import models


def create_pod(context, pod_dict):
    with context.session.begin():
        return core.create_resource(context, models.Pod, pod_dict)


def delete_pod(context, pod_id):
    with context.session.begin():
        return core.delete_resource(context, models.Pod, pod_id)


def get_pod(context, pod_id):
    with context.session.begin():
        return core.get_resource(context, models.Pod, pod_id)


def list_pods(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.Pod, filters or [],
                                   sorts or [])


def update_pod(context, pod_id, update_dict):
    with context.session.begin():
        return core.update_resource(context, models.Pod, pod_id, update_dict)


def create_pod_service_configuration(context, config_dict):
    with context.session.begin():
        return core.create_resource(context, models.PodServiceConfiguration,
                                    config_dict)


def delete_pod_service_configuration(context, config_id):
    with context.session.begin():
        return core.delete_resource(context, models.PodServiceConfiguration,
                                    config_id)


def get_pod_service_configuration(context, config_id):
    with context.session.begin():
        return core.get_resource(context, models.PodServiceConfiguration,
                                 config_id)


def list_pod_service_configurations(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.PodServiceConfiguration,
                                   filters or [], sorts or [])


def update_pod_service_configuration(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, models.PodServiceConfiguration, config_id, update_dict)


def get_bottom_mappings_by_top_id(context, top_id, resource_type):
    """Get resource id and pod name on bottom

    :param context: context object
    :param top_id: resource id on top
    :return: a list of tuple (pod dict, bottom_id)
    """
    route_filters = [{'key': 'top_id', 'comparator': 'eq', 'value': top_id},
                     {'key': 'resource_type',
                      'comparator': 'eq',
                      'value': resource_type}]
    mappings = []
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        for route in routes:
            if not route['bottom_id']:
                continue
            pod = core.get_resource(context, models.Pod, route['pod_id'])
            mappings.append((pod, route['bottom_id']))
    return mappings


def get_bottom_mappings_by_tenant_pod(context,
                                      tenant_id,
                                      pod_id,
                                      resource_type):
    """Get resource routing for specific tenant and pod

    :param context: context object
    :param tenant_id: tenant id to look up
    :param pod_id: pod to look up
    :param resource_type: specific resource
    :return: a dic {top_id : route}
    """
    route_filters = [{'key': 'pod_id',
                      'comparator': 'eq',
                      'value': pod_id},
                     {'key': 'project_id',
                      'comparator': 'eq',
                      'value': tenant_id},
                     {'key': 'resource_type',
                      'comparator': 'eq',
                      'value': resource_type}]
    routings = {}
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        for _route in routes:
            if not _route['bottom_id']:
                continue
            routings[_route['top_id']] = _route
    return routings


def get_next_bottom_pod(context, current_pod_id=None):
    pods = list_pods(context, sorts=[(models.Pod.pod_id, True)])
    # NOTE(zhiyuan) number of pods is small, just traverse to filter top pod
    pods = [pod for pod in pods if pod['az_name']]
    for index, pod in enumerate(pods):
        if not current_pod_id:
            return pod
        if pod['pod_id'] == current_pod_id and index < len(pods) - 1:
            return pods[index + 1]
    return None


def get_top_pod(context):

    filters = [{'key': 'az_name', 'comparator': 'eq', 'value': ''}]
    pods = list_pods(context, filters=filters)

    # only one should be searched
    for pod in pods:
        if (pod['pod_name'] != '') and \
                (pod['az_name'] == ''):
            return pod

    return None


def get_pod_by_name(context, pod_name):

    filters = [{'key': 'pod_name', 'comparator': 'eq', 'value': pod_name}]
    pods = list_pods(context, filters=filters)

    # only one should be searched
    for pod in pods:
        if pod['pod_name'] == pod_name:
            return pod

    return None
