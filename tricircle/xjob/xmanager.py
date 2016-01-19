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

import netaddr

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task

from tricircle.common import client
from tricircle.common import constants
from tricircle.common.i18n import _
from tricircle.common.i18n import _LI
import tricircle.db.api as db_api


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class XManager(PeriodicTasks):

    target = messaging.Target(version='1.0')

    def __init__(self, host=None, service_name='xjob'):

        LOG.debug(_('XManager initialization...'))

        if not host:
            host = CONF.host
        self.host = host
        self.service_name = service_name
        # self.notifier = rpc.get_notifier(self.service_name, self.host)
        self.additional_endpoints = []
        self.clients = {'top': client.Client()}
        super(XManager, self).__init__()

    def _get_client(self, pod_name=None):
        if not pod_name:
            return self.clients['top']
        if pod_name not in self.clients:
            self.clients[pod_name] = client.Client(pod_name)
        return self.clients[pod_name]

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

    def init_host(self):

        """init_host

        Hook to do additional manager initialization when one requests
        the service be started.  This is called before any service record
        is created.
        Child classes should override this method.
        """

        LOG.debug(_('XManager init_host...'))

        pass

    def cleanup_host(self):

        """cleanup_host

        Hook to do cleanup work when the service shuts down.
        Child classes should override this method.
        """

        LOG.debug(_('XManager cleanup_host...'))

        pass

    def pre_start_hook(self):

        """pre_start_hook

        Hook to provide the manager the ability to do additional
        start-up work before any RPC queues/consumers are created. This is
        called after other initialization has succeeded and a service
        record is created.
        Child classes should override this method.
        """

        LOG.debug(_('XManager pre_start_hook...'))

        pass

    def post_start_hook(self):

        """post_start_hook

        Hook to provide the manager the ability to do additional
        start-up work immediately after a service creates RPC consumers
        and starts 'running'.
        Child classes should override this method.
        """

        LOG.debug(_('XManager post_start_hook...'))

        pass

    # rpc message endpoint handling
    def test_rpc(self, ctx, payload):

        LOG.info(_LI("xmanager receive payload: %s"), payload)

        info_text = "xmanager receive payload: %s" % payload

        return info_text

    def configure_extra_routes(self, ctx, payload):
        # TODO(zhiyuan) performance and reliability issue
        # better have a job tracking mechanism
        t_router_id = payload['router']

        b_pods, b_router_ids = zip(*db_api.get_bottom_mappings_by_top_id(
            ctx, t_router_id, constants.RT_ROUTER))

        router_bridge_ip_map = {}
        router_cidr_map = {}
        for i, b_pod in enumerate(b_pods):
            bottom_client = self._get_client(pod_name=b_pod['pod_name'])
            b_inferfaces = bottom_client.list_ports(
                ctx, filters=[{'key': 'device_id',
                               'comparator': 'eq',
                               'value': b_router_ids[i]}])
            cidrs = []
            for b_inferface in b_inferfaces:
                ip = b_inferface['fixed_ips'][0]['ip_address']
                bridge_cidr = '100.0.0.0/8'
                if netaddr.IPAddress(ip) in netaddr.IPNetwork(bridge_cidr):
                    router_bridge_ip_map[b_router_ids[i]] = ip
                    continue
                b_subnet = bottom_client.get_subnets(
                    ctx, b_inferface['fixed_ips'][0]['subnet_id'])
                cidrs.append(b_subnet['cidr'])
            router_cidr_map[b_router_ids[i]] = cidrs

        for i, b_router_id in enumerate(b_router_ids):
            bottom_client = self._get_client(pod_name=b_pods[i]['pod_name'])
            extra_routes = []
            for router_id, cidrs in router_cidr_map.iteritems():
                if router_id == b_router_id:
                    continue
                for cidr in cidrs:
                    extra_routes.append(
                        {'nexthop': router_bridge_ip_map[router_id],
                         'destination': cidr})
            bottom_client.update_routers(ctx, b_router_id,
                                         {'router': {'routes': extra_routes}})
