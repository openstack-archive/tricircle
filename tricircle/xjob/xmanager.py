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
import tricircle.db.api as db_api


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _job_handle(job_type):
    def handle_func(func):
        @six.wraps(func)
        def handle_args(*args, **kwargs):
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
        self.job_handles = {constants.JT_ROUTER: self.configure_extra_routes}
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

    @_job_handle(constants.JT_ROUTER)
    def configure_extra_routes(self, ctx, payload):
        # TODO(zhiyuan) performance and reliability issue
        # better have a job tracking mechanism
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
