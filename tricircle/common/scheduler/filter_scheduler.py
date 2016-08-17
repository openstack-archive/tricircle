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

from tricircle.common.scheduler import driver


class FilterScheduler(driver.Scheduler):

    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)

    def select_destination(self, context, az_name, tenant_id, pod_group):
        current_binding, current_pod = \
            self.pod_manager.get_current_binding_and_pod(
                context, az_name, tenant_id, pod_group)

        if current_binding and current_pod:
            return current_pod, current_pod['pod_az_name']
        else:
            pods = self.pod_manager.get_available_pods(
                context, az_name, pod_group)
            if not pods:
                return None, None
            # TODO(Yipei): Weigh pods and select one whose weight
            # is the maximum. Here we chose one randomly.
            is_current = False
            best_pod = None
            # select the pod by a circle in pods
            for pod in pods:
                if is_current:
                    best_pod = pod
                    break
                if current_binding \
                        and pod['pod_id'] == current_binding['pod_id']:
                    is_current = True
            if is_current and len(pods) == 1:
                return None, None
            if not best_pod:
                best_pod = pods[0]

            if current_binding:
                is_successful = self.pod_manager.update_binding(
                    context, current_binding, best_pod['pod_id'])
            else:
                is_successful = self.pod_manager.create_binding(
                    context, tenant_id, best_pod['pod_id'])
            if not is_successful:
                return None, None
            return best_pod, best_pod['pod_az_name']
