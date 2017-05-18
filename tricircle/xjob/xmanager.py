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

import collections
import datetime
import eventlet
import netaddr
import random
import six

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task

import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions
import neutronclient.common.exceptions as q_cli_exceptions

from tricircle.common import client
from tricircle.common import constants
import tricircle.common.context as t_context
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
import tricircle.network.exceptions as t_network_exc
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
            start_time = datetime.datetime.now()

            while True:
                current_time = datetime.datetime.now()
                delta = current_time - start_time
                if delta.seconds >= CONF.worker_handle_timeout:
                    # quit when this handle is running for a long time
                    break
                job_new = db_api.get_latest_job(
                    ctx, constants.JS_New, job_type, resource_id)
                if not job_new:
                    break
                job_succ = db_api.get_latest_job(
                    ctx, constants.JS_Success, job_type, resource_id)
                if job_succ and job_succ['timestamp'] >= job_new['timestamp']:
                    break
                job = db_api.register_job(ctx, job_new['project_id'], job_type,
                                          resource_id)
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
                                          job_new['timestamp'])
                        LOG.warning('Job %(job)s of type %(job_type)s for '
                                    'resource %(resource)s expires, set '
                                    'its state to Fail',
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
                    db_api.finish_job(ctx, job['id'], False,
                                      job_new['timestamp'])
                    LOG.error('Job %(job)s of type %(job_type)s for '
                              'resource %(resource)s fails',
                              {'job': job['id'],
                               'job_type': job_type,
                               'resource': resource_id})
                    break
                db_api.finish_job(ctx, job['id'], True, job_new['timestamp'])
                eventlet.sleep(CONF.worker_sleep_time)
        return handle_args
    return handle_func


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class XManager(PeriodicTasks):

    target = messaging.Target(version='1.0')

    def __init__(self, host=None, service_name='xjob'):

        LOG.debug('XManager initialization...')

        if not host:
            host = CONF.host
        self.host = host
        self.service_name = service_name
        # self.notifier = rpc.get_notifier(self.service_name, self.host)
        self.additional_endpoints = []
        self.clients = {constants.TOP: client.Client()}
        self.job_handles = {
            constants.JT_CONFIGURE_ROUTE: self.configure_route,
            constants.JT_ROUTER_SETUP: self.setup_bottom_router,
            constants.JT_PORT_DELETE: self.delete_server_port,
            constants.JT_SEG_RULE_SETUP: self.configure_security_group_rules,
            constants.JT_NETWORK_UPDATE: self.update_network,
            constants.JT_SUBNET_UPDATE: self.update_subnet,
            constants.JT_SHADOW_PORT_SETUP: self.setup_shadow_ports,
            constants.JT_TRUNK_SYNC: self.sync_trunk}
        self.helper = helper.NetworkHelper()
        self.xjob_handler = xrpcapi.XJobAPI()
        super(XManager, self).__init__()

    def _get_client(self, region_name=None):
        if not region_name:
            return self.clients[constants.TOP]
        if region_name not in self.clients:
            self.clients[region_name] = client.Client(region_name)
        return self.clients[region_name]

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
        LOG.debug('XManager init_host...')

    def cleanup_host(self):
        """cleanup_host

        Hook to do cleanup work when the service shuts down.
        Child classes should override this method.
        """
        LOG.debug('XManager cleanup_host...')

    def pre_start_hook(self):
        """pre_start_hook

        Hook to provide the manager the ability to do additional
        start-up work before any RPC queues/consumers are created. This is
        called after other initialization has succeeded and a service
        record is created.
        Child classes should override this method.
        """
        LOG.debug('XManager pre_start_hook...')

    def post_start_hook(self):
        """post_start_hook

        Hook to provide the manager the ability to do additional
        start-up work immediately after a service creates RPC consumers
        and starts 'running'.
        Child classes should override this method.
        """
        LOG.debug('XManager post_start_hook...')

    # rpc message endpoint handling
    def test_rpc(self, ctx, payload):

        LOG.info("xmanager receive payload: %s", payload)

        info_text = "xmanager receive payload: %s" % payload

        return info_text

    @staticmethod
    def _get_resource_by_name(cli, cxt, _type, name):
        return cli.list_resources(_type, cxt, filters=[{'key': 'name',
                                                        'comparator': 'eq',
                                                        'value': name}])[0]

    @staticmethod
    def _get_router_interfaces(cli, cxt, router_id, net_id):
        interfaces = cli.list_ports(
            cxt, filters=[{'key': 'network_id', 'comparator': 'eq',
                           'value': net_id},
                          {'key': 'device_id', 'comparator': 'eq',
                           'value': router_id}])
        return [inf for inf in interfaces if inf['device_owner'] in (
            q_constants.DEVICE_OWNER_ROUTER_INTF,
            q_constants.DEVICE_OWNER_DVR_INTERFACE)]

    @periodic_task.periodic_task
    def redo_failed_or_new_job(self, ctx):
        failed_jobs, new_jobs = db_api.get_latest_failed_or_new_jobs(ctx)
        failed_jobs = [
            job for job in failed_jobs if job['type'] in self.job_handles]
        new_jobs = [
            job for job in new_jobs if job['type'] in self.job_handles]
        if not failed_jobs and not new_jobs:
            return
        if new_jobs:
            jobs = new_jobs
            is_new_job = True
        else:
            jobs = failed_jobs
            is_new_job = False
        # in one run we only pick one job to handle
        job_index = random.randint(0, len(jobs) - 1)
        job_type = jobs[job_index]['type']
        resource_id = jobs[job_index]['resource_id']
        project_id = jobs[job_index]['project_id']
        payload = {job_type: resource_id}
        LOG.debug('Redo %(status)s job for %(resource_id)s of type '
                  '%(job_type)s',
                  {'status': 'new' if is_new_job else 'failed',
                   'resource_id': resource_id, 'job_type': job_type})
        # this is an admin context, we set the correct project id
        ctx.tenant = project_id
        if not is_new_job:
            db_api.new_job(ctx, project_id, job_type, resource_id)
        self.job_handles[job_type](ctx, payload=payload)

    @staticmethod
    def _safe_create_bottom_floatingip(t_ctx, pod, client, fip_net_id,
                                       fip_address, port_id):
        try:
            client.create_floatingips(
                t_ctx, {'floatingip': {'floating_network_id': fip_net_id,
                                       'floating_ip_address': fip_address,
                                       'port_id': port_id}})
        except q_cli_exceptions.IpAddressInUseClient:
            fips = client.list_floatingips(t_ctx,
                                           [{'key': 'floating_ip_address',
                                             'comparator': 'eq',
                                             'value': fip_address}])
            if not fips:
                # this is rare case that we got IpAddressInUseClient exception
                # a second ago but now the floating ip is missing
                raise t_network_exc.BottomPodOperationFailure(
                    resource='floating ip', region_name=pod['region_name'])
            associated_port_id = fips[0].get('port_id')
            if associated_port_id == port_id:
                # if the internal port associated with the existing fip is what
                # we expect, just ignore this exception
                pass
            elif not associated_port_id:
                # if the existing fip is not associated with any internal port,
                # update the fip to add association
                client.update_floatingips(t_ctx, fips[0]['id'],
                                          {'floatingip': {'port_id': port_id}})
            else:
                raise

    def _setup_router_one_pod(self, ctx, t_pod, b_pod, t_client, t_net,
                              t_router, t_bridge_net, t_bridge_subnet,
                              is_ext_net_pod):
        # NOTE(zhiyuan) after the bridge network combination, external network
        # is attached to a separate router, which is created in central plugin,
        # so is_ext_net_pod is not used in the current implementation, but we
        # choose to keep this parameter since it's an important attribute of a
        # pod and we may need to use it later.
        b_client = self._get_client(b_pod['region_name'])

        is_distributed = t_router.get('distributed', False)
        router_body = {'router': {'name': t_router['id'],
                                  'distributed': is_distributed}}
        project_id = t_router['tenant_id']
        q_ctx = None  # no need to pass neutron context when using client
        is_local_router = self.helper.is_local_router(ctx, t_router)

        if is_local_router:
            # for local router, it's safe for us to get the first element as
            # pod name
            pod_name = self.helper.get_router_az_hints(t_router)[0]
            if pod_name != b_pod['region_name']:
                # now we allow to attach a cross-pod network to a local router,
                # so if the pod of the local router is different from the pod
                # of the bottom network, we do nothing.
                return

        # create bottom router in target bottom pod
        _, b_router_id = self.helper.prepare_bottom_element(
            ctx, project_id, b_pod, t_router, constants.RT_ROUTER, router_body)

        if not is_local_router:
            # create top bridge port
            t_bridge_port_id = self.helper.get_bridge_interface(
                ctx, q_ctx, project_id, t_pod, t_bridge_net['id'], b_router_id)

            # create bottom bridge port
            # if target bottom pod is hosting real external network, we create
            # another bottom router and attach the bridge network as internal
            # network, but this work is done by central plugin when user sets
            # router gateway.
            t_bridge_port = t_client.get_ports(ctx, t_bridge_port_id)
            (is_new, b_bridge_port_id, b_bridge_subnet_id,
             b_bridge_net_id) = self.helper.get_bottom_bridge_elements(
                ctx, project_id, b_pod, t_bridge_net,
                True, t_bridge_subnet, None)

            # we attach the bridge port as router gateway
            # add_gateway is update operation, which can run multiple times
            gateway_ip = t_bridge_port['fixed_ips'][0]['ip_address']
            b_client.action_routers(
                ctx, 'add_gateway', b_router_id,
                {'network_id': b_bridge_net_id,
                 'enable_snat': False,
                 'external_fixed_ips': [{'subnet_id': b_bridge_subnet_id,
                                         'ip_address': gateway_ip}]})

        # attach internal port to bottom router
        t_ports = self._get_router_interfaces(t_client, ctx, t_router['id'],
                                              t_net['id'])
        b_net_id = db_api.get_bottom_id_by_top_id_region_name(
            ctx, t_net['id'], b_pod['region_name'], constants.RT_NETWORK)
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
        elif t_ports and not b_ports:
            # create new bottom interface
            t_port = t_ports[0]

            # only consider ipv4 address currently
            t_subnet_id = t_port['fixed_ips'][0]['subnet_id']
            t_port_ip = t_port['fixed_ips'][0]['ip_address']
            t_subnet = t_client.get_subnets(ctx, t_subnet_id)
            is_default_gw = t_port_ip == t_subnet['gateway_ip']

            if CONF.enable_api_gateway:
                (b_net_id,
                 subnet_map) = self.helper.prepare_bottom_network_subnets(
                    ctx, q_ctx, project_id, b_pod, t_net, [t_subnet])
            else:
                (b_net_id,
                 subnet_map) = (t_net['id'], {t_subnet['id']: t_subnet['id']})

            if is_local_router:
                # if the attaching router is local router, we update the bottom
                # subnet gateway ip to the interface ip
                new_pools = self.helper.get_bottom_subnet_pools(t_subnet,
                                                                t_port_ip)
                b_client.update_subnets(ctx, t_subnet_id,
                                        {'subnet': {
                                            'gateway_ip': t_port_ip,
                                            'allocation_pools': new_pools}})
                b_client.action_routers(
                    ctx, 'add_interface', b_router_id,
                    {'subnet_id': subnet_map[t_subnet_id]})
            else:
                # the attaching router is not local router
                if is_default_gw:
                    # if top interface ip is equal to gateway ip of top subnet,
                    # bottom subnet gateway is set to the ip of the reservered
                    # gateway port, so we just attach the bottom subnet to the
                    # bottom router and local neutron server will create the
                    # interface for us, using the gateway ip.
                    b_client.action_routers(
                        ctx, 'add_interface', b_router_id,
                        {'subnet_id': subnet_map[t_subnet_id]})
                else:
                    # if top interface ip is different from gateway ip of top
                    # subnet, meaning that this interface is explicitly created
                    # by users, then the subnet may be already attached to a
                    # local router and its gateway ip is changed, so we need to
                    # query the reservered gateway port to get its ip.
                    gateway_port_name = constants.interface_port_name % (
                        b_pod['region_name'], t_subnet['id'])
                    gateway_port = t_client.list_ports(
                        ctx, filters=[{'key': 'name',
                                       'comparator': 'eq',
                                       'value': gateway_port_name}])[0]
                    b_port_body = self.helper.get_create_port_body(
                        gateway_port['project_id'], gateway_port,
                        {t_subnet_id: t_subnet_id}, b_net_id)
                    b_port_body['port'][
                        'device_owner'] = q_constants.DEVICE_OWNER_ROUTER_INTF
                    b_port = b_client.create_ports(ctx, b_port_body)
                    b_client.action_routers(ctx, 'add_interface', b_router_id,
                                            {'port_id': b_port['id']})

        if not t_router['external_gateway_info']:
            return

        # handle floatingip
        t_ext_net_id = t_router['external_gateway_info']['network_id']
        t_fips = t_client.list_floatingips(ctx, [{'key': 'floating_network_id',
                                                  'comparator': 'eq',
                                                  'value': t_ext_net_id}])
        # skip unbound top floatingip
        t_ip_fip_map = dict([(fip['floating_ip_address'],
                              fip) for fip in t_fips if fip['port_id']])
        mappings = db_api.get_bottom_mappings_by_top_id(ctx, t_ext_net_id,
                                                        constants.RT_NETWORK)
        # bottom external network should exist
        b_ext_pod, b_ext_net_id = mappings[0]
        b_ext_client = self._get_client(b_ext_pod['region_name'])
        b_fips = b_ext_client.list_floatingips(
            ctx, [{'key': 'floating_network_id', 'comparator': 'eq',
                   'value': b_ext_net_id}])
        b_ip_fip_map = dict([(fip['floating_ip_address'],
                              fip) for fip in b_fips])
        add_fips = [ip for ip in t_ip_fip_map if ip not in b_ip_fip_map]
        del_fips = [ip for ip in b_ip_fip_map if ip not in t_ip_fip_map]

        for add_fip in add_fips:
            fip = t_ip_fip_map[add_fip]
            t_int_port_id = fip['port_id']
            b_int_port_id = db_api.get_bottom_id_by_top_id_region_name(
                ctx, t_int_port_id, b_pod['region_name'], constants.RT_PORT)
            if not b_int_port_id:
                LOG.warning('Port %(port_id)s associated with floating ip '
                            '%(fip)s is not mapped to bottom pod',
                            {'port_id': t_int_port_id, 'fip': add_fip})
                continue
            t_int_port = t_client.get_ports(ctx, t_int_port_id)
            if t_int_port['network_id'] != t_net['id']:
                # only handle floating ip association for the given top network
                continue

            if b_ext_pod['pod_id'] != b_pod['pod_id']:
                # if the internal port is not located in the external network
                # pod, we need to create a shadow port in that pod for floating
                # ip association purpose
                t_int_net_id = t_int_port['network_id']
                t_int_subnet_id = t_int_port['fixed_ips'][0]['subnet_id']

                b_int_port = b_client.get_ports(ctx, b_int_port_id)
                host = b_int_port['binding:host_id']
                agent_type = self.helper.get_agent_type_by_vif(
                    b_int_port['binding:vif_type'])
                agent = db_api.get_agent_by_host_type(ctx, host, agent_type)
                max_bulk_size = CONF.client.max_shadow_port_bulk_size
                self.helper.prepare_shadow_ports(
                    ctx, project_id, b_ext_pod, t_int_net_id,
                    [b_int_port], [agent], max_bulk_size)

                # create routing entries for shadow network and subnet so we
                # can easily find them during central network and subnet
                # deletion, create_resource_mapping will catch DBDuplicateEntry
                # exception and ignore it so it's safe to call this function
                # multiple times
                db_api.create_resource_mapping(ctx, t_int_net_id, t_int_net_id,
                                               b_ext_pod['pod_id'], project_id,
                                               constants.RT_SD_NETWORK)
                db_api.create_resource_mapping(ctx, t_int_subnet_id,
                                               t_int_subnet_id,
                                               b_ext_pod['pod_id'], project_id,
                                               constants.RT_SD_SUBNET)

            self._safe_create_bottom_floatingip(
                ctx, b_pod, b_ext_client, b_ext_net_id, add_fip,
                b_int_port_id)

        for del_fip in del_fips:
            fip = b_ip_fip_map[del_fip]
            if b_ext_pod['pod_id'] != b_pod['pod_id'] and fip['port_id']:
                # shadow port is created in this case, but we leave shadow port
                # deletion work to plugin, so do nothing
                pass
            b_ext_client.delete_floatingips(ctx, fip['id'])

    @_job_handle(constants.JT_ROUTER_SETUP)
    def setup_bottom_router(self, ctx, payload):
        (b_pod_id,
         t_router_id, t_net_id) = payload[constants.JT_ROUTER_SETUP].split('#')

        t_client = self._get_client()
        t_pod = db_api.get_top_pod(ctx)
        t_router = t_client.get_routers(ctx, t_router_id)

        if not t_router:
            # we just end this job if top router no longer exists
            return

        project_id = t_router['tenant_id']
        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_net_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                # NOTE(zhiyuan) we create one job for each pod to avoid
                # conflict caused by different workers operating the same pod
                self.xjob_handler.setup_bottom_router(
                    ctx, project_id, t_net_id, t_router_id, b_pod['pod_id'])
            return

        t_net = t_client.get_networks(ctx, t_net_id)
        if not t_net:
            # we just end this job if top network no longer exists
            return
        project_id = t_router['tenant_id']

        b_pod = db_api.get_pod(ctx, b_pod_id)
        is_local_router = self.helper.is_local_router(ctx, t_router)
        if is_local_router:
            t_bridge_net = None
            t_bridge_subnet = None
        else:
            t_bridge_net_name = constants.bridge_net_name % project_id
            t_bridge_subnet_name = constants.bridge_subnet_name % project_id
            t_bridge_net = self._get_resource_by_name(t_client, ctx, 'network',
                                                      t_bridge_net_name)
            t_bridge_subnet = self._get_resource_by_name(
                t_client, ctx, 'subnet', t_bridge_subnet_name)

        ext_nets = t_client.list_networks(ctx,
                                          filters=[{'key': 'router:external',
                                                    'comparator': 'eq',
                                                    'value': True}])
        ext_net_region_names = set(
            [ext_net[AZ_HINTS][0] for ext_net in ext_nets])

        if not ext_net_region_names:
            is_ext_net_pod = False
        elif b_pod['region_name'] in ext_net_region_names:
            is_ext_net_pod = True
        else:
            is_ext_net_pod = False

        self._setup_router_one_pod(
            ctx, t_pod, b_pod, t_client, t_net, t_router, t_bridge_net,
            t_bridge_subnet, is_ext_net_pod)
        if not is_local_router:
            self.xjob_handler.configure_route(ctx, project_id,
                                              t_router_id)

    @_job_handle(constants.JT_CONFIGURE_ROUTE)
    def configure_route(self, ctx, payload):
        t_router_id = payload[constants.JT_CONFIGURE_ROUTE]
        t_client = self._get_client()
        t_router = t_client.get_routers(ctx, t_router_id)
        if not t_router:
            return
        if t_router.get('external_gateway_info'):
            t_ext_net_id = t_router['external_gateway_info']['network_id']
        else:
            t_ext_net_id = None

        non_vm_port_types = [q_constants.DEVICE_OWNER_ROUTER_INTF,
                             q_constants.DEVICE_OWNER_DVR_INTERFACE,
                             q_constants.DEVICE_OWNER_ROUTER_SNAT,
                             q_constants.DEVICE_OWNER_ROUTER_GW,
                             q_constants.DEVICE_OWNER_DHCP,
                             constants.DEVICE_OWNER_SHADOW]
        ew_attached_port_types = [q_constants.DEVICE_OWNER_ROUTER_INTF,
                                  q_constants.DEVICE_OWNER_DVR_INTERFACE,
                                  q_constants.DEVICE_OWNER_ROUTER_GW]
        ns_attached_port_types = [q_constants.DEVICE_OWNER_ROUTER_INTF,
                                  q_constants.DEVICE_OWNER_DVR_INTERFACE]

        mappings = db_api.get_bottom_mappings_by_top_id(ctx, t_router_id,
                                                        constants.RT_ROUTER)
        if not mappings:
            b_pods, b_router_ids = [], []
        else:
            b_pods, b_router_ids = map(list, zip(*mappings))
        ns_mappings = db_api.get_bottom_mappings_by_top_id(
            ctx, t_router_id, constants.RT_NS_ROUTER)
        b_ns_pdd, b_ns_router_id = None, None
        if ns_mappings:
            b_ns_pdd, b_ns_router_id = ns_mappings[0]
            b_pods.append(b_ns_pdd)
            b_router_ids.append(b_ns_router_id)

        router_ew_bridge_ip_map = {}
        router_ns_bridge_ip_map = {}
        router_ips_map = {}

        pod_subnet_nexthop_map = {}  # {pod_name: {subnet_id: nexthop}
        subnet_cidr_map = {}  # {subnet_id: cidr}

        for i, b_pod in enumerate(b_pods):
            is_ns_router = b_router_ids[i] == b_ns_router_id
            bottom_client = self._get_client(b_pod['region_name'])
            if is_ns_router:
                device_owner_filter = ns_attached_port_types
            else:
                device_owner_filter = ew_attached_port_types
            b_interfaces = bottom_client.list_ports(
                ctx, filters=[{'key': 'device_id',
                               'comparator': 'eq',
                               'value': b_router_ids[i]},
                              {'key': 'device_owner',
                               'comparator': 'eq',
                               'value': device_owner_filter}])
            router_ips_map[b_router_ids[i]] = {}
            pod_subnet_nexthop_map[b_pod['region_name']] = {}

            for b_interface in b_interfaces:
                ip = b_interface['fixed_ips'][0]['ip_address']
                bridge_cidr = CONF.client.bridge_cidr
                if netaddr.IPAddress(ip) in netaddr.IPNetwork(bridge_cidr):
                    if is_ns_router:
                        # this ip is the default gateway ip for north-south
                        # networking
                        router_ns_bridge_ip_map[b_router_ids[i]] = ip
                    else:
                        # this ip is the next hop for east-west networking
                        router_ew_bridge_ip_map[b_router_ids[i]] = ip
                    continue
                b_net_id = b_interface['network_id']
                b_subnet_id = b_interface['fixed_ips'][0]['subnet_id']

                b_subnet = bottom_client.get_subnets(ctx, b_subnet_id)
                if b_subnet['gateway_ip'] != ip:
                    # ip of the interface attached to the non local router is
                    # different from the gateway ip, meaning that the interface
                    # is for east-west traffic purpose, so we save necessary
                    # information for next process
                    pod_subnet_nexthop_map[
                        b_pod['region_name']][b_subnet_id] = ip
                    subnet_cidr_map[b_subnet_id] = b_subnet['cidr']

                b_ports = bottom_client.list_ports(
                    ctx, filters=[{'key': 'network_id',
                                   'comparator': 'eq',
                                   'value': b_net_id}])
                b_vm_ports = [b_port for b_port in b_ports if b_port.get(
                    'device_owner', '') not in non_vm_port_types]
                ips = [vm_port['fixed_ips'][0][
                    'ip_address'] for vm_port in b_vm_ports]
                router_ips_map[b_router_ids[i]][b_subnet['cidr']] = ips

        # handle extra routes for east-west traffic
        for i, b_router_id in enumerate(b_router_ids):
            if b_router_id == b_ns_router_id:
                continue
            bottom_client = self._get_client(b_pods[i]['region_name'])
            extra_routes = []
            if not router_ips_map[b_router_id]:
                bottom_client.update_routers(
                    ctx, b_router_id, {'router': {'routes': extra_routes}})
                continue
            for router_id, cidr_ips_map in six.iteritems(router_ips_map):
                if router_id == b_router_id:
                    continue
                for cidr, ips in six.iteritems(cidr_ips_map):
                    if router_ips_map[b_router_id].get(cidr):
                        # if the ip list is not empty, meaning that there are
                        # already vm ports in the pod of b_router, so no need
                        # to add extra routes
                        continue
                    for ip in ips:
                        route = {'nexthop': router_ew_bridge_ip_map[router_id],
                                 'destination': ip + '/32'}
                        extra_routes.append(route)

            if router_ns_bridge_ip_map and t_ext_net_id:
                extra_routes.append(
                    {'nexthop': router_ns_bridge_ip_map.values()[0],
                     'destination': constants.DEFAULT_DESTINATION})
            bottom_client.update_routers(
                ctx, b_router_id, {'router': {'routes': extra_routes}})

        # configure host routes for local network attached to local router
        for (pod_name,
             subnet_nexthop_map) in pod_subnet_nexthop_map.items():
            for subnet_id, nexthop in subnet_nexthop_map.items():
                host_routes = []
                for _subnet_id, cidr in subnet_cidr_map.items():
                    if _subnet_id in subnet_nexthop_map:
                        continue
                    host_routes.append({'destination': cidr,
                                        'nexthop': nexthop})
                bottom_client = self._get_client(pod_name)
                bottom_client.update_subnets(
                    ctx, subnet_id, {'subnet': {'host_routes': host_routes}})

        if not b_ns_router_id:
            # router for north-south networking not exist, skip extra routes
            # configuration for north-south router
            return
        if not t_ext_net_id:
            # router not attached to external gateway but router for north-
            # south networking exists, clear the extra routes
            bottom_client = self._get_client(b_ns_pdd['region_name'])
            bottom_client.update_routers(
                ctx, b_ns_router_id, {'router': {'routes': []}})
            return

        # handle extra routes for north-south router
        ip_bridge_ip_map = {}
        for router_id, cidr_ips_map in six.iteritems(router_ips_map):
            if router_id not in router_ew_bridge_ip_map:
                continue
            for cidr, ips in six.iteritems(cidr_ips_map):
                for ip in ips:
                    nexthop = router_ew_bridge_ip_map[router_id]
                    destination = ip + '/32'
                    ip_bridge_ip_map[destination] = nexthop

        bottom_client = self._get_client(b_ns_pdd['region_name'])
        extra_routes = []
        for fixed_ip in ip_bridge_ip_map:
            extra_routes.append(
                {'nexthop': ip_bridge_ip_map[fixed_ip],
                 'destination': fixed_ip})
        bottom_client.update_routers(
            ctx, b_ns_router_id, {'router': {'routes': extra_routes}})

    @_job_handle(constants.JT_PORT_DELETE)
    def delete_server_port(self, ctx, payload):
        b_pod_id, b_port_id = payload[constants.JT_PORT_DELETE].split('#')
        b_pod = db_api.get_pod(ctx, b_pod_id)
        self._get_client(b_pod['region_name']).delete_ports(ctx, b_port_id)

    @staticmethod
    def _safe_create_security_group_rule(context, client, body):
        try:
            client.create_security_group_rules(context, body)
        except q_exceptions.Conflict:
            return

    @staticmethod
    def _safe_delete_security_group_rule(context, client, _id):
        try:
            client.delete_security_group_rules(context, _id)
        except q_exceptions.NotFound:
            return

    @staticmethod
    def _construct_bottom_rule(rule, sg_id, ip=None):
        ip = ip or rule['remote_ip_prefix']
        # if ip is passed, this is an extended rule for remote group
        return {'remote_group_id': None,
                'direction': rule['direction'],
                'remote_ip_prefix': ip,
                'protocol': rule.get('protocol'),
                'ethertype': rule['ethertype'],
                'port_range_max': rule.get('port_range_max'),
                'port_range_min': rule.get('port_range_min'),
                'security_group_id': sg_id}

    @staticmethod
    def _compare_rule(rule1, rule2):
        for key in ('direction', 'remote_ip_prefix', 'protocol', 'ethertype',
                    'port_range_max', 'port_range_min'):
            if rule1[key] != rule2[key]:
                return False
        return True

    @_job_handle(constants.JT_SEG_RULE_SETUP)
    def configure_security_group_rules(self, ctx, payload):
        project_id = payload[constants.JT_SEG_RULE_SETUP]
        top_client = self._get_client()
        sg_filters = [{'key': 'tenant_id', 'comparator': 'eq',
                       'value': project_id}]
        top_sgs = top_client.list_security_groups(ctx, sg_filters)
        for top_sg in top_sgs:
            new_b_rules = []
            for t_rule in top_sg['security_group_rules']:
                if not t_rule['remote_group_id']:
                    # leave sg_id empty here
                    new_b_rules.append(
                        self._construct_bottom_rule(t_rule, ''))
                    continue
                if top_sg['name'] != 'default':
                    # currently we only handle rules containing remote_group_id
                    # for default security group
                    continue
                if t_rule['ethertype'] != 'IPv4':
                    continue
                subnets = top_client.list_subnets(
                    ctx, [{'key': 'tenant_id', 'comparator': 'eq',
                           'value': project_id}])
                bridge_ip_net = netaddr.IPNetwork(CONF.client.bridge_cidr)
                subnet_cidr_set = set()
                for subnet in subnets:
                    ip_net = netaddr.IPNetwork(subnet['cidr'])
                    if ip_net in bridge_ip_net:
                        continue
                    # leave sg_id empty here.
                    # Tricircle has not supported IPv6 well yet,
                    # so we ignore seg rules temporarily.
                    if subnet['ip_version'] == q_constants.IP_VERSION_4:
                        if subnet['cidr'] in subnet_cidr_set:
                            continue
                        subnet_cidr_set.add(subnet['cidr'])
                        new_b_rules.append(
                            self._construct_bottom_rule(t_rule, '',
                                                        subnet['cidr']))

            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, top_sg['id'], constants.RT_SG)
            for pod, b_sg_id in mappings:
                client = self._get_client(pod['region_name'])
                b_sg = client.get_security_groups(ctx, b_sg_id)
                add_rules = []
                del_rules = []
                match_index = set()
                for b_rule in b_sg['security_group_rules']:
                    match = False
                    for i, rule in enumerate(new_b_rules):
                        if self._compare_rule(b_rule, rule):
                            match = True
                            match_index.add(i)
                            break
                    if not match:
                        del_rules.append(b_rule)
                for i, rule in enumerate(new_b_rules):
                    if i not in match_index:
                        add_rules.append(rule)

                for del_rule in del_rules:
                    self._safe_delete_security_group_rule(
                        ctx, client, del_rule['id'])
                if add_rules:
                    rule_body = {'security_group_rules': []}
                    for add_rule in add_rules:
                        add_rule['security_group_id'] = b_sg_id
                        rule_body['security_group_rules'].append(add_rule)
                    self._safe_create_security_group_rule(
                        ctx, client, rule_body)

    @_job_handle(constants.JT_NETWORK_UPDATE)
    def update_network(self, ctx, payload):
        """update bottom network

        if bottom pod id equal to POD_NOT_SPECIFIED, dispatch jobs for every
        mapped bottom pod via RPC, otherwise update network in the specified
        pod.

        :param ctx: tricircle context
        :param payload: dict whose key is JT_NETWORK_UPDATE and value
        is "bottom_pod_id#top_network_id"
        :return: None
        """
        (b_pod_id, t_network_id) = payload[
            constants.JT_NETWORK_UPDATE].split('#')

        t_client = self._get_client()
        t_network = t_client.get_networks(ctx, t_network_id)
        if not t_network:
            return

        project_id = t_network['tenant_id']
        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_network_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                self.xjob_handler.update_network(ctx, project_id,
                                                 t_network_id, b_pod['pod_id'])
            return

        b_pod = db_api.get_pod(ctx, b_pod_id)
        b_region_name = b_pod['region_name']
        b_client = self._get_client(region_name=b_region_name)
        b_network_id = db_api.get_bottom_id_by_top_id_region_name(
            ctx, t_network_id, b_region_name, constants.RT_NETWORK)
        # name is not allowed to be updated, because it is used by
        # lock_handle to retrieve bottom/local resources that have been
        # created but not registered in the resource routing table
        body = {
            'network': {
                'description': t_network['description'],
                'admin_state_up': t_network['admin_state_up'],
                'shared': t_network['shared']
            }
        }

        try:
            b_client.update_networks(ctx, b_network_id, body)
        except q_cli_exceptions.NotFound:
            LOG.error('network: %(net_id)s not found,'
                      'pod name: %(name)s',
                      {'net_id': b_network_id, 'name': b_region_name})

    @_job_handle(constants.JT_SUBNET_UPDATE)
    def update_subnet(self, ctx, payload):
        """update bottom subnet

        if bottom pod id equal to POD_NOT_SPECIFIED, dispatch jobs for every
        mapped bottom pod via RPC, otherwise update subnet in the specified
        pod.

        :param ctx: tricircle context
        :param payload: dict whose key is JT_SUBNET_UPDATE and value
        is "bottom_pod_id#top_subnet_id"
        :return: None
        """
        (b_pod_id, t_subnet_id) = payload[
            constants.JT_SUBNET_UPDATE].split('#')

        t_client = self._get_client()
        t_subnet = t_client.get_subnets(ctx, t_subnet_id)
        if not t_subnet:
            return

        project_id = t_subnet['tenant_id']
        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_subnet_id, constants.RT_SUBNET)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                self.xjob_handler.update_subnet(ctx, project_id,
                                                t_subnet_id, b_pod['pod_id'])
            return

        b_pod = db_api.get_pod(ctx, b_pod_id)
        b_region_name = b_pod['region_name']
        b_subnet_id = db_api.get_bottom_id_by_top_id_region_name(
            ctx, t_subnet_id, b_region_name, constants.RT_SUBNET)
        b_client = self._get_client(region_name=b_region_name)
        b_subnet = b_client.get_subnets(ctx, b_subnet_id)
        b_gateway_ip = b_subnet['gateway_ip']

        # we need to remove the bottom subnet gateway ip from the top subnet
        # allaction pools
        b_allocation_pools = helper.NetworkHelper.get_bottom_subnet_pools(
            t_subnet, b_gateway_ip)

        # bottom gateway_ip doesn't need to be updated, because it is reserved
        # by top pod.
        # name is not allowed to be updated, because it is used by
        # lock_handle to retrieve bottom/local resources that have been
        # created but not registered in the resource routing table
        body = {
            'subnet':
                {'description': t_subnet['description'],
                 'enable_dhcp': t_subnet['enable_dhcp'],
                 'allocation_pools': b_allocation_pools,
                 'host_routes': t_subnet['host_routes'],
                 'dns_nameservers': t_subnet['dns_nameservers']}
        }
        try:
            b_client.update_subnets(ctx, b_subnet_id, body)
        except q_cli_exceptions.NotFound:
            LOG.error('subnet: %(subnet_id)s not found, '
                      'pod name: %(name)s',
                      {'subnet_id': b_subnet_id, 'name': b_region_name})

    @_job_handle(constants.JT_SHADOW_PORT_SETUP)
    def setup_shadow_ports(self, ctx, payload):
        """Setup shadow ports for the target pod and network

        this job workes as following:
        (1) query all shadow ports from pods the target network is mapped to
        (2) query all real ports from pods the target network is mapped to
        (3) check the shadow ports and real ports in the target pod, create
            needed shadow ports
        (4) check the shadow ports and real ports in other pods, create a new
            job if the pod lacks some shadow ports

        :param ctx: tricircle context
        :param payload: {JT_SHADOW_PORT_SETUP: pod_id#network_id}
        :return: None
        """
        run_label = 'during shadow ports setup'

        (target_pod_id,
         t_net_id) = payload[constants.JT_SHADOW_PORT_SETUP].split('#')
        target_pod = db_api.get_pod(ctx, target_pod_id)
        t_client = self._get_client()
        t_net = t_client.get_networks(ctx, t_net_id)
        if not t_net:
            # we just end this job if top network no longer exists
            return
        project_id = t_net['tenant_id']
        mappings = db_api.get_bottom_mappings_by_top_id(ctx, t_net_id,
                                                        constants.RT_NETWORK)
        pod_ids = set([pod['pod_id'] for pod, _ in mappings])
        pod_port_ids_map = collections.defaultdict(set)
        pod_sw_port_ids_map = {}
        port_info_map = {}
        if target_pod_id not in pod_ids:
            LOG.debug('Pod %s not found %s', target_pod_id, run_label)
            # network is not mapped to the specified pod, nothing to do
            return
        for b_pod, b_net_id in mappings:
            b_client = self._get_client(b_pod['region_name'])
            # port table has (network_id, device_owner) index
            b_sw_ports = b_client.list_ports(
                ctx, filters=[{'key': 'network_id', 'comparator': 'eq',
                               'value': b_net_id},
                              {'key': 'device_owner', 'comparator': 'eq',
                               'value': constants.DEVICE_OWNER_SHADOW},
                              {'key': 'fields', 'comparator': 'eq',
                               'value': ['id', 'status']}])
            b_sw_port_ids = set([port['id'] for port in b_sw_ports])
            if b_pod['pod_id'] == target_pod['pod_id']:
                b_down_sw_port_ids = set(
                    [port['id'] for port in b_sw_ports if (
                        port['status'] == q_constants.PORT_STATUS_DOWN)])
            pod_sw_port_ids_map[b_pod['pod_id']] = b_sw_port_ids
            # port table has (network_id, device_owner) index
            b_ports = b_client.list_ports(
                ctx, filters=[{'key': 'network_id', 'comparator': 'eq',
                               'value': b_net_id},
                              {'key': 'fields', 'comparator': 'eq',
                               'value': ['id', 'binding:vif_type',
                                         'binding:host_id', 'fixed_ips',
                                         'device_owner', 'mac_address']}])
            LOG.debug('Shadow ports %s in pod %s %s',
                      b_sw_ports, target_pod_id, run_label)
            LOG.debug('Ports %s in pod %s %s',
                      b_ports, target_pod_id, run_label)
            for b_port in b_ports:
                if not self.helper.is_need_top_sync_port(
                        b_port, cfg.CONF.client.bridge_cidr):
                    continue
                if b_port['device_owner'] == constants.DEVICE_OWNER_SHADOW:
                    continue
                b_port_id = b_port['id']
                pod_port_ids_map[b_pod['pod_id']].add(b_port_id)
                port_info_map[b_port_id] = b_port

        all_port_ids = set()
        for port_ids in six.itervalues(pod_port_ids_map):
            all_port_ids |= port_ids
        sync_port_ids = all_port_ids - (
            pod_port_ids_map[target_pod_id] | pod_sw_port_ids_map[
                target_pod_id])
        sync_pod_list = []
        for pod_id in pod_port_ids_map:
            if pod_id == target_pod_id:
                continue
            if pod_port_ids_map[target_pod_id] - (
                    pod_port_ids_map[pod_id] | pod_sw_port_ids_map[pod_id]):
                sync_pod_list.append(pod_id)

        LOG.debug('Sync port ids %s %s', sync_port_ids, run_label)
        LOG.debug('Sync pod ids %s %s', sync_pod_list, run_label)

        agent_info_map = {}
        port_bodys = []
        agents = []
        for port_id in sync_port_ids:
            port_body = port_info_map[port_id]
            host = port_body['binding:host_id']
            agent_type = self.helper.get_agent_type_by_vif(
                port_body['binding:vif_type'])
            if not agent_type:
                continue
            key = '%s#%s' % (host, agent_type)
            if key in agent_info_map:
                agent = agent_info_map[key]
            else:
                agent = db_api.get_agent_by_host_type(ctx, host, agent_type)
                if not agent:
                    LOG.error('Agent of type %(agent_type)s in '
                              'host %(host)s not found during shadow '
                              'ports setup',
                              {'agent_type': agent_type, 'host': host})
                    continue
                agent_info_map[key] = agent
            port_bodys.append(port_body)
            agents.append(agent)

        max_bulk_size = CONF.client.max_shadow_port_bulk_size
        sw_port_ids = self.helper.prepare_shadow_ports(
            ctx, project_id, target_pod, t_net_id, port_bodys, agents,
            max_bulk_size)
        b_down_sw_port_ids = b_down_sw_port_ids | set(sw_port_ids)
        # value for key constants.PROFILE_FORCE_UP does not matter
        update_body = {
            'port': {
                'binding:profile': {constants.PROFILE_FORCE_UP: 'True'}
            }
        }
        for sw_port_id in b_down_sw_port_ids:
            self._get_client(target_pod['region_name']).update_ports(
                ctx, sw_port_id, update_body)

        for pod_id in sync_pod_list:
            self.xjob_handler.setup_shadow_ports(ctx, project_id,
                                                 pod_id, t_net_id)

    def _get_bottom_need_created_subports(self, ctx, t_ctx, project_id,
                                          trunk_id, add_subport_ids):
        t_client = self._get_client()
        need_created_ports = []
        port_filters = [{'key': 'device_id',
                        'comparator': 'eq',
                         'value': trunk_id},
                        {'key': 'device_owner',
                         'comparator': 'eq',
                         'value': constants.DEVICE_OWNER_SUBPORT}
                        ]
        trunk_subports = t_client.list_ports(ctx, filters=port_filters)
        map_filters = [{'key': 'resource_type',
                        'comparator': 'eq',
                        'value': constants.RT_PORT},
                       {'key': 'project_id',
                        'comparator': 'eq',
                        'value': project_id}]

        port_mappings = db_api.list_resource_routings(t_ctx, map_filters)
        mapping_port_ids = [port['top_id'] for port in port_mappings]
        pop_attrs = ['status', 'tags', 'updated_at',
                     'created_at', 'revision_number', 'id']
        for port in trunk_subports:
            if (port['id'] in add_subport_ids
                    and port['id'] not in mapping_port_ids):
                port['device_id'] = port['id']
                # pop attributes which not allowed in POST
                for attr in pop_attrs:
                    port.pop(attr, None)
                need_created_ports.append(port)

        return need_created_ports

    def _create_trunk_subport_mapping(self, t_ctx, project_id, pod, ports):
        entries = []
        for port in ports:
            port['id'] = port['device_id']
            entries.extend(self.helper.extract_resource_routing_entries(port))
        self.helper.ensure_resource_mapping(t_ctx, project_id, pod, entries)

    def _create_bottom_trunk_subports(self, ctx, target_pod,
                                      full_create_bodys, max_bulk_size):
        cursor = 0
        ret_port_ids = []
        b_client = self._get_client(target_pod['region_name'])
        while cursor < len(full_create_bodys):
            ret_port_ids.extend(self.helper.prepare_ports_with_retry(
                ctx, b_client,
                full_create_bodys[cursor: cursor + max_bulk_size]))
            cursor += max_bulk_size
        return ret_port_ids

    @_job_handle(constants.JT_TRUNK_SYNC)
    def sync_trunk(self, ctx, payload):
        b_pod_id, t_trunk_id = payload[constants.JT_TRUNK_SYNC].split('#')
        b_pod = db_api.get_pod(ctx, b_pod_id)
        b_region_name = b_pod['region_name']
        b_client = self._get_client(region_name=b_region_name)
        b_trunk_id = db_api.get_bottom_id_by_top_id_region_name(
            ctx, t_trunk_id, b_region_name, constants.RT_TRUNK)
        if not b_trunk_id:
            return
        t_client = self._get_client()
        t_trunk = t_client.get_trunks(ctx, t_trunk_id)
        # delete trunk action
        if not t_trunk:
            b_client.delete_trunks(ctx, b_trunk_id)
            db_api.delete_mappings_by_top_id(ctx, t_trunk_id)
            return

        # update trunk action
        b_trunk = b_client.get_trunks(ctx, b_trunk_id)

        if not b_trunk:
            LOG.error('trunk: %(trunk_id)s not found, pod name: %(name)s',
                      {'trunk_id': b_trunk_id, 'name': b_region_name})
            return

        body = {
            'trunk':
                {'description': t_trunk['description'],
                 'admin_state_up': t_trunk['admin_state_up']}
        }

        t_subports = set(
            [(subport['port_id'],
              subport['segmentation_id']) for subport in t_trunk['sub_ports']])
        b_subports = set(
            [(subport['port_id'],
              subport['segmentation_id']) for subport in b_trunk['sub_ports']])
        add_subports = t_subports - b_subports
        del_subports = b_subports - t_subports

        add_subport_bodies = [
            {'port_id': subport[0],
             'segmentation_type': 'vlan',
             'segmentation_id': subport[1]} for subport in add_subports]

        del_subport_bodies = [
            {'port_id': subport[0]} for subport in del_subports]

        try:
            b_client.update_trunks(ctx, b_trunk_id, body)
            # must first delete subports, then add subports, otherwise it
            # will lead to the addition of existing subports
            if del_subport_bodies:
                b_client.action_trunks(ctx, 'remove_subports', b_trunk_id,
                                       {'sub_ports': del_subport_bodies})

            # create bottom ports bulk
            if add_subport_bodies:
                project_id = t_trunk['project_id']
                t_ctx = t_context.get_context_from_neutron_context(ctx)
                max_bulk_size = CONF.client.max_trunk_subports_bulk_size
                add_subport_ids = [
                    subport['port_id'] for subport in add_subport_bodies]
                need_created_ports = self._get_bottom_need_created_subports(
                    ctx, t_ctx, project_id, t_trunk_id, add_subport_ids)
                if need_created_ports:
                    self._create_bottom_trunk_subports(
                        ctx, b_pod, need_created_ports, max_bulk_size)
                    self._create_trunk_subport_mapping(
                        ctx, project_id, b_pod, need_created_ports)
                    self.xjob_handler.configure_security_group_rules(
                        t_ctx, project_id)

                b_client.action_trunks(ctx, 'add_subports', b_trunk_id,
                                       {'sub_ports': add_subport_bodies})
        except q_cli_exceptions.NotFound:
            LOG.error('trunk: %(trunk_id)s not found, pod name: %(name)s',
                      {'trunk_id': b_trunk_id, 'name': b_region_name})
