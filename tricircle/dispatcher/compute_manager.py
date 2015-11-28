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

import oslo_log.log as logging
import oslo_messaging as messaging

from tricircle.common.i18n import _LI
from tricircle.common.i18n import _LW
from tricircle.common.nova_lib import context as nova_context
from tricircle.common.nova_lib import exception
from tricircle.common.nova_lib import manager
from tricircle.common.nova_lib import objects
from tricircle.common.nova_lib import objects_base
from tricircle.common.nova_lib import rpc as nova_rpc
from tricircle.common import utils

LOG = logging.getLogger(__name__)


class DispatcherComputeManager(manager.Manager):

    target = messaging.Target(version='4.0')

    def __init__(self, site_manager=None, *args, **kwargs):
        self._site_manager = site_manager

        target = messaging.Target(topic="proxy", version='4.0')
        serializer = objects_base.NovaObjectSerializer()
        self.proxy_client = nova_rpc.get_client(target, '4.0', serializer)

        super(DispatcherComputeManager, self).__init__(service_name="compute",
                                                       *args, **kwargs)

    def _get_compute_node(self, context):
        """Returns compute node for the host and nodename."""
        try:
            return objects.ComputeNode.get_by_host_and_nodename(
                context, self.host, utils.get_node_name(self.host))
        except exception.NotFound:
            LOG.warning(_LW("No compute node record for %(host)s:%(node)s"),
                        {'host': self.host,
                         'node': utils.get_node_name(self.host)})

    def _copy_resources(self, compute_node, resources):
        """Copy resource values to initialise compute_node"""

        # update the allocation ratios for the related ComputeNode object
        compute_node.ram_allocation_ratio = 1
        compute_node.cpu_allocation_ratio = 1

        # now copy rest to compute_node
        for key in resources:
            compute_node[key] = resources[key]

    def _init_compute_node(self, context, resources):
        """Initialise the compute node if it does not already exist.

        The nova scheduler will be inoperable if compute_node
        is not defined. The compute_node will remain undefined if
        we fail to create it or if there is no associated service
        registered.
        If this method has to create a compute node it needs initial
        values - these come from resources.
        :param context: security context
        :param resources: initial values
        """

        # try to get the compute node record from the
        # database. If we get one we use resources to initialize
        compute_node = self._get_compute_node(context)
        if compute_node:
            self._copy_resources(compute_node, resources)
            compute_node.save()
            return

        # there was no local copy and none in the database
        # so we need to create a new compute node. This needs
        # to be initialised with resource values.
        compute_node = objects.ComputeNode(context)
        service = objects.Service.get_by_host_and_binary(
            context, self.host, 'nova-compute')
        compute_node.host = self.host
        compute_node.service_id = service['id']
        self._copy_resources(compute_node, resources)
        compute_node.create()
        LOG.info(_LI('Compute_service record created for '
                     '%(host)s:%(node)s'),
                 {'host': self.host, 'node': utils.get_node_name(self.host)})

    # NOTE(zhiyuan) register fake compute node information in db so nova
    # scheduler can properly select destination
    def pre_start_hook(self):
        site = self._site_manager.get_site(self.host)
        node = site.get_nodes()[0]
        resources = node.get_available_resource()
        context = nova_context.get_admin_context()
        self._init_compute_node(context, resources)

    def build_and_run_instance(self, context, instance, image, request_spec,
                               filter_properties, admin_password=None,
                               injected_files=None, requested_networks=None,
                               security_groups=None, block_device_mapping=None,
                               node=None, limits=None):
        version = '4.0'
        cctxt = self.proxy_client.prepare(version=version)
        cctxt.cast(context, 'build_and_run_instance', host=self.host,
                   instance=instance, image=image, request_spec=request_spec,
                   filter_properties=filter_properties,
                   admin_password=admin_password,
                   injected_files=injected_files,
                   requested_networks=requested_networks,
                   security_groups=security_groups,
                   block_device_mapping=block_device_mapping, node=node,
                   limits=limits)
