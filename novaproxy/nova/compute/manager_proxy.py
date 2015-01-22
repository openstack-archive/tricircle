# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Handles all processes relating to instances (guest vms).

The :py:class:`ComputeManager` class is a :py:class:`nova.manager.Manager` that
handles RPC calls relating to creating instances.  It is responsible for
building a disk image, launching it via the underlying virtualization driver,
responding to calls to check its state, attaching persistent storage, and
terminating it.

"""

import base64
import contextlib
import datetime
import functools
import os
import socket
import sys
import time
import traceback
import uuid

from cinderclient import exceptions as cinder_exception
import eventlet.event
from eventlet import greenthread
import eventlet.timeout
from oslo.config import cfg
from oslo import messaging
import six

import novaclient
from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.cloudpipe import pipelib
from nova import compute
from nova.compute import clients
from nova.compute import compute_context
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova import consoleauth
import nova.context
from nova import exception
from nova import hooks
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LI
from nova.i18n import _LW
from nova import image
from nova.image import cascading
from nova.image import glance
from nova import manager
from nova import network
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import aggregate as agg_obj
from nova.objects import base as obj_base
from nova.objects import flavor as flavor_obj
from nova.objects import quotas as quotas_obj
from nova.objects import block_device as block_device_obj
from nova.objects import compute_node as compute_node_obj
from nova.objects import service as service_obj
from nova.openstack.common import excutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import periodic_task
from nova.openstack.common import strutils
from nova.openstack.common import timeutils
from nova import paths
from nova import rpc
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import utils
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import virtapi
from nova import volume
#extra import
from neutronclient.v2_0 import client as clientv20
from neutronclient.common.exceptions import NeutronClientException
from novaclient.exceptions import ClientException


compute_opts = [
    cfg.StrOpt('console_host',
               default=socket.gethostname(),
               help='Console proxy host to use to connect '
                    'to instances on this host.'),
    cfg.StrOpt('default_access_ip_network_name',
               help='Name of network to use to set access IPs for instances'),
    cfg.BoolOpt('defer_iptables_apply',
                default=False,
                help='Whether to batch up the application of IPTables rules'
                     ' during a host restart and apply all at the end of the'
                     ' init phase'),
    cfg.StrOpt('instances_path',
               default=paths.state_path_def('instances'),
               help='Where instances are stored on disk'),
    cfg.BoolOpt('instance_usage_audit',
                default=False,
                help="Generate periodic compute.instance.exists"
                     " notifications"),
    cfg.IntOpt('live_migration_retry_count',
               default=30,
               help="Number of 1 second retries needed in live_migration"),
    cfg.BoolOpt('resume_guests_state_on_host_boot',
                default=False,
                help='Whether to start guests that were running before the '
                     'host rebooted'),
    cfg.IntOpt('network_allocate_retries',
               default=0,
               help="Number of times to retry network allocation on failures"),
    cfg.IntOpt('block_device_allocate_retries',
               default=60,
               help='Number of times to retry block device'
                    ' allocation on failures'),
    cfg.StrOpt('keystone_auth_url',
               default='http://127.0.0.1:5000/v2.0/',
               help='value of keystone url'),
    cfg.StrOpt('nova_admin_username',
               default='nova',
               help='username for connecting to nova in admin context'),
    cfg.StrOpt('nova_admin_password',
               default='nova',
               help='password for connecting to nova in admin context',
               secret=True),
    cfg.StrOpt('nova_admin_tenant_name',
               default='admin',
               help='tenant name for connecting to nova in admin context'),
    cfg.StrOpt('proxy_region_name',
               deprecated_name='proxy_region_name',
               help='region name for connecting to neutron in admin context'),
    cfg.IntOpt('novncproxy_port',
               default=6080,
               help='Port on which to listen for incoming requests'),
    cfg.StrOpt('cascading_nova_url',
               default='http://127.0.0.1:8774/v2',
               help='value of cascading url'),
    cfg.StrOpt('cascaded_nova_url',
               default='http://127.0.0.1:8774/v2',
               help='value of cascaded url'),
    cfg.StrOpt('cascaded_neutron_url',
               default='http://127.0.0.1:9696',
               help='value of cascaded neutron url'),
    cfg.BoolOpt('cascaded_glance_flag',
                default=False,
                help='Whether to use glance cescaded'),
    cfg.StrOpt('cascaded_glance_url',
               default='http://127.0.0.1:9292',
               help='value of cascaded glance url'),
    cfg.StrOpt('os_region_name',
               default='RegionOne',
               help='value of cascaded glance url')
]

interval_opts = [
    cfg.IntOpt('bandwidth_poll_interval',
               default=600,
               help='Interval to pull network bandwidth usage info. Not '
                    'supported on all hypervisors. Set to -1 to disable. '
                    'Setting this to 0 will disable, but this will change in '
                    'the K release to mean "run at the default rate".'),
    # TODO(gilliard): Clean the above message after the K release
    cfg.IntOpt('sync_power_state_interval',
               default=600,
               help='Interval to sync power states between the database and '
                    'the hypervisor. Set to -1 to disable. '
                    'Setting this to 0 will disable, but this will change in '
                    'Juno to mean "run at the default rate".'),
    # TODO(gilliard): Clean the above message after the K release
    cfg.IntOpt("heal_instance_info_cache_interval",
               default=60,
               help="Number of seconds between instance info_cache self "
                    "healing updates"),
    cfg.IntOpt('reclaim_instance_interval',
               default=0,
               help='Interval in seconds for reclaiming deleted instances'),
    cfg.IntOpt('volume_usage_poll_interval',
               default=0,
               help='Interval in seconds for gathering volume usages'),
    cfg.IntOpt('shelved_poll_interval',
               default=3600,
               help='Interval in seconds for polling shelved instances to '
                    'offload. Set to -1 to disable.'
                    'Setting this to 0 will disable, but this will change in '
                    'Juno to mean "run at the default rate".'),
    # TODO(gilliard): Clean the above message after the K release
    cfg.IntOpt('shelved_offload_time',
               default=0,
               help='Time in seconds before a shelved instance is eligible '
                    'for removing from a host.  -1 never offload, 0 offload '
                    'when shelved'),
    cfg.IntOpt('instance_delete_interval',
               default=300,
               help=('Interval in seconds for retrying failed instance file '
                     'deletes')),
    cfg.IntOpt('block_device_allocate_retries_interval',
               default=3,
               help='Waiting time interval (seconds) between block'
                    ' device allocation retries on failures'),
    cfg.IntOpt('sync_instance_state_interval',
               default=5,
               help='interval to sync instance states between '
                    'the nova and the nova-proxy'),
    cfg.IntOpt('sync_aggregate_info_interval',
               default=1800,
               help='interval to sync aggregate info between '
                    'the nova and the nova-proxy'),
    cfg.BoolOpt('resource_tracker_synced',
                default=False,
                help='Whether to use sync cescaded resources'),

]

timeout_opts = [
    cfg.IntOpt("reboot_timeout",
               default=0,
               help="Automatically hard reboot an instance if it has been "
                    "stuck in a rebooting state longer than N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("instance_build_timeout",
               default=0,
               help="Amount of time in seconds an instance can be in BUILD "
                    "before going into ERROR status."
                    "Set to 0 to disable."),
    cfg.IntOpt("rescue_timeout",
               default=0,
               help="Automatically unrescue an instance after N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("resize_confirm_window",
               default=0,
               help="Automatically confirm resizes after N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("shutdown_timeout",
               default=60,
               help="Total amount of time to wait in seconds for an instance "
                    "to perform a clean shutdown."),
    ]

running_deleted_opts = [
    cfg.StrOpt("running_deleted_instance_action",
               default="reap",
               help="Action to take if a running deleted instance is detected."
                    "Valid options are 'noop', 'log', 'shutdown', or 'reap'. "
                    "Set to 'noop' to take no action."),
    cfg.IntOpt("running_deleted_instance_poll_interval",
               default=1800,
               help="Number of seconds to wait between runs of the cleanup "
                    "task."),
    cfg.IntOpt("running_deleted_instance_timeout",
               default=0,
               help="Number of seconds after being deleted when a running "
                    "instance should be considered eligible for cleanup."),
    ]

instance_cleaning_opts = [
    cfg.IntOpt('maximum_instance_delete_attempts',
               default=5,
               help=('The number of times to attempt to reap an instance\'s '
                     'files.')),
    ]

CONF = cfg.CONF
CONF.register_opts(compute_opts)
CONF.register_opts(interval_opts)
CONF.register_opts(timeout_opts)
CONF.register_opts(running_deleted_opts)
CONF.register_opts(instance_cleaning_opts)
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('console_topic', 'nova.console.rpcapi')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('enabled', 'nova.spice', group='spice')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('image_cache_manager_interval', 'nova.virt.imagecache')
CONF.import_opt('enabled', 'nova.rdp', group='rdp')
CONF.import_opt('html5_proxy_base_url', 'nova.rdp', group='rdp')
CONF.import_opt('enabled', 'nova.console.serial', group='serial_console')
CONF.import_opt('base_url', 'nova.console.serial', group='serial_console')
CONF.import_opt('host', 'nova.netconf')

EXCLUDE_TASK_STATES = (task_states.BLOCK_DEVICE_MAPPING,
                       task_states.NETWORKING,
                       task_states.SPAWNING,
                       task_states.SCHEDULING,
                       task_states.POWERING_OFF,
                       task_states.RESIZE_PREP,
                       task_states.RESIZE_MIGRATING,
                       task_states.RESIZE_MIGRATED,
                       task_states.RESIZE_FINISH)


LOG = logging.getLogger(__name__)

get_notifier = functools.partial(rpc.get_notifier, service='compute')
wrap_exception = functools.partial(exception.wrap_exception,
                                   get_notifier=get_notifier)


@utils.expects_func_args('migration')
def errors_out_migration(function):
    """Decorator to error out migration on failure."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                migration = kwargs['migration']
                status = migration.status
                if status not in ['migrating', 'post-migrating']:
                    return
                migration.status = 'error'
                try:
                    migration.save(context.elevated())
                except Exception:
                    LOG.debug('Error setting migration status '
                              'for instance %s.',
                              migration.instance_uuid, exc_info=True)

    return decorated_function


@utils.expects_func_args('instance')
def reverts_task_state(function):
    """Decorator to revert task_state on failure."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except exception.UnexpectedTaskStateError as e:
            # Note(maoy): unexpected task state means the current
            # task is preempted. Do not clear task state in this
            # case.
            with excutils.save_and_reraise_exception():
                LOG.info(_("Task possibly preempted: %s") % e.format_message())
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._instance_update(context,
                                          kwargs['instance']['uuid'],
                                          task_state=None)
                except Exception:
                    pass

    return decorated_function


@utils.expects_func_args('instance')
def wrap_instance_fault(function):
    """Wraps a method to catch exceptions related to instances.

    This decorator wraps a method to catch any exceptions having to do with
    an instance that may get thrown. It then logs an instance fault in the db.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except exception.InstanceNotFound:
            raise
        except Exception as e:
            # NOTE(gtt): If argument 'instance' is in args rather than kwargs,
            # we will get a KeyError exception which will cover up the real
            # exception. So, we update kwargs with the values from args first.
            # then, we can get 'instance' from kwargs easily.
            kwargs.update(dict(zip(function.func_code.co_varnames[2:], args)))

            with excutils.save_and_reraise_exception():
                compute_utils.add_instance_fault_from_exc(context,
                                                          kwargs['instance'], e, sys.exc_info())

    return decorated_function


@utils.expects_func_args('instance')
def wrap_instance_event(function):
    """Wraps a method to log the event taken on the instance, and result.

    This decorator wraps a method to log the start and result of an event, as
    part of an action taken on an instance.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        # wrapped_func = utils.get_wrapped_function(function)
        # keyed_args = safe_utils.getcallargs(wrapped_func, context, *args,
        #                                     **kwargs)
        # instance_uuid = keyed_args['instance']['uuid']
        #
        # event_name = 'compute_{0}'.format(function.func_name)
        # with compute_utils.EventReporter(context, event_name, instance_uuid):
        return function(self, context, *args, **kwargs)

    return decorated_function


def get_nova_sync_client():
    kwargs = {
        'username': CONF.nova_admin_username,
        'password': CONF.nova_admin_password,
        'tenant': CONF.nova_admin_tenant_name,
        'auth_url': CONF.keystone_auth_url,
        'region_name': CONF.proxy_region_name
    }
    req_context = compute_context.RequestContext(**kwargs)
    openstack_clients = clients.OpenStackClients(req_context)
    return openstack_clients.nova()


def get_nova_csg_client():
    kwargs = {
        'username': CONF.nova_admin_username,
        'password': CONF.nova_admin_password,
        'tenant': CONF.nova_admin_tenant_name,
        'auth_url': CONF.keystone_auth_url,
        'region_name': CONF.os_region_name,
    }
    req_context = compute_context.RequestContext(**kwargs)
    openstack_clients = clients.OpenStackClients(req_context)
    return openstack_clients.nova()


@utils.expects_func_args('image_id', 'instance')
def delete_image_on_error(function):
    """Used for snapshot related method to ensure the image created in
    compute.api is deleted when an error occurs.
    """

    @functools.wraps(function)
    def decorated_function(self, context, image_id, instance,
                           *args, **kwargs):
        try:
            return function(self, context, image_id, instance,
                            *args, **kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug("Cleaning up image %s", image_id,
                          exc_info=True, instance=instance)
                try:
                    self.image_api.delete(context, image_id)
                except Exception:
                    LOG.exception(_LE("Error while trying to clean up "
                                      "image %s"), image_id,
                                  instance=instance)

    return decorated_function


# TODO(danms): Remove me after Icehouse
# NOTE(mikal): if the method being decorated has more than one decorator, then
# put this one first. Otherwise the various exception handling decorators do
# not function correctly.
def object_compat(function):
    """Wraps a method that expects a new-world instance

    This provides compatibility for callers passing old-style dict
    instances.

    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        def _load_instance(instance_or_dict):
            if isinstance(instance_or_dict, dict):
                instance = objects.Instance._from_db_object(
                    context, objects.Instance(), instance_or_dict,
                    expected_attrs=metas)
                instance._context = context
                return instance
            return instance_or_dict

        metas = ['metadata', 'system_metadata']
        try:
            kwargs['instance'] = _load_instance(kwargs['instance'])
        except KeyError:
            args = (_load_instance(args[0]),) + args[1:]

        migration = kwargs.get('migration')
        if isinstance(migration, dict):
            migration = objects.Migration._from_db_object(
                context.elevated(), objects.Migration(),
                migration)
            kwargs['migration'] = migration

        return function(self, context, *args, **kwargs)

    return decorated_function


