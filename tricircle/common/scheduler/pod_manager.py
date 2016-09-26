# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log as logging
from stevedore import driver

from tricircle.common.i18n import _LE
from tricircle.db import api as db_api

LOG = logging.getLogger(__name__)


class PodManager(object):
    def __init__(self):
        filter_names = ['bottom_pod_filter']
        self.default_filters = self._choose_pod_filters(filter_names)

    @staticmethod
    def _choose_pod_filters(filter_names):
        good_filters = []
        for filter_name in filter_names:
            filter_ = driver.DriverManager(
                'tricircle.common.schedulers',
                filter_name,
                invoke_on_load=True
            ).driver
            good_filters.append(filter_)
        return good_filters

    @staticmethod
    def get_current_binding_and_pod(context, az_name, tenant_id, pod_group):
        filter_b = [{'key': 'tenant_id', 'comparator': 'eq',
                    'value': tenant_id}]
        current_bindings = db_api.get_pod_binding_by_tenant_id(
            context, filter_b)
        if not current_bindings:
            return None, None

        has_available_pods = False
        for pod_b in current_bindings:
            if pod_b['is_binding']:
                pod = db_api.get_pod_by_pod_id(context, pod_b['pod_id'])
                if az_name and pod['az_name'] == az_name:
                    has_available_pods = True
                elif az_name == '' and pod['az_name'] != '':
                    # if the az_name is not specified, a default bottom
                    # pod will be selected
                    has_available_pods = True

                if has_available_pods:
                    # TODO(Yipei): check resource_affinity_tag
                    # if the resource utilization of the pod reaches the limit,
                    # return [], []. Considering the feature of checking
                    # resource utilization is not implemented, we use
                    # resource_affinity_tag to test the logic of updating
                    # a binding relationship.
                    if pod_group != '':
                        return pod_b, None
                    # TODO(Yipei): check resource utilization of the pod
                    # if the resource utilization of the pod reaches the limit,
                    # return pod_b, []

                    # If a pod passes the above checking, both the pod and its
                    # corresponding binding are returned.
                    return pod_b, pod
        return None, None

    @staticmethod
    def create_binding(context, tenant_id, pod_id):
        try:
            db_api.create_pod_binding(context, tenant_id, pod_id)
        except Exception as e:
            LOG.error(_LE('Fail to create pod binding: %(exception)s'),
                      {'exception': e})
            return False
        return True

    @staticmethod
    def update_binding(context, current_binding, pod_id):
        current_binding['is_binding'] = False
        try:
            db_api.change_pod_binding(
                context, current_binding, pod_id)
        except Exception as e:
            LOG.error(_LE('Fail to update pod binding: %(exception)s'),
                      {'exception': e})
            return False
        return True

    def get_available_pods(self, context, az_name, pod_group):
        if az_name != '':
            filter_q = [{'key': 'az_name',
                         'comparator': 'eq', 'value': az_name}]
        else:
            filter_q = None
        pods = db_api.list_pods(context, filter_q)
        for filter_ in self.default_filters:
            objs_ = filter_.filter_all(pods, pod_group)
            pods = list(objs_)
        return pods
