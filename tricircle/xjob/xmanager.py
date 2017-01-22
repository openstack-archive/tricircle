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

import neutron_lib.constants as q_constants
import neutron_lib.exceptions as q_exceptions
import neutronclient.common.exceptions as q_cli_exceptions

from tricircle.common import client
from tricircle.common import constants
from tricircle.common.i18n import _LE, _LI, _LW
from tricircle.common import xrpcapi
import tricircle.db.api as db_api
from tricircle.db import core
from tricircle.db import models
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
                time_new = db_api.get_latest_timestamp(ctx, constants.JS_New,
                                                       job_type, resource_id)
                if not time_new:
                    break
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

        LOG.debug('XManager initialization...')

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
            constants.JT_PORT_DELETE: self.delete_server_port,
            constants.JT_SEG_RULE_SETUP: self.configure_security_group_rules,
            constants.JT_NETWORK_UPDATE: self.update_network,
            constants.JT_SUBNET_UPDATE: self.update_subnet}
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
        payload = {job_type: resource_id}
        LOG.debug('Redo %(status)s job for %(resource_id)s of type '
                  '%(job_type)s',
                  {'status': 'new' if is_new_job else 'failed',
                   'resource_id': resource_id, 'job_type': job_type})
        if not is_new_job:
            db_api.new_job(ctx, job_type, resource_id)
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

        # create bottom router in target bottom pod
        _, b_router_id = self.helper.prepare_bottom_element(
            ctx, project_id, b_pod, t_router, constants.RT_ROUTER, router_body)

        # create top bridge port
        q_ctx = None  # no need to pass neutron context when using client
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
            ctx, project_id, b_pod, t_bridge_net, True, t_bridge_subnet, None)

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
            t_subnet = t_client.get_subnets(ctx, t_subnet_id)

            if CONF.enable_api_gateway:
                (b_net_id,
                 subnet_map) = self.helper.prepare_bottom_network_subnets(
                    ctx, q_ctx, project_id, b_pod, t_net, [t_subnet])
            else:
                (b_net_id,
                 subnet_map) = (t_net['id'], {t_subnet['id']: t_subnet['id']})

            # the gateway ip of bottom subnet is set to the ip of t_port, so
            # we just attach the bottom subnet to the bottom router and neutron
            # server in the bottom pod will create the interface for us, using
            # the gateway ip.
            b_client.action_routers(ctx, 'add_interface', b_router_id,
                                    {'subnet_id': subnet_map[t_subnet_id]})

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
                LOG.warning(_LW('Port %(port_id)s associated with floating ip '
                                '%(fip)s is not mapped to bottom pod'),
                            {'port_id': t_int_port_id, 'fip': add_fip})
                continue
            t_int_port = t_client.get_ports(ctx, t_int_port_id)
            if t_int_port['network_id'] != t_net['id']:
                # only handle floating ip association for the given top network
                continue

            if b_ext_pod['pod_id'] != b_pod['pod_id']:
                # if the internal port is not located in the external network
                # pod, we need to create a copied port in that pod for floating
                # ip association purpose
                t_int_net_id = t_int_port['network_id']
                t_int_subnet_id = t_int_port['fixed_ips'][0]['subnet_id']
                port_body = {
                    'port': {
                        'tenant_id': project_id,
                        'admin_state_up': True,
                        'name': constants.shadow_port_name % t_int_port['id'],
                        'network_id': t_int_net_id,
                        'fixed_ips': [{'ip_address': t_int_port[
                            'fixed_ips'][0]['ip_address']}]
                    }
                }
                self.helper.prepare_bottom_element(
                    ctx, project_id, b_ext_pod, t_int_port,
                    constants.RT_SD_PORT, port_body)
                # create routing entries for copied network and subnet so we
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
                # expire the routing entry for copy port
                with ctx.session.begin():
                    core.update_resources(
                        ctx, models.ResourceRouting,
                        [{'key': 'bottom_id', 'comparator': 'eq',
                          'value': fip['port_id']},
                         {'key': 'resource_type', 'comparator': 'eq',
                          'value': constants.RT_SD_PORT}],
                        {'bottom_id': None,
                         'created_at': constants.expire_time,
                         'updated_at': constants.expire_time})
                # delete copy port
                b_ext_client.delete_ports(ctx, fip['port_id'])
                # delete the expired entry, even if this deletion fails, we
                # still have a chance that lock_handle module will delete it
                with ctx.session.begin():
                    core.delete_resources(ctx, models.ResourceRouting,
                                          [{'key': 'top_id',
                                            'comparator': 'eq',
                                            'value': fip['port_id']},
                                           {'key': 'resource_type',
                                            'comparator': 'eq',
                                            'value': constants.RT_SD_PORT}])
                    # delete port before floating ip disassociation, copy
                    # network and copy subnet are deleted during central
                    # network and subnet deletion
            b_ext_client.delete_floatingips(ctx, fip['id'])
            # we first delete the internal port then delete the floating
            # ip. during the deletion of the internal port, the floating
            # ip will be disassociated automatically.

            # the reason we delete the internal port first is that if we
            # succeed to delete the internal port but fail to delete the
            # floating ip, in the next run, we can still find the floating
            # ip and try to delete it. but if we delete the floating ip
            # first, after we fail to delete the internal port, it's not
            # easy for us to find the internal port again because we cannot
            # find the internal port id the floating ip body

    @_job_handle(constants.JT_ROUTER_SETUP)
    def setup_bottom_router(self, ctx, payload):
        (b_pod_id,
         t_router_id, t_net_id) = payload[constants.JT_ROUTER_SETUP].split('#')

        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_net_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                # NOTE(zhiyuan) we create one job for each pod to avoid
                # conflict caused by different workers operating the same pod
                self.xjob_handler.setup_bottom_router(
                    ctx, t_net_id, t_router_id, b_pod['pod_id'])
            return

        t_client = self._get_client()
        t_pod = db_api.get_top_pod(ctx)
        t_router = t_client.get_routers(ctx, t_router_id)
        if not t_router:
            # we just end this job if top router no longer exists
            return
        t_net = t_client.get_networks(ctx, t_net_id)
        if not t_net:
            # we just end this job if top network no longer exists
            return
        project_id = t_router['tenant_id']

        b_pod = db_api.get_pod(ctx, b_pod_id)

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
        self._setup_router_one_pod(ctx, t_pod, b_pod, t_client, t_net,
                                   t_router, t_bridge_net,
                                   t_bridge_subnet, is_ext_net_pod)

        self.xjob_handler.configure_extra_routes(ctx, t_router_id)

    @_job_handle(constants.JT_ROUTER)
    def configure_extra_routes(self, ctx, payload):
        t_router_id = payload[constants.JT_ROUTER]
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
                             q_constants.DEVICE_OWNER_DHCP]
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
                b_subnet = bottom_client.get_subnets(
                    ctx, b_interface['fixed_ips'][0]['subnet_id'])
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
                    if cidr in router_ips_map[b_router_id]:
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
                for subnet in subnets:
                    ip_net = netaddr.IPNetwork(subnet['cidr'])
                    if ip_net in bridge_ip_net:
                        continue
                    # leave sg_id empty here
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
        is "top_network_id#bottom_pod_id"
        :return: None
        """
        (b_pod_id, t_network_id) = payload[
            constants.JT_NETWORK_UPDATE].split('#')
        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_network_id, constants.RT_NETWORK)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                self.xjob_handler.update_network(ctx, t_network_id,
                                                 b_pod['pod_id'])
            return

        t_client = self._get_client()
        t_network = t_client.get_networks(ctx, t_network_id)
        if not t_network:
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
            LOG.error(_LE('network: %(net_id)s not found,'
                          'pod name: %(name)s'),
                      {'net_id': b_network_id, 'name': b_region_name})

    @_job_handle(constants.JT_SUBNET_UPDATE)
    def update_subnet(self, ctx, payload):
        """update bottom subnet

        if bottom pod id equal to POD_NOT_SPECIFIED, dispatch jobs for every
        mapped bottom pod via RPC, otherwise update subnet in the specified
        pod.

        :param ctx: tricircle context
        :param payload: dict whose key is JT_SUBNET_UPDATE and value
        is "top_subnet_id#bottom_pod_id"
        :return: None
        """
        (b_pod_id, t_subnet_id) = payload[
            constants.JT_SUBNET_UPDATE].split('#')
        if b_pod_id == constants.POD_NOT_SPECIFIED:
            mappings = db_api.get_bottom_mappings_by_top_id(
                ctx, t_subnet_id, constants.RT_SUBNET)
            b_pods = [mapping[0] for mapping in mappings]
            for b_pod in b_pods:
                self.xjob_handler.update_subnet(ctx, t_subnet_id,
                                                b_pod['pod_id'])
            return

        t_client = self._get_client()
        t_subnet = t_client.get_subnets(ctx, t_subnet_id)
        if not t_subnet:
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
            LOG.error(_LE('subnet: %(subnet_id)s not found, '
                          'pod name: %(name)s'),
                      {'subnet_id': b_subnet_id, 'name': b_region_name})