# TODO(danms): Remove me after Icehouse
def aggregate_object_compat(function):
    """Wraps a method that expects a new-world aggregate."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        aggregate = kwargs.get('aggregate')
        if isinstance(aggregate, dict):
            aggregate = objects.Aggregate._from_db_object(
                context.elevated(), objects.Aggregate(),
                aggregate)
            kwargs['aggregate'] = aggregate
        return function(self, context, *args, **kwargs)
    return decorated_function


def _cmp_as_same(dict1, dict2, compare_keys):
    if type(dict1) is dict and type(dict2) is dict:
        if not compare_keys:
            return False
        for key in compare_keys:
            if dict1[key] != dict2[key]:
                return False
        return True
    return False


class InstanceEvents(object):
    def __init__(self):
        self._events = {}

    @staticmethod
    def _lock_name(instance):
        return '%s-%s' % (instance.uuid, 'events')

    def prepare_for_instance_event(self, instance, event_name):
        """Prepare to receive an event for an instance.

        This will register an event for the given instance that we will
        wait on later. This should be called before initiating whatever
        action will trigger the event. The resulting eventlet.event.Event
        object should be wait()'d on to ensure completion.

        :param instance: the instance for which the event will be generated
        :param event_name: the name of the event we're expecting
        :returns: an event object that should be wait()'d on
        """
        @utils.synchronized(self._lock_name(instance))
        def _create_or_get_event():
            if instance.uuid not in self._events:
                self._events.setdefault(instance.uuid, {})
            return self._events[instance.uuid].setdefault(
                event_name, eventlet.event.Event())
        LOG.debug('Preparing to wait for external event %(event)s',
                  {'event': event_name}, instance=instance)
        return _create_or_get_event()

    def pop_instance_event(self, instance, event):
        """Remove a pending event from the wait list.

        This will remove a pending event from the wait list so that it
        can be used to signal the waiters to wake up.

        :param instance: the instance for which the event was generated
        :param event: the nova.objects.external_event.InstanceExternalEvent
                      that describes the event
        :returns: the eventlet.event.Event object on which the waiters
                  are blocked
        """
        no_events_sentinel = object()
        no_matching_event_sentinel = object()

        @utils.synchronized(self._lock_name(instance))
        def _pop_event():
            events = self._events.get(instance.uuid)
            if not events:
                return no_events_sentinel
            _event = events.pop(event.key, None)
            if not events:
                del self._events[instance.uuid]
            if _event is None:
                return no_matching_event_sentinel
            return _event

        result = _pop_event()
        if result == no_events_sentinel:
            LOG.debug('No waiting events found dispatching %(event)s',
                      {'event': event.key},
                      instance=instance)
            return None
        elif result == no_matching_event_sentinel:
            LOG.debug('No event matching %(event)s in %(events)s',
                      {'event': event.key,
                       'events': self._events.get(instance.uuid, {}).keys()},
                      instance=instance)
            return None
        else:
            return result

    def clear_events_for_instance(self, instance):
        """Remove all pending events for an instance.

        This will remove all events currently pending for an instance
        and return them (indexed by event name).

        :param instance: the instance for which events should be purged
        :returns: a dictionary of {event_name: eventlet.event.Event}
        """
        @utils.synchronized(self._lock_name(instance))
        def _clear_events():
            # NOTE(danms): Use getitem syntax for the instance until
            # all the callers are using objects
            return self._events.pop(instance['uuid'], {})
        return _clear_events()


class ComputeVirtAPI(virtapi.VirtAPI):
    def __init__(self, compute):
        super(ComputeVirtAPI, self).__init__()
        self._compute = compute

    def provider_fw_rule_get_all(self, context):
        return self._compute.conductor_api.provider_fw_rule_get_all(context)

    def _default_error_callback(self, event_name, instance):
        raise exception.NovaException(_('Instance event failed'))

    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        """Plan to wait for some events, run some code, then wait.

        This context manager will first create plans to wait for the
        provided event_names, yield, and then wait for all the scheduled
        events to complete.

        Note that this uses an eventlet.timeout.Timeout to bound the
        operation, so callers should be prepared to catch that
        failure and handle that situation appropriately.

        If the event is not received by the specified timeout deadline,
        eventlet.timeout.Timeout is raised.

        If the event is received but did not have a 'completed'
        status, a NovaException is raised.  If an error_callback is
        provided, instead of raising an exception as detailed above
        for the failure case, the callback will be called with the
        event_name and instance, and can return True to continue
        waiting for the rest of the events, False to stop processing,
        or raise an exception which will bubble up to the waiter.

        :param instance: The instance for which an event is expected
        :param event_names: A list of event names. Each element can be a
                            string event name or tuple of strings to
                            indicate (name, tag).
        :param deadline: Maximum number of seconds we should wait for all
                         of the specified events to arrive.
        :param error_callback: A function to be called if an event arrives

        """

        if error_callback is None:
            error_callback = self._default_error_callback
        events = {}
        for event_name in event_names:
            if isinstance(event_name, tuple):
                name, tag = event_name
                event_name = objects.InstanceExternalEvent.make_key(
                    name, tag)
            events[event_name] = (
                self._compute.instance_events.prepare_for_instance_event(
                    instance, event_name))
        yield
        with eventlet.timeout.Timeout(deadline):
            for event_name, event in events.items():
                actual_event = event.wait()
                if actual_event.status == 'completed':
                    continue
                decision = error_callback(event_name, instance)
                if decision is False:
                    break


class ComputeManager(manager.Manager):
    """Manages the running instances from creation to destruction."""

    target = messaging.Target(version='3.35')

    # How long to wait in seconds before re-issuing a shutdown
    # signal to a instance during power off.  The overall
    # time to wait is set by CONF.shutdown_timeout.
    SHUTDOWN_RETRY_INTERVAL = 10
    QUERY_PER_PAGE_LIMIT = 50
    INSTANCE_UUID_LENGTH = 36
    NEUTRON_UUID_LENGTH = 36
    NAME_FIELD_MAX_LENGTH = 255
    NAME_SPLIT_MARK_LENGTH = 1
    CSG_INSTANCE_NAME_MAX_LEN = (NAME_FIELD_MAX_LENGTH - INSTANCE_UUID_LENGTH
                                 - NAME_SPLIT_MARK_LENGTH)
    CSG_NET_NAME_MAX_LEN = (NAME_FIELD_MAX_LENGTH - NEUTRON_UUID_LENGTH
                            - NAME_SPLIT_MARK_LENGTH)

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        self.virtapi = ComputeVirtAPI(self)
        self.network_api = network.API()
        self.volume_api = volume.API()
        self.image_api = image.API()
        self._last_host_check = 0
        self._last_bw_usage_poll = 0
        self._bw_usage_supported = True
        self._last_bw_usage_cell_update = 0
        self.compute_api = compute.API()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.conductor_api = conductor.API()
        self.compute_task_api = conductor.ComputeTaskAPI()
        self.is_neutron_security_groups = (
            openstack_driver.is_neutron_security_groups())
        self.consoleauth_rpcapi = consoleauth.rpcapi.ConsoleAuthAPI()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self._resource_tracker_dict = {}
        self.instance_events = InstanceEvents()
        self._sync_power_pool = eventlet.GreenPool()
        self._syncs_in_progress = {}
        self.sync_nova_client = get_nova_sync_client()
        self.csg_nova_client = get_nova_csg_client()

        super(ComputeManager, self).__init__(service_name="compute",
                                             *args, **kwargs)

        # NOTE(russellb) Load the driver last.  It may call back into the
        # compute manager via the virtapi, so we want it to be fully
        # initialized before that happens.
        self.driver = driver.load_compute_driver(self.virtapi, compute_driver)
        self.use_legacy_block_device_info = \
            self.driver.need_legacy_block_device_info
        #cascading patch
        self._last_info_instance_state_heal = 0
        self._change_since_time = None
        self._init_caches()

    def _init_caches(self):
        self._flavor_sync_map = {}
        self._keypair_sync_map = {}
        self._uuid_mapping = {}
        self._network_mapping = {}
        sync_nova_client = self.sync_nova_client
        if sync_nova_client is None:
            return
        csd_flavors = sync_nova_client.flavors.list()

        """ for flavors """
        for flavor in csd_flavors:
            flavor_accesses = []
            try:
                if not flavor.is_public:
                    flavor_accesses = (sync_nova_client.flavor_access.list(
                        flavor=flavor.id))
            except Exception:
                pass
            """ 'extra_specs' is a dict, and 'projects' is a list """
            self._flavor_sync_map[flavor.name] = {
                'flavorid': flavor.id,
                'name': flavor.name,
                'memory_mb': flavor.ram,
                'vcpus': flavor.vcpus,
                'swap': flavor.swap or 0,
                'is_public': flavor.is_public,
                'rxtx_factor': flavor.rxtx_factor,
                'ephemeral_gb': flavor.ephemeral or 0,
                'root_gb': flavor.disk,
                'extra_specs': flavor.get_keys(),
                'projects': [f_a.tenant_id for f_a in flavor_accesses]
            }
        """ for keypairs """
        # sync keypair when operating instance to check if it's necessary.
        csd_keypairs = sync_nova_client.keypairs.list()
        for keypair in csd_keypairs:
            self._keypair_sync_map[keypair.name] = {
                'id': keypair.id,
                'key_name': keypair.name,
                'key_data': keypair.public_key,
                #'fingerprint': keypair.fingerprint
            }
        """ for instances """
        search_opts_args = {
            'all_tenants': True
        }
        marker = None
        while True:
            servers = sync_nova_client.servers.list(search_opts=search_opts_args,
                                           limit=self.QUERY_PER_PAGE_LIMIT,
                                           marker=marker)
            if servers:
                marker = servers[-1].id
            else:
                break
            for server in servers:
                csg_instance_uuid = ComputeManager._extract_csg_uuid(server)
                self._uuid_mapping[csg_instance_uuid] = \
                    {'mapping_id': server.id,
                     'metadata': server.metadata,
                    }
        """handle neutron mapping
        """
        self._load_cascaded_net_info()
        LOG.debug(_('DEBUG: the neutron_mapping is %s'), self._network_mapping)

    def _load_cascaded_net_info(self):
        """
        Only called when the compute service restarted.Gathering the cascaded
        network's information(include network, subnet)."""
        try:
            csd_neutron_client = self.get_neutron_client(CONF.proxy_region_name)
            search_opts = {'status': 'ACTIVE'}
            csd_networks = csd_neutron_client.list_networks(**search_opts)
            csd_subnets = csd_neutron_client.list_subnets(**search_opts)
            for csd_net in csd_networks['networks']:
                csg_net_id = ComputeManager._extract_nets_csg_uuid(csd_net['name'])
                if not csg_net_id:
                    #todo(jd) Add exception log.
                    continue
                # csg_net_name = ComputeManager._extract_nets_csg_name(csd_net['name'])
                self._network_mapping[csg_net_id] = {'mapping_id': csd_net['id'],
                                                     'name': '',
                                                     'subnets': []}
            for subnet in csd_subnets['subnets']:
                network_id = subnet['network_id']
                csg_sub_id = ComputeManager._extract_nets_csg_uuid(subnet['name'])
                csg_net_ids = [nm[0] for nm in self._network_mapping.items()
                               if nm[1]['mapping_id'] == network_id]
                if not csg_net_ids:
                #not self._network_mapping.get(network_id, None):
                    #todo(jd) Add exception log.
                    continue
                self._network_mapping[csg_net_ids[0]]['subnets'].append({
                    'csg_id': csg_sub_id,
                    'name': subnet['name'],
                    'id': subnet['id'],
                    'allocation_pools': subnet['allocation_pools'],
                    'gateway_ip': subnet['gateway_ip'],
                    'ip_version': subnet['ip_version'],
                    'cidr': subnet['cidr'],
                    'tenant_id': subnet['tenant_id'],
                    'network_id': subnet['network_id'],
                    'enable_dhcp': subnet['enable_dhcp'],
                    }
                )
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Fail to synchronize the network info when start.'))

    @staticmethod
    def _extract_csg_uuid(server):
        csd_name = server.name
        uuid_len = ComputeManager.INSTANCE_UUID_LENGTH
        if len(csd_name) > (uuid_len+1) and csd_name[-(uuid_len+1)] == '@':
            return csd_name[-uuid_len:]
        try:
            return server.metadata['mapping_uuid']
        except KeyError:
            return ''

    @staticmethod
    def _gen_csd_instance_name(name, instance):
        max_len = ComputeManager.CSG_INSTANCE_NAME_MAX_LEN
        save_name = name[:(max_len-len(name))] if max_len < len(name) else name
        return save_name + '@' + instance['uuid']

    @staticmethod
    def _extract_nets_csg_uuid(neutron_obj_name):
        # uuid_len = ComputeManager.NEUTRON_UUID_LENGTH
        # if (len(neutron_obj_name) > (uuid_len+1)
        #         and neutron_obj_name[-(uuid_len+1)] == '_'):
        #     return neutron_obj_name[-uuid_len:]
        # return ''
        return neutron_obj_name

    @staticmethod
    def _extract_nets_csg_name(neutron_obj_name):
        uuid_len = ComputeManager.NEUTRON_UUID_LENGTH
        if (len(neutron_obj_name) > (uuid_len+1)
                and neutron_obj_name[-(uuid_len+1)] == '_'):
            return neutron_obj_name[:(len(neutron_obj_name)-uuid_len-1)]
        return ''

    @staticmethod
    def _gen_csd_nets_name(csg_name, csg_uuid):
        # max_len = ComputeManager.CSG_NET_NAME_MAX_LEN
        # save_name = (csg_name[:(max_len-len(csg_name))]
        #              if max_len < len(csg_name) else csg_name)
        # return save_name + '_' + csg_uuid
        return csg_uuid

    def _get_resource_tracker(self, nodename):
        rt = self._resource_tracker_dict.get(nodename)
        if not rt:
            rt = resource_tracker.ResourceTracker(self.host,
                                                  self.driver,
                                                  nodename)
            self._resource_tracker_dict[nodename] = rt
        return rt

    def _get_csd_instance_uuid(self, instance):
        proxy_instance_id = (self._uuid_mapping.get(instance['uuid'], {})
                             .get('mapping_id', None))
        if not proxy_instance_id:
            #In this case, we search cascaded with cascading instance's
            #display_name and uuid by name rule.
            want_csd_name = self._gen_csd_instance_name(instance['display_name'],
                                                        instance)
            sync_nova_client = self.sync_nova_client
            search_opts = {'all_tenants': True,
                           'display_name': want_csd_name,
                            }
            try:
                vms = sync_nova_client.servers.list(search_opts=search_opts)

                if vms:
                    proxy_instance_id = vms[0].id
                    self._uuid_mapping[instance['uuid']] = \
                        {'mapping_id': vms[0].id,
                         'metadata': vms[0].metadata,
                         }
            except Exception:
                pass

        return proxy_instance_id

    def _update_resource_tracker(self, context, instance):
        """Let the resource tracker know that an instance has changed state."""
        pass
        # if (instance['host'] == self.host and
        #         self.driver.node_is_available(instance['node'])):
            # rt = self._get_resource_tracker(instance.get('node'))
            # rt.update_usage(context, instance)

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""

        instance_ref = self.conductor_api.instance_update(context,
                                                          instance_uuid,
                                                          **kwargs)
        self._update_resource_tracker(context, instance_ref)
        return instance_ref

    def _delete_proxy_instance(self, context, instance):
        proxy_instance_id = self._get_csd_instance_uuid(instance)

        if proxy_instance_id is None:
            LOG.error(_('Delete server %s,but can not find this server'),
                      proxy_instance_id)
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        try:
            cascaded_nova_cli.servers.delete(proxy_instance_id)
            self._instance_update(
                context,
                instance['uuid'],
                vm_state=vm_states.DELETED,
                task_state=None)
            LOG.debug(_('delete the server %s from nova-proxy'),
                      instance['uuid'])
        except Exception:
            if isinstance(sys.exc_info()[1], novaclient.exceptions.NotFound):
                return
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to delete server %s'), proxy_instance_id)

    @staticmethod
    def _get_cascaded_image_uuid(context, image_uuid):
        try:
            glance_client = glance.GlanceClientWrapper()
            cascading_image = glance_client.call(context, 2, 'get', image_uuid)
            for location in cascading_image['locations']:
                if location['url'] and location['url'].startswith(
                        cfg.CONF.cascaded_glance_url):
                    cascaded_image_uuid = location['url'].split('/')[-1]
                    return cascaded_image_uuid
            # can not find the cascaded-image-id in locations
            sync_service = cascading.GlanceCascadingService()
            return sync_service.sync_image(context,
                                           cfg.CONF.cascaded_glance_url,
                                           cascading_image)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error while trying to get cascaded"
                            " image and cascading uuid %s")
                          % image_uuid)

    @staticmethod
    def get_neutron_client(region_name):
        kwargs = {
            'username': CONF.neutron.admin_username,
            'password': CONF.neutron.admin_password,
            'tenant': CONF.neutron.admin_tenant_name,
            'auth_url': CONF.neutron.admin_auth_url,
            'region_name': region_name
        }
        req_context = compute_context.RequestContext(**kwargs)
        ks_clients = clients.OpenStackClients(req_context)
        return ks_clients.neutron()

    @staticmethod
    def _get_neutron_python_client(context, regNam, neutrol_url):
        try:
            kwargs = {
                'endpoint_url': neutrol_url,
                'timeout': CONF.neutron.url_timeout,
                'insecure': CONF.neutron.api_insecure,
                'ca_cert': CONF.neutron.ca_certificates_file,
                'username': CONF.neutron.admin_username,
                'password': CONF.neutron.admin_password,
                'tenant_name': CONF.neutron.admin_tenant_name,
                'auth_url': CONF.neutron.admin_auth_url,
                'auth_strategy': CONF.neutron.auth_strategy
            }
            return clientv20.Client(**kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get neutron python client.'))

    def _get_csg_python_client(self, context):
        return self._get_nova_python_client(context,
                                            reg_name=CONF.os_region_name,
                                            nova_url=CONF.cascading_nova_url)

    def _get_nova_python_client(self, context, reg_name=None, nova_url=None):
        try:
            kwargs = {
                'auth_token': context.auth_token,
                'username': context.user_name,
                'tenant_id': context.tenant,
                'auth_url': cfg.CONF.keystone_auth_url,
                'roles': context.roles,
                'is_admin': context.is_admin,
                'region_name': reg_name or CONF.proxy_region_name,
                'nova_url': nova_url or CONF.cascaded_nova_url,
            }
            req_context = compute_context.RequestContext(**kwargs)
            openstack_clients = clients.OpenStackClients(req_context)
            return openstack_clients.nova()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get nova python client.'))

    def _heal_instance_metadata(self, instance_uuid, metadata):
        csd_mapping = self._uuid_mapping.get(instance_uuid, {})
        if not csd_mapping or metadata == csd_mapping['metadata']:
            return
        csd_uuid = csd_mapping['mapping_id']
        self.sync_nova_client.servers.set_meta(csd_uuid, metadata)
        csd_mapping['metadata'] = metadata

    def _sync_instance_flavor(self, context, instance):
        try:
            flavor_name = instance['system_metadata']['instance_type_name']
            # Get the active flavor by flavor_name in the instance.
            active_flavor = flavor_obj.Flavor.get_by_name(context,
                                                          flavor_name)
            active_flavor._load_projects(context)
            if not active_flavor:
                LOG.info(_('the flavor %s not exists, may be deleted.'),
                         flavor_name)
                #(todo) Should delete the cascaed flavor accordingly and
                #remove it from the cache?
                return
            instance_type = {
                'flavorid': active_flavor.flavorid,
                'name': active_flavor.name,
                'memory_mb': active_flavor.memory_mb,
                'vcpus': active_flavor.vcpus,
                'swap': active_flavor.swap,
                'rxtx_factor': active_flavor.rxtx_factor,
                'ephemeral_gb': active_flavor.ephemeral_gb,
                'root_gb': active_flavor.root_gb,
                'extra_specs': active_flavor.extra_specs,
                'projects': active_flavor.projects,
                'is_public': active_flavor.is_public,
            }
            self._heal_syn_flavor_info(context, instance_type)
        except KeyError:
            LOG.error(_('Can not find flavor info in instance %s when reboot.'),
                      instance['uuid'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Fail to get/sync flavor %s when reboot.'),
                          flavor_name)

    def _heal_syn_flavor_info(self, context, instance_type):
        _cmp_keys = ('flavorid', 'name', 'memory_mb', 'vcpus', 'swap',
                     'is_public', 'ephemeral_gb', 'root_gb', 'rxtx_factor')

        flavor_name = instance_type['name']
        csd_flavor = self._flavor_sync_map.get(flavor_name, {})

        _no_exist_flag = not csd_flavor
        _update_flag = not _no_exist_flag and not _cmp_as_same(csd_flavor,
                                                       instance_type,
                                                       _cmp_keys)
        _extra_specs_change_flag = (csd_flavor and
                                    csd_flavor.get('extra_specs', {}) !=
                                    instance_type['extra_specs'])

        _projects_changed_flag = (csd_flavor and
                                  set(csd_flavor.get('projects', [])) !=
                                  instance_type['projects'])

        if _no_exist_flag:
            LOG.info(_('flavor not exists in cascaded, need sync: %s'),
                     flavor_name)

        if _update_flag:
            LOG.info(_('flavor not full same to cascaded, need sync: %s'),
                     flavor_name)

        if _extra_specs_change_flag:
            """check the extra_specs changed or not.
            """
            LOG.info(_('flavor extra_specs not full same to cascaded,'
                       'need sync: %s'),
                     flavor_name)

        if not (_no_exist_flag or _update_flag or _extra_specs_change_flag or
                _projects_changed_flag):
            return

        cascaded_nova_cli = self.sync_nova_client

        if _update_flag:
            # update = delete + create new.
            LOG.info(_('delete the cascaded flavor %s by id: %s'),
                     csd_flavor['name'], csd_flavor['flavorid'])
            cascaded_nova_cli.flavors.delete(csd_flavor['flavorid'])

        if _update_flag or _no_exist_flag:
            my_flavor = cascaded_nova_cli.flavors.create(
                name=instance_type['name'],
                ram=instance_type['memory_mb'],
                vcpus=instance_type['vcpus'],
                disk=instance_type['root_gb'],
                is_public=instance_type['is_public'],
                flavorid=instance_type['flavorid'],
                ephemeral=instance_type['ephemeral_gb'],
                swap=instance_type['swap'],
                rxtx_factor=instance_type['rxtx_factor']
            )

            if instance_type['extra_specs']:
                my_flavor.set_keys(instance_type['extra_specs'])

            for project in instance_type['projects']:
                try:
                    cascaded_nova_cli.flavor_access.add_tenant_access(my_flavor, project)
                except Exception:
                    LOG.exception(_('Modified flavor information, '
                                    'but unable to modify flavor access.'))

        else:
            my_flavor = cascaded_nova_cli.flavors.get(instance_type['flavorid'])
            if _extra_specs_change_flag:
                my_flavor.unset_keys(csd_flavor.get('extra_specs', {}))
                my_flavor.set_keys(instance_type['extra_specs'])

            if _projects_changed_flag:
                for project in csd_flavor['projects']:
                    if project in instance_type['projects']:
                        continue
                    try:
                        cascaded_nova_cli.flavor_access.remove_tenant_access(my_flavor, project)
                    except Exception:
                        LOG.exception(_('Unable to delete flavor access'))
                for project in instance_type['projects']:
                    if project in csd_flavor['projects']:
                        continue
                    try:
                        cascaded_nova_cli.flavor_access.add_tenant_access(my_flavor, project)
                    except Exception:
                        LOG.exception(_('Unable to add flavor access'))

        # refresh the cache.
        self._flavor_sync_map[flavor_name] = instance_type.copy()
        LOG.debug(_('create/update flavor %s done.'), flavor_name)

    def _heal_syn_keypair_info(self, context, instance):
        kp_name = instance['key_name']
        kp_data = instance['key_data']

        csd_keypair = self._keypair_sync_map.get(kp_name, None)
        _update_keypair_flag = False
        if csd_keypair is None:
            LOG.info(_('Keypair not exists in cascaded, need sync: %s'),
                     kp_name)
        elif kp_data != csd_keypair['key_data']:
            LOG.info(_('Keypair changed and is different from cascaded,'
                       'need sync: %s'), kp_name)
            _update_keypair_flag = True
        else:
            return
        cascaded_nova_cli = self.sync_nova_client

        if _update_keypair_flag:
            LOG.info(_('delete the cascaded keypair %s by id: %s'),
                     csd_keypair['name'], csd_keypair['id'])
            cascaded_nova_cli.keypairs.delete(csd_keypair['id'])

        key_pair = cascaded_nova_cli.keypairs.create(name=kp_name,
                                                     public_key=kp_data)
        #refresh the keypair cache
        self._keypair_sync_map[kp_name] = {
            'id': key_pair.id,
            'key_name': key_pair.name,
            'key_data': key_pair.public_key
        }
        LOG.debug(_('create/update keypair %s done.'), kp_name)

    @periodic_task.periodic_task(spacing=CONF.sync_instance_state_interval,
                                 run_immediately=True)
    def _heal_instance_state(self, context):
        time_shift_tolerance = 3
        heal_interval = CONF.sync_instance_state_interval
        if not heal_interval:
            return
        curr_time = time.time()
        if self._last_info_instance_state_heal != 0:
            if self._last_info_instance_state_heal + heal_interval > curr_time:
                return
        self._last_info_instance_state_heal = curr_time

        sync_client = self.sync_nova_client
        # cascaded_nova_cli = openstack_clients.nova()
        try:
            # if self._change_since_time is None:
            #     search_opts_args = {'all_tenants': True}
            #     servers = cascaded_nova_cli.servers.list(
            #         search_opts=search_opts_args)
            # else:

            # In first time query, the self._change_since_time is
            # None, but has not affect.
            search_opts_args = {
                'changes-since': self._change_since_time,
                'all_tenants': True
            }
            # (jd):update change_since time for next search, it's done before
            # the state-sync handle in case of the handle spend too much
            # time which results in missing some instance the next time to
            # search.
            LOG.debug(_('the current time is %s'), timeutils.utcnow())
            _change_since_time = timeutils.utcnow() - \
                             datetime.timedelta(seconds=time_shift_tolerance)
            self._change_since_time = timeutils.isotime(_change_since_time)
            LOG.debug(_('the change since time update to %s'),
                      self._change_since_time)

            marker = None
            while True:
                servers = sync_client.servers.list(search_opts=search_opts_args,
                    limit=self.QUERY_PER_PAGE_LIMIT, marker=marker)

                if servers:
                    marker = servers[-1].id
                else:
                    break

                LOG.debug(_('Updated the servers %s '), servers)

                for server in servers:
                    csg_uuid = ComputeManager._extract_csg_uuid(server)
                    if csg_uuid:
                        csd_task_state = server._info['OS-EXT-STS:task_state']
                        if csd_task_state in EXCLUDE_TASK_STATES:
                            continue
                        self._instance_update(
                            context,
                            csg_uuid,
                            vm_state=server._info['OS-EXT-STS:vm_state'],
                            task_state=server._info['OS-EXT-STS:task_state'],
                            power_state=server._info['OS-EXT-STS:power_state'],
                            launched_at=server._info['OS-SRV-USG:launched_at']
                        )
                        LOG.debug(_('Updated the server %s from nova-proxy'),
                                  server.id)
        except exception.InstanceNotFound:
            pass
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to sys server status to db.'))

    def _heal_proxy_ports(self, context, instance, network_info):
        physical_ports = []
        for netObj in network_info:
            net_id = netObj['network']['id']
            net_name = netObj['network']['label']
            physical_net_id = None
            ovs_interface_mac = netObj['address']
            fixed_ips = []
            physical_net_id_exist_flag = False
            if net_id in self._network_mapping.keys():
                physical_net_id = self._network_mapping[net_id]['mapping_id']
                physical_net_id_exist_flag = True
                LOG.debug(_('Physical network has been created in physical'
                            ' leval,logicalNetId:%s, physicalNetId: %s '),
                          net_id, physical_net_id)
            if not physical_net_id_exist_flag:
                raise exception.NetworkNotFound(network_id=net_id)

            fixed_ips.append(
                {'ip_address': netObj['network']['subnets'][0]['ips'][0]['address']}
            )
            #use cascading vif id directly.
            csg_port_name = netObj['ovs_interfaceid'] or ''
            req_body = {'port':
                           {'tenant_id': instance['project_id'],
                            'admin_state_up': True,
                            'name': csg_port_name,
                            'network_id': physical_net_id,
                            'mac_address': ovs_interface_mac,
                            'fixed_ips': fixed_ips,
                            'binding:profile': {
                                "cascading_port_id": netObj['ovs_interfaceid']
                            }
                           }}
            neutron_client = ComputeManager.get_neutron_client(CONF.proxy_region_name)
            try:
                body_repsonse = neutron_client.create_port(req_body)
                physical_ports.append(body_repsonse)
                LOG.debug(_('Finish to create Physical port, body_response %s'),
                          body_repsonse)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Fail to create physical port req_body %s .'),
                              req_body)

        return physical_ports

    @staticmethod
    def _get_network_req(network, instance):

        if network['provider:network_type'] == 'vxlan':
            req_network = {
                'network': {
                    'provider:network_type': network['provider:network_type'],
                    'provider:segmentation_id': network['provider:segmentation_id'],
                    'tenant_id': instance['project_id'],
                    'admin_state_up': True}}
        elif network['provider:network_type'] == 'flat':
            req_network = {
                'network': {
                    'provider:network_type': network['provider:network_type'],
                    'provider:physical_network': network['provider:physical_network'],
                    'tenant_id': instance['project_id'],
                    'admin_state_up': True}}
        elif network['provider:network_type'] == 'local':
            req_network = {
                'network': {
                    'provider:network_type': network['provider:network_type'],
                    'tenant_id': instance['project_id'],
                    'admin_state_up': True}}
        else:
            req_network = {
                'network': {
                    'provider:network_type': network['provider:network_type'],
                    'provider:physical_network': network['provider:physical_network'],
                    'provider:segmentation_id': network['provider:segmentation_id'],
                    'tenant_id': instance['project_id'],
                    'admin_state_up': True}}
        return req_network

    def _heal_proxy_networks(self, context, instance, network_info):
        cascaded_network_list = []

        neutron_client = ComputeManager.get_neutron_client(CONF.os_region_name)
        csd_neutron_client = ComputeManager.get_neutron_client(CONF.proxy_region_name)

        for net_obj in network_info:
            net_id = net_obj['network']['id']
            net_name = net_obj['network']['label']
            physical_net_id_exist_flag = False
            if net_id in self._network_mapping.keys():
                physical_net_id_exist_flag = True
                physical_net_id = self._network_mapping[net_id]['mapping_id']
                cascaded_network_list.append(physical_net_id)
                LOG.debug(_('Physical network has been exist, the mapping '
                            'is %s:%s.'), net_id, physical_net_id)
            if not physical_net_id_exist_flag:
                LOG.debug(_('Physical network not exist.'
                          'need to create,logicalNetId:%s'),
                          net_id)
                self._network_mapping[net_id] = {'mapping_id': '',
                                                 'name': '',
                                                 'subnets': []}
                search_opts = {'id': [net_id]}
                logical_nets = neutron_client.list_networks(**search_opts).get('networks', [])
                # create cascaded network and add the mapping relationship.
                req_network = self._get_network_req(logical_nets[0], instance)
                csd_net_name = ComputeManager._gen_csd_nets_name(net_name, net_id)
                req_network['network']['name'] = csd_net_name
                try:
                    net_response = csd_neutron_client.create_network(req_network)
                    csd_net_id = net_response['network']['id']
                except NeutronClientException as ne:
                    if ne.status_code == 409:
                        _search_opts = {'name': csd_net_name}
                        _nets = (csd_neutron_client.list_networks(**_search_opts)
                                                          .get('networks', []))
                        if _nets:
                            net_response = _nets[0]
                            csd_net_id = net_response['id']
                        else:
                            LOG.exception(_('Create cascaded network conflict, but '
                                            'still can not find the cascaded network:'
                                            '%s'), csd_net_name)
                            raise
                except Exception:
                    LOG.exception(_('Create cascaded network failed, with the '
                                    'req_network: %s'), req_network)
                    raise

                cascaded_network_list.append(csd_net_id)
                LOG.debug(_('Finish to create Physical network,'
                            'net_response %s'), req_network)
                #Actually, only one subnet item in net_obj
                cidr_list = [sn['cidr'] for sn in net_obj['network']['subnets']]

                self._network_mapping[net_id]['mapping_id'] = csd_net_id
                # self._network_mapping[net_id]['name'] = net_name
            else:
                csd_net_id = self._network_mapping[net_id]['mapping_id']
                # old_csg_net_name = self._network_mapping[net_id]['name']
                # #Need Check if network name has been changed.
                # max_len = ComputeManager.CSG_NET_NAME_MAX_LEN
                # csg_net_name = (net_name if len(net_name) <= max_len
                #                 else net_name[:max_len])
                #
                # if old_csg_net_name != csg_net_name:
                #     csd_net_name = ComputeManager._gen_csd_nets_name(net_name, net_id)
                #     update_req = {'network': {'name': csd_net_name, }}
                #     csd_neutron_client.update_network(csd_net_id, update_req)
                #     self._network_mapping[net_id]['name'] = net_name

                #Can not find subnet id in "net_obj['network']['subnets']", so
                #we have to compare the cidr.
                mapping_subnets = self._network_mapping[net_id]['subnets']
                cidr_list = [sn['cidr'] for sn in net_obj['network']['subnets']
                             if sn['cidr'] not in [m_sn['cidr']
                                                   for m_sn in mapping_subnets]]
                if not cidr_list:
                    #todo(jiadong) May check if some other subnets not exists
                    # or modified ?
                    continue
                LOG.debug(_('Check subnet not full synced, the un-sync cidrs are %s'),
                          cidr_list)

            try:
                # create cascaded subnets based on the cascaded network.
                for cidr in cidr_list:
                    sub_search_opts = {'network_id': net_id, 'cidr': cidr}
                    csg_subnet = neutron_client.list_subnets(**sub_search_opts).get('subnets', [])[0]
                    csd_subnet_name = ComputeManager._gen_csd_nets_name(csg_subnet['name'],
                                                                        csg_subnet['id'])
                    req_subnet = {
                        'subnet': {
                            'network_id': csd_net_id,
                            'name': csd_subnet_name,
                            'ip_version': csg_subnet['ip_version'],
                            'cidr': csg_subnet['cidr'],
                            'gateway_ip': csg_subnet['gateway_ip'],
                            'allocation_pools': csg_subnet['allocation_pools'],
                            'enable_dhcp': csg_subnet['enable_dhcp'],
                            'tenant_id': instance['project_id']}}
                    sn_resp = csd_neutron_client.create_subnet(req_subnet)
                    mapping_subnets = self._network_mapping[net_id]['subnets']
                    mapping_subnets.append({
                        'csg_id': csg_subnet['id'],
                        'name': csd_subnet_name,
                        'id': sn_resp['subnet']['id'],
                        'allocation_pools': csg_subnet['allocation_pools'],
                        'gateway_ip': csg_subnet['gateway_ip'],
                        'ip_version': csg_subnet['ip_version'],
                        'cidr': csg_subnet['cidr'],
                        'tenant_id': csg_subnet['tenant_id'],
                        'network_id': csg_subnet['network_id'],
                        'enable_dhcp': csg_subnet['enable_dhcp'],
                    })
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Fail to synchronizate physical network'))
        return cascaded_network_list

    def _set_instance_error_state(self, context, instance):
        instance_uuid = instance['uuid']
        try:
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ERROR)
        except exception.InstanceNotFound:
            LOG.debug('Instance has been destroyed from under us while '
                      'trying to set it to ERROR',
                      instance_uuid=instance_uuid)

    def _set_instance_obj_error_state(self, context, instance):
        try:
            instance.vm_state = vm_states.ERROR
            instance.save()
        except exception.InstanceNotFound:
            LOG.debug('Instance has been destroyed from under us while '
                      'trying to set it to ERROR', instance=instance)

    def _get_instances_on_driver(self, context, filters=None):
        """Return a list of instance records for the instances found
        on the hypervisor which satisfy the specified filters. If filters=None
        return a list of instance records for all the instances found on the
        hypervisor.
        """
        if not filters:
            filters = {}
        try:
            driver_uuids = self.driver.list_instance_uuids()
            filters['uuid'] = driver_uuids
            local_instances = objects.InstanceList.get_by_filters(
                context, filters, use_slave=True)
            return local_instances
        except NotImplementedError:
            pass

        # The driver doesn't support uuids listing, so we'll have
        # to brute force.
        driver_instances = self.driver.list_instances()
        instances = objects.InstanceList.get_by_filters(context, filters,
                                                        use_slave=True)
        name_map = dict((instance.name, instance) for instance in instances)
        local_instances = []
        for driver_instance in driver_instances:
            instance = name_map.get(driver_instance)
            if not instance:
                continue
            local_instances.append(instance)
        return local_instances

    def _destroy_evacuated_instances(self, context):
        """Destroys evacuated instances.

        While nova-compute was down, the instances running on it could be
        evacuated to another host. Check that the instances reported
        by the driver are still associated with this host.  If they are
        not, destroy them, with the exception of instances which are in
        the MIGRATING, RESIZE_MIGRATING, RESIZE_MIGRATED, RESIZE_FINISH
        task state or RESIZED vm state.
        """
        our_host = self.host
        filters = {'deleted': False}
        local_instances = self._get_instances_on_driver(context, filters)
        for instance in local_instances:
            if instance.host != our_host:
                if (instance.task_state in [task_states.MIGRATING,
                                            task_states.RESIZE_MIGRATING,
                                            task_states.RESIZE_MIGRATED,
                                            task_states.RESIZE_FINISH]
                    or instance.vm_state in [vm_states.RESIZED]):
                    LOG.debug('Will not delete instance as its host ('
                              '%(instance_host)s) is not equal to our '
                              'host (%(our_host)s) but its task state is '
                              '(%(task_state)s) and vm state is '
                              '(%(vm_state)s)',
                              {'instance_host': instance.host,
                               'our_host': our_host,
                               'task_state': instance.task_state,
                               'vm_state': instance.vm_state},
                              instance=instance)
                    continue
                LOG.info(_('Deleting instance as its host ('
                           '%(instance_host)s) is not equal to our '
                           'host (%(our_host)s).'),
                         {'instance_host': instance.host,
                          'our_host': our_host}, instance=instance)
                try:
                    network_info = self._get_instance_nw_info(context,
                                                              instance)
                    bdi = self._get_instance_block_device_info(context,
                                                               instance)
                    destroy_disks = not (self._is_instance_storage_shared(
                        context, instance))
                except exception.InstanceNotFound:
                    network_info = network_model.NetworkInfo()
                    bdi = {}
                    LOG.info(_('Instance has been marked deleted already, '
                               'removing it from the hypervisor.'),
                             instance=instance)
                    # always destroy disks if the instance was deleted
                    destroy_disks = True
                self.driver.destroy(context, instance,
                                    network_info,
                                    bdi, destroy_disks)

    def _is_instance_storage_shared(self, context, instance):
        shared_storage = True
        data = None
        try:
            data = self.driver.check_instance_shared_storage_local(context,
                                                                   instance)
            if data:
                shared_storage = (self.compute_rpcapi.
                                  check_instance_shared_storage(context,
                                                                instance, data))
        except NotImplementedError:
            LOG.warning(_('Hypervisor driver does not support '
                          'instance shared storage check, '
                          'assuming it\'s not on shared storage'),
                        instance=instance)
            shared_storage = False
        except Exception:
            LOG.exception(_LE('Failed to check if instance shared'),
                          instance=instance)
        finally:
            if data:
                self.driver.check_instance_shared_storage_cleanup(context,
                                                                  data)
        return shared_storage

    def _complete_partial_deletion(self, context, instance):
        """Complete deletion for instances in DELETED status but not marked as
        deleted in the DB
        """
        instance.destroy()
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        quotas = objects.Quotas(context)
        project_id, user_id = quotas_obj.ids_from_instance(context, instance)
        quotas.reserve(context, project_id=project_id, user_id=user_id,
                       instances=-1, cores=-instance.vcpus,
                       ram=-instance.memory_mb)
        self._complete_deletion(context,
                                instance,
                                bdms,
                                quotas,
                                instance.system_metadata)

    def _complete_deletion(self, context, instance, bdms,
                           quotas, system_meta):
        if quotas:
            quotas.commit()

        # ensure block device mappings are not leaked
        for bdm in bdms:
            bdm.destroy()

        self._notify_about_instance_usage(context, instance, "delete.end",
                                          system_metadata=system_meta)

        if CONF.vnc_enabled or CONF.spice.enabled:
            if CONF.cells.enable:
                self.cells_rpcapi.consoleauth_delete_tokens(context,
                                                            instance.uuid)
            else:
                self.consoleauth_rpcapi.delete_tokens_for_instance(context,
                                                                   instance.uuid)

    def _init_instance(self, context, instance):
        '''Initialize this instance during service init.'''

        # Instances that are shut down, or in an error state can not be
        # initialized and are not attempted to be recovered. The exception
        # to this are instances that are in RESIZE_MIGRATING or DELETING,
        # which are dealt with further down.
        if (instance.vm_state == vm_states.SOFT_DELETED or
                (instance.vm_state == vm_states.ERROR and
                         instance.task_state not in
                         (task_states.RESIZE_MIGRATING, task_states.DELETING))):
            LOG.debug("Instance is in %s state.",
                      instance.vm_state, instance=instance)
            return

        if instance.vm_state == vm_states.DELETED:
            try:
                self._complete_partial_deletion(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _LE('Failed to complete a deletion')
                LOG.exception(msg, instance=instance)
            return

        if (instance.vm_state == vm_states.BUILDING or
                    instance.task_state in [task_states.SCHEDULING,
                                            task_states.BLOCK_DEVICE_MAPPING,
                                            task_states.NETWORKING,
                                            task_states.SPAWNING]):
            # NOTE(dave-mcnally) compute stopped before instance was fully
            # spawned so set to ERROR state. This is safe to do as the state
            # may be set by the api but the host is not so if we get here the
            # instance has already been scheduled to this particular host.
            LOG.debug("Instance failed to spawn correctly, "
                      "setting to ERROR state", instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        if (instance.vm_state in [vm_states.ACTIVE, vm_states.STOPPED] and
                    instance.task_state in [task_states.REBUILDING,
                                            task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                                            task_states.REBUILD_SPAWNING]):
            # NOTE(jichenjc) compute stopped before instance was fully
            # spawned so set to ERROR state. This is consistent to BUILD
            LOG.debug("Instance failed to rebuild correctly, "
                      "setting to ERROR state", instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        if (instance.vm_state != vm_states.ERROR and
                    instance.task_state in [task_states.IMAGE_SNAPSHOT_PENDING,
                                            task_states.IMAGE_PENDING_UPLOAD,
                                            task_states.IMAGE_UPLOADING,
                                            task_states.IMAGE_SNAPSHOT]):
            LOG.debug("Instance in transitional state %s at start-up "
                      "clearing task state",
                      instance['task_state'], instance=instance)
            try:
                self._post_interrupted_snapshot_cleanup(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _LE('Failed to cleanup snapshot.')
                LOG.exception(msg, instance=instance)
            instance.task_state = None
            instance.save()

        if instance.task_state == task_states.DELETING:
            try:
                LOG.info(_('Service started deleting the instance during '
                           'the previous run, but did not finish. Restarting '
                           'the deletion now.'), instance=instance)
                instance.obj_load_attr('metadata')
                instance.obj_load_attr('system_metadata')
                bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)
                # FIXME(comstud): This needs fixed. We should be creating
                # reservations and updating quotas, because quotas
                # wouldn't have been updated for this instance since it is
                # still in DELETING.  See bug 1296414.
                #
                # Create a dummy quota object for now.
                quotas = objects.Quotas.from_reservations(
                    context, None, instance=instance)
                self._delete_instance(context, instance, bdms, quotas)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _LE('Failed to complete a deletion')
                LOG.exception(msg, instance=instance)
                self._set_instance_error_state(context, instance)
            return

        try_reboot, reboot_type = self._retry_reboot(context, instance)
        current_power_state = self._get_power_state(context, instance)

        if try_reboot:
            LOG.debug("Instance in transitional state (%(task_state)s) at "
                      "start-up and power state is (%(power_state)s), "
                      "triggering reboot",
                      {'task_state': instance['task_state'],
                       'power_state': current_power_state},
                      instance=instance)
            self.compute_rpcapi.reboot_instance(context, instance,
                                                block_device_info=None,
                                                reboot_type=reboot_type)
            return

        elif (current_power_state == power_state.RUNNING and
                      instance.task_state in [task_states.REBOOT_STARTED,
                                              task_states.REBOOT_STARTED_HARD]):
            LOG.warning(_("Instance in transitional state "
                          "(%(task_state)s) at start-up and power state "
                          "is (%(power_state)s), clearing task state"),
                        {'task_state': instance['task_state'],
                         'power_state': current_power_state},
                        instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ACTIVE
            instance.save()

        if instance.task_state == task_states.POWERING_OFF:
            try:
                LOG.debug("Instance in transitional state %s at start-up "
                          "retrying stop request",
                          instance['task_state'], instance=instance)
                self.stop_instance(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _LE('Failed to stop instance')
                LOG.exception(msg, instance=instance)
            return

        if instance.task_state == task_states.POWERING_ON:
            try:
                LOG.debug("Instance in transitional state %s at start-up "
                          "retrying start request",
                          instance['task_state'], instance=instance)
                self.start_instance(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _LE('Failed to start instance')
                LOG.exception(msg, instance=instance)
            return

        net_info = compute_utils.get_nw_info_for_instance(instance)
        try:
            self.driver.plug_vifs(instance, net_info)
        except NotImplementedError as e:
            LOG.debug(e, instance=instance)
        if instance.task_state == task_states.RESIZE_MIGRATING:
            # We crashed during resize/migration, so roll back for safety
            try:
                # NOTE(mriedem): check old_vm_state for STOPPED here, if it's
                # not in system_metadata we default to True for backwards
                # compatibility
                power_on = (instance.system_metadata.get('old_vm_state') !=
                            vm_states.STOPPED)

                block_dev_info = self._get_instance_block_device_info(context,
                                                                      instance)

                self.driver.finish_revert_migration(context,
                                                    instance, net_info, block_dev_info, power_on)

            except Exception as e:
                LOG.exception(_LE('Failed to revert crashed migration'),
                              instance=instance)
            finally:
                LOG.info(_('Instance found in migrating state during '
                           'startup. Resetting task_state'),
                         instance=instance)
                instance.task_state = None
                instance.save()
        if instance.task_state == task_states.MIGRATING:
            # Live migration did not complete, but instance is on this
            # host, so reset the state.
            instance.task_state = None
            instance.save(expected_task_state=[task_states.MIGRATING])

        db_state = instance.power_state
        drv_state = self._get_power_state(context, instance)
        expect_running = (db_state == power_state.RUNNING and
                          drv_state != db_state)

        LOG.debug('Current state is %(drv_state)s, state in DB is '
                  '%(db_state)s.',
                  {'drv_state': drv_state, 'db_state': db_state},
                  instance=instance)

        if expect_running and CONF.resume_guests_state_on_host_boot:
            LOG.info(_('Rebooting instance after nova-compute restart.'),
                     instance=instance)

            block_device_info = \
                self._get_instance_block_device_info(context, instance)

            try:
                self.driver.resume_state_on_host_boot(
                    context, instance, net_info, block_device_info)
            except NotImplementedError:
                LOG.warning(_('Hypervisor driver does not support '
                              'resume guests'), instance=instance)
            except Exception:
                # NOTE(vish): The instance failed to resume, so we set the
                #             instance to error and attempt to continue.
                LOG.warning(_('Failed to resume instance'), instance=instance)
                self._set_instance_error_state(context, instance)

        elif drv_state == power_state.RUNNING:
            # VMwareAPI drivers will raise an exception
            try:
                self.driver.ensure_filtering_rules_for_instance(
                    instance, net_info)
            except NotImplementedError:
                LOG.warning(_('Hypervisor driver does not support '
                              'firewall rules'), instance=instance)

    def _retry_reboot(self, context, instance):
        current_power_state = self._get_power_state(context, instance)
        current_task_state = instance.task_state
        retry_reboot = False
        reboot_type = compute_utils.get_reboot_type(current_task_state,
                                                    current_power_state)

        pending_soft = (current_task_state == task_states.REBOOT_PENDING and
                        instance.vm_state in vm_states.ALLOW_SOFT_REBOOT)
        pending_hard = (current_task_state == task_states.REBOOT_PENDING_HARD
                        and instance.vm_state in vm_states.ALLOW_HARD_REBOOT)
        started_not_running = (current_task_state in
                               [task_states.REBOOT_STARTED,
                                task_states.REBOOT_STARTED_HARD] and
                               current_power_state != power_state.RUNNING)

        if pending_soft or pending_hard or started_not_running:
            retry_reboot = True

        return retry_reboot, reboot_type

    def handle_events(self, event):
        if isinstance(event, virtevent.LifecycleEvent):
            try:
                self.handle_lifecycle_event(event)
            except exception.InstanceNotFound:
                LOG.debug("Event %s arrived for non-existent instance. The "
                          "instance was probably deleted.", event)
        else:
            LOG.debug("Ignoring event %s", event)

    def init_virt_events(self):
        self.driver.register_event_listener(self.handle_events)

    def init_host(self):
        """Initialization for a standalone compute service."""
        self.driver.init_host(host=self.host)
        context = nova.context.get_admin_context()
        instances = objects.InstanceList.get_by_host(
            context, self.host, expected_attrs=['info_cache'])

        if CONF.defer_iptables_apply:
            self.driver.filter_defer_apply_on()

        self.init_virt_events()

        try:
            # checking that instance was not already evacuated to other host
            self._destroy_evacuated_instances(context)
            for instance in instances:
                self._init_instance(context, instance)
        finally:
            if CONF.defer_iptables_apply:
                self.driver.filter_defer_apply_off()

    def cleanup_host(self):
        self.driver.cleanup_host(host=self.host)

    def pre_start_hook(self):
        """After the service is initialized, but before we fully bring
        the service up by listening on RPC queues, make sure to update
        our available resources (and indirectly our available nodes).
        """
        self.update_available_resource(nova.context.get_admin_context())
        self.update_aggrgates_info(nova.context.get_admin_context())

    def _get_power_state(self, context, instance):
        """Retrieve the power state for the given instance."""
        LOG.debug('Checking state', instance=instance)
        try:
            return self.driver.get_info(instance)["state"]
        except exception.NotFound:
            return power_state.NOSTATE

    def get_console_topic(self, context):
        """Retrieves the console host for a project on this host.

        Currently this is just set in the flags for each compute host.

        """
        # TODO(mdragon): perhaps make this variable by console_type?
        return '%s.%s' % (CONF.console_topic, CONF.console_host)

    @wrap_exception()
    def refresh_instance_security_rules(self, context, instance):
        """Tell the virtualization driver to refresh security rules for
        an instance.

        Passes straight through to the virtualization driver.

        Synchronise the call because we may still be in the middle of
        creating the instance.
        """
        @utils.synchronized(instance['uuid'])
        def _sync_refresh():
            try:
                return self.driver.refresh_instance_security_rules(instance)
            except NotImplementedError:
                LOG.warning(_('Hypervisor driver does not support '
                              'security groups.'), instance=instance)

        return _sync_refresh()


    def _get_instance_nw_info(self, context, instance, use_slave=False):
        """Get a list of dictionaries of network data of an instance."""
        if (not hasattr(instance, 'system_metadata') or
                    len(instance['system_metadata']) == 0):
            # NOTE(danms): Several places in the code look up instances without
            # pulling system_metadata for performance, and call this function.
            # If we get an instance without it, re-fetch so that the call
            # to network_api (which requires it for instance_type) will
            # succeed.
            instance = objects.Instance.get_by_uuid(context,
                                                    instance['uuid'],
                                                    use_slave=use_slave)

        network_info = self.network_api.get_instance_nw_info(context,
                                                             instance)
        return network_info

    def _await_block_device_map_created(self, context, vol_id):
        # TODO(yamahata): creating volume simultaneously
        #                 reduces creation time?
        # TODO(yamahata): eliminate dumb polling
        start = time.time()
        retries = CONF.block_device_allocate_retries
        if retries < 0:
            LOG.warn(_LW("Treating negative config value (%(retries)s) for "
                         "'block_device_retries' as 0."),
                     {'retries': retries})
        # (1) treat  negative config value as 0
        # (2) the configured value is 0, one attempt should be made
        # (3) the configured value is > 0, then the total number attempts
        #      is (retries + 1)
        attempts = 1
        if retries >= 1:
            attempts = retries + 1
        for attempt in range(1, attempts + 1):
            volume = self.volume_api.get(context, vol_id)
            volume_status = volume['status']
            if volume_status not in ['creating', 'downloading']:
                if volume_status != 'available':
                    LOG.warn(_("Volume id: %s finished being created but was"
                               " not set as 'available'"), vol_id)
                return attempt
            greenthread.sleep(CONF.block_device_allocate_retries_interval)
        # NOTE(harlowja): Should only happen if we ran out of attempts
        raise exception.VolumeNotCreated(volume_id=vol_id,
                                         seconds=int(time.time() - start),
                                         attempts=attempts)

    def _decode_files(self, injected_files):
        """Base64 decode the list of files to inject."""
        if not injected_files:
            return []

        def _decode(f):
            path, contents = f
            try:
                decoded = base64.b64decode(contents)
                return path, decoded
            except TypeError:
                raise exception.Base64Exception(path=path)

        return [_decode(f) for f in injected_files]

    def _run_instance(self, context, request_spec,
                      filter_properties, requested_networks, injected_files,
                      admin_password, is_first_time, node, instance,
                      legacy_bdm_in_spec):
        """Launch a new instance with specified options."""

        extra_usage_info = {}

        def notify(status, msg="", fault=None, **kwargs):
            """Send a create.{start,error,end} notification."""
            type_ = "create.%(status)s" % dict(status=status)
            info = extra_usage_info.copy()
            info['message'] = msg
            self._notify_about_instance_usage(context, instance, type_,
                                              extra_usage_info=info, fault=fault, **kwargs)

        try:
            self._prebuild_instance(context, instance)

            if request_spec and request_spec.get('image'):
                image_meta = request_spec['image']
            else:
                image_meta = {}

            extra_usage_info = {"image_name": image_meta.get('name', '')}

            notify("start")  # notify that build is starting

            instance, network_info = self._build_instance(context,
                                                          request_spec, filter_properties, requested_networks,
                                                          injected_files, admin_password, is_first_time, node,
                                                          instance, image_meta, legacy_bdm_in_spec)
            notify("end", msg=_("Success"), network_info=network_info)

        except exception.RescheduledException as e:
            # Instance build encountered an error, and has been rescheduled.
            notify("error", fault=e)

        except exception.BuildAbortException as e:
            # Instance build aborted due to a non-failure
            LOG.info(e)
            notify("end", msg=e.format_message())  # notify that build is done

        except Exception as e:
            # Instance build encountered a non-recoverable error:
            with excutils.save_and_reraise_exception():
                self._set_instance_error_state(context, instance)
                notify("error", fault=e)  # notify that build failed

    def _prebuild_instance(self, context, instance):
        # self._check_instance_exists(context, instance)

        try:
            self._start_building(context, instance)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            msg = _("Instance disappeared before we could start it")
            # Quickly bail out of here
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)

    def _validate_instance_group_policy(self, context, instance,
                                        filter_properties):
        # NOTE(russellb) Instance group policy is enforced by the scheduler.
        # However, there is a race condition with the enforcement of
        # anti-affinity.  Since more than one instance may be scheduled at the
        # same time, it's possible that more than one instance with an
        # anti-affinity policy may end up here.  This is a validation step to
        # make sure that starting the instance here doesn't violate the policy.

        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        group_hint = scheduler_hints.get('group')
        if not group_hint:
            return

        @utils.synchronized(group_hint)
        def _do_validation(context, instance, group_hint):
            group = objects.InstanceGroup.get_by_hint(context, group_hint)
            if 'anti-affinity' not in group.policies:
                return

            group_hosts = group.get_hosts(context, exclude=[instance.uuid])
            if self.host in group_hosts:
                msg = _("Anti-affinity instance group policy was violated.")
                raise exception.RescheduledException(
                    instance_uuid=instance.uuid,
                    reason=msg)

        _do_validation(context, instance, group_hint)

    def _build_instance(self, context, request_spec, filter_properties,
                        requested_networks, injected_files, admin_password, is_first_time,
                        node, instance, image_meta, legacy_bdm_in_spec):
        original_context = context
        context = context.elevated()

        # NOTE(danms): This method is deprecated, but could be called,
        # and if it is, it will have an old megatuple for requested_networks.
        if requested_networks is not None:
            requested_networks_obj = objects.NetworkRequestList(
                objects=[objects.NetworkRequest.from_tuple(t)
                         for t in requested_networks])
        else:
            requested_networks_obj = None

        # If neutron security groups pass requested security
        # groups to allocate_for_instance()
        if request_spec and self.is_neutron_security_groups:
            security_groups = request_spec.get('security_group')
        else:
            security_groups = []

        if node is None:
            node = self.driver.get_available_nodes(refresh=True)[0]
            LOG.debug("No node specified, defaulting to %s", node)

        network_info = None
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)

        # b64 decode the files to inject:
        injected_files_orig = injected_files
        injected_files = self._decode_files(injected_files)

        rt = self._get_resource_tracker(node)
        try:
            limits = filter_properties.get('limits', {})
            with rt.instance_claim(context, instance, limits):
                # NOTE(russellb) It's important that this validation be done
                # *after* the resource tracker instance claim, as that is where
                # the host is set on the instance.
                self._validate_instance_group_policy(context, instance,
                                                     filter_properties)
                macs = self.driver.macs_for_instance(instance)
                dhcp_options = self.driver.dhcp_options_for_instance(instance)

                network_info = self._allocate_network(original_context,
                                                      instance, requested_networks_obj, macs,
                                                      security_groups, dhcp_options)

                instance.vm_state = vm_states.BUILDING
                instance.task_state = task_states.BLOCK_DEVICE_MAPPING
                instance.save()

                # Verify that all the BDMs have a device_name set and assign a
                # default to the ones missing it with the help of the driver.
                self._default_block_device_names(context, instance, image_meta,
                                                 bdms)

                block_device_info = self._prep_block_device(
                    context, instance, bdms)

                set_access_ip = (is_first_time and
                                 not instance.access_ip_v4 and
                                 not instance.access_ip_v6)

                #cascading patch
                self._heal_proxy_networks(context, instance, network_info)
                cascaded_ports = self._heal_proxy_ports(context, instance,
                                                        network_info)
                self._proxy_run_instance(context,
                                         instance,
                                         request_spec,
                                         filter_properties,
                                         requested_networks,
                                         injected_files,
                                         admin_password,
                                         is_first_time,
                                         node,
                                         legacy_bdm_in_spec,
                                         cascaded_ports)

                # instance = self._spawn(context, instance, image_meta,
                #                        network_info, block_device_info,
                #                        injected_files, admin_password,
                #                        set_access_ip=set_access_ip)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            # the instance got deleted during the spawn
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            try:
                self._deallocate_network(context, instance)
            except Exception:
                msg = _LE('Failed to dealloc network '
                          'for deleted instance')
                LOG.exception(msg, instance=instance)
            raise exception.BuildAbortException(
                instance_uuid=instance.uuid,
                reason=_("Instance disappeared during build"))
        except (exception.UnexpectedTaskStateError,
                exception.VirtualInterfaceCreateException) as e:
            # Don't try to reschedule, just log and reraise.
            with excutils.save_and_reraise_exception():
                LOG.debug(e.format_message(), instance=instance)
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
        except exception.InvalidBDM:
            with excutils.save_and_reraise_exception():
                if network_info is not None:
                    network_info.wait(do_raise=False)
                try:
                    self._deallocate_network(context, instance)
                except Exception:
                    msg = _LE('Failed to dealloc network '
                              'for failed instance')
                    LOG.exception(msg, instance=instance)
        except Exception:
            exc_info = sys.exc_info()
            # try to re-schedule instance:
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            rescheduled = self._reschedule_or_error(original_context, instance,
                                                    exc_info, requested_networks, admin_password,
                                                    injected_files_orig, is_first_time, request_spec,
                                                    filter_properties, bdms, legacy_bdm_in_spec)
            if rescheduled:
                # log the original build error
                self._log_original_error(exc_info, instance.uuid)
                raise exception.RescheduledException(
                    instance_uuid=instance.uuid,
                    reason=unicode(exc_info[1]))
            else:
                # not re-scheduling, go to error:
                raise exc_info[0], exc_info[1], exc_info[2]

        # spawn success
        return instance, network_info

    def _log_original_error(self, exc_info, instance_uuid):
        LOG.error(_('Error: %s') % exc_info[1], instance_uuid=instance_uuid,
                  exc_info=exc_info)

    def _reschedule_or_error(self, context, instance, exc_info,
                             requested_networks, admin_password, injected_files, is_first_time,
                             request_spec, filter_properties, bdms=None,
                             legacy_bdm_in_spec=True):
        """Try to re-schedule the build or re-raise the original build error to
        error out the instance.
        """
        original_context = context
        context = context.elevated()

        instance_uuid = instance['uuid']
        rescheduled = False

        compute_utils.add_instance_fault_from_exc(context,
                                                  instance, exc_info[1], exc_info=exc_info)
        self._notify_about_instance_usage(context, instance,
                                          'instance.create.error', fault=exc_info[1])

        try:
            LOG.debug("Clean up resource before rescheduling.",
                      instance=instance)
            if bdms is None:
                bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

            self._shutdown_instance(context, instance,
                                    bdms, requested_networks)
            self._cleanup_volumes(context, instance['uuid'], bdms)
        except Exception:
            # do not attempt retry if clean up failed:
            with excutils.save_and_reraise_exception():
                self._log_original_error(exc_info, instance_uuid)

        #cascading patch
        # try:
        #     method_args = (request_spec, admin_password, injected_files,
        #                    requested_networks, is_first_time, filter_properties,
        #                    legacy_bdm_in_spec)
        #     task_state = task_states.SCHEDULING
        #
        #     rescheduled = self._reschedule(original_context, request_spec,
        #                                    filter_properties, instance,
        #                                    self.scheduler_rpcapi.run_instance, method_args,
        #                                    task_state, exc_info)
        #
        # except Exception:
        #     rescheduled = False
        #     LOG.exception(_LE("Error trying to reschedule"),
        #                   instance_uuid=instance_uuid)

        return rescheduled

    def _reschedule(self, context, request_spec, filter_properties,
                    instance, reschedule_method, method_args, task_state,
                    exc_info=None):
        """Attempt to re-schedule a compute operation."""

        instance_uuid = instance['uuid']
        retry = filter_properties.get('retry', None)
        if not retry:
            # no retry information, do not reschedule.
            LOG.debug("Retry info not present, will not reschedule",
                      instance_uuid=instance_uuid)
            return

        if not request_spec:
            LOG.debug("No request spec, will not reschedule",
                      instance_uuid=instance_uuid)
            return

        request_spec['instance_uuids'] = [instance_uuid]

        LOG.debug("Re-scheduling %(method)s: attempt %(num)d",
                  {'method': reschedule_method.func_name,
                   'num': retry['num_attempts']}, instance_uuid=instance_uuid)

        # reset the task state:
        self._instance_update(context, instance_uuid, task_state=task_state)

        if exc_info:
            # stringify to avoid circular ref problem in json serialization:
            retry['exc'] = traceback.format_exception_only(exc_info[0],
                                                           exc_info[1])

        reschedule_method(context, *method_args)
        return True

    @periodic_task.periodic_task
    def _check_instance_build_time(self, context):
        """Ensure that instances are not stuck in build."""
        timeout = CONF.instance_build_timeout
        if timeout == 0:
            return

        filters = {'vm_state': vm_states.BUILDING,
                   'host': self.host}

        building_insts = objects.InstanceList.get_by_filters(context,
                                                             filters, expected_attrs=[], use_slave=True)

        for instance in building_insts:
            if timeutils.is_older_than(instance['created_at'], timeout):
                self._set_instance_error_state(context, instance)
                LOG.warn(_("Instance build timed out. Set to error state."),
                         instance=instance)

    def _check_instance_exists(self, context, instance):
        """Ensure an instance with the same name is not already present."""
        if self.driver.instance_exists(instance):
            raise exception.InstanceExists(name=instance.name)

    def _start_building(self, context, instance):
        """Save the host and launched_on fields and log appropriately."""
        LOG.audit(_('Starting instance...'), context=context,
                  instance=instance)
        self._instance_update(context, instance.uuid,
                              vm_state=vm_states.BUILDING,
                              task_state=None,
                              expected_task_state=(task_states.SCHEDULING,
                                                   None))

    def _allocate_network_async(self, context, instance, requested_networks,
                                macs, security_groups, is_vpn, dhcp_options):
        """Method used to allocate networks in the background.

        Broken out for testing.
        """
        LOG.debug("Allocating IP information in the background.",
                  instance=instance)
        retries = CONF.network_allocate_retries
        if retries < 0:
            LOG.warn(_("Treating negative config value (%(retries)s) for "
                       "'network_allocate_retries' as 0."),
                     {'retries': retries})
        attempts = retries > 1 and retries + 1 or 1
        retry_time = 1
        for attempt in range(1, attempts + 1):
            try:
                nwinfo = self.network_api.allocate_for_instance(
                    context, instance, vpn=is_vpn,
                    requested_networks=requested_networks,
                    macs=macs,
                    security_groups=security_groups,
                    dhcp_options=dhcp_options)
                LOG.debug('Instance network_info: |%s|', nwinfo,
                          instance=instance)
                sys_meta = instance.system_metadata
                sys_meta['network_allocated'] = 'True'
                self._instance_update(context, instance.uuid,
                                      system_metadata=sys_meta)
                return nwinfo
            except Exception:
                exc_info = sys.exc_info()
                log_info = {'attempt': attempt,
                            'attempts': attempts}
                if attempt == attempts:
                    LOG.exception(_LE('Instance failed network setup '
                                      'after %(attempts)d attempt(s)'),
                                  log_info)
                    raise exc_info[0], exc_info[1], exc_info[2]
                LOG.warn(_('Instance failed network setup '
                           '(attempt %(attempt)d of %(attempts)d)'),
                         log_info, instance=instance)
                time.sleep(retry_time)
                retry_time *= 2
                if retry_time > 30:
                    retry_time = 30
                    # Not reached.

    def _build_networks_for_instance(self, context, instance,
                                     requested_networks, security_groups):

        # If we're here from a reschedule the network may already be allocated.
        if strutils.bool_from_string(
                instance.system_metadata.get('network_allocated', 'False')):
            return self._get_instance_nw_info(context, instance)

        if not self.is_neutron_security_groups:
            security_groups = []

        macs = self.driver.macs_for_instance(instance)
        dhcp_options = self.driver.dhcp_options_for_instance(instance)
        network_info = self._allocate_network(context, instance,
                                              requested_networks, macs, security_groups, dhcp_options)

        if not instance.access_ip_v4 and not instance.access_ip_v6:
            # If CONF.default_access_ip_network_name is set, grab the
            # corresponding network and set the access ip values accordingly.
            # Note that when there are multiple ips to choose from, an
            # arbitrary one will be chosen.
            network_name = CONF.default_access_ip_network_name
            if not network_name:
                return network_info

            for vif in network_info:
                if vif['network']['label'] == network_name:
                    for ip in vif.fixed_ips():
                        if ip['version'] == 4:
                            instance.access_ip_v4 = ip['address']
                        if ip['version'] == 6:
                            instance.access_ip_v6 = ip['address']
                    instance.save()
                    break

        return network_info

    def _allocate_network(self, context, instance, requested_networks, macs,
                          security_groups, dhcp_options):
        """Start network allocation asynchronously.  Return an instance
        of NetworkInfoAsyncWrapper that can be used to retrieve the
        allocated networks when the operation has finished.
        """
        # NOTE(comstud): Since we're allocating networks asynchronously,
        # this task state has little meaning, as we won't be in this
        # state for very long.
        instance.vm_state = vm_states.BUILDING
        instance.task_state = task_states.NETWORKING
        instance.save(expected_task_state=[None])
        self._update_resource_tracker(context, instance)

        is_vpn = pipelib.is_vpn_image(instance.image_ref)
        return network_model.NetworkInfoAsyncWrapper(
            self._allocate_network_async, context, instance,
            requested_networks, macs, security_groups, is_vpn,
            dhcp_options)

    def _default_root_device_name(self, instance, image_meta, root_bdm):
        try:
            return self.driver.default_root_device_name(instance,
                                                        image_meta,
                                                        root_bdm)
        except NotImplementedError:
            return compute_utils.get_next_device_name(instance, [])

    def _default_device_names_for_instance(self, instance,
                                           root_device_name,
                                           *block_device_lists):
        try:
            self.driver.default_device_names_for_instance(instance,
                                                          root_device_name,
                                                          *block_device_lists)
        except NotImplementedError:
            compute_utils.default_device_names_for_instance(
                instance, root_device_name, *block_device_lists)

    def _default_block_device_names(self, context, instance,
                                    image_meta, block_devices):
        """Verify that all the devices have the device_name set. If not,
        provide a default name.

        It also ensures that there is a root_device_name and is set to the
        first block device in the boot sequence (boot_index=0).
        """
        root_bdm = block_device.get_root_bdm(block_devices)
        if not root_bdm:
            return

        # Get the root_device_name from the root BDM or the instance
        root_device_name = None
        update_instance = False
        update_root_bdm = False

        if root_bdm.device_name:
            root_device_name = root_bdm.device_name
            instance.root_device_name = root_device_name
            update_instance = True
        elif instance.root_device_name:
            root_device_name = instance.root_device_name
            root_bdm.device_name = root_device_name
            update_root_bdm = True
        else:
            root_device_name = self._default_root_device_name(instance,
                                                              image_meta,
                                                              root_bdm)

            instance.root_device_name = root_device_name
            root_bdm.device_name = root_device_name
            update_instance = update_root_bdm = True

        if update_instance:
            instance.save()
        if update_root_bdm:
            root_bdm.save()

        ephemerals = filter(block_device.new_format_is_ephemeral,
                            block_devices)
        swap = filter(block_device.new_format_is_swap,
                      block_devices)
        block_device_mapping = filter(
            driver_block_device.is_block_device_mapping, block_devices)

        self._default_device_names_for_instance(instance,
                                                root_device_name,
                                                ephemerals,
                                                swap,
                                                block_device_mapping)

    def _prep_block_device(self, context, instance, bdms,
                           do_check_attach=True):
        """Set up the block device for an instance with error logging."""
        try:
            block_device_info = {
                'root_device_name': instance['root_device_name'],
                'swap': driver_block_device.convert_swap(bdms),
                'ephemerals': driver_block_device.convert_ephemerals(bdms),
                'block_device_mapping': (
                    driver_block_device.attach_block_devices(
                        driver_block_device.convert_volumes(bdms),
                        context, instance, self.volume_api,
                        self.driver, do_check_attach=do_check_attach) +
                    driver_block_device.attach_block_devices(
                        driver_block_device.convert_snapshots(bdms),
                        context, instance, self.volume_api,
                        self.driver, self._await_block_device_map_created,
                        do_check_attach=do_check_attach) +
                    driver_block_device.attach_block_devices(
                        driver_block_device.convert_images(bdms),
                        context, instance, self.volume_api,
                        self.driver, self._await_block_device_map_created,
                        do_check_attach=do_check_attach) +
                    driver_block_device.attach_block_devices(
                        driver_block_device.convert_blanks(bdms),
                        context, instance, self.volume_api,
                        self.driver, self._await_block_device_map_created,
                        do_check_attach=do_check_attach))
            }

            if self.use_legacy_block_device_info:
                for bdm_type in ('swap', 'ephemerals', 'block_device_mapping'):
                    block_device_info[bdm_type] = \
                        driver_block_device.legacy_block_devices(
                            block_device_info[bdm_type])

            # Get swap out of the list
            block_device_info['swap'] = driver_block_device.get_swap(
                block_device_info['swap'])
            return block_device_info

        except exception.OverQuota:
            msg = _LW('Failed to create block device for instance due to '
                      'being over volume resource quota')
            LOG.warn(msg, instance=instance)
            raise exception.InvalidBDM()

        except Exception:
            LOG.exception(_LE('Instance failed block device setup'),
                          instance=instance)
            raise exception.InvalidBDM()

    @object_compat
    def _spawn(self, context, instance, image_meta, network_info,
               block_device_info, injected_files, admin_password,
               set_access_ip=False):
        """Spawn an instance with error logging and update its power state."""
        instance.vm_state = vm_states.BUILDING
        instance.task_state = task_states.SPAWNING
        instance.save(expected_task_state=task_states.BLOCK_DEVICE_MAPPING)

        try:
            self.driver.spawn(context, instance, image_meta,
                              injected_files, admin_password,
                              network_info,
                              block_device_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Instance failed to spawn'),
                              instance=instance)

        current_power_state = self._get_power_state(context, instance)

        instance.power_state = current_power_state
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.launched_at = timeutils.utcnow()

        def _set_access_ip_values():
            """Add access ip values for a given instance.

            If CONF.default_access_ip_network_name is set, this method will
            grab the corresponding network and set the access ip values
            accordingly. Note that when there are multiple ips to choose
            from, an arbitrary one will be chosen.
            """

            network_name = CONF.default_access_ip_network_name
            if not network_name:
                return

            for vif in network_info:
                if vif['network']['label'] == network_name:
                    for ip in vif.fixed_ips():
                        if ip['version'] == 4:
                            instance.access_ip_v4 = ip['address']
                        if ip['version'] == 6:
                            instance.access_ip_v6 = ip['address']
                    return

        if set_access_ip:
            _set_access_ip_values()

        network_info.wait(do_raise=True)
        instance.info_cache.network_info = network_info
        instance.save(expected_task_state=task_states.SPAWNING)
        return instance

    def _notify_about_instance_usage(self, context, instance, event_suffix,
                                     network_info=None, system_metadata=None,
                                     extra_usage_info=None, fault=None):
        pass
        # compute_utils.notify_about_instance_usage(
        #     self.notifier, context, instance, event_suffix,
        #     network_info=network_info,
        #     system_metadata=system_metadata,
        #     extra_usage_info=extra_usage_info, fault=fault)

    def _deallocate_network(self, context, instance,
                            requested_networks=None):
        LOG.debug('Deallocating network for instance', instance=instance)
        self.network_api.deallocate_for_instance(
            context, instance, requested_networks=requested_networks)

    def _get_instance_block_device_info(self, context, instance,
                                        refresh_conn_info=False,
                                        bdms=None):
        """Transform block devices to the driver block_device format."""

        if not bdms:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance['uuid'])
        swap = driver_block_device.convert_swap(bdms)
        ephemerals = driver_block_device.convert_ephemerals(bdms)
        block_device_mapping = (
            driver_block_device.convert_volumes(bdms) +
            driver_block_device.convert_snapshots(bdms) +
            driver_block_device.convert_images(bdms))

        if not refresh_conn_info:
            # if the block_device_mapping has no value in connection_info
            # (returned as None), don't include in the mapping
            block_device_mapping = [
                bdm for bdm in block_device_mapping
                if bdm.get('connection_info')]
        else:
            block_device_mapping = driver_block_device.refresh_conn_infos(
                block_device_mapping, context, instance, self.volume_api,
                self.driver)

        if self.use_legacy_block_device_info:
            swap = driver_block_device.legacy_block_devices(swap)
            ephemerals = driver_block_device.legacy_block_devices(ephemerals)
            block_device_mapping = driver_block_device.legacy_block_devices(
                block_device_mapping)

        # Get swap out of the list
        swap = driver_block_device.get_swap(swap)

        return {'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

    # NOTE(mikal): No object_compat wrapper on this method because its
    # callers all pass objects already
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def build_and_run_instance(self, context, instance, image, request_spec,
                               filter_properties, admin_password=None,
                               injected_files=None, requested_networks=None,
                               security_groups=None, block_device_mapping=None,
                               node=None, limits=None):

        # NOTE(danms): Remove this in v4.0 of the RPC API
        if (requested_networks and
                not isinstance(requested_networks,
                               objects.NetworkRequestList)):
            requested_networks = objects.NetworkRequestList(
                objects=[objects.NetworkRequest.from_tuple(t)
                         for t in requested_networks])

        @utils.synchronized(instance.uuid)
        def do_build_and_run_instance(context, instance, image, request_spec,
                    filter_properties, admin_password, injected_files,
                    requested_networks, security_groups, block_device_mapping,
                    node=None, limits=None):

            try:
                LOG.audit(_('Starting instance...'), context=context,
                          instance=instance)
                instance.vm_state = vm_states.BUILDING
                instance.task_state = None
                instance.save(expected_task_state=
                              (task_states.SCHEDULING, None))
            except exception.InstanceNotFound:
                msg = 'Instance disappeared before build.'
                LOG.debug(msg, instance=instance)
                return
            except exception.UnexpectedTaskStateError as e:
                LOG.debug(e.format_message(), instance=instance)
                return

            # b64 decode the files to inject:
            decoded_files = self._decode_files(injected_files)

            if limits is None:
                limits = {}

            if node is None:
                node = self.driver.get_available_nodes(refresh=True)[0]
                LOG.debug('No node specified, defaulting to %s', node,
                          instance=instance)

            try:
                self._build_and_run_instance(context, instance, image, request_spec,
                        decoded_files, admin_password, requested_networks,
                        security_groups, block_device_mapping, node, limits,
                        filter_properties)
            except exception.RescheduledException as e:
                LOG.debug(e.format_message(), instance=instance)
                retry = filter_properties.get('retry', None)
                if not retry:
                    # no retry information, do not reschedule.
                    LOG.debug("Retry info not present, will not reschedule",
                              instance=instance)
                    self._cleanup_allocated_networks(context, instance,
                                                     requested_networks)
                    compute_utils.add_instance_fault_from_exc(context,
                            instance, e, sys.exc_info())
                    self._set_instance_error_state(context, instance)
                    return
                retry['exc'] = traceback.format_exception(*sys.exc_info())
                # NOTE(comstud): Deallocate networks if the driver wants
                # us to do so.
                if self.driver.deallocate_networks_on_reschedule(instance):
                    self._cleanup_allocated_networks(context, instance,
                                                     requested_networks)

                instance.task_state = task_states.SCHEDULING
                instance.save()

                self.compute_task_api.build_instances(context, [instance],
                        image, filter_properties, admin_password,
                        injected_files, requested_networks, security_groups,
                        block_device_mapping)
            except (exception.InstanceNotFound,
                    exception.UnexpectedDeletingTaskStateError):
                msg = 'Instance disappeared during build.'
                LOG.debug(msg, instance=instance)
                self._cleanup_allocated_networks(context, instance,
                                                 requested_networks)
            except exception.BuildAbortException as e:
                LOG.exception(e.format_message(), instance=instance)
                self._cleanup_allocated_networks(context, instance,
                                                 requested_networks)
                self._cleanup_volumes(context, instance.uuid,
                                      block_device_mapping, raise_exc=False)
                compute_utils.add_instance_fault_from_exc(context, instance,
                                                          e, sys.exc_info())
                self._set_instance_error_state(context, instance)
            except Exception as e:
                # Should not reach here.
                msg = _LE('Unexpected build failure, not rescheduling build.')
                LOG.exception(msg, instance=instance)
                self._cleanup_allocated_networks(context, instance,
                                                 requested_networks)
                self._cleanup_volumes(context, instance.uuid,
                                      block_device_mapping, raise_exc=False)
                compute_utils.add_instance_fault_from_exc(context, instance,
                                                          e, sys.exc_info())
                self._set_instance_error_state(context, instance)

        do_build_and_run_instance(context, instance, image, request_spec,
                filter_properties, admin_password, injected_files,
                requested_networks, security_groups, block_device_mapping,
                node, limits)

    def _build_and_run_instance(self, context, instance, image, request_spec,
                                injected_files, admin_password, requested_networks,
                                security_groups, block_device_mapping, node, limits,
                                filter_properties):

        image_name = image.get('name')
        self._notify_about_instance_usage(context, instance, 'create.start',
                                          extra_usage_info={'image_name': image_name})
        try:
            rt = self._get_resource_tracker(node)
            with rt.instance_claim(context, instance, limits):
                # NOTE(russellb) It's important that this validation be done
                # *after* the resource tracker instance claim, as that is where
                # the host is set on the instance.
                self._validate_instance_group_policy(context, instance,
                                                     filter_properties)
                with self._build_resources(context, instance,
                                           requested_networks, security_groups, image,
                                           block_device_mapping) as resources:
                    instance.vm_state = vm_states.BUILDING
                    instance.task_state = task_states.SPAWNING
                    instance.save(expected_task_state=
                                  task_states.BLOCK_DEVICE_MAPPING)
                    block_device_info = resources['block_device_info']
                    network_info = resources['network_info']
                    cascaded_ports = resources['cascaded_ports']
                    request_spec['block_device_mapping'] = block_device_mapping
                    request_spec['security_group'] = security_groups
                    self._proxy_run_instance(context,
                                             instance,
                                             request_spec,
                                             filter_properties,
                                             requested_networks,
                                             injected_files,
                                             admin_password,
                                             None,
                                             node,
                                             None,
                                             cascaded_ports)

                    # self.driver.spawn(context, instance, image,
                    #                   injected_files, admin_password,
                    #                   network_info=network_info,
                    #                   block_device_info=block_device_info)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError) as e:
            with excutils.save_and_reraise_exception():
                self._notify_about_instance_usage(context, instance,
                                                  'create.end', fault=e)
        except exception.ComputeResourcesUnavailable as e:
            LOG.debug(e.format_message(), instance=instance)
            self._notify_about_instance_usage(context, instance,
                                              'create.error', fault=e)
            raise exception.RescheduledException(
                instance_uuid=instance.uuid, reason=e.format_message())
        except exception.BuildAbortException as e:
            with excutils.save_and_reraise_exception():
                LOG.debug(e.format_message(), instance=instance)
                self._notify_about_instance_usage(context, instance,
                                                  'create.error', fault=e)
        except (exception.FixedIpLimitExceeded,
                exception.NoMoreNetworks) as e:
            LOG.warn(_LW('No more network or fixed IP to be allocated'),
                     instance=instance)
            self._notify_about_instance_usage(context, instance,
                                              'create.error', fault=e)
            msg = _('Failed to allocate the network(s) with error %s, '
                    'not rescheduling.') % e.format_message()
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)
        except (exception.VirtualInterfaceCreateException,
                exception.VirtualInterfaceMacAddressException) as e:
            LOG.exception(_LE('Failed to allocate network(s)'),
                          instance=instance)
            self._notify_about_instance_usage(context, instance,
                                              'create.error', fault=e)
            msg = _('Failed to allocate the network(s), not rescheduling.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)
        except (exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.ImageNotActive,
                exception.ImageUnacceptable) as e:
            self._notify_about_instance_usage(context, instance,
                                              'create.error', fault=e)
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=e.format_message())
        except Exception as e:
            self._notify_about_instance_usage(context, instance,
                                              'create.error', fault=e)
            raise exception.RescheduledException(
                instance_uuid=instance.uuid, reason=six.text_type(e))

        # NOTE(alaski): This is only useful during reschedules, remove it now.
        #instance.system_metadata.pop('network_allocated', None)

        #instance.power_state = self._get_power_state(context, instance)
        #instance.vm_state = vm_states.ACTIVE
        #instance.task_state = None
        #instance.launched_at = timeutils.utcnow()

        #try:
        #    instance.save(expected_task_state=task_states.SPAWNING)
        #except (exception.InstanceNotFound,
        #        exception.UnexpectedDeletingTaskStateError) as e:
        #    with excutils.save_and_reraise_exception():
        #        self._notify_about_instance_usage(context, instance,
        #                                          'create.end', fault=e)

        #self._notify_about_instance_usage(context, instance, 'create.end',
        #                                  extra_usage_info={'message': _('Success')},
        #                                  network_info=network_info)

    def _proxy_run_instance(self, context, instance, request_spec=None, filter_properties=None,
                            requested_networks=None, injected_files=None, admin_password=None,
                            is_first_time=False, node=None, legacy_bdm_in_spec=True,
                            physical_ports=None):
        cascaded_nova_cli = self._get_nova_python_client(context)
        nicsList = []
        for port in physical_ports:
            nicsList.append({'port-id': port['port']['id']})
        #        for net in requested_networks:
        #            nicsList.append({'net-id':net[0]})
        metadata = request_spec['instance_properties']['metadata']
        # metadata['mapping_uuid'] = instance['uuid']

        try:
            instance_type = request_spec['instance_type']
            flavor_name = instance_type['name']
            active_flavor = flavor_obj.Flavor.get_by_name(context, flavor_name)
            active_flavor._load_projects(context)
            instance_type['projects'] = active_flavor.projects
            instance_type['is_public'] = active_flavor.is_public
            self._heal_syn_flavor_info(context, instance_type)
        except Exception:
            pass

        if instance['key_name'] is not None:
            self._heal_syn_keypair_info(context, instance)

        availability_zone_info = \
            request_spec['instance_properties']['availability_zone']
        force_hosts = filter_properties.get('force_hosts')
        if force_hosts and len(force_hosts) > 0:
            availability_zone_info = availability_zone_info + \
                                     ":" + force_hosts[0]

        files = {}
        if injected_files is not None:
            for injected_file in injected_files:
                file_path = injected_file[0]
                context = injected_file[1]
                files[file_path] = context

        image_uuid = None
        if 'id' in request_spec['image']:
            if cfg.CONF.cascaded_glance_flag:
                image_uuid = self._get_cascaded_image_uuid(
                    context,
                    request_spec['image']['id'])
            else:
                image_uuid = request_spec['image']['id']

        try:
            block_device_mapping_v2_lst = None
            block_device_mapping = request_spec['block_device_mapping']
            for block_device_mapping_value in block_device_mapping:
                if block_device_mapping_value['source_type'] == 'volume':
                    proxy_volume_id = None
                    bdm = block_device_obj.BlockDeviceMapping.get_by_volume_id(
                        context, block_device_mapping_value['volume_id'])
                    driver_bdm = \
                        driver_block_device.DriverVolumeBlockDevice(bdm)
                    try:
                        if driver_bdm['mount_device'] is None:
                            mount_point = '/dev/vda'
                        else:
                            mount_point = driver_bdm['mount_device']
                        self.volume_api.attach(context, bdm.volume_id,
                                               instance['uuid'], mount_point)
                    except Exception:
                        with excutils.save_and_reraise_exception():
                            self.volume_api.detach(context.elevated(),
                                                   bdm.volume_id)
                            bdm.destroy(context)
                    try:
                        volume_response = self.volume_api.get(
                            context,
                            block_device_mapping_value['volume_id'])
                        proxy_volume_id = \
                            volume_response['volume_metadata']['mapping_uuid']
                    except Exception:
                        with excutils.save_and_reraise_exception():
                            LOG.error(_('Failed to get  physical volume id ,'
                                        'logical volume id %s,device %s'),
                                      block_device_mapping_value['volume_id'],
                                      block_device_mapping_value['device_name'])
                    if proxy_volume_id is None:
                        LOG.error(_('Can not find physical volume'
                                    ' id %s in physical opensack lay,'
                                    'logical volume id %s'),
                                  instance['uuid'],
                                  block_device_mapping_value['volume_id'])
                        return

                    block_device_mapping_v2_value = {}
                    block_device_mapping_v2_value['uuid'] = proxy_volume_id
                    block_device_mapping_v2_value['boot_index'] = \
                        block_device_mapping_value['boot_index']
                    block_device_mapping_v2_value['volume_size'] = \
                        block_device_mapping_value['volume_size']
                    block_device_mapping_v2_value['source_type'] = \
                        block_device_mapping_value['source_type']
                    block_device_mapping_v2_value['destination_type'] = \
                        block_device_mapping_value['destination_type']
                    block_device_mapping_v2_value['delete_on_termination'] = \
                        block_device_mapping_value['delete_on_termination']
                    block_device_mapping_v2_value['device_name'] = \
                        block_device_mapping_value['device_name']
                    block_device_mapping_v2_lst = \
                        [block_device_mapping_v2_value]
                    LOG.info(_("block_device_mapping_v2_value is:%s")
                             % block_device_mapping_v2_value)
                    break
            _name = request_spec['instance_properties']['display_name']
            csd_name = ComputeManager._gen_csd_instance_name(_name, instance)
            response = cascaded_nova_cli.servers.create(
                name=csd_name,
                image=image_uuid,
                flavor=request_spec['instance_type']['flavorid'],
                meta=metadata,
                key_name=request_spec['instance_properties']['key_name'],
                security_groups=request_spec['security_group'],
                userdata=request_spec['instance_properties']['user_data'],
                block_device_mapping_v2=block_device_mapping_v2_lst,
                scheduler_hints=filter_properties['scheduler_hints'],
                nics=nicsList,
                files=files,
                availability_zone=availability_zone_info)
            # save the cascaded instance uuid
            self._uuid_mapping[instance['uuid']] = {
                'mapping_id': response.id,
                'metadata': response.metadata,
            }
            # self._instance_update(context, instance['uuid'],
            #                       vm_state=vm_states.BUILDING,
            #                       mapping_uuid=response.id,
            #                       task_state=None)
        except Exception:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to create server for instance.'),
                          instance=instance)
                self._set_instance_error_state(context, instance)


    @contextlib.contextmanager
    def _build_resources(self, context, instance, requested_networks,
                         security_groups, image, block_device_mapping):
        resources = {}
        network_info = None
        try:
            network_info = self._build_networks_for_instance(context, instance,
                                                             requested_networks, security_groups)
            resources['network_info'] = network_info
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            raise
        except exception.UnexpectedTaskStateError as e:
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=e.format_message())
        except Exception:
            # Because this allocation is async any failures are likely to occur
            # when the driver accesses network_info during spawn().
            LOG.exception(_LE('Failed to allocate network(s)'),
                          instance=instance)
            msg = _('Failed to allocate the network(s), not rescheduling.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)

        try:
            # Verify that all the BDMs have a device_name set and assign a
            # default to the ones missing it with the help of the driver.
            self._default_block_device_names(context, instance, image,
                                             block_device_mapping)

            instance.vm_state = vm_states.BUILDING
            instance.task_state = task_states.BLOCK_DEVICE_MAPPING
            instance.save()

            #block_device_info = self._prep_block_device(context, instance,
            #                                            block_device_mapping)
            resources['block_device_info'] = None
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            with excutils.save_and_reraise_exception() as ctxt:
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
        except exception.UnexpectedTaskStateError as e:
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=e.format_message())
        except Exception:
            LOG.exception(_LE('Failure prepping block device'),
                          instance=instance)
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            msg = _('Failure prepping block device.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)

        try:
            #get cascaded_ports
            #cascaded_ports = []
            self._heal_proxy_networks(context, instance, network_info)
            cascaded_ports = self._heal_proxy_ports(context, instance,
                                                    network_info)
            resources['cascaded_ports'] = cascaded_ports
            # Note(lizm) send port info to neutron
            ports = {"ports":{}}
            socket_dir = '/var/l2proxysock'
            if not os.path.exists(socket_dir):
                LOG.debug("socket file is not exist!")
                raise
            else:
                retry = 5
                cas_ports = [cas_port_id["port"]["id"] for cas_port_id in cascaded_ports]
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                for i in xrange(retry):
                    try:
                        sock.connect(socket_dir)
                        time.sleep(1)
                        ports["ports"]["add"] = cas_ports
                        LOG.debug("csa port is %s",ports)
                        ports_data = jsonutils.dumps(ports)
                        sock.send(str(ports_data))
                    except socket.error:
                        LOG.debug("socket error! continue")
                        sock.close()
                        raise
                sock.close()
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                LOG.exception(_LE('Instance failed to get cascaded ports'),
                              instance=instance)

        try:
            yield resources
        except Exception as exc:
            with excutils.save_and_reraise_exception() as ctxt:
                if not isinstance(exc, (exception.InstanceNotFound,
                                        exception.UnexpectedDeletingTaskStateError)):
                    LOG.exception(_LE('Instance failed to spawn'),
                                  instance=instance)
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
                try:
                    self._shutdown_instance(context, instance,
                                            block_device_mapping, requested_networks,
                                            try_deallocate_networks=False)
                except Exception:
                    ctxt.reraise = False
                    msg = _('Could not clean up failed build,'
                            ' not rescheduling')
                    raise exception.BuildAbortException(
                        instance_uuid=instance.uuid, reason=msg)

    def _cleanup_allocated_networks(self, context, instance,
                                    requested_networks):
        try:
            self._deallocate_network(context, instance, requested_networks)
        except Exception:
            msg = _LE('Failed to deallocate networks')
            LOG.exception(msg, instance=instance)
            return

        instance.system_metadata['network_allocated'] = 'False'
        try:
            instance.save()
        except exception.InstanceNotFound:
            # NOTE(alaski): It's possible that we're cleaning up the networks
            # because the instance was deleted.  If that's the case then this
            # exception will be raised by instance.save()
            pass

    @object_compat
    @messaging.expected_exceptions(exception.BuildAbortException,
                                   exception.UnexpectedTaskStateError,
                                   exception.VirtualInterfaceCreateException,
                                   exception.RescheduledException)
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def run_instance(self, context, instance, request_spec,
                     filter_properties, requested_networks,
                     injected_files, admin_password,
                     is_first_time, node, legacy_bdm_in_spec):
        # NOTE(alaski) This method should be deprecated when the scheduler and
        # compute rpc interfaces are bumped to 4.x, and slated for removal in
        # 5.x as it is no longer used.

        if filter_properties is None:
            filter_properties = {}

        @utils.synchronized(instance.uuid)
        def do_run_instance():
            self._run_instance(context, request_spec,
                               filter_properties, requested_networks, injected_files,
                               admin_password, is_first_time, node, instance,
                               legacy_bdm_in_spec)
        do_run_instance()

    def _try_deallocate_network(self, context, instance,
                                requested_networks=None):
        try:
            # tear down allocated network structure
            self._deallocate_network(context, instance, requested_networks)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to deallocate network for instance.'),
                          instance=instance)
                self._set_instance_error_state(context, instance)

    def _get_power_off_values(self, context, instance, clean_shutdown):
        """Get the timing configuration for powering down this instance."""
        if clean_shutdown:
            timeout = compute_utils.get_value_from_system_metadata(instance,
                                                                   key='image_os_shutdown_timeout', type=int,
                                                                   default=CONF.shutdown_timeout)
            retry_interval = self.SHUTDOWN_RETRY_INTERVAL
        else:
            timeout = 0
            retry_interval = 0

        return timeout, retry_interval

    def _power_off_instance(self, context, instance, clean_shutdown=True):
        """Power off an instance on this host."""
        timeout, retry_interval = self._get_power_off_values(context,
                                                             instance, clean_shutdown)
        self.driver.power_off(instance, timeout, retry_interval)

    def _shutdown_instance(self, context, instance,
                           bdms, requested_networks=None, notify=True,
                           try_deallocate_networks=True):
        """Shutdown an instance on this host.

        :param:context: security context
        :param:instance: a nova.objects.Instance object
        :param:bdms: the block devices for the instance to be torn
                     down
        :param:requested_networks: the networks on which the instance
                                   has ports
        :param:notify: true if a final usage notification should be
                       emitted
        :param:try_deallocate_networks: false if we should avoid
                                        trying to teardown networking
        """
        context = context.elevated()
        LOG.audit(_('%(action_str)s instance') % {'action_str': 'Terminating'},
                  context=context, instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.start")

        network_info = compute_utils.get_nw_info_for_instance(instance)

        # NOTE(vish) get bdms before destroying the instance
        vol_bdms = [bdm for bdm in bdms if bdm.is_volume]
        # block_device_info = self._get_instance_block_device_info(
        #     context, instance, bdms=bdms)

        # NOTE(melwitt): attempt driver destroy before releasing ip, may
        #                want to keep ip allocated for certain failures
        try:
            self._delete_proxy_instance(context, instance)
            # self.driver.destroy(context, instance, network_info,
            #                     block_device_info)
        except exception.InstancePowerOffFailure:
            # if the instance can't power off, don't release the ip
            with excutils.save_and_reraise_exception():
                pass
        except Exception:
            with excutils.save_and_reraise_exception():
                # deallocate ip and fail without proceeding to
                # volume api calls, preserving current behavior
                if try_deallocate_networks:
                    self._try_deallocate_network(context, instance,
                                                 requested_networks)

        if try_deallocate_networks:
            self._try_deallocate_network(context, instance, requested_networks)

        for bdm in vol_bdms:
            try:
                # NOTE(vish): actual driver detach done in driver.destroy, so
                #             just tell cinder that we are done with it.
                #connector = self.driver.get_volume_connector(instance)
                #self.volume_api.terminate_connection(context,
                #                                     bdm.volume_id,
                #                                     connector)
                self.volume_api.detach(context, bdm.volume_id)
            except exception.DiskNotFound as exc:
                LOG.debug('Ignoring DiskNotFound: %s', exc,
                          instance=instance)
            except exception.VolumeNotFound as exc:
                LOG.debug('Ignoring VolumeNotFound: %s', exc,
                          instance=instance)
            except cinder_exception.EndpointNotFound as exc:
                LOG.warn(_LW('Ignoring EndpointNotFound: %s'), exc,
                         instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.end")

    def _cleanup_volumes(self, context, instance_uuid, bdms, raise_exc=True):
        exc_info = None

        for bdm in bdms:
            LOG.debug("terminating bdm %s", bdm,
                      instance_uuid=instance_uuid)
            if bdm.volume_id and bdm.delete_on_termination:
                try:
                    self.volume_api.delete(context, bdm.volume_id)
                except Exception as exc:
                    exc_info = sys.exc_info()
                    LOG.warn(_LW('Failed to delete volume: %(volume_id)s due '
                                 'to %(exc)s'), {'volume_id': bdm.volume_id,
                                                 'exc': unicode(exc)})
        if exc_info is not None and raise_exc:
            six.reraise(exc_info[0], exc_info[1], exc_info[2])

    @periodic_task.periodic_task(
            spacing=CONF.running_deleted_instance_poll_interval)
    def _cleanup_running_deleted_instances(self, context):
        sync_nova_client = self.sync_nova_client

        with utils.temporary_mutation(context, read_deleted="yes"):
            for instance in self._running_deleted_instances(context):
                csd_instance_uuid = self._get_csd_instance_uuid(instance)
                if not csd_instance_uuid:
                    continue
                LOG.debug(_('Get cascaded instance %s that should be deleted'),
                          csd_instance_uuid)
                try:
                    csd_instance = sync_nova_client.servers.get(csd_instance_uuid)
                    if csd_instance._info['OS-EXT-STS:vm_state'] != 'deleted':
                        sync_nova_client.servers.delete(csd_instance)
                        self._uuid_mapping.pop(instance.uuid, {})
                        LOG.debug(_('delete the cascaded instance %s in'
                                    'periodic_task'), csd_instance.id)
                except Exception:
                    pass

    def _running_deleted_instances(self, context):
        """Returns a list of instances nova thinks is deleted,
        but the hypervisor thinks is still running.
        """
        timeout = CONF.running_deleted_instance_timeout
        filters = {'deleted': True,
                   'soft_deleted': False,
                   # 'host': self.host
                  }
        instances = self._get_instances_on_db(context, filters)
        return [i for i in instances if self._deleted_old_enough(i, timeout)]

    def _deleted_old_enough(self, instance, timeout):
        deleted_at = instance['deleted_at']
        if isinstance(instance, obj_base.NovaObject) and deleted_at:
            deleted_at = deleted_at.replace(tzinfo=None)
        return (not deleted_at or timeutils.is_older_than(deleted_at, timeout))

    def _get_instances_on_db(self, context, filters):

        return objects.InstanceList.get_by_filters(context, filters,
                                                   use_slave=True)

    @hooks.add_hook("delete_instance")
    def _delete_instance(self, context, instance, bdms, quotas):
        """Delete an instance on this host.  Commit or rollback quotas
        as necessary.
        """
        instance_uuid = instance['uuid']

        was_soft_deleted = instance['vm_state'] == vm_states.SOFT_DELETED
        if was_soft_deleted:
            # Instances in SOFT_DELETED vm_state have already had quotas
            # decremented.
            try:
                quotas.rollback()
            except Exception:
                pass

        try:
            events = self.instance_events.clear_events_for_instance(instance)
            if events:
                LOG.debug('Events pending at deletion: %(events)s',
                          {'events': ','.join(events.keys())},
                          instance=instance)
            instance.info_cache.delete()
            self._notify_about_instance_usage(context, instance,
                                              "delete.start")
            self._shutdown_instance(context, instance, bdms)
            # NOTE(vish): We have already deleted the instance, so we have
            #             to ignore problems cleaning up the volumes. It
            #             would be nice to let the user know somehow that
            #             the volume deletion failed, but it is not
            #             acceptable to have an instance that can not be
            #             deleted. Perhaps this could be reworked in the
            #             future to set an instance fault the first time
            #             and to only ignore the failure if the instance
            #             is already in ERROR.
            self._cleanup_volumes(context, instance_uuid, bdms,
                                  raise_exc=False)
            # if a delete task succeed, always update vm state and task
            # state without expecting task state to be DELETING
            instance.vm_state = vm_states.DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            instance.save()
            self._update_resource_tracker(context, instance)
            system_meta = instance.system_metadata
            instance.destroy()
        except Exception:
            with excutils.save_and_reraise_exception():
                quotas.rollback()

        self._complete_deletion(context,
                                instance,
                                bdms,
                                quotas,
                                system_meta)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def terminate_instance(self, context, instance, bdms, reservations):
        """Terminate an instance on this host."""
        # NOTE (ndipanov): If we get non-object BDMs, just get them from the
        # db again, as this means they are sent in the old format and we want
        # to avoid converting them back when we can just get them.
        # Remove this when we bump the RPC major version to 4.0
        if (bdms and
                any(not isinstance(bdm, obj_base.NovaObject)
                    for bdm in bdms)):
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        quotas = objects.Quotas.from_reservations(context,
                                                  reservations,
                                                  instance=instance)

        @utils.synchronized(instance['uuid'])
        def do_terminate_instance(instance, bdms):
            try:
                self._delete_instance(context, instance, bdms, quotas)
                self._uuid_mapping.pop(instance['uuid'], {})
            except exception.InstanceNotFound:
                LOG.info(_("Instance disappeared during terminate"),
                         instance=instance)
            except Exception:
                # As we're trying to delete always go to Error if something
                # goes wrong that _delete_instance can't handle.
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE('Setting instance vm_state to ERROR'),
                                  instance=instance)
                    self._set_instance_error_state(context, instance)

        do_terminate_instance(instance, bdms)

    # NOTE(johannes): This is probably better named power_off_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def stop_instance(self, context, instance, clean_shutdown=True):
        """Stopping an instance on this host."""

        @utils.synchronized(instance.uuid)
        def do_stop_instance():
            current_power_state = self._get_power_state(context, instance)
            LOG.debug('Stopping instance; current vm_state: %(vm_state)s, '
                      'current task_state: %(task_state)s, current DB '
                      'power_state: %(db_power_state)s, current VM '
                      'power_state: %(current_power_state)s',
                      dict(vm_state=instance.vm_state,
                           task_state=instance.task_state,
                           db_power_state=instance.power_state,
                           current_power_state=current_power_state),
                      instance_uuid=instance.uuid)

            # NOTE(mriedem): If the instance is already powered off, we are
            # possibly tearing down and racing with other operations, so we can
            # expect the task_state to be None if something else updates the
            # instance and we're not locking it.
            # expected_task_state = [task_states.POWERING_OFF]
            # The list of power states is from _sync_instance_power_state.
            if current_power_state in (power_state.NOSTATE,
                                       power_state.SHUTDOWN,
                                       power_state.CRASHED):
                LOG.info(_LI('Instance is already powered off in the '
                             'hypervisor when stop is called.'),
                         instance=instance)
                # expected_task_state.append(None)

            self._notify_about_instance_usage(context, instance,
                                              "power_off.start")
            cascaded_instance_id = self._get_csd_instance_uuid(instance)
            if cascaded_instance_id is None:
                LOG.error(_LE('stop vm failed,can not find server'
                            ' in cascaded layer.'),
                          instance['uuid'])
                return
            cascaded_nova_cli = self._get_nova_python_client(context)
            cascaded_nova_cli.servers.stop(cascaded_instance_id)
            self._notify_about_instance_usage(context, instance,
                                              "power_off.end")

        do_stop_instance()

    def _power_on(self, context, instance):
        network_info = self._get_instance_nw_info(context, instance)
        block_device_info = self._get_instance_block_device_info(context,
                                                                 instance)
        self.driver.power_on(context, instance,
                             network_info,
                             block_device_info)

    # NOTE(johannes): This is probably better named power_on_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def start_instance(self, context, instance):
        """Starting an instance on this host."""
        self._notify_about_instance_usage(context, instance, "power_on.start")
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        ' in cascaded layer.'), instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        cascaded_nova_cli.servers.start(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, "power_on.end")

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def soft_delete_instance(self, context, instance, reservations):
        """Soft delete an instance on this host."""

        quotas = objects.Quotas.from_reservations(context,
                                                  reservations,
                                                  instance=instance)
        try:
            self._notify_about_instance_usage(context, instance,
                                              "soft_delete.start")
            try:
                self.driver.soft_delete(instance)
            except NotImplementedError:
                # Fallback to just powering off the instance if the
                # hypervisor doesn't implement the soft_delete method
                self.driver.power_off(instance)
            current_power_state = self._get_power_state(context, instance)
            instance.power_state = current_power_state
            instance.vm_state = vm_states.SOFT_DELETED
            instance.task_state = None
            instance.save(expected_task_state=[task_states.SOFT_DELETING])
        except Exception:
            with excutils.save_and_reraise_exception():
                quotas.rollback()
        quotas.commit()
        self._notify_about_instance_usage(context, instance, "soft_delete.end")

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def restore_instance(self, context, instance):
        """Restore a soft-deleted instance on this host."""
        self._notify_about_instance_usage(context, instance, "restore.start")
        try:
            self.driver.restore(instance)
        except NotImplementedError:
            # Fallback to just powering on the instance if the hypervisor
            # doesn't implement the restore method
            self._power_on(context, instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=task_states.RESTORING)
        self._notify_about_instance_usage(context, instance, "restore.end")

    @object_compat
    @messaging.expected_exceptions(exception.PreserveEphemeralNotSupported)
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate, on_shared_storage,
                         preserve_ephemeral=False):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance: Instance object
        :param orig_image_ref: Original image_ref before rebuild
        :param image_ref: New image_ref for rebuild
        :param injected_files: Files to inject
        :param new_pass: password to set on rebuilt instance
        :param orig_sys_metadata: instance system metadata from pre-rebuild
        :param bdms: block-device-mappings to use for rebuild
        :param recreate: True if the instance is being recreated (e.g. the
            hypervisor it was on failed) - cleanup of old state will be
            skipped.
        :param on_shared_storage: True if instance files on shared storage
        :param preserve_ephemeral: True if the default ephemeral storage
                                   partition must be preserved on rebuild
        """

        if (bdms and
                any(not isinstance(bdm, obj_base.NovaObject)
                    for bdm in bdms)):
            bdms = None

        if bdms is None:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        #cascading patch
        context = context.elevated()
        with self._error_out_instance_on_exception(context, instance):
            LOG.audit(_("Rebuilding instance"), context=context,
                      instance=instance)
            # if bdms is None:
            #     bdms = self.conductor_api. \
            #         block_device_mapping_get_all_by_instance(
            #         context, instance)
            # NOTE(sirp): this detach is necessary b/c we will reattach the
            # volumes in _prep_block_devices below.
            # for bdm in bdms:
            #     self.volume_api.detach(context, bdm['volume_id'])

            kwargs = {}
            disk_config = None
            if len(injected_files) > 0:
                kwargs['personality'] = injected_files
            cascaded_instance_id = self._get_csd_instance_uuid(instance)
            if cascaded_instance_id is None:
                LOG.error(_('Rebuild failed,can not find server %s '),
                          instance['uuid'])
                return
            if cfg.CONF.cascaded_glance_flag:
                image_uuid = ComputeManager._get_cascaded_image_uuid(context,
                                                                image_ref)
            else:
                image_uuid = image_ref
            rebuild_name = self._gen_csd_instance_name(instance['display_name'],
                                                       instance)
            cascaded_nova_cli = self._get_nova_python_client(context)
            cascaded_nova_cli.servers.rebuild(cascaded_instance_id, image_uuid,
                                              password=new_pass,
                                              disk_config=disk_config,
                                              preserve_ephemeral=preserve_ephemeral,
                                              name=rebuild_name,
                                              **kwargs)

    def _heal_syn_server_metadata(self, context,
                                  cascading_ins_id, cascaded_ins_id):
        """
        when only reboots the server scenario,
        needs to synchronize server metadata between
        logical and physical openstack.
        """
        cascaded_nova_cli = self._get_nova_python_client(context)
        cascaded_ser_inf = cascaded_nova_cli.servers.get(cascaded_ins_id)
        cascaded_ser_med_inf = cascaded_ser_inf.metadata

        cascading_nov_cli = self._get_csg_python_client(context)
        cascading_ser_inf = cascading_nov_cli.servers.get(cascading_ins_id)
        cascading_ser_med_inf = cascading_ser_inf.metadata

        tmp_csd_meta_inf = dict(cascaded_ser_med_inf)
        # del tmp_csd_meta_inf['mapping_uuid']

        if tmp_csd_meta_inf == cascading_ser_med_inf:
            LOG.debug(_("Don't need to synchronize server metadata between"
                        "logical and physical openstack."))
            return
        else:
            LOG.debug(_('synchronize server metadata between logical and'
                        'physical openstack,cascadingSerMedInf %s,cascadedSerMedInf %s'),
                      cascading_ser_med_inf,
                      cascaded_ser_med_inf)
            del_keys = []
            for key in cascaded_ser_med_inf:
                if key not in cascading_ser_med_inf:
                    del_keys.append(key)
            if len(del_keys) > 0:
                cascaded_nova_cli.servers.delete_meta(cascaded_ins_id, del_keys)
            # cascading_ser_med_inf['mapping_uuid'] = \
            #     cascaded_ser_med_inf['mapping_uuid']
            cascaded_nova_cli.servers.set_meta(cascaded_ins_id,
                                               cascading_ser_med_inf)


    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def reboot_instance(self, context, instance, block_device_info,
                        reboot_type):
        """Reboot an instance on this host."""
        #cascading patch
        self._notify_about_instance_usage(context, instance, "reboot.start")
        context = context.elevated()
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('Reboot can not find server %s.'), instance)
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        try:
            # self._heal_syn_server_metadata(context, instance['uuid'],
            #                                          cascaded_instance_id)
            self._heal_instance_metadata(instance['uuid'], instance['metadata'])

            self._sync_instance_flavor(context, instance)

            cascaded_nova_cli.servers.reboot(cascaded_instance_id, reboot_type)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to reboot server %s .'),
                          cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, "reboot.end")

    @delete_image_on_error
    def _do_snapshot_instance(self, context, image_id, instance, rotation):
        if rotation < 0:
            raise exception.RotationRequiredForBackup()
        self._snapshot_instance(context, image_id, instance,
                                task_states.IMAGE_BACKUP)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    @delete_image_on_error
    def snapshot_instance(self, context, image_id, instance):
        """Snapshot an instance on this host.

        :param context: security context
        :param instance: a nova.objects.instance.Instance object
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        """
        # NOTE(dave-mcnally) the task state will already be set by the api
        # but if the compute manager has crashed/been restarted prior to the
        # request getting here the task state may have been cleared so we set
        # it again and things continue normally
        #cascading patch
        glanceClient = glance.GlanceClientWrapper()
        image = glanceClient.call(context, 2, 'get', image_id)

        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('can not snapshot instance server %s.'),
                      instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        resp_image_id = cascaded_nova_cli.servers.create_image(
            cascaded_instance_id,
            image['name'])
        # update image's location
        url = '%s/v2/images/%s' % (CONF.cascaded_glance_url, resp_image_id)
        locations = [{
                         'url': url,
                         'metadata': {
                             'image_id': str(resp_image_id),
                             'image_from': 'snapshot'
                         }
                     }]
        glanceClient.call(context, 2, 'update', image_id,
                          remove_props=None, locations=locations)
        LOG.debug(_('Finish update image %s locations %s'),
                  image_id, locations)

    def _snapshot_instance(self, context, image_id, instance,
                           expected_task_state):
        context = context.elevated()

        current_power_state = self._get_power_state(context, instance)
        try:
            instance.power_state = current_power_state
            instance.save()

            LOG.audit(_('instance snapshotting'), context=context,
                      instance=instance)

            if instance.power_state != power_state.RUNNING:
                state = instance.power_state
                running = power_state.RUNNING
                LOG.warn(_('trying to snapshot a non-running instance: '
                           '(state: %(state)s expected: %(running)s)'),
                         {'state': state, 'running': running},
                         instance=instance)

            self._notify_about_instance_usage(
                context, instance, "snapshot.start")

            def update_task_state(task_state,
                                  expected_state=expected_task_state):
                instance.task_state = task_state
                instance.save(expected_task_state=expected_state)

            self.driver.snapshot(context, instance, image_id,
                                 update_task_state)

            instance.task_state = None
            instance.save(expected_task_state=task_states.IMAGE_UPLOADING)

            self._notify_about_instance_usage(context, instance,
                                              "snapshot.end")
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            # the instance got deleted during the snapshot
            # Quickly bail out of here
            msg = 'Instance disappeared during snapshot'
            LOG.debug(msg, instance=instance)
            try:
                image_service = glance.get_default_image_service()
                image = image_service.show(context, image_id)
                if image['status'] != 'active':
                    image_service.delete(context, image_id)
            except Exception:
                LOG.warning(_("Error while trying to clean up image %s"),
                            image_id, instance=instance)
        except exception.ImageNotFound:
            instance.task_state = None
            instance.save()
            msg = _("Image not found during snapshot")
            LOG.warn(msg, instance=instance)

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def set_admin_password(self, context, instance, new_pass):
        """Set the root/admin password for an instance on this host.

        This is generally only called by API password resets after an
        image has been built.

        @param context: Nova auth context.
        @param instance: Nova instance object.
        @param new_pass: The admin password for the instance.
        """

        context = context.elevated()
        if new_pass is None:
            # Generate a random password
            new_pass = utils.generate_password()

        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING

        if current_power_state != expected_state:
            instance.task_state = None
            instance.save(expected_task_state=task_states.UPDATING_PASSWORD)
            _msg = _('Failed to set admin password. Instance %s is not'
                     ' running') % instance.uuid
            raise exception.InstancePasswordSetFailed(
                instance=instance.uuid, reason=_msg)

        try:
            self.driver.set_admin_password(instance, new_pass)
            LOG.audit(_("Root password set"), instance=instance)
            instance.task_state = None
            instance.save(
                expected_task_state=task_states.UPDATING_PASSWORD)
        except NotImplementedError:
            _msg = _('set_admin_password is not implemented '
                     'by this driver or guest instance.')
            LOG.warn(_msg, instance=instance)
            instance.task_state = None
            instance.save(
                expected_task_state=task_states.UPDATING_PASSWORD)
            raise NotImplementedError(_msg)
        except exception.UnexpectedTaskStateError:
            # interrupted by another (most likely delete) task
            # do not retry
            raise
        except Exception as e:
            # Catch all here because this could be anything.
            LOG.exception(_LE('set_admin_password failed: %s'), e,
                          instance=instance)
            self._set_instance_obj_error_state(context, instance)
            # We create a new exception here so that we won't
            # potentially reveal password information to the
            # API caller.  The real exception is logged above
            _msg = _('error setting admin password')
            raise exception.InstancePasswordSetFailed(
                instance=instance.uuid, reason=_msg)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def inject_file(self, context, path, file_contents, instance):
        """Write a file to the specified path in an instance on this host."""
        # NOTE(russellb) Remove this method, as well as the underlying virt
        # driver methods, when the compute rpc interface is bumped to 4.x
        # as it is no longer used.
        context = context.elevated()
        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING
        if current_power_state != expected_state:
            LOG.warn(_('trying to inject a file into a non-running (state: '
                       '%(current_state)s expected: %(expected_state)s)'),
                     {'current_state': current_power_state,
                      'expected_state': expected_state},
                     instance=instance)
        LOG.audit(_('injecting file to %s'), path,
                  instance=instance)
        self.driver.inject_file(instance, path, file_contents)

    def _get_rescue_image(self, context, instance, rescue_image_ref=None):
        """Determine what image should be used to boot the rescue VM."""
        # 1. If rescue_image_ref is passed in, use that for rescue.
        # 2. Else, use the base image associated with instance's current image.
        #       The idea here is to provide the customer with a rescue
        #       environment which they are familiar with.
        #       So, if they built their instance off of a Debian image,
        #       their rescue VM will also be Debian.
        # 3. As a last resort, use instance's current image.
        if not rescue_image_ref:
            system_meta = utils.instance_sys_meta(instance)
            rescue_image_ref = system_meta.get('image_base_image_ref')

        if not rescue_image_ref:
            LOG.warn(_('Unable to find a different image to use for rescue VM,'
                       ' using instance\'s current image'), instance=instance)
            rescue_image_ref = instance.image_ref

        image_meta = compute_utils.get_image_metadata(context, self.image_api,
                                                      rescue_image_ref,
                                                      instance)
        # NOTE(belliott) bug #1227350 - xenapi needs the actual image id
        image_meta['id'] = rescue_image_ref
        return image_meta

    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def change_instance_metadata(self, context, diff, instance):
        """Update the metadata published to the instance."""
        LOG.debug("Changing instance metadata according to %r",
                  diff, instance=instance)
        self.driver.change_instance_metadata(context, instance, diff)

    def _cleanup_stored_instance_types(self, migration, instance,
                                       restore_old=False):
        """Clean up "old" and "new" instance_type information stored in
        instance's system_metadata. Optionally update the "current"
        instance_type to the saved old one first.

        Returns the updated system_metadata as a dict, the
        post-cleanup current instance type and the to-be dropped
        instance type.
        """
        sys_meta = instance.system_metadata
        if restore_old:
            instance_type = flavors.extract_flavor(instance, 'old_')
            drop_instance_type = flavors.extract_flavor(instance)
            sys_meta = flavors.save_flavor_info(sys_meta, instance_type)
        else:
            instance_type = flavors.extract_flavor(instance)
            drop_instance_type = flavors.extract_flavor(instance, 'old_')

        flavors.delete_flavor_info(sys_meta, 'old_')
        flavors.delete_flavor_info(sys_meta, 'new_')

        return sys_meta, instance_type, drop_instance_type

    @wrap_exception()
    @wrap_instance_event
    @wrap_instance_fault
    def confirm_resize(self, context, instance, reservations, migration):

        quotas = objects.Quotas.from_reservations(context,
                                                  reservations,
                                                  instance=instance)

        @utils.synchronized(instance['uuid'])
        def do_confirm_resize(context, instance, migration_id):
            # NOTE(wangpan): Get the migration status from db, if it has been
            #                confirmed, we do nothing and return here
            LOG.debug("Going to confirm migration %s", migration_id,
                      context=context, instance=instance)
            try:
                # TODO(russellb) Why are we sending the migration object just
                # to turn around and look it up from the db again?
                migration = objects.Migration.get_by_id(
                    context.elevated(), migration_id)
            except exception.MigrationNotFound:
                LOG.error(_("Migration %s is not found during confirmation") %
                          migration_id, context=context, instance=instance)
                quotas.rollback()
                return

            if migration.status == 'confirmed':
                LOG.info(_("Migration %s is already confirmed") %
                         migration_id, context=context, instance=instance)
                quotas.rollback()
                return
            elif migration.status not in ('finished', 'confirming'):
                LOG.warn(_("Unexpected confirmation status '%(status)s' of "
                           "migration %(id)s, exit confirmation process") %
                         {"status": migration.status, "id": migration_id},
                         context=context, instance=instance)
                quotas.rollback()
                return

            # NOTE(wangpan): Get the instance from db, if it has been
            #                deleted, we do nothing and return here
            expected_attrs = ['metadata', 'system_metadata']
            try:
                instance = objects.Instance.get_by_uuid(
                    context, instance.uuid,
                    expected_attrs=expected_attrs)
            except exception.InstanceNotFound:
                LOG.info(_("Instance is not found during confirmation"),
                         context=context, instance=instance)
                quotas.rollback()
                return

            self._confirm_resize(context, instance, quotas,
                                 migration=migration)

        do_confirm_resize(context, instance, migration.id)

    def _confirm_resize(self, context, instance, quotas,
                        migration=None):
        """Destroys the source instance."""
        self._notify_about_instance_usage(context, instance,
                                          "resize.confirm.start")

        with self._error_out_instance_on_exception(context, instance,
                                                   quotas=quotas):
            # NOTE(danms): delete stashed migration information
            sys_meta, instance_type, old_instance_type = (
                self._cleanup_stored_instance_types(migration, instance))
            sys_meta.pop('old_vm_state', None)

            instance.system_metadata = sys_meta
            instance.save()

            # NOTE(tr3buchet): tear down networks on source host
            self.network_api.setup_networks_on_host(context, instance,
                                                    migration.source_compute, teardown=True)

            network_info = self._get_instance_nw_info(context, instance)
            #cascading patch
            cascaded_instance_id = self._get_csd_instance_uuid(instance)
            if cascaded_instance_id is None:
                LOG.debug(_('Confirm resize can not find server %s.'),
                          instance['uuid'])
                return

            cascaded_nova_cli = self._get_nova_python_client(context)
            try:
                cascaded_nova_cli.servers.confirm_resize(cascaded_instance_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to confirm resize server %s .'),
                              cascaded_instance_id)

            #self.driver.confirm_migration(migration, instance, network_info)

            migration.status = 'confirmed'
            migration.save(context.elevated())

            # rt = self._get_resource_tracker(migration.source_node)
            # rt.drop_resize_claim(context, instance, old_instance_type)

            # NOTE(mriedem): The old_vm_state could be STOPPED but the user
            # might have manually powered up the instance to confirm the
            # resize/migrate, so we need to check the current power state
            # on the instance and set the vm_state appropriately. We default
            # to ACTIVE because if the power state is not SHUTDOWN, we
            # assume _sync_instance_power_state will clean it up.
            p_state = instance.power_state
            vm_state = None
            if p_state == power_state.SHUTDOWN:
                vm_state = vm_states.STOPPED
                LOG.debug("Resized/migrated instance is powered off. "
                          "Setting vm_state to '%s'.", vm_state,
                          instance=instance)
            else:
                vm_state = vm_states.ACTIVE

            instance.vm_state = vm_state
            instance.task_state = None
            instance.save(expected_task_state=[None, task_states.DELETING])

            self._notify_about_instance_usage(
                context, instance, "resize.confirm.end",
                network_info=network_info)

            quotas.commit()

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def revert_resize(self, context, instance, migration, reservations):
        """Destroys the new instance on the destination machine.

        Reverts the model changes, and powers on the old instance on the
        source machine.

        """

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)

        # NOTE(comstud): A revert_resize is essentially a resize back to
        # the old size, so we need to send a usage event here.
        self.conductor_api.notify_usage_exists(
            context, instance, current_period=True)

        with self._error_out_instance_on_exception(context, instance,
                                                   quotas=quotas):
            # NOTE(tr3buchet): tear down networks on destination host
            self.network_api.setup_networks_on_host(context, instance,
                                                    teardown=True)

            instance_p = obj_base.obj_to_primitive(instance)
            migration_p = obj_base.obj_to_primitive(migration)
            self.network_api.migrate_instance_start(context,
                                                    instance_p,
                                                    migration_p)

            # network_info = self._get_instance_nw_info(context, instance)
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
            # block_device_info = self._get_instance_block_device_info(
            #     context, instance, bdms=bdms)
            #
            # self.driver.destroy(context, instance, network_info,
            #                     block_device_info)

            self._terminate_volume_connections(context, instance, bdms)

            migration.status = 'reverted'
            migration.save(context.elevated())

            rt = self._get_resource_tracker(instance.node)
            rt.drop_resize_claim(context, instance)

            self.compute_rpcapi.finish_revert_resize(context, instance,
                                                     migration, migration.source_compute,
                                                     quotas.reservations)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def finish_revert_resize(self, context, instance, reservations, migration):
        """Finishes the second half of reverting a resize.

        Bring the original source instance state back (active/shutoff) and
        revert the resized attributes in the database.

        """

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)

        with self._error_out_instance_on_exception(context, instance,
                                                   quotas=quotas):
            network_info = self._get_instance_nw_info(context, instance)

            self._notify_about_instance_usage(
                context, instance, "resize.revert.start")

            sys_meta, instance_type, drop_instance_type = (
                self._cleanup_stored_instance_types(migration, instance, True))

            # NOTE(mriedem): delete stashed old_vm_state information; we
            # default to ACTIVE for backwards compatibility if old_vm_state
            # is not set
            old_vm_state = sys_meta.pop('old_vm_state', vm_states.ACTIVE)

            instance.system_metadata = sys_meta
            instance.memory_mb = instance_type['memory_mb']
            instance.vcpus = instance_type['vcpus']
            instance.root_gb = instance_type['root_gb']
            instance.ephemeral_gb = instance_type['ephemeral_gb']
            instance.instance_type_id = instance_type['id']
            instance.host = migration['source_compute']
            instance.node = migration['source_node']
            instance.save()

            self.network_api.setup_networks_on_host(context, instance,
                                                    migration['source_compute'])

            # block_device_info = self._get_instance_block_device_info(
            #     context, instance, refresh_conn_info=True)

            power_on = old_vm_state != vm_states.STOPPED
            # self.driver.finish_revert_migration(context, instance,
            #                                     network_info,
            #                                     block_device_info, power_on)

            #cascading patch
            cascaded_instance_id = self._get_csd_instance_uuid(instance)
            if cascaded_instance_id is None:
                LOG.debug(_('Revert resize can not find server %s.'),
                          instance['uuid'])
                return
            cascaded_nova_cli = self._get_nova_python_client(context)
            try:
                cascaded_nova_cli.servers.revert_resize(cascaded_instance_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to resize server %s .'),
                              cascaded_instance_id)

            instance.launched_at = timeutils.utcnow()
            instance.save(expected_task_state=task_states.RESIZE_REVERTING)

            instance_p = obj_base.obj_to_primitive(instance)
            migration_p = obj_base.obj_to_primitive(migration)
            self.network_api.migrate_instance_finish(context,
                                                     instance_p,
                                                     migration_p)

            # if the original vm state was STOPPED, set it back to STOPPED
            LOG.info(_("Updating instance to original state: '%s'") %
                     old_vm_state)
            if power_on:
                instance.vm_state = vm_states.ACTIVE
                instance.task_state = None
                instance.save()
            else:
                instance.task_state = task_states.POWERING_OFF
                instance.save()
                self.stop_instance(context, instance=instance)

            self._notify_about_instance_usage(
                context, instance, "resize.revert.end")
            quotas.commit()

    def _prep_resize(self, context, image, instance, instance_type,
                     quotas, request_spec, filter_properties, node):

        if not filter_properties:
            filter_properties = {}

        if not instance['host']:
            self._set_instance_error_state(context, instance)
            msg = _('Instance has no source host')
            raise exception.MigrationError(msg)

        same_host = instance['host'] == self.host
        if same_host and not CONF.allow_resize_to_same_host:
            self._set_instance_error_state(context, instance)
            msg = _('destination same as source!')
            raise exception.MigrationError(msg)

        # NOTE(danms): Stash the new instance_type to avoid having to
        # look it up in the database later
        sys_meta = instance.system_metadata
        flavors.save_flavor_info(sys_meta, instance_type, prefix='new_')
        # NOTE(mriedem): Stash the old vm_state so we can set the
        # resized/reverted instance back to the same state later.
        vm_state = instance['vm_state']
        LOG.debug('Stashing vm_state: %s', vm_state, instance=instance)
        sys_meta['old_vm_state'] = vm_state
        instance.save()

        limits = filter_properties.get('limits', {})
        rt = self._get_resource_tracker(node)
        with rt.resize_claim(context, instance, instance_type,
                             image_meta=image, limits=limits) as claim:
            LOG.audit(_('Migrating'), context=context, instance=instance)
            self.compute_rpcapi.resize_instance(
                context, instance, claim.migration, image,
                instance_type, quotas.reservations)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def prep_resize(self, context, image, instance, instance_type,
                    reservations, request_spec, filter_properties, node):
        """Initiates the process of moving a running instance to another host.

        Possibly changes the RAM and disk size in the process.

        """
        if node is None:
            node = self.driver.get_available_nodes(refresh=True)[0]
            LOG.debug("No node specified, defaulting to %s", node,
                      instance=instance)

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)
        with self._error_out_instance_on_exception(context, instance,
                                                   quotas=quotas):
            self.conductor_api.notify_usage_exists(
                context, instance, current_period=True)
            self._notify_about_instance_usage(
                context, instance, "resize.prep.start")
            try:
                self._prep_resize(context, image, instance,
                                  instance_type, quotas,
                                  request_spec, filter_properties,
                                  node)
            # NOTE(dgenin): This is thrown in LibvirtDriver when the
            #               instance to be migrated is backed by LVM.
            #               Remove when LVM migration is implemented.
            except exception.MigrationPreCheckError:
                raise
            except Exception:
                # try to re-schedule the resize elsewhere:
                exc_info = sys.exc_info()
                self._reschedule_resize_or_reraise(context, image, instance,
                                                   exc_info, instance_type, quotas, request_spec,
                                                   filter_properties)
            finally:
                extra_usage_info = dict(
                    new_instance_type=instance_type['name'],
                    new_instance_type_id=instance_type['id'])

                self._notify_about_instance_usage(
                    context, instance, "resize.prep.end",
                    extra_usage_info=extra_usage_info)

    def _reschedule_resize_or_reraise(self, context, image, instance, exc_info,
                                      instance_type, quotas, request_spec, filter_properties):
        """Try to re-schedule the resize or re-raise the original error to
        error out the instance.
        """
        if not request_spec:
            request_spec = {}
        if not filter_properties:
            filter_properties = {}

        rescheduled = False
        instance_uuid = instance['uuid']

        try:
            reschedule_method = self.compute_task_api.resize_instance
            scheduler_hint = dict(filter_properties=filter_properties)
            method_args = (instance, None, scheduler_hint, instance_type,
                           quotas.reservations)
            task_state = task_states.RESIZE_PREP

            rescheduled = self._reschedule(context, request_spec,
                                           filter_properties, instance, reschedule_method,
                                           method_args, task_state, exc_info)
        except Exception as error:
            rescheduled = False
            LOG.exception(_LE("Error trying to reschedule"),
                          instance_uuid=instance_uuid)
            compute_utils.add_instance_fault_from_exc(context,
                                                      instance, error,
                                                      exc_info=sys.exc_info())
            self._notify_about_instance_usage(context, instance,
                                              'resize.error', fault=error)

        if rescheduled:
            self._log_original_error(exc_info, instance_uuid)
            compute_utils.add_instance_fault_from_exc(context,
                                                      instance, exc_info[1], exc_info=exc_info)
            self._notify_about_instance_usage(context, instance,
                                              'resize.error', fault=exc_info[1])
        else:
            # not re-scheduling
            raise exc_info[0], exc_info[1], exc_info[2]

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @errors_out_migration
    @wrap_instance_fault
    def resize_instance(self, context, instance, image,
                        reservations, migration, instance_type,
                        clean_shutdown=True):
        """Starts the migration of a running instance to another host."""

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)
        with self._error_out_instance_on_exception(context, instance,
                                                   quotas=quotas):
            if not instance_type:
                instance_type = objects.Flavor.get_by_id(
                    context, migration['new_instance_type_id'])

            network_info = self._get_instance_nw_info(context, instance)

            migration.status = 'migrating'
            migration.save(context.elevated())

            instance.task_state = task_states.RESIZE_MIGRATING
            instance.save(expected_task_state=task_states.RESIZE_PREP)

            self._notify_about_instance_usage(
                context, instance, "resize.start", network_info=network_info)

            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
            # block_device_info = self._get_instance_block_device_info(
            #     context, instance, bdms=bdms)

            # timeout, retry_interval = self._get_power_off_values(context,
            #         instance, clean_shutdown)
            # disk_info = self.driver.migrate_disk_and_power_off(
            #     context, instance, migration.dest_host,
            #     instance_type, network_info,
            #     block_device_info,
            #     timeout, retry_interval)
            disk_info = None
            self._terminate_volume_connections(context, instance, bdms)

            migration_p = obj_base.obj_to_primitive(migration)
            instance_p = obj_base.obj_to_primitive(instance)
            self.network_api.migrate_instance_start(context,
                                                    instance_p,
                                                    migration_p)

            migration.status = 'post-migrating'
            migration.save(context.elevated())

            instance.host = migration.dest_compute
            instance.node = migration.dest_node
            instance.task_state = task_states.RESIZE_MIGRATED
            instance.save(expected_task_state=task_states.RESIZE_MIGRATING)

            self.compute_rpcapi.finish_resize(context, instance,
                    migration, image, disk_info,
                    migration.dest_compute, reservations=quotas.reservations)

            self._notify_about_instance_usage(context, instance, "resize.end",
                    network_info=network_info)
            self.instance_events.clear_events_for_instance(instance)

    def _terminate_volume_connections(self, context, instance, bdms):
        connector = self.driver.get_volume_connector(instance)
        for bdm in bdms:
            if bdm.is_volume:
                self.volume_api.terminate_connection(context, bdm.volume_id,
                                                     connector)

    @staticmethod
    def _save_instance_info(instance, instance_type, sys_meta):
        flavors.save_flavor_info(sys_meta, instance_type)
        instance.instance_type_id = instance_type['id']
        instance.memory_mb = instance_type['memory_mb']
        instance.vcpus = instance_type['vcpus']
        instance.root_gb = instance_type['root_gb']
        instance.ephemeral_gb = instance_type['ephemeral_gb']
        instance.system_metadata = sys_meta
        instance.save()

    def _finish_resize(self, context, instance, migration, disk_info,
                       image):
        resize_instance = False
        old_instance_type_id = migration['old_instance_type_id']
        new_instance_type_id = migration['new_instance_type_id']
        old_instance_type = flavors.extract_flavor(instance)
        sys_meta = instance.system_metadata
        # NOTE(mriedem): Get the old_vm_state so we know if we should
        # power on the instance. If old_vm_state is not set we need to default
        # to ACTIVE for backwards compatibility
        old_vm_state = sys_meta.get('old_vm_state', vm_states.ACTIVE)
        flavors.save_flavor_info(sys_meta,
                                 old_instance_type,
                                 prefix='old_')

        if old_instance_type_id != new_instance_type_id:
            instance_type = flavors.extract_flavor(instance, prefix='new_')
            self._save_instance_info(instance, instance_type, sys_meta)
            # the instance_type contains no extra_specs and flavor_accesses.
            flavor_name = instance_type['name']
            active_flavor = flavor_obj.Flavor.get_by_name(context, flavor_name)
            active_flavor._load_projects(context)
            instance_type['extra_specs'] = active_flavor.extra_specs
            instance_type['projects'] = active_flavor.projects
            instance_type['is_public'] = active_flavor.is_public
            self._heal_syn_flavor_info(context, instance_type)
            resize_instance = True

        self._heal_instance_metadata(instance.id, instance.metadata)

        # NOTE(tr3buchet): setup networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                migration['dest_compute'])

        instance_p = obj_base.obj_to_primitive(instance)
        migration_p = obj_base.obj_to_primitive(migration)
        self.network_api.migrate_instance_finish(context,
                                                 instance_p,
                                                 migration_p)

        network_info = self._get_instance_nw_info(context, instance)

        instance.task_state = task_states.RESIZE_FINISH
        instance.system_metadata = sys_meta
        instance.save(expected_task_state=task_states.RESIZE_MIGRATED)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.start",
            network_info=network_info)

        # block_device_info = self._get_instance_block_device_info(
        #     context, instance, refresh_conn_info=True)
        #
        # # NOTE(mriedem): If the original vm_state was STOPPED, we don't
        # # automatically power on the instance after it's migrated
        # power_on = old_vm_state != vm_states.STOPPED
        #
        # try:
        #     self.driver.finish_migration(context, migration, instance,
        #                                  disk_info,
        #                                  network_info,
        #                                  image, resize_instance,
        #                                  block_device_info, power_on)
        # except Exception:
        #     with excutils.save_and_reraise_exception():
        #         if resize_instance:
        #             self._save_instance_info(instance,
        #                                      old_instance_type, sys_meta)

        #cascading patch
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('Finish resize can not find server %s %s .'),
                      instance['uuid'])
            return

        cascaded_nova_cli = self._get_nova_python_client(context)
        try:
            cascaded_nova_cli.servers.resize(
                cascaded_instance_id,
                instance.system_metadata['new_instance_type_flavorid'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to resize server %s, rollback flavor.'),
                          cascaded_instance_id)
                flavors.delete_flavor_info(sys_meta, 'old_')
                if resize_instance:
                    self._save_instance_info(instance, old_instance_type, sys_meta)

        migration.status = 'finished'
        migration.save(context.elevated())

        # instance.vm_state = vm_states.RESIZED
        # instance.task_state = None
        # instance.launched_at = timeutils.utcnow()
        # instance.save(expected_task_state=task_states.RESIZE_FINISH)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.end",
            network_info=network_info)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @errors_out_migration
    @wrap_instance_fault
    def finish_resize(self, context, disk_info, image, instance,
                      reservations, migration):
        """Completes the migration process.

        Sets up the newly transferred disk and turns on the instance at its
        new host machine.

        """
        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)
        try:
            self._finish_resize(context, instance, migration,
                                disk_info, image)
            quotas.commit()
        except Exception:
            LOG.exception(_LE('Setting instance vm_state to ERROR'),
                          instance=instance)
            with excutils.save_and_reraise_exception():
                try:
                    quotas.rollback()
                except Exception as qr_error:
                    LOG.exception(_LE("Failed to rollback quota for failed "
                                      "finish_resize: %s"),
                                  qr_error, instance=instance)
                self._set_instance_error_state(context, instance)

    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def add_fixed_ip_to_instance(self, context, network_id, instance):
        """Calls network_api to add new fixed_ip to instance
        then injects the new network info and resets instance networking.

        """
        self._notify_about_instance_usage(
            context, instance, "create_ip.start")

        network_info = self.network_api.add_fixed_ip_to_instance(context,
                                                                 instance,
                                                                 network_id)
        self._inject_network_info(context, instance, network_info)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        instance.updated_at = timeutils.utcnow()
        instance.save()

        self._notify_about_instance_usage(
            context, instance, "create_ip.end", network_info=network_info)

    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def remove_fixed_ip_from_instance(self, context, address, instance):
        """Calls network_api to remove existing fixed_ip from instance
        by injecting the altered network info and resetting
        instance networking.
        """
        self._notify_about_instance_usage(
            context, instance, "delete_ip.start")

        network_info = self.network_api.remove_fixed_ip_from_instance(context,
                                                                      instance,
                                                                      address)
        self._inject_network_info(context, instance, network_info)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        instance.updated_at = timeutils.utcnow()
        instance.save()

        self._notify_about_instance_usage(
            context, instance, "delete_ip.end", network_info=network_info)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def pause_instance(self, context, instance):
        """Pause an instance on this host."""
        context = context.elevated()
        LOG.audit(_('Pausing'), context=context, instance=instance)
        self._notify_about_instance_usage(context, instance, 'pause.start')
        # self.driver.pause(instance)
        # current_power_state = self._get_power_state(context, instance)
        # instance.power_state = current_power_state
        # instance.vm_state = vm_states.PAUSED
        # instance.task_state = None
        # instance.save(expected_task_state=task_states.PAUSING)
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        'in cascaded layer.'), instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        cascaded_nova_cli.servers.pause(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'pause.end')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def unpause_instance(self, context, instance):
        """Unpause a paused instance on this host."""
        context = context.elevated()
        LOG.audit(_('Unpausing'), context=context, instance=instance)
        self._notify_about_instance_usage(context, instance, 'unpause.start')
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        ' in cascaded layer.'), instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        cascaded_nova_cli.servers.unpause(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'unpause.end')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def suspend_instance(self, context, instance):
        """Suspend the given instance."""
        context = context.elevated()

        # Store the old state
        instance.system_metadata['old_vm_state'] = instance.vm_state

        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server '
                        'in cascaded layer.'),
                      instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)
        cascaded_nova_cli.servers.suspend(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'suspend')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def resume_instance(self, context, instance):
        """Resume the given suspended instance."""
        #cascading patch
        context = context.elevated()
        LOG.audit(_('Resuming'), context=context, instance=instance)

        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.error(_('resume server,but can not find server'),
                      instance['uuid'])
            return

        cascaded_nova_cli = self._get_nova_python_client(context)
        try:
            cascaded_nova_cli.servers.resume(cascaded_instance_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to resume server %s .'),
                          cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'resume')


    @object_compat
    @messaging.expected_exceptions(NotImplementedError,
                                   exception.InstanceNotFound)
    @wrap_exception()
    @wrap_instance_fault
    def get_console_output(self, context, instance, tail_length):
        """Send the console output for the given instance."""
        context = context.elevated()
        LOG.audit(_("Get console output"), context=context,
                  instance=instance)
        # output = self.driver.get_console_output(context, instance)

        #cascading patch
        cascaded_instance_id = self._get_csd_instance_uuid(instance)
        if cascaded_instance_id is None:
            LOG.debug(_('get_vnc_console can not find server %s .'),
                      instance['uuid'])
            return
        cascaded_nova_cli = self._get_nova_python_client(context)

        try:
            output = cascaded_nova_cli.servers.get_console_output(
                cascaded_instance_id, tail_length)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get_vnc_console server %s .'),
                          cascaded_instance_id)


        # if tail_length is not None:
        #     output = self._tail_log(output, tail_length)
        #
        # return output.decode('utf-8', 'replace').encode('ascii', 'replace')
        return output

    def _tail_log(self, log, length):
        try:
            length = int(length)
        except ValueError:
            length = 0

        if length == 0:
            return ''
        else:
            return '\n'.join(log.split('\n')[-int(length):])

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound,
                                   exception.ConsoleTypeUnavailable,
                                   NotImplementedError)
    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def get_vnc_console(self, context, console_type, instance):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug("Getting vnc console", instance=instance)
        token = str(uuid.uuid4())

        if not CONF.vnc_enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        # if console_type == 'novnc':
        #     # For essex, novncproxy_base_url must include the full path
        #     # including the html file (like http://myhost/vnc_auto.html)
        #     access_url = '%s?token=%s' % (CONF.novncproxy_base_url, token)
        # elif console_type == 'xvpvnc':
        #     access_url = '%s?token=%s' % (CONF.xvpvncproxy_base_url, token)
        # else:
        #     raise exception.ConsoleTypeInvalid(console_type=console_type)
        #
        # try:
        #     # Retrieve connect info from driver, and then decorate with our
        #     # access info token
        #     console = self.driver.get_vnc_console(context, instance)
        #     connect_info = console.get_connection_info(token, access_url)
        # except exception.InstanceNotFound:
        #     if instance['vm_state'] != vm_states.BUILDING:
        #         raise
        #     raise exception.InstanceNotReady(instance_id=instance['uuid'])

        #cascading patch
        connect_info = {}
        try:
            # access info token
            cascaded_instance_id = self._get_csd_instance_uuid(instance)
            if cascaded_instance_id is None:
                LOG.debug(_('Get vnc_console can not find server %s .'),
                          instance['uuid'])
                return
            cascaded_nova_cli = self._get_nova_python_client(context)
            try:
                body_response = cascaded_nova_cli.servers.get_vnc_console(
                    cascaded_instance_id, console_type)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to get_vnc_console server %s .'),
                              cascaded_instance_id)
            if console_type != 'novnc' and console_type != 'xvpvnc':
                # For essex, novncproxy_base_url must include the full path
                # including the html file (like http://myhost/vnc_auto.html)
                raise exception.ConsoleTypeInvalid(console_type=console_type)

            connect_info['token'] = token
            connect_info['access_url'] = body_response['console']['url']
            connect_info['host'] = CONF.vncserver_proxyclient_address
            connect_info['port'] = CONF.novncproxy_port
            connect_info['internal_access_path'] = None
        except exception.InstanceNotFound:
            if instance['vm_state'] != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        return connect_info


    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def reserve_block_device_name(self, context, instance, device,
                                  volume_id, disk_bus=None, device_type=None,
                                  return_bdm_object=False):
        # NOTE(ndipanov): disk_bus and device_type will be set to None if not
        # passed (by older clients) and defaulted by the virt driver. Remove
        # default values on the next major RPC version bump.

        @utils.synchronized(instance['uuid'])
        def do_reserve():
            bdms = (
                objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid))

            device_name = compute_utils.get_device_name_for_instance(
                context, instance, bdms, device)

            # NOTE(vish): create bdm here to avoid race condition
            bdm = objects.BlockDeviceMapping(
                source_type='volume', destination_type='volume',
                instance_uuid=instance.uuid,
                volume_id=volume_id or 'reserved',
                device_name=device_name,
                disk_bus=disk_bus, device_type=device_type)
            bdm.create(context)

            if return_bdm_object:
                return bdm
            else:
                return device_name

        return do_reserve()

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def attach_volume(self, context, volume_id, mountpoint,
                      instance, bdm=None):
        """Attach a volume to an instance."""
        if not bdm:
            bdm = objects.BlockDeviceMapping.get_by_volume_id(
                context, volume_id)
        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm)

        @utils.synchronized(instance.uuid)
        def do_attach_volume(context, instance, driver_bdm):
            try:
                return self._attach_volume(context, instance, driver_bdm)
            except Exception:
                with excutils.save_and_reraise_exception():
                    bdm.destroy(context)

        do_attach_volume(context, instance, driver_bdm)

    def _attach_volume(self, context, instance, bdm):
        context = context.elevated()
        LOG.audit(_('Attaching volume %(volume_id)s to %(mountpoint)s'),
                  {'volume_id': bdm.volume_id,
                   'mountpoint': bdm['mount_device']},
                  context=context, instance=instance)
        try:
            #            bdm.attach(context, instance, self.volume_api, self.driver,
            # do_check_attach=False, do_driver_attach=True)
            self.volume_api.attach(context, bdm.volume_id,
                                   instance['uuid'], bdm['mount_device'])
            proxy_volume_id = None
            try:
                body_response = self.volume_api.get(context, bdm.volume_id)
                proxy_volume_id = body_response['volume_metadata']['mapping_uuid']
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to get  physical volume id ,logical'
                                ' volume id %s,device %s'),
                              bdm.volume_id, bdm['mount_device'])
            if proxy_volume_id is None:
                LOG.error(_('attach_volume can not find physical volume id %s'
                            ' in physical opensack lay,logical volume id %s'),
                          instance['uuid'], bdm.volume_id)
                return

            cascaded_nova_cli = self._get_nova_python_client(context)
            body_response = cascaded_nova_cli.volumes.create_server_volume(
                self._get_csd_instance_uuid(instance),
                proxy_volume_id, bdm['mount_device'])
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to attach %(volume_id)s "
                                "at %(mountpoint)s"),
                              {'volume_id': bdm.volume_id,
                               'mountpoint': bdm['mount_device']},
                              context=context, instance=instance)
                self.volume_api.unreserve_volume(context, bdm.volume_id)

        info = {'volume_id': bdm.volume_id}
        self._notify_about_instance_usage(
            context, instance, "volume.attach", extra_usage_info=info)

    def _detach_volume(self, context, instance, bdm):
        """Do the actual driver detach using block device mapping."""
        mp = bdm.device_name
        volume_id = bdm.volume_id

        LOG.audit(_('Detach volume %(volume_id)s from mountpoint %(mp)s'),
                  {'volume_id': volume_id, 'mp': mp},
                  context=context, instance=instance)

        connection_info = jsonutils.loads(bdm.connection_info or '{}')
        # NOTE(vish): We currently don't use the serial when disconnecting,
        #             but added for completeness in case we ever do.
        if connection_info and 'serial' not in connection_info:
            connection_info['serial'] = volume_id
        try:
            #cascading patch
            proxy_volume_id = None
            try:
                body_response = self.volume_api.get(context, volume_id)
                proxy_volume_id = body_response['volume_metadata']['mapping_uuid']
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to get  physical volume id ,logical'
                                ' volume id %s,device %s'), volume_id, mp)
            if proxy_volume_id is None:
                LOG.error(_('detach_volume can not find physical volume id %s '
                            'in physical opensack lay,logical volume id %s'),
                          instance['uuid'], volume_id)
                return
            cascaded_nova_cli = self._get_nova_python_client(context)
            body_response = cascaded_nova_cli.volumes.delete_server_volume(
                self._get_csd_instance_uuid(instance), proxy_volume_id)

            # if not self.driver.instance_exists(instance):
            #     LOG.warn(_('Detaching volume from unknown instance'),
            #              context=context, instance=instance)

            # encryption = encryptors.get_encryption_metadata(
            #     context, self.volume_api, volume_id, connection_info)
            #
            # self.driver.detach_volume(connection_info,
            #                           instance,
            #                           mp,
            #                           encryption=encryption)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Failed to detach volume %(volume_id)s '
                                  'from %(mp)s'),
                              {'volume_id': volume_id, 'mp': mp},
                              context=context, instance=instance)
                self.volume_api.roll_detaching(context, volume_id)

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def detach_volume(self, context, volume_id, instance):
        """Detach a volume from an instance."""
        bdm = objects.BlockDeviceMapping.get_by_volume_id(context, volume_id)
        LOG.debug(_('detach bmd info is %s') % bdm)
        if CONF.volume_usage_poll_interval > 0:
            vol_stats = []
            mp = bdm.device_name
            # Handle bootable volumes which will not contain /dev/
            if '/dev/' in mp:
                mp = mp[5:]
            try:
                vol_stats = self.driver.block_stats(instance.name, mp)
            except NotImplementedError:
                pass

            if vol_stats:
                LOG.debug("Updating volume usage cache with totals",
                          instance=instance)
                rd_req, rd_bytes, wr_req, wr_bytes, flush_ops = vol_stats
                self.conductor_api.vol_usage_update(context, volume_id,
                                                    rd_req, rd_bytes,
                                                    wr_req, wr_bytes,
                                                    instance,
                                                    update_totals=True)

        self._detach_volume(context, instance, bdm)
        connector = self.driver.get_volume_connector(instance)
        bdm.destroy()
        info = dict(volume_id=volume_id)
        self._notify_about_instance_usage(
            context, instance, "volume.detach", extra_usage_info=info)
        self.volume_api.detach(context.elevated(), volume_id)

    def _init_volume_connection(self, context, new_volume_id,
                                old_volume_id, connector, instance, bdm):

        new_cinfo = self.volume_api.initialize_connection(context,
                                                          new_volume_id,
                                                          connector)
        old_cinfo = jsonutils.loads(bdm['connection_info'])
        if old_cinfo and 'serial' not in old_cinfo:
            old_cinfo['serial'] = old_volume_id
        new_cinfo['serial'] = old_cinfo['serial']
        return (old_cinfo, new_cinfo)

    @wrap_exception()
    def remove_volume_connection(self, context, volume_id, instance):
        """Remove a volume connection using the volume api."""
        # NOTE(vish): We don't want to actually mark the volume
        #             detached, or delete the bdm, just remove the
        #             connection from this host.

        # NOTE(PhilDay): Can't use object_compat decorator here as
        #                instance is not the second parameter
        if isinstance(instance, dict):
            metas = ['metadata', 'system_metadata']
            instance = objects.Instance._from_db_object(
                context, objects.Instance(), instance,
                expected_attrs=metas)
            instance._context = context
        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_id(
                context, volume_id)
            self._detach_volume(context, instance, bdm)
            connector = self.driver.get_volume_connector(instance)
            self.volume_api.terminate_connection(context, volume_id, connector)
        except exception.NotFound:
            pass

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def attach_interface(self, context, instance, network_id, port_id,
                         requested_ip):
        """Use hotplug to add an network adapter to an instance."""
        network_info = self.network_api.allocate_port_for_instance(
            context, instance, port_id, network_id, requested_ip)
        if len(network_info) != 1:
            LOG.error(_('allocate_port_for_instance returned %(ports)s ports')
                      % dict(ports=len(network_info)))
            raise exception.InterfaceAttachFailed(
                instance_uuid=instance.uuid)
        image_ref = instance.get('image_ref')
        image_meta = compute_utils.get_image_metadata(
            context, self.image_api, image_ref, instance)

        self.driver.attach_interface(instance, image_meta, network_info[0])
        return network_info[0]

    @wrap_exception()
    @wrap_instance_fault
    def check_can_live_migrate_destination(self, ctxt, instance,
                                           block_migration, disk_over_commit):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit
        :returns: a dict containing migration info
        """
        src_compute_info = obj_base.obj_to_primitive(
            self._get_compute_info(ctxt, instance.host))
        dst_compute_info = obj_base.obj_to_primitive(
            self._get_compute_info(ctxt, CONF.host))
        dest_check_data = self.driver.check_can_live_migrate_destination(ctxt,
                                                                         instance, src_compute_info, dst_compute_info,
                                                                         block_migration, disk_over_commit)
        migrate_data = {}
        try:
            migrate_data = self.compute_rpcapi. \
                check_can_live_migrate_source(ctxt, instance,
                                              dest_check_data)
        finally:
            self.driver.check_can_live_migrate_destination_cleanup(ctxt,
                                                                   dest_check_data)
        if 'migrate_data' in dest_check_data:
            migrate_data.update(dest_check_data['migrate_data'])
        return migrate_data

    @wrap_exception()
    @wrap_instance_fault
    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance: dict of instance data
        :param dest_check_data: result of check_can_live_migrate_destination
        :returns: a dict containing migration info
        """
        is_volume_backed = self.compute_api.is_volume_backed_instance(ctxt,
                                                                      instance)
        dest_check_data['is_volume_backed'] = is_volume_backed
        return self.driver.check_can_live_migrate_source(ctxt, instance,
                                                         dest_check_data)

    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def pre_live_migration(self, context, instance, block_migration, disk,
                           migrate_data):
        """Preparations for live migration at dest host.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
        :param migrate_data: if not None, it is a dict which holds data
                             required for live migration without shared
                             storage.

        """
        block_device_info = self._get_instance_block_device_info(
            context, instance, refresh_conn_info=True)

        network_info = self._get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
            context, instance, "live_migration.pre.start",
            network_info=network_info)

        pre_live_migration_data = self.driver.pre_live_migration(context,
                                                                 instance,
                                                                 block_device_info,
                                                                 network_info,
                                                                 disk,
                                                                 migrate_data)

        # NOTE(tr3buchet): setup networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                self.host)

        # Creating filters to hypervisors and firewalls.
        # An example is that nova-instance-instance-xxx,
        # which is written to libvirt.xml(Check "virsh nwfilter-list")
        # This nwfilter is necessary on the destination host.
        # In addition, this method is creating filtering rule
        # onto destination host.
        self.driver.ensure_filtering_rules_for_instance(instance,
                                                        network_info)

        self._notify_about_instance_usage(
            context, instance, "live_migration.pre.end",
            network_info=network_info)

        return pre_live_migration_data

    @wrap_exception()
    @wrap_instance_fault
    def live_migration(self, context, dest, instance, block_migration,
                       migrate_data):
        """Executing live migration.

        :param context: security context
        :param instance: a nova.objects.instance.Instance object
        :param dest: destination host
        :param block_migration: if true, prepare for block migration
        :param migrate_data: implementation specific params

        """

        # NOTE(danms): since instance is not the first parameter, we can't
        # use @object_compat on this method. Since this is the only example,
        # we do this manually instead of complicating the decorator
        if not isinstance(instance, obj_base.NovaObject):
            expected = ['metadata', 'system_metadata',
                        'security_groups', 'info_cache']
            instance = objects.Instance._from_db_object(
                context, objects.Instance(), instance,
                expected_attrs=expected)

        # Create a local copy since we'll be modifying the dictionary
        migrate_data = dict(migrate_data or {})
        try:
            if block_migration:
                disk = self.driver.get_instance_disk_info(instance.name)
            else:
                disk = None

            pre_migration_data = self.compute_rpcapi.pre_live_migration(
                context, instance,
                block_migration, disk, dest, migrate_data)
            migrate_data['pre_live_migration_result'] = pre_migration_data

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Pre live migration failed at %s'),
                              dest, instance=instance)
                self._rollback_live_migration(context, instance, dest,
                                              block_migration, migrate_data)

        # Executing live migration
        # live_migration might raises exceptions, but
        # nothing must be recovered in this version.
        self.driver.live_migration(context, instance, dest,
                                   self._post_live_migration,
                                   self._rollback_live_migration,
                                   block_migration, migrate_data)

    @periodic_task.periodic_task(spacing=CONF.sync_aggregate_info_interval)
    def update_aggrgates_info(self, context):
        """Periodic process that keeps that the nova controller understanding of
        aggregates and metadta/hosts in sync with the underlying openstacks.

        :param context: security context
        """
        if not CONF.resource_tracker_synced:
            return
        my_host = CONF.host
        admin_ctxt = context.elevated()
        csd_aggregate_list = self.sync_nova_client.aggregates.list()
        csg_aggregate_list = self.csg_nova_client.aggregates.list()
        csd_agg_dict = [agg.to_dict() for agg in csd_aggregate_list]
        csg_aggs = [{agg.to_dict()['name']:{
                        'id': agg.to_dict()['id'],
                        'metadata': agg.to_dict()['metadata'],
                        'hosts': [h for h in agg.to_dict().get('hosts', [])
                                  if h.startswith(my_host + '_')],
                        }}
                    for agg in csg_aggregate_list]
        csg_aggs_dict = {}
        for csg_agg in csg_aggs:
            csg_aggs_dict.update(csg_agg)

        for csd_ag in csd_agg_dict:
            ag_obj = agg_obj.Aggregate()
            csd_meta = csd_ag['metadata'] or {}
            if csd_ag['name'] not in csg_aggs_dict:
                ag_obj.name = csd_ag['name']
                full_hosts = [my_host + '_' + h for h in csd_ag['hosts']]
                # ag_obj.hosts = full_hosts
                ag_obj.metadata = csd_meta
                ag_obj.create(admin_ctxt)
                for full_host in full_hosts:
                    ag_obj.add_host(admin_ctxt, full_host)

            else:
                csg_id = csg_aggs_dict[csd_ag['name']]['id']
                csg_hosts = [h.split('_')[1] for h
                             in csg_aggs_dict[csd_ag['name']]['hosts']
                             if h.find('_')]

                if csd_meta and csg_aggs_dict[csd_ag['name']]['metadata'] != csd_meta:
                    ag_obj.id = csg_id
                    ag_obj.metadata = csg_aggs_dict[csd_ag['name']]['metadata']
                    ag_obj.update_metadata(admin_ctxt, csd_meta)

                if csg_hosts != csd_ag['hosts']:
                    ag_obj.id = csg_id
                    ag_obj.hosts = csg_aggs_dict[csd_ag['name']]['hosts']
                    to_add_hosts = [h for h in csd_ag['hosts']
                                    if h not in csg_hosts]
                    to_del_hosts = [h for h in csg_hosts
                                    if h not in csd_ag['hosts']]
                    for add_host in to_add_hosts:
                        full_host = my_host + '_' + add_host
                        ag_obj.add_host(admin_ctxt, full_host)
                    for del_host in to_del_hosts:
                        full_host = my_host + '_' + del_host
                        ag_obj.delete_host(csg_id, full_host)

    def _update_available_cascaded_resource(self, context):
        my_host = CONF.host
        admin_ctxt = context.elevated()
        csd_hypervisor_list = self.sync_nova_client.hypervisors.list()
        csd_hyper_dict_list = [h.to_dict() for h in csd_hypervisor_list]
        conductor_api = conductor.API()
        for hyper in csd_hyper_dict_list:
            hyper_obj = compute_node_obj.ComputeNode()
            ser_obj = service_obj.Service()

            host = hyper.pop('service', {}).get('host', '')
            hyper.pop('id', None)
            host_full_name = my_host + '_' + host

            csd_services = self.sync_nova_client.services.list(host=host,
                                                        binary='nova-compute')
            try:
                csg_service = conductor_api.service_get_by_args(context,
                                            host_full_name, 'nova-compute')
            except Exception:
                csg_service = None

            if csd_services:
                csd_service_dict = (csd_services[0].to_dict() if csd_services
                                    else {})
            else:
                LOG.warn('Can not find the nova-compute service in host %s', host)
            if csg_service:
                updates = {}
                updates['report_count'] = csg_service['report_count'] + 1
                if csd_service_dict:
                    updates['disabled'] = csd_service_dict['status'] != 'enabled'
                    if csd_service_dict['state'] == 'up':
                        conductor_api.service_update(context, csg_service, updates)

                csg_hyper = compute_node_obj.ComputeNode.get_by_service_id(context,
                                                                csg_service['id'])

                hyper['service_id'] = csg_service['id']
                for field in hyper_obj.fields:
                    if hyper.get(field, None) is not None:
                        setattr(hyper_obj, field, hyper.get(field))
                hyper_obj.id = csg_hyper.id
                hyper_obj.save(admin_ctxt)
            else:
                ser_obj.host = host_full_name
                ser_obj.binary = 'nova-compute'
                ser_obj.topic = 'compute'
                if csd_service_dict:
                    ser_obj.disabled = csd_service_dict['status'] != 'enabled'
                ser_obj.create(admin_ctxt)
                hyper['service_id'] = ser_obj.id
                try:
                    for field in hyper_obj.fields:
                        if hyper.get(field, None) is not None:
                            setattr(hyper_obj, field, hyper.get(field))
                    hyper_obj.create(admin_ctxt)
                except Exception:
                    raise

    def _update_available_resource(self, context):
        nodenames = set(self.driver.get_available_nodes())
        for nodename in nodenames:
            rt = self._get_resource_tracker(nodename)
            resources = rt.driver.get_available_resource(rt.nodename)
            resources['host_ip'] = CONF.my_ip
            resources['local_gb_used'] = CONF.reserved_host_disk_mb / 1024
            resources['memory_mb_used'] = CONF.reserved_host_memory_mb
            resources['free_ram_mb'] = (resources['memory_mb'] -
                                        resources['memory_mb_used'])
            resources['free_disk_gb'] = (resources['local_gb'] -
                                         resources['local_gb_used'])
            resources['current_workload'] = 0
            resources['running_vms'] = 0
            resources['pci_stats'] = jsonutils.dumps([])
            resources['stats'] = {}
            rt._update_usage_from_instances(context, resources, [])
            rt._sync_compute_node(context, resources)

    @periodic_task.periodic_task
    def update_available_resource(self, context):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        """
        if CONF.resource_tracker_synced:
            self._update_available_cascaded_resource(context)
        else:
            self._update_available_resource(context)

    def _get_compute_nodes_in_db(self, context, use_slave=False):
        service = objects.Service.get_by_compute_host(context, self.host,
                                                      use_slave=use_slave)
        if not service:
            LOG.error(_("No service record for host %s"), self.host)
            return []
        return objects.ComputeNodeList.get_by_service(context,
                                                      service,
                                                      use_slave=use_slave)

    @contextlib.contextmanager
    def _error_out_instance_on_exception(self, context, instance,
                                         quotas=None,
                                         instance_state=vm_states.ACTIVE):
        instance_uuid = instance['uuid']
        try:
            yield
        except NotImplementedError as error:
            with excutils.save_and_reraise_exception():
                if quotas:
                    quotas.rollback()
                LOG.info(_("Setting instance back to %(state)s after: "
                           "%(error)s") %
                         {'state': instance_state, 'error': error},
                         instance_uuid=instance_uuid)
                self._instance_update(context, instance_uuid,
                                      vm_state=instance_state,
                                      task_state=None)
        except exception.InstanceFaultRollback as error:
            if quotas:
                quotas.rollback()
            LOG.info(_("Setting instance back to ACTIVE after: %s"),
                     error, instance_uuid=instance_uuid)
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None)
            raise error.inner_exception
        except Exception:
            LOG.exception(_LE('Setting instance vm_state to ERROR'),
                          instance_uuid=instance_uuid)
            with excutils.save_and_reraise_exception():
                if quotas:
                    quotas.rollback()
                self._set_instance_error_state(context, instance)

    @aggregate_object_compat
    @wrap_exception()
    def add_aggregate_host(self, context, aggregate, host, slave_info):
        """Notify hypervisor of change (for hypervisor pools)."""
        try:
            self.driver.add_to_aggregate(context, aggregate, host,
                                         slave_info=slave_info)
        except NotImplementedError:
            LOG.debug('Hypervisor driver does not support '
                      'add_aggregate_host')
        except exception.AggregateError:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                    context,
                    aggregate.delete_host,
                    aggregate, host)

    @aggregate_object_compat
    @wrap_exception()
    def remove_aggregate_host(self, context, host, slave_info, aggregate):
        """Removes a host from a physical hypervisor pool."""
        try:
            self.driver.remove_from_aggregate(context, aggregate, host,
                                              slave_info=slave_info)
        except NotImplementedError:
            LOG.debug('Hypervisor driver does not support '
                      'remove_aggregate_host')
        except (exception.AggregateError,
                exception.InvalidAggregateAction) as e:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                    context,
                    aggregate.add_host,
                    aggregate, host,
                    isinstance(e, exception.AggregateError))


    @wrap_exception()
    def external_instance_event(self, context, instances, events):
        # NOTE(danms): Some event types are handled by the manager, such
        # as when we're asked to update the instance's info_cache. If it's
        # not one of those, look for some thread(s) waiting for the event and
        # unblock them if so.
        for event in events:
            instance = [inst for inst in instances
                        if inst.uuid == event.instance_uuid][0]
            LOG.debug('Received event %(event)s',
                      {'event': event.key},
                      instance=instance)
            if event.name == 'network-changed':
                self.network_api.get_instance_nw_info(context, instance)
            else:
                self._process_instance_event(instance, event)

