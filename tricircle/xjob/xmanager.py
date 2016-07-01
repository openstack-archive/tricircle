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

import datetime
import eventlet
import netaddr
import random
import six

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task

from tricircle.common import client
from tricircle.common import constants
from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common.i18n import _LI
from tricircle.common.i18n import _LW
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.network import helper


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

IN_TEST = False
AZ_HINTS = 'availability_zone_hints'


def _job_handle(job_type):
    def handle_func(func):
        @six.wraps(func)
        def handle_args(*args, **kwargs):
            if IN_TEST:
                # NOTE(zhiyuan) job mechanism will cause some unpredictable
                # result in unit test so we would like to bypass it. However
                # we have problem mocking a decorator which decorates member
                # functions, that's why we use this label, not an elegant
                # way though.
                func(*args, **kwargs)
                return
            ctx = args[1]
            payload = kwargs['payload']

            resource_id = payload[job_type]
            db_api.new_job(ctx, job_type, resource_id)
            start_time = datetime.datetime.now()

            while True:
                current_time = datetime.datetime.now()
                delta = current_time - start_time
                if delta.seconds >= CONF.worker_handle_timeout:
                    # quit when this handle is running for a long time
                    break
                time_new = db_api.get_latest_timestamp(ctx, constants.JS_New,
                                                       job_type, resource_id)
                time_success = db_api.get_latest_timestamp(
                    ctx, constants.JS_Success, job_type, resource_id)
                if time_success and time_success >= time_new:
                    break
                job = db_api.register_job(ctx, job_type, resource_id)
                if not job:
                    # fail to obtain the lock, let other worker handle the job
                    running_job = db_api.get_running_job(ctx, job_type,
                                                         resource_id)
                    if not running_job:
                        # there are two reasons that running_job is None. one
                        # is that the running job has just been finished, the
                        # other is that all workers fail to register the job
                        # due to deadlock exception. so we sleep and try again
                        eventlet.sleep(CONF.worker_sleep_time)
                        continue
                    job_time = running_job['timestamp']
                    current_time = datetime.datetime.now()
                    delta = current_time - job_time
                    if delta.seconds > CONF.job_run_expire:
                        # previous running job expires, we set its status to
                        # fail and try again to obtain the lock
                        db_api.finish_job(ctx, running_job['id'], False,
                                          time_new)
                        LOG.warning(_LW('Job %(job)s of type %(job_type)s for '
                                        'resource %(resource)s expires, set '
                                        'its state to Fail'),
                                    {'job': running_job['id'],
                                     'job_type': job_type,
                                     'resource': resource_id})
                        eventlet.sleep(CONF.worker_sleep_time)
                        continue
                    else:
                        # previous running job is still valid, we just leave
                        # the job to the worker who holds the lock
                        break
                # successfully obtain the lock, start to execute handler
                try:
                    func(*args, **kwargs)
                except Exception:
                    db_api.finish_job(ctx, job['id'], False, time_new)
                    LOG.error(_LE('Job %(job)s of type %(job_type)s for '
                                  'resource %(resource)s fails'),
                              {'job': job['id'],
                               'job_type': job_type,
                               'resource': resource_id})
                    break
                db_api.finish_job(ctx, job['id'], True, time_new)
                eventlet.sleep(CONF.worker_sleep_time)
        return handle_args
    return handle_func


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
        self.clients = {constants.TOP: client.Client()}
        self.job_handles = {
            constants.JT_ROUTER: self.configure_extra_routes,
            constants.JT_ROUTER_SETUP: self.setup_bottom_router,
            constants.JT_PORT_DELETE: self.delete_server_port}
        self.helper = helper.NetworkHelper()
        self.xjob_handler = xrpcapi.XJobAPI()
        super(XManager, self).__init__()

    def _get_client(self, pod_name=None):
        if not pod_name:
            return self.clients[constants.TOP]
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

    @staticmethod
    def _get_resource_by_name(cli, cxt, _type, name):
        return cli.list_resources(_type, cxt, filters=[{'key': 'name',
                                                        'comparator': 'eq',
                                                        'value': name}])[0]

    @staticmethod
    def _get_router_interfaces(cli, cxt, router_id, net_id):
        return cli.list_ports(
            cxt, filters=[{'key': 'network_id', 'comparator': 'eq',
                           'value': net_id},
                          {'key': 'device_id', 'comparator': 'eq',
                           'value': router_id}])

    @periodic_task.periodic_task
    def redo_failed_job(self, ctx):
        failed_jobs = db_api.get_latest_failed_jobs(ctx)
        failed_jobs = [
            job for job in failed_jobs if job['type'] in self.job_handles]
        if not failed_jobs:
            return
        # in one run we only pick one job to handle
        job_index = random.randint(0, len(failed_jobs) - 1)
        failed_job = failed_jobs[job_index]
        job_type = failed_job['type']
        payload = {job_type: failed_job['resource_id']}
        LOG.debug(_('Redo failed job for %(resource_id)s of type '
                    '%(job_type)s'),
                  {'resource_id': failed_job['resource_id'],
                   'job_type': job_type})
        self.job_handles[job_type](ctx, payload=payload)

    @_job_handle(constants.JT_ROUTER_SETUP)
    def setup_bottom_router(self, ctx, payload):
        (b_pod_id,
         t_router_id, t_net_id) = payload[constants.JT_ROUTER_SETUP].split('#')

        t_client = self._get_client()
        t_pod = db_api.get_top_pod(ctx)
        b_pod = db_api.get_pod(ctx, b_pod_id)
        b_client = self._get_client(b_pod['pod_name'])
        b_az = b_pod['az_name']

        t_router = t_client.get_routers(ctx, t_router_id)
        if not t_router:
            # we just end this job if top router no longer exists
            return
        router_body = {'router': {'name': t_router_id,
                                  'distributed': False}}
        project_id = t_router['tenant_id']

        # create bottom router in target bottom pod
        _, b_router_id = self.helper.prepare_bottom_element(
            ctx, project_id, b_pod, t_router, 'router', router_body)

        # create top E-W bridge port
        t_bridge_net_name = constants.ew_bridge_net_name % project_id
        t_bridge_subnet_name = constants.ew_bridge_subnet_name % project_id
        t_bridge_net = self._get_resource_by_name(t_client, ctx, 'network',
                                                  t_bridge_net_name)
        t_bridge_subnet = self._get_resource_by_name(t_client, ctx, 'subnet',
                                                     t_bridge_subnet_name)
        q_cxt = None  # no need to pass neutron context when using client
        t_bridge_port_id = self.helper.get_bridge_interface(
            ctx, q_cxt, project_id, t_pod, t_bridge_net['id'],
            b_router_id, None, True)

        # create bottom E-W bridge port
        t_bridge_port = t_client.get_ports(ctx, t_bridge_port_id)
        (is_new, b_bridge_port_id,
         _, _) = self.helper.get_bottom_bridge_elements(
            ctx, project_id, b_pod, t_bridge_net, False, t_bridge_subnet,
            t_bridge_port)

        # attach bottom E-W bridge port to bottom router
        if is_new:
            # only attach bridge port the first time
            b_client.action_routers(ctx, 'add_interface', b_router_id,
                                    {'port_id': b_bridge_port_id})
        else:
            # still need to check if the bridge port is bound
            port = b_client.get_ports(ctx, b_bridge_port_id)
            if not port.get('device_id'):
                b_client.action_routers(ctx, 'add_interface', b_router_id,
                                        {'port_id': b_bridge_port_id})

        # handle N-S networking
        ext_nets = t_client.list_networks(ctx,
                                          filters=[{'key': 'router:external',
                                                    'comparator': 'eq',
                                                    'value': True}])
        if not ext_nets:
            need_ns_bridge = False
        else:
            ext_net_pod_names = set(
                [ext_net[AZ_HINTS][0] for ext_net in ext_nets])
            if b_pod['pod_name'] in ext_net_pod_names:
                need_ns_bridge = False
            else:
                need_ns_bridge = True
        if need_ns_bridge:
            t_bridge_net_name = constants.ns_bridge_net_name % project_id
            t_bridge_subnet_name = constants.ns_bridge_subnet_name % project_id
            t_bridge_net = self._get_resource_by_name(
                t_client, ctx, 'network', t_bridge_net_name)
            t_bridge_subnet = self._get_resource_by_name(
                t_client, ctx, 'subnet', t_bridge_subnet_name)
            # create bottom N-S bridge network and subnet
            (_, _, b_bridge_subnet_id,
             b_bridge_net_id) = self.helper.get_bottom_bridge_elements(
                ctx, project_id, b_pod, t_bridge_net, True,
                t_bridge_subnet, None)
            # create top N-S bridge port
            ns_bridge_port_id = self.helper.get_bridge_interface(
                ctx, q_cxt, project_id, t_pod, t_bridge_net['id'],
                b_router_id, None, False)
            ns_bridge_port = t_client.get_ports(ctx, ns_bridge_port_id)
            # add external gateway for bottom router
            # add gateway is update operation, can run multiple times
            gateway_ip = ns_bridge_port['fixed_ips'][0]['ip_address']
            b_client.action_routers(
                ctx, 'add_gateway', b_router_id,
                {'network_id': b_bridge_net_id,
                 'external_fixed_ips': [{'subnet_id': b_bridge_subnet_id,
                                         'ip_address': gateway_ip}]})

        # attach internal port to bottom router
        t_net = t_client.get_networks(ctx, t_net_id)
        if not t_net:
            # we just end this job if top network no longer exists
            return
        net_azs = t_net.get(AZ_HINTS, [])
        if net_azs and b_az not in net_azs:
            return
        t_ports = self._get_router_interfaces(t_client, ctx, t_router_id,
                                              t_net_id)
        b_net_id = db_api.get_bottom_id_by_top_id_pod_name(
            ctx, t_net_id, b_pod['pod_name'], constants.RT_NETWORK)
        if b_net_id:
            b_ports = self._get_router_interfaces(b_client, ctx, b_router_id,
                                                  b_net_id)
        else:
            b_ports = []
        if not t_ports and b_ports:
            # remove redundant bottom interface
            b_port = b_ports[0]
            request_body = {'port_id': b_port['id']}
            b_client.action_routers(ctx, 'remove_interface', b_router_id,
                                    request_body)
            with ctx.session.begin():
                core.delete_resources(ctx, models.ResourceRouting,
                                      filters=[{'key': 'bottom_id',
                                                'comparator': 'eq',
                                                'value': b_port['id']}])
        elif t_ports and not b_ports:
            # create new bottom interface
            t_port = t_ports[0]
            # only consider ipv4 address currently
            t_subnet_id = t_port['fixed_ips'][0]['subnet_id']
            t_subnet = t_client.get_subnets(ctx, t_subnet_id)
            b_port_id = self.helper.get_bottom_elements(
                ctx, project_id, b_pod, t_net, t_subnet, t_port)
            b_client.action_routers(ctx, 'add_interface', b_router_id,
                                    {'port_id': b_port_id})
        elif t_ports and b_ports:
            # when users remove the interface again, it's possible that top
            # interface is removed but deletion of bottom interface fails.
            # if users add the interface again during the retry of the job,
            # we have top and bottom interfaces exist but the id mapping
            # in the routing entry is incorrect, so we update it here
            t_port = t_ports[0]
            b_port = b_ports[0]
            with ctx.session.begin():
                core.update_resources(ctx, models.ResourceRouting,
                                      [{'key': 'bottom_id', 'comparator': 'eq',
                                        'value': b_port['id']},
                                       {'key': 'pod_id', 'comparator': 'eq',
                                        'value': b_pod_id}
                                       ], {'top_id': t_port['id']})

        self.xjob_handler.configure_extra_routes(ctx, t_router_id)

    @_job_handle(constants.JT_ROUTER)
    def configure_extra_routes(self, ctx, payload):
        t_router_id = payload[constants.JT_ROUTER]

        b_pods, b_router_ids = zip(*db_api.get_bottom_mappings_by_top_id(
            ctx, t_router_id, constants.RT_ROUTER))

        router_bridge_ip_map = {}
        router_cidr_map = {}
        for i, b_pod in enumerate(b_pods):
            bottom_client = self._get_client(pod_name=b_pod['pod_name'])
            b_inferfaces = bottom_client.list_ports(
                ctx, filters=[{'key': 'device_id',
                               'comparator': 'eq',
                               'value': b_router_ids[i]},
                              {'key': 'device_owner',
                               'comparator': 'eq',
                               'value': 'network:router_interface'}])
            cidrs = []
            for b_inferface in b_inferfaces:
                ip = b_inferface['fixed_ips'][0]['ip_address']
                ew_bridge_cidr = '100.0.0.0/9'
                ns_bridge_cidr = '100.128.0.0/9'
                if netaddr.IPAddress(ip) in netaddr.IPNetwork(ew_bridge_cidr):
                    router_bridge_ip_map[b_router_ids[i]] = ip
                    continue
                if netaddr.IPAddress(ip) in netaddr.IPNetwork(ns_bridge_cidr):
                    continue
                b_subnet = bottom_client.get_subnets(
                    ctx, b_inferface['fixed_ips'][0]['subnet_id'])
                cidrs.append(b_subnet['cidr'])
            router_cidr_map[b_router_ids[i]] = cidrs

        for i, b_router_id in enumerate(b_router_ids):
            if b_router_id not in router_bridge_ip_map:
                continue
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

    @_job_handle(constants.JT_PORT_DELETE)
    def delete_server_port(self, ctx, payload):
        t_port_id = payload[constants.JT_PORT_DELETE]
        self._get_client().delete_ports(ctx, t_port_id)
