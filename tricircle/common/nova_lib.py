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

import nova.block_device
import nova.cloudpipe.pipelib
import nova.compute.manager
import nova.compute.task_states
import nova.compute.utils
import nova.compute.vm_states
import nova.conductor
import nova.conductor.rpcapi
import nova.context
import nova.db.api
import nova.exception
import nova.manager
import nova.network
import nova.network.model
import nova.network.security_group.openstack_driver
import nova.objects
import nova.objects.base
import nova.quota
import nova.rpc
import nova.service
import nova.utils
import nova.version
import nova.virt.block_device
import nova.volume


block_device = nova.block_device
pipelib = nova.cloudpipe.pipelib
compute_manager = nova.compute.manager
task_states = nova.compute.task_states
vm_states = nova.compute.vm_states
compute_utils = nova.compute.utils
conductor = nova.conductor
conductor_rpcapi = nova.conductor.rpcapi
context = nova.context
db_api = nova.db.api
exception = nova.exception
manager = nova.manager
network = nova.network
network_model = nova.network.model
openstack_driver = nova.network.security_group.openstack_driver
objects = nova.objects
objects_base = nova.objects.base
quota = nova.quota
rpc = nova.rpc
service = nova.service
utils = nova.utils
driver_block_device = nova.virt.block_device
volume = nova.volume
version = nova.version
