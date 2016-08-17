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

from oslo_log import log as logging
from oslo_utils import uuidutils

from tricircle.common.i18n import _LE

from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.db import models

LOG = logging.getLogger(__name__)


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


def get_pod_by_az_tenant(context, az_name, tenant_id):
    pod_bindings = core.query_resource(context,
                                       models.PodBinding,
                                       [{'key': 'tenant_id',
                                         'comparator': 'eq',
                                         'value': tenant_id}],
                                       [])
    for pod_b in pod_bindings:
        pod = core.get_resource(context,
                                models.Pod,
                                pod_b['pod_id'])
        if az_name and pod['az_name'] == az_name:
            return pod, pod['pod_az_name']
        elif az_name == '' and pod['az_name'] != '':
            # if the az_name is not specified, a defult bottom
            # pod will be selected
            return pod, pod['pod_az_name']
        else:
            pass

    # TODO(joehuang): schedule one dynamically in the future
    if az_name != '':
        filters = [{'key': 'az_name', 'comparator': 'eq', 'value': az_name}]
    else:
        filters = None

    # if az_name is valid, select a pod under this az_name
    # if az_name is '', select the first valid bottom pod.
    # change to dynamic schedluing in the future
    pods = db_api.list_pods(context, filters=filters)
    for pod in pods:
        if pod['pod_name'] != '' and pod['az_name'] != '':
            try:
                with context.session.begin():
                    core.create_resource(
                        context, models.PodBinding,
                        {'id': uuidutils.generate_uuid(),
                         'tenant_id': tenant_id,
                         'pod_id': pod['pod_id'],
                         'is_binding': True})
                    return pod, pod['pod_az_name']
            except Exception as e:
                LOG.error(_LE('Fail to create pod binding: %(exception)s'),
                          {'exception': e})
                return None, None

    return None, None


def list_pods_by_tenant(context, tenant_id):

    pod_bindings = core.query_resource(context,
                                       models.PodBinding,
                                       [{'key': 'tenant_id',
                                         'comparator': 'eq',
                                         'value': tenant_id}],
                                       [])

    pods = []
    if pod_bindings:
        for pod_b in pod_bindings:
            pod = core.get_resource(context,
                                    models.Pod,
                                    pod_b['pod_id'])
            pods.append(pod)

    return pods
