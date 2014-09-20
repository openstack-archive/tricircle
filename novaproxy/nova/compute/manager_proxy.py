import base64
import contextlib
import functools
import os
import sys
import time
import traceback
import uuid

import novaclient
import eventlet.event
import eventlet.timeout
from oslo.config import cfg
from oslo import messaging

from nova.compute import clients
from nova.compute import compute_context
from nova.openstack.common import timeutils

from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.cloudpipe import pipelib
from nova import compute
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
from nova.image import glance
from nova import manager
from nova import network
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova.objects import aggregate as aggregate_obj
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import external_event as external_event_obj
from nova.objects import flavor as flavor_obj
from nova.objects import instance as instance_obj
from nova.objects import instance_group as instance_group_obj
from nova.objects import migration as migration_obj
from nova.objects import quotas as quotas_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import periodic_task
from nova import paths
from nova import rpc
from nova import safe_utils
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import utils
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.virt import virtapi
from nova import volume

from nova.virt.libvirt import utils as libvirt_utils
from nova.network import neutronv2
from neutronclient.v2_0 import client as clientv20


compute_opts = [
    cfg.StrOpt('instances_path',
               default=paths.state_path_def('instances'),
               help='Where instances are stored on disk'),
    cfg.IntOpt('network_allocate_retries',
               default=0,
               help="Number of times to retry network allocation on failures"),
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
               help='value of cascaded glance url')
]

interval_opts = [
    cfg.IntOpt('volume_usage_poll_interval',
               default=0,
               help='Interval in seconds for gathering volume usages'),
    cfg.IntOpt('sync_instance_state_interval',
               default=5,
               help='interval to sync instance states between '
                    'the nova and the nova-proxy')

]

CONF = cfg.CONF
CONF.register_opts(compute_opts)
CONF.register_opts(interval_opts)
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('enabled', 'nova.spice', group='spice')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('enabled', 'nova.rdp', group='rdp')

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
                # Find migration argument. The argument cannot be
                # defined by position because the wrapped functions
                # do not have the same signature.
                for arg in args:
                    if not isinstance(arg, migration_obj.Migration):
                        continue
                    status = arg.status
                    if status not in ['migrating', 'post-migrating']:
                        continue
                    arg.status = 'error'
                    try:
                        arg.save(context.elevated())
                    except Exception:
                        LOG.debug(_('Error setting migration status '
                                    'for instance %s.') %
                                  arg.instance_uuid, exc_info=True)
                    break

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
                                                          self.conductor_api,
                                                          kwargs['instance'],
                                                          e, sys.exc_info())

    return decorated_function


@utils.expects_func_args('instance')
def wrap_instance_event(function):
    """Wraps a method to log the event taken on the instance, and result.

    This decorator wraps a method to log the start and result of an event, as
    part of an action taken on an instance.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        wrapped_func = utils.get_wrapped_function(function)
        keyed_args = safe_utils.getcallargs(wrapped_func, context, *args,
                                            **kwargs)
        instance_uuid = keyed_args['instance']['uuid']

        event_name = 'compute_{0}'.format(function.func_name)
        with compute_utils.EventReporter(context, self.conductor_api,
                                         event_name, instance_uuid):

            function(self, context, *args, **kwargs)

    return decorated_function


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
                LOG.debug(_("Cleaning up image %s") % image_id,
                          exc_info=True, instance=instance)
                try:
                    image_service = glance.get_default_image_service()
                    image_service.delete(context, image_id)
                except Exception:
                    LOG.exception(_("Error while trying to clean up image %s")
                                  % image_id, instance=instance)

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
                instance = instance_obj.Instance._from_db_object(
                    context, instance_obj.Instance(), instance_or_dict,
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
            migration = migration_obj.Migration._from_db_object(
                context.elevated(),
                migration_obj.Migration(),
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
            aggregate = aggregate_obj.Aggregate._from_db_object(
                context.elevated(), aggregate_obj.Aggregate(),
                aggregate)
            kwargs['aggregate'] = aggregate
        return function(self, context, *args, **kwargs)
    return decorated_function


def _get_image_meta(context, image_ref):
    image_service, image_id = glance.get_remote_image_service(context,
                                                              image_ref)
    return image_service.show(context, image_id)


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
        @utils.synchronized(self._lock_name)
        def _create_or_get_event():
            if instance.uuid not in self._events:
                self._events.setdefault(instance.uuid, {})
            return self._events[instance.uuid].setdefault(
                event_name, eventlet.event.Event())
        LOG.debug(_('Preparing to wait for external event %(event)s'),
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
        @utils.synchronized(self._lock_name)
        def _pop_event():
            events = self._events.get(instance.uuid)
            if not events:
                return None
            _event = events.pop(event.key, None)
            if not events:
                del self._events[instance.uuid]
            return _event
        return _pop_event()

    def clear_events_for_instance(self, instance):
        """Remove all pending events for an instance.

        This will remove all events currently pending for an instance
        and return them (indexed by event name).

        :param instance: the instance for which events should be purged
        :returns: a dictionary of {event_name: eventlet.event.Event}
        """
        @utils.synchronized(self._lock_name)
        def _clear_events():
            # NOTE(danms): Use getitem syntax for the instance until
            # all the callers are using objects
            return self._events.pop(instance['uuid'], {})
        return _clear_events()


class ComputeVirtAPI(virtapi.VirtAPI):

    def __init__(self, compute):
        super(ComputeVirtAPI, self).__init__()
        self._compute = compute

    def instance_update(self, context, instance_uuid, updates):
        return self._compute._instance_update(context,
                                              instance_uuid,
                                              **updates)

    def provider_fw_rule_get_all(self, context):
        return self._compute.conductor_api.provider_fw_rule_get_all(context)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        return self._compute.conductor_api.agent_build_get_by_triple(
            context, hypervisor, os, architecture)

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

        :param:instance: The instance for which an event is expected
        :param:event_names: A list of event names. Each element can be a
                            string event name or tuple of strings to
                            indicate (name, tag).
        :param:deadline: Maximum number of seconds we should wait for all
                         of the specified events to arrive.
        :param:error_callback: A function to be called if an event arrives
        """

        if error_callback is None:
            error_callback = self._default_error_callback
        events = {}
        for event_name in event_names:
            if isinstance(event_name, tuple):
                name, tag = event_name
                event_name = external_event_obj.InstanceExternalEvent.make_key(
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

    target = messaging.Target(version='3.23')

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        self.virtapi = ComputeVirtAPI(self)
        self.network_api = network.API()
        self.volume_api = volume.API()
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

        super(ComputeManager, self).__init__(service_name="compute",
                                             *args, **kwargs)

        # NOTE(russellb) Load the driver last.  It may call back into the
        # compute manager via the virtapi, so we want it to be fully
        # initialized before that happens.
        self.driver = driver.load_compute_driver(self.virtapi, compute_driver)
        self.use_legacy_block_device_info = \
            self.driver.need_legacy_block_device_info
        self._last_info_instance_state_heal = 0
        self._change_since_time = None

    def _get_resource_tracker(self, nodename):
        rt = self._resource_tracker_dict.get(nodename)
        if not rt:
            if not self.driver.node_is_available(nodename):
                raise exception.NovaException(
                    _("%s is not a valid node managed by this "
                      "compute host.") % nodename)

            rt = resource_tracker.ResourceTracker(self.host,
                                                  self.driver,
                                                  nodename)
            self._resource_tracker_dict[nodename] = rt
        return rt

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""

        instance_ref = self.conductor_api.instance_update(context,
                                                          instance_uuid,
                                                          **kwargs)
        if (instance_ref['host'] == self.host and
                self.driver.node_is_available(instance_ref['node'])):
            rt = self._get_resource_tracker(instance_ref.get('node'))
            rt.update_usage(context, instance_ref)

        return instance_ref

    @periodic_task.periodic_task(spacing=CONF.sync_instance_state_interval,
                                 run_immediately=True)
    def _heal_instance_state(self, context):
        heal_interval = CONF.sync_instance_state_interval
        if not heal_interval:
            return
        curr_time = time.time()
        if self._last_info_instance_state_heal != 0:
            if self._last_info_instance_state_heal + heal_interval > curr_time:
                return
        self._last_info_instance_state_heal = curr_time

        kwargs = {
            'username': cfg.CONF.nova_admin_username,
            'password': cfg.CONF.nova_admin_password,
            'tenant': cfg.CONF.nova_admin_tenant_name,
            'auth_url': cfg.CONF.keystone_auth_url,
            'region_name': cfg.CONF.proxy_region_name
        }
        reqCon = compute_context.RequestContext(**kwargs)
        openStackClients = clients.OpenStackClients(reqCon)
        cascadedNovaCli = openStackClients.nova()
        try:
            if self._change_since_time is None:
                search_opts_args = {'all_tenants': True}
                servers = cascadedNovaCli.servers.list(
                    search_opts=search_opts_args)
            else:
                search_opts_args = {
                    'changes-since': self._change_since_time,
                    'all_tenants': True
                }
                servers = cascadedNovaCli.servers.list(
                    search_opts=search_opts_args)
            self._change_since_time = timeutils.isotime()
            if len(servers) > 0:
                LOG.debug(_('Updated the servers %s '), servers)

            for server in servers:
                self._instance_update(
                    context,
                    server._info['metadata']['mapping_uuid'],
                    vm_state=server._info['OS-EXT-STS:vm_state'],
                    task_state=server._info['OS-EXT-STS:task_state'],
                    power_state=server._info['OS-EXT-STS:power_state'],
                    launched_at=server._info['OS-SRV-USG:launched_at']
                )
                LOG.debug(_('Updated the server %s from nova-proxy'),
                          server.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to sys server status to db.'))

    @periodic_task.periodic_task
    def update_available_resource(self, context):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        """
        new_resource_tracker_dict = {}
        nodenames = set(self.driver.get_available_nodes())
        for nodename in nodenames:
            rt = self._get_resource_tracker(nodename)
            rt.update_available_resource(context)
            new_resource_tracker_dict[nodename] = rt

        self._resource_tracker_dict = new_resource_tracker_dict

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def run_instance(self, context, instance, request_spec,
                     filter_properties, requested_networks,
                     injected_files, admin_password,
                     is_first_time, node, legacy_bdm_in_spec):

        if filter_properties is None:
            filter_properties = {}

        @utils.synchronized(instance['uuid'])
        def do_run_instance():
            self._run_instance(
                context,
                request_spec,
                filter_properties,
                requested_networks,
                injected_files,
                admin_password,
                is_first_time,
                node,
                instance,
                legacy_bdm_in_spec)
        do_run_instance()

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
            info['message'] = unicode(msg)
            self._notify_about_instance_usage(
                context,
                instance,
                type_,
                extra_usage_info=info,
                fault=fault,
                **kwargs)

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
            notify("end", msg=unicode(e))  # notify that build is done

        except Exception as e:
            # Instance build encountered a non-recoverable error:
            with excutils.save_and_reraise_exception():
                self._set_instance_error_state(context, instance['uuid'])
                notify("error", fault=e)  # notify that build failed

    def _set_instance_error_state(self, context, instance_uuid):
        try:
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ERROR)
        except exception.InstanceNotFound:
            LOG.debug(_('Instance has been destroyed from under us while '
                        'trying to set it to ERROR'),
                      instance_uuid=instance_uuid)

    def _notify_about_instance_usage(self, context, instance, event_suffix,
                                     network_info=None, system_metadata=None,
                                     extra_usage_info=None, fault=None):
        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, event_suffix,
            network_info=network_info,
            system_metadata=system_metadata,
            extra_usage_info=extra_usage_info, fault=fault)

    def _prebuild_instance(self, context, instance):
        try:
            self._start_building(context, instance)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            msg = _("Instance disappeared before we could start it")
            # Quickly bail out of here
            raise exception.BuildAbortException(instance_uuid=instance['uuid'],
                                                reason=msg)

    def _start_building(self, context, instance):
        """Save the host and launched_on fields and log appropriately."""
        LOG.audit(_('Starting instance...'), context=context,
                  instance=instance)
        self._instance_update(context, instance['uuid'],
                              vm_state=vm_states.BUILDING,
                              task_state=None,
                              expected_task_state=(task_states.SCHEDULING,
                                                   None))

    def _build_instance(
            self,
            context,
            request_spec,
            filter_properties,
            requested_networks,
            injected_files,
            admin_password,
            is_first_time,
            node,
            instance,
            image_meta,
            legacy_bdm_in_spec):
        context = context.elevated()

        # If neutron security groups pass requested security
        # groups to allocate_for_instance()
        if request_spec and self.is_neutron_security_groups:
            security_groups = request_spec.get('security_group')
        else:
            security_groups = []

        if node is None:
            node = self.driver.get_available_nodes(refresh=True)[0]
            LOG.debug(_("No node specified, defaulting to %s"), node)

        network_info = None
        bdms = block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance['uuid'])

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

                network_info = self._allocate_network(
                    context,
                    instance,
                    requested_networks,
                    macs,
                    security_groups,
                    dhcp_options)

                self._instance_update(
                    context, instance['uuid'],
                    vm_state=vm_states.BUILDING,
                    task_state=task_states.BLOCK_DEVICE_MAPPING)

                cascaded_ports = []
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
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            # the instance got deleted during the spawn
            # Make sure the async call finishes
            msg = _("Instance disappeared during build")
            if network_info is not None:
                network_info.wait(do_raise=False)
            try:
                self._deallocate_network(context, instance)
            except Exception:
                msg = _('Failed to dealloc network '
                        'for deleted instance')
                LOG.exception(msg, instance=instance)
            raise exception.BuildAbortException(
                instance_uuid=instance['uuid'],
                reason=msg)
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
                    msg = _('Failed to dealloc network '
                            'for failed instance')
                    LOG.exception(msg, instance=instance)
        except Exception:
            exc_info = sys.exc_info()
            # try to re-schedule instance:
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            self._reschedule_or_error(
                context,
                instance,
                exc_info,
                requested_networks,
                admin_password,
                injected_files_orig,
                is_first_time,
                request_spec,
                filter_properties,
                bdms,
                legacy_bdm_in_spec)
            raise exc_info[0], exc_info[1], exc_info[2]

        # spawn success
        return instance, network_info

    def _heal_proxy_ports(self, context, network_info):
        physical_ports = []
        for netObj in network_info:
            net_id = netObj['network']['id']
            physical_net_id = None
            ovs_interface_mac = netObj['address']
            fixed_ips = []
            physicalNetIdExiFlag = False
            if net_id in self.cascading_info_mapping['networks']:
                physical_net_id = \
                    self.cascading_info_mapping['networks'][net_id]
                physicalNetIdExiFlag = True
                LOG.debug(_('Physical network has been created in physical'
                            ' leval,logicalNetId:%s, physicalNetId: %s '),
                          net_id, physical_net_id)
            if not physicalNetIdExiFlag:
                raise exception.NetworkNotFound(network_id=net_id)
            fixed_ips.append(
                {'ip_address':
                 netObj['network']['subnets']
                 [0]['ips'][0]['address']}
            )
            reqbody = {'port':
                       {
                           'tenant_id': instance['project_id'],
                           'admin_state_up': True,
                           'network_id': physical_net_id,
                           'mac_address': ovs_interface_mac,
                           'fixed_ips': fixed_ips,
                           'binding:profile':
                           {"cascading_port_id": netObj['ovs_interfaceid']}
                       }
                       }
            neutronClient = self._get_neutron_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_neutron_url)
            try:
                bodyReps = neutronClient.create_port(reqbody)
                physical_ports.append(bodyReps)
                LOG.debug(_('Finish to create Physical port, bodyReps %s'),
                          bodyReps)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Fail to create physical port reqbody %s .'),
                              reqbody)

        return physical_ports

    def _heal_proxy_networks(self, context, instance, network_info):
        cascaded_network_list = []
        self.cascading_info_mapping = {}
        self.cascading_info_mapping['networks'] = {}
        cascading_info_mapping_file = os.path.join(
            CONF.instances_path,
            'cascading_info_mapping.json')
        if os.path.isfile(cascading_info_mapping_file):
            cascading_info_mapping_file_context = libvirt_utils.load_file(
                cascading_info_mapping_file)
            mapping_networks = jsonutils.loads(
                cascading_info_mapping_file_context)['networks']
            self.cascading_info_mapping['networks'] = mapping_networks
        for netObj in network_info:
            net_id = netObj['network']['id']
            physicalNetIdExiFlag = False
            if net_id in self.cascading_info_mapping['networks']:
                physicalNetIdExiFlag = True
                physicalNetId = self.cascading_info_mapping['networks'][net_id]
                cascaded_network_list.append(physicalNetId)
                LOG.debug(_('Physical network has been exist, do not'
                            ' need to create,logicalNetId:%s,'
                            'physicalNetId: %s '), net_id, physicalNetId)
            if not physicalNetIdExiFlag:
                try:
                    LOG.debug(_('Physical network do not be exist,'
                                'need to create,logicalNetId:%s'),
                              net_id)
                    kwargs = {
                        'username': cfg.CONF.neutron_admin_username,
                        'password': cfg.CONF.neutron_admin_password,
                        'tenant': cfg.CONF.neutron_admin_tenant_name,
                        'auth_url': cfg.CONF.neutron_admin_auth_url,
                        'region_name': cfg.CONF.os_region_name
                    }
                    reqCon = compute_context.RequestContext(**kwargs)
                    neutron = neutronv2.get_client(reqCon, True)
                    logicalnets = self.network_api._get_available_networks(
                        reqCon,
                        instance['project_id'],
                        [net_id],
                        neutron)
                    neutronClient = self._get_neutron_pythonClient(
                        context,
                        cfg.CONF.proxy_region_name,
                        cfg.CONF.cascaded_neutron_url)

                    if logicalnets[0]['provider:network_type'] == 'vxlan':
                        reqNetwork = {
                            'network': {
                                'provider:network_type': logicalnets[0]['provider:network_type'],
                                'provider:segmentation_id': logicalnets[0]['provider:segmentation_id'],
                                'tenant_id': instance['project_id'],
                                'admin_state_up': True}}
                    elif logicalnets[0]['provider:network_type'] == 'flat':
                        reqNetwork = {
                            'network': {
                                'provider:network_type': logicalnets[0]['provider:network_type'],
                                'provider:physical_network': logicalnets[0]['provider:physical_network'],
                                'tenant_id': instance['project_id'],
                                'admin_state_up': True}}
                    else:
                        reqNetwork = {
                            'network': {
                                'provider:network_type': logicalnets[0]['provider:network_type'],
                                'provider:physical_network': logicalnets[0]['provider:physical_network'],
                                'provider:segmentation_id': logicalnets[0]['provider:segmentation_id'],
                                'tenant_id': instance['project_id'],
                                'admin_state_up': True}}
                    repsNetwork = neutronClient.create_network(reqNetwork)
                    self.cascading_info_mapping['networks'][net_id] = \
                        repsNetwork['network']['id']
                    cascaded_network_list.append(repsNetwork['network']['id'])
                    LOG.debug(_('Finish to create Physical network,'
                                'repsNetwork %s'), reqNetwork)
                    reqSubnet = {
                        'subnet': {
                            'network_id': repsNetwork['network']['id'],
                            'cidr': netObj['network']['subnets'][0]['cidr'],
                            'ip_version': netObj['network']['subnets'][0]['version'],
                            'tenant_id': instance['project_id']}}
                    neutronClient.create_subnet(reqSubnet)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_('Fail to synchronizate physical network'))

        cascading_info_mapping_path = os.path.join(
            CONF.instances_path,
            'cascading_info_mapping.json')
        libvirt_utils.write_to_file(
            cascading_info_mapping_path,
            jsonutils.dumps(
                self.cascading_info_mapping))

        return cascaded_network_list

    def _log_original_error(self, exc_info, instance_uuid):
        LOG.error(_('Error: %s') % exc_info[1], instance_uuid=instance_uuid,
                  exc_info=exc_info)

    def _cleanup_volumes(self, context, instance_uuid, bdms):
        for bdm in bdms:
            LOG.debug(_("terminating bdm %s") % bdm,
                      instance_uuid=instance_uuid)
            if bdm.volume_id and bdm.delete_on_termination:
                self.volume_api.delete(context, bdm.volume_id)
            # NOTE(vish): bdms will be deleted on instance destroy

    def _reschedule_or_error(
            self,
            context,
            instance,
            exc_info,
            requested_networks,
            admin_password,
            injected_files,
            is_first_time,
            request_spec,
            filter_properties,
            bdms=None,
            legacy_bdm_in_spec=True):
        instance_uuid = instance['uuid']
        rescheduled = False

        compute_utils.add_instance_fault_from_exc(
            context,
            self.conductor_api,
            instance,
            exc_info[1],
            exc_info=exc_info)
        self._notify_about_instance_usage(
            context,
            instance,
            'instance.create.error',
            fault=exc_info[1])

        try:
            LOG.debug(_("Clean up resource before rescheduling."),
                      instance=instance)
            if bdms is None:
                bdms = (block_device_obj.BlockDeviceMappingList.
                        get_by_instance_uuid(context, instance.uuid))

            self._shutdown_instance(context, instance,
                                    bdms, requested_networks)
            self._cleanup_volumes(context, instance['uuid'], bdms)
        except Exception:
            # do not attempt retry if clean up failed:
            with excutils.save_and_reraise_exception():
                self._log_original_error(exc_info, instance_uuid)

        return rescheduled

    def _quota_rollback(self, context, reservations, project_id=None,
                        user_id=None):
        if reservations:
            self.conductor_api.quota_rollback(context, reservations,
                                              project_id=project_id,
                                              user_id=user_id)

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
                self.consoleauth_rpcapi.delete_tokens_for_instance(
                    context,
                    instance.uuid)

    @hooks.add_hook("delete_instance")
    def _delete_instance(self, context, instance, bdms,
                         reservations=None):
        """Delete an instance on this host.  Commit or rollback quotas
        as necessary.
        """
        instance_uuid = instance['uuid']

        project_id, user_id = quotas_obj.ids_from_instance(context, instance)

        was_soft_deleted = instance['vm_state'] == vm_states.SOFT_DELETED
        if was_soft_deleted:
            # Instances in SOFT_DELETED vm_state have already had quotas
            # decremented.
            try:
                self._quota_rollback(context, reservations,
                                     project_id=project_id,
                                     user_id=user_id)
            except Exception:
                pass
            reservations = None

        try:
            events = self.instance_events.clear_events_for_instance(instance)
            if events:
                LOG.debug(_('Events pending at deletion: %(events)s'),
                          {'events': ','.join(events.keys())},
                          instance=instance)
            db_inst = obj_base.obj_to_primitive(instance)
            instance.info_cache.delete()
            self._notify_about_instance_usage(context, instance,
                                              "delete.start")
            self._shutdown_instance(context, db_inst, bdms)
            # NOTE(vish): We have already deleted the instance, so we have
            #             to ignore problems cleaning up the volumes. It
            #             would be nice to let the user know somehow that
            #             the volume deletion failed, but it is not
            #             acceptable to have an instance that can not be
            #             deleted. Perhaps this could be reworked in the
            #             future to set an instance fault the first time
            #             and to only ignore the failure if the instance
            #             is already in ERROR.
            try:
                self._cleanup_volumes(context, instance_uuid, bdms)
            except Exception as exc:
                err_str = _("Ignoring volume cleanup failure due to %s")
                LOG.warn(err_str % exc, instance=instance)
            # if a delete task succeed, always update vm state and task
            # state without expecting task state to be DELETING
            instance.vm_state = vm_states.DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            instance.save()
            system_meta = utils.instance_sys_meta(instance)
            db_inst = self.conductor_api.instance_destroy(
                context, obj_base.obj_to_primitive(instance))
            instance = instance_obj.Instance._from_db_object(context,
                                                             instance,
                                                             db_inst)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations,
                                     project_id=project_id,
                                     user_id=user_id)

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)
        self._complete_deletion(context,
                                instance,
                                bdms,
                                quotas,
                                system_meta)

    @wrap_exception()
    @wrap_instance_event
    @wrap_instance_fault
    def terminate_instance(self, context, instance, bdms, reservations):
        """Terminate an instance on this host."""
        # NOTE (ndipanov): If we get non-object BDMs, just get them from the
        # db again, as this means they are sent in the old format and we want
        # to avoid converting them back when we can just get them.
        # Remove this when we bump the RPC major version to 4.0
        if (bdms and
            any(not isinstance(bdm, block_device_obj.BlockDeviceMapping)
                for bdm in bdms)):
            bdms = (block_device_obj.BlockDeviceMappingList.
                    get_by_instance_uuid(context, instance.uuid))

        @utils.synchronized(instance['uuid'])
        def do_terminate_instance(instance, bdms):
            try:
                self._delete_instance(context, instance, bdms,
                                      reservations=reservations)
            except exception.InstanceNotFound:
                LOG.info(_("Instance disappeared during terminate"),
                         instance=instance)
            except Exception:
                # As we're trying to delete always go to Error if something
                # goes wrong that _delete_instance can't handle.
                with excutils.save_and_reraise_exception():
                    LOG.exception(_('Setting instance vm_state to ERROR'),
                                  instance=instance)
                    self._set_instance_error_state(context, instance['uuid'])

        do_terminate_instance(instance, bdms)

    def _heal_syn_server_metadata(self, context,
                                  cascadingInsId, cascadedInsId):
        """
        when only reboots the server scenario,
        needs to synchronize server metadata between
        logical and physical openstack.
        """
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedSerInf = cascadedNovaCli.servers.get(cascadedInsId)
        cascadedSerMedInf = cascadedSerInf.metadata

        cascadingNovCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.os_region_name,
            cfg.CONF.cascading_nova_url)
        cascadingSerInf = cascadingNovCli.servers.get(cascadingInsId)
        cascadingSerMedInf = cascadingSerInf.metadata

        tmpCascadedSerMedInf = dict(cascadedSerMedInf)
        del tmpCascadedSerMedInf['mapping_uuid']

        if tmpCascadedSerMedInf == cascadingSerMedInf:
            LOG.debug(_("Don't need to synchronize server metadata between"
                        "logical and physical openstack."))
            return
        else:
            LOG.debug(_('synchronize server metadata between logical and'
                        'physical openstack,cascadingSerMedInf %s,cascadedSerMedInf %s'),
                      cascadingSerMedInf,
                      cascadedSerMedInf)
            delKeys = []
            for key in cascadedSerMedInf:
                if key != 'mapping_uuid' and key not in cascadingSerMedInf:
                    delKeys.append(key)
            if len(delKeys) > 0:
                cascadedNovaCli.servers.delete_meta(cascadedInsId, delKeys)
            cascadingSerMedInf['mapping_uuid'] = \
                cascadedSerMedInf['mapping_uuid']
            cascadedNovaCli.servers.set_meta(cascadedInsId, cascadingSerMedInf)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def pause_instance(self, context, instance):
        """Pause an instance on this host."""
        context = context.elevated()
        LOG.audit(_('Pausing'), context=context, instance=instance)
        self._notify_about_instance_usage(context, instance, 'pause.start')
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        'in cascaded layer.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedNovaCli.servers.pause(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'pause.end')

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
        glanceClient = glance.GlanceClientWrapper()
        image = glanceClient.call(context, 2, 'get', image_id)

        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('can not snapshot instance server %s.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        resp_image_id = cascadedNovaCli.servers.create_image(
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

    def pre_start_hook(self):
        """After the service is initialized, but before we fully bring
        the service up by listening on RPC queues, make sure to update
        our available resources (and indirectly our available nodes).
        """
        self.update_available_resource(nova.context.get_admin_context())

    @contextlib.contextmanager
    def _error_out_instance_on_exception(self, context, instance_uuid,
                                         reservations=None,
                                         instance_state=vm_states.ACTIVE):
        try:
            yield
        except NotImplementedError as error:
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations)
                LOG.info(_("Setting instance back to %(state)s after: "
                           "%(error)s") %
                         {'state': instance_state, 'error': error},
                         instance_uuid=instance_uuid)
                self._instance_update(context, instance_uuid,
                                      vm_state=instance_state,
                                      task_state=None)
        except exception.InstanceFaultRollback as error:
            self._quota_rollback(context, reservations)
            LOG.info(_("Setting instance back to ACTIVE after: %s"),
                     error, instance_uuid=instance_uuid)
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None)
            raise error.inner_exception
        except Exception as error:
            LOG.exception(_('Setting instance vm_state to ERROR'),
                          instance_uuid=instance_uuid)
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations)
                self._set_instance_error_state(context, instance_uuid)

    def _get_volume_bdms(self, bdms, legacy=True):
        """Return only bdms that have a volume_id."""
        if legacy:
            return [bdm for bdm in bdms if bdm['volume_id']]
        else:
            return [bdm for bdm in bdms
                    if bdm['destination_type'] == 'volume']

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
        context = context.elevated()
        with self._error_out_instance_on_exception(context, instance['uuid']):
            LOG.audit(_("Rebuilding instance"), context=context,
                      instance=instance)
            if bdms is None:
                bdms = self.conductor_api.\
                    block_device_mapping_get_all_by_instance(
                        context, instance)
            # NOTE(sirp): this detach is necessary b/c we will reattach the
            # volumes in _prep_block_devices below.
            for bdm in self._get_volume_bdms(bdms):
                self.volume_api.detach(context, bdm['volume_id'])

            kwargs = {}
            disk_config = None
            if len(injected_files) > 0:
                kwargs['personality'] = injected_files
            cascaded_instance_id = instance['mapping_uuid']
            if cascaded_instance_id is None:
                LOG.error(_('Rebuild failed,can not find server %s '),
                          instance['uuid'])
                return
            if cfg.CONF.cascaded_glance_flag:
                image_uuid = self._get_cascaded_image_uuid(context,
                                                           image_ref)
            else:
                image_uuid = image_ref
            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            cascadedNovaCli.servers.rebuild(cascaded_instance_id, image_uuid,
                                            new_pass, disk_config, **kwargs)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def suspend_instance(self, context, instance):
        """Suspend the given instance."""
        context = context.elevated()

        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server '
                        'in cascaded layer.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedNovaCli.servers.suspend(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'suspend')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def resume_instance(self, context, instance):
        """Resume the given suspended instance."""
        context = context.elevated()
        LOG.audit(_('Resuming'), context=context, instance=instance)

        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('resume server,but can not find server'),
                      instance['uuid'])
            return

        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        try:
            cascadedNovaCli.servers.resume(cascaded_instance_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to resume server %s .'),
                          cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'resume')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def unpause_instance(self, context, instance):
        """Unpause a paused instance on this host."""
        context = context.elevated()
        LOG.audit(_('Unpausing'), context=context, instance=instance)
        self._notify_about_instance_usage(context, instance, 'unpause.start')
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        ' in cascaded layer.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedNovaCli.servers.unpause(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, 'unpause.end')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def start_instance(self, context, instance):
        """Starting an instance on this host."""
        self._notify_about_instance_usage(context, instance, "power_on.start")
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('start vm failed,can not find server'
                        ' in cascaded layer.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedNovaCli.servers.start(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, "power_on.end")

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def stop_instance(self, context, instance):
        """Stopping an instance on this host."""
        self._notify_about_instance_usage(context,
                                          instance, "power_off.start")
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('stop vm failed,can not find server'
                        ' in cascaded layer.'),
                      instance['uuid'])
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        cascadedNovaCli.servers.stop(cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, "power_off.end")

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def reboot_instance(self, context, instance, block_device_info,
                        reboot_type):
        """Reboot an instance on this host."""
        self._notify_about_instance_usage(context, instance, "reboot.start")
        context = context.elevated()
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('Reboot can not find server %s.'), instance)
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        try:
            self._heal_syn_server_metadata(context, instance['uuid'],
                                           cascaded_instance_id)
            cascadedNovaCli.servers.reboot(cascaded_instance_id, reboot_type)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to reboot server %s .'),
                          cascaded_instance_id)
        self._notify_about_instance_usage(context, instance, "reboot.end")

    def _delete_proxy_instance(self, context, instance):
        proxy_instance_id = instance['mapping_uuid']
        if proxy_instance_id is None:
            LOG.error(_('Delete server %s,but can not find this server'),
                      proxy_instance_id)
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        try:
            cascadedNovaCli.servers.delete(proxy_instance_id)
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

    def _get_instance_nw_info(self, context, instance, use_slave=False):
        """Get a list of dictionaries of network data of an instance."""
        if (not hasattr(instance, 'system_metadata') or
                len(instance['system_metadata']) == 0):
            # NOTE(danms): Several places in the code look up instances without
            # pulling system_metadata for performance, and call this function.
            # If we get an instance without it, re-fetch so that the call
            # to network_api (which requires it for instance_type) will
            # succeed.
            instance = instance_obj.Instance.get_by_uuid(context,
                                                         instance['uuid'],
                                                         use_slave=use_slave)

        network_info = self.network_api.get_instance_nw_info(context,
                                                             instance)
        return network_info

    def _get_instance_volume_block_device_info(self, context, instance,
                                               refresh_conn_info=False,
                                               bdms=None):
        """Transform volumes to the driver block_device format."""

        if not bdms:
            bdms = (block_device_obj.BlockDeviceMappingList.
                    get_by_instance_uuid(context, instance['uuid']))
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
            block_device_mapping = driver_block_device.legacy_block_devices(
                block_device_mapping)
        return {'block_device_mapping': block_device_mapping}

    def _try_deallocate_network(self, context, instance,
                                requested_networks=None):
        try:
            # tear down allocated network structure
            self._deallocate_network(context, instance, requested_networks)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to deallocate network for instance.'),
                          instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

    def _deallocate_network(self, context, instance,
                            requested_networks=None):
        LOG.debug(_('Deallocating network for instance'), instance=instance)
        self.network_api.deallocate_for_instance(
            context, instance, requested_networks=requested_networks)

    def _shutdown_instance(self, context, instance,
                           bdms, requested_networks=None, notify=True):
        """Shutdown an instance on this host."""
        context = context.elevated()
        LOG.audit(_('%(action_str)s instance') % {'action_str': 'Terminating'},
                  context=context, instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.start")

        # get network info before tearing down
        try:
            self._get_instance_nw_info(context, instance)
        except (exception.NetworkNotFound, exception.NoMoreFixedIps,
                exception.InstanceInfoCacheNotFound):
            network_model.NetworkInfo()

        # NOTE(vish) get bdms before destroying the instance
        vol_bdms = [bdm for bdm in bdms if bdm.is_volume]
#        block_device_info = self._get_instance_volume_block_device_info(
#            context, instance, bdms=bdms)

        # NOTE(melwitt): attempt driver destroy before releasing ip, may
        #                want to keep ip allocated for certain failures
        try:
            self._delete_proxy_instance(context, instance)
        except exception.InstancePowerOffFailure:
            # if the instance can't power off, don't release the ip
            with excutils.save_and_reraise_exception():
                pass
        except Exception:
            with excutils.save_and_reraise_exception():
                # deallocate ip and fail without proceeding to
                # volume api calls, preserving current behavior
                self._try_deallocate_network(context, instance,
                                             requested_networks)

        self._try_deallocate_network(context, instance, requested_networks)

        for bdm in vol_bdms:
            try:
                # NOTE(vish): actual driver detach done in driver.destroy, so
                #             just tell cinder that we are done with it.
                #                connector = self.driver.get_volume_connector(instance)
                #                self.volume_api.terminate_connection(context,
                #                                                     bdm.volume_id,
                #                                                     connector)
                self.volume_api.detach(context, bdm.volume_id)
            except exception.DiskNotFound as exc:
                LOG.warn(_('Ignoring DiskNotFound: %s') % exc,
                         instance=instance)
            except exception.VolumeNotFound as exc:
                LOG.warn(_('Ignoring VolumeNotFound: %s') % exc,
                         instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.end")

    def _get_nova_pythonClient(self, context, regNam, nova_url):
        try:
            #            kwargs = {'auth_token':None,
            #                      'username':context.values['user_name'],
            #                      'password':cfg.CONF.nova_admin_password,
            #                      'aws_creds':None,'tenant':None,
            #                      'tenant_id':context.values['tenant'],
            #                      'auth_url':cfg.CONF.keystone_auth_url,
            #                      'roles':context.values['roles'],
            #                      'is_admin':context.values['is_admin'],
            #                      'region_name':regNam
            #                      }
            kwargs = {
                'auth_token': context.auth_token,
                'username': context.user_name,
                'tenant_id': context.tenant,
                'auth_url': cfg.CONF.keystone_auth_url,
                'roles': context.roles,
                'is_admin': context.is_admin,
                'region_name': regNam,
                'nova_url': nova_url
            }
            reqCon = compute_context.RequestContext(**kwargs)
            openStackClients = clients.OpenStackClients(reqCon)
            novaClient = openStackClients.nova()
            return novaClient
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get nova python client.'))

    def _get_neutron_pythonClient(self, context, regNam, neutrol_url):
        try:
            kwargs = {
                'endpoint_url': neutrol_url,
                'timeout': CONF.neutron_url_timeout,
                'insecure': CONF.neutron_api_insecure,
                'ca_cert': CONF.neutron_ca_certificates_file,
                'username': CONF.neutron_admin_username,
                'password': CONF.neutron_admin_password,
                'tenant_name': CONF.neutron_admin_tenant_name,
                'auth_url': CONF.neutron_admin_auth_url,
                'auth_strategy': CONF.neutron_auth_strategy
            }
            neutronClient = clientv20.Client(**kwargs)
            return neutronClient
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get neutron python client.'))

    def _reschedule(self, context, request_spec, filter_properties,
                    instance_uuid, scheduler_method, method_args, task_state,
                    exc_info=None):
        """Attempt to re-schedule a compute operation."""

        retry = filter_properties.get('retry', None)
        if not retry:
            # no retry information, do not reschedule.
            LOG.debug(_("Retry info not present, will not reschedule"),
                      instance_uuid=instance_uuid)
            return

        if not request_spec:
            LOG.debug(_("No request spec, will not reschedule"),
                      instance_uuid=instance_uuid)
            return

        request_spec['instance_uuids'] = [instance_uuid]

        LOG.debug(_("Re-scheduling %(method)s: attempt %(num)d") %
                  {'method': scheduler_method.func_name,
                   'num': retry['num_attempts']}, instance_uuid=instance_uuid)

        # reset the task state:
        self._instance_update(context, instance_uuid, task_state=task_state)

        if exc_info:
            # stringify to avoid circular ref problem in json serialization:
            retry['exc'] = traceback.format_exception(*exc_info)

        scheduler_method(context, *method_args)
        return True

    def _reschedule_resize_or_reraise(
            self,
            context,
            image,
            instance,
            exc_info,
            instance_type,
            reservations,
            request_spec,
            filter_properties):
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
            # NOTE(comstud): remove the scheduler RPCAPI method when
            # this is adjusted to send to conductor... and then
            # deprecate the scheduler manager method.
            scheduler_method = self.scheduler_rpcapi.prep_resize
            instance_p = obj_base.obj_to_primitive(instance)
            method_args = (instance_p, instance_type, image, request_spec,
                           filter_properties, reservations)
            task_state = task_states.RESIZE_PREP

            rescheduled = self._reschedule(
                context,
                request_spec,
                filter_properties,
                instance_uuid,
                scheduler_method,
                method_args,
                task_state,
                exc_info)
        except Exception as error:
            rescheduled = False
            LOG.exception(_("Error trying to reschedule"),
                          instance_uuid=instance_uuid)
            compute_utils.add_instance_fault_from_exc(
                context,
                self.conductor_api,
                instance,
                error,
                exc_info=sys.exc_info())
            self._notify_about_instance_usage(context, instance,
                                              'resize.error', fault=error)

        if rescheduled:
            self._log_original_error(exc_info, instance_uuid)
            compute_utils.add_instance_fault_from_exc(
                context,
                self.conductor_api,
                instance,
                exc_info[1],
                exc_info=exc_info)
            self._notify_about_instance_usage(
                context,
                instance,
                'resize.error',
                fault=exc_info[1])
        else:
            # not re-scheduling
            raise exc_info[0], exc_info[1], exc_info[2]

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
            LOG.debug(_("No node specified, defaulting to %s"), node,
                      instance=instance)

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            self.conductor_api.notify_usage_exists(
                context, instance, current_period=True)
            self._notify_about_instance_usage(
                context, instance, "resize.prep.start")
            try:
                self._prep_resize(context, image, instance,
                                  instance_type, reservations,
                                  request_spec, filter_properties,
                                  node)
            except Exception:
                # try to re-schedule the resize elsewhere:
                exc_info = sys.exc_info()
                self._reschedule_resize_or_reraise(
                    context,
                    image,
                    instance,
                    exc_info,
                    instance_type,
                    reservations,
                    request_spec,
                    filter_properties)
            finally:
                extra_usage_info = dict(
                    new_instance_type=instance_type['name'],
                    new_instance_type_id=instance_type['id'])

                self._notify_about_instance_usage(
                    context, instance, "resize.prep.end",
                    extra_usage_info=extra_usage_info)

    def _prep_resize(self, context, image, instance, instance_type,
                     reservations, request_spec, filter_properties, node):

        if not filter_properties:
            filter_properties = {}

        if not instance['host']:
            self._set_instance_error_state(context, instance['uuid'])
            msg = _('Instance has no source host')
            raise exception.MigrationError(msg)

        same_host = instance['host'] == self.host
        if same_host and not CONF.allow_resize_to_same_host:
            self._set_instance_error_state(context, instance['uuid'])
            msg = _('destination same as source!')
            raise exception.MigrationError(msg)

        # NOTE(danms): Stash the new instance_type to avoid having to
        # look it up in the database later
        sys_meta = instance.system_metadata
        flavors.save_flavor_info(sys_meta, instance_type, prefix='new_')
        # NOTE(mriedem): Stash the old vm_state so we can set the
        # resized/reverted instance back to the same state later.
        vm_state = instance['vm_state']
        LOG.debug(_('Stashing vm_state: %s'), vm_state, instance=instance)
        sys_meta['old_vm_state'] = vm_state
        instance.save()

        limits = filter_properties.get('limits', {})
        rt = self._get_resource_tracker(node)
        with rt.resize_claim(context, instance, instance_type,
                             limits=limits) as claim:
            LOG.audit(_('Migrating'), context=context, instance=instance)
            self.compute_rpcapi.resize_instance(
                context,
                instance,
                claim.migration,
                image,
                instance_type,
                reservations)

    def _terminate_volume_connections(self, context, instance, bdms):
        connector = self.driver.get_volume_connector(instance)
        for bdm in bdms:
            if bdm.is_volume:
                self.volume_api.terminate_connection(context, bdm.volume_id,
                                                     connector)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @errors_out_migration
    @wrap_instance_fault
    def resize_instance(self, context, instance, image,
                        reservations, migration, instance_type):
        """Starts the migration of a running instance to another host."""
        with self._error_out_instance_on_exception(context, instance.uuid,
                                                   reservations):
            if not instance_type:
                instance_type = flavor_obj.Flavor.get_by_id(
                    context, migration['new_instance_type_id'])

            network_info = self._get_instance_nw_info(context, instance)

            migration.status = 'migrating'
            migration.save(context.elevated())

            instance.task_state = task_states.RESIZE_MIGRATING
            instance.save(expected_task_state=task_states.RESIZE_PREP)

            self._notify_about_instance_usage(
                context, instance, "resize.start", network_info=network_info)

            bdms = (block_device_obj.BlockDeviceMappingList.
                    get_by_instance_uuid(context, instance.uuid))
#            block_device_info = self._get_instance_volume_block_device_info(
#                                context, instance, bdms=bdms)

#            disk_info = self.driver.migrate_disk_and_power_off(
#                    context, instance, migration.dest_host,
#                    instance_type, network_info,
#                    block_device_info)
            disk_info = None

            self._terminate_volume_connections(context, instance, bdms)

            migration_p = obj_base.obj_to_primitive(migration)
            instance_p = obj_base.obj_to_primitive(instance)
            self.conductor_api.network_migrate_instance_start(context,
                                                              instance_p,
                                                              migration_p)

            migration.status = 'post-migrating'
            migration.save(context.elevated())

            instance.host = migration.dest_compute
            instance.node = migration.dest_node
            instance.task_state = task_states.RESIZE_MIGRATED
            instance.save(expected_task_state=task_states.RESIZE_MIGRATING)

            self.compute_rpcapi.finish_resize(
                context,
                instance,
                migration,
                image,
                disk_info,
                migration.dest_compute,
                reservations=reservations)

            self._notify_about_instance_usage(context, instance, "resize.end",
                                              network_info=network_info)
            self.instance_events.clear_events_for_instance(instance)

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
        try:
            self._finish_resize(context, instance, migration,
                                disk_info, image)
            self._quota_commit(context, reservations)
        except Exception:
            LOG.exception(_('Setting instance vm_state to ERROR'),
                          instance=instance)
            with excutils.save_and_reraise_exception():
                try:
                    self._quota_rollback(context, reservations)
                except Exception as qr_error:
                    LOG.exception(_("Failed to rollback quota for failed "
                                    "finish_resize: %s"),
                                  qr_error, instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

    @object_compat
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def reserve_block_device_name(self, context, instance, device,
                                  volume_id, disk_bus=None, device_type=None):
        # NOTE(ndipanov): disk_bus and device_type will be set to None if not
        # passed (by older clients) and defaulted by the virt driver. Remove
        # default values on the next major RPC version bump.

        @utils.synchronized(instance['uuid'])
        def do_reserve():
            bdms = (
                block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid))

            device_name = compute_utils.get_device_name_for_instance(
                context, instance, bdms, device)

            # NOTE(vish): create bdm here to avoid race condition
            bdm = block_device_obj.BlockDeviceMapping(
                source_type='volume', destination_type='volume',
                instance_uuid=instance.uuid,
                volume_id=volume_id or 'reserved',
                device_name=device_name,
                disk_bus=disk_bus, device_type=device_type)
            bdm.create(context)

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
            bdm = block_device_obj.BlockDeviceMapping.get_by_volume_id(
                context, volume_id)
        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm)
        try:
            return self._attach_volume(context, instance, driver_bdm)
        except Exception:
            with excutils.save_and_reraise_exception():
                bdm.destroy(context)

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
                bodyReps = self.volume_api.get(context, bdm.volume_id)
                proxy_volume_id = bodyReps['volume_metadata']['mapping_uuid']
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

            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            bodyReps = cascadedNovaCli.volumes.create_server_volume(
                instance['mapping_uuid'],
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

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def detach_volume(self, context, volume_id, instance):
        """Detach a volume from an instance."""
        bdm = block_device_obj.BlockDeviceMapping.get_by_volume_id(
            context, volume_id)
        if CONF.volume_usage_poll_interval > 0:
            vol_stats = []
            mp = bdm.device_name
            # Handle bootable volumes which will not contain /dev/
            if '/dev/' in mp:
                mp = mp[5:]
            try:
                vol_stats = self.driver.block_stats(instance['name'], mp)
            except NotImplementedError:
                pass

            if vol_stats:
                LOG.debug(_("Updating volume usage cache with totals"),
                          instance=instance)
                rd_req, rd_bytes, wr_req, wr_bytes, flush_ops = vol_stats
                self.conductor_api.vol_usage_update(context, volume_id,
                                                    rd_req, rd_bytes,
                                                    wr_req, wr_bytes,
                                                    instance,
                                                    update_totals=True)

        self._detach_volume(context, instance, bdm)
        self.volume_api.detach(context.elevated(), volume_id)
        bdm.destroy()
        info = dict(volume_id=volume_id)
        self._notify_about_instance_usage(
            context, instance, "volume.detach", extra_usage_info=info)

    def _detach_volume(self, context, instance, bdm):
        """Do the actual driver detach using block device mapping."""
        mp = bdm.device_name
        volume_id = bdm.volume_id

        LOG.audit(_('Detach volume %(volume_id)s from mountpoint %(mp)s'),
                  {'volume_id': volume_id, 'mp': mp},
                  context=context, instance=instance)
        try:
            proxy_volume_id = None
            try:
                bodyReps = self.volume_api.get(context, volume_id)
                proxy_volume_id = bodyReps['volume_metadata']['mapping_uuid']
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to get  physical volume id ,logical'
                                ' volume id %s,device %s'),
                              volume_id, mp)
            if proxy_volume_id is None:
                LOG.error(_('detach_volume can not find physical volume id %s '
                            'in physical opensack lay,logical volume id %s'),
                          instance['uuid'], volume_id)
                return
            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            bodyReps = cascadedNovaCli.volumes.delete_server_volume(
                instance['mapping_uuid'], proxy_volume_id)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Failed to detach volume %(volume_id)s '
                                'from %(mp)s'),
                              {'volume_id': volume_id, 'mp': mp},
                              context=context, instance=instance)
                self.volume_api.roll_detaching(context, volume_id)

    @wrap_exception()
    @wrap_instance_event
    @wrap_instance_fault
    def confirm_resize(self, context, instance, reservations, migration):

        @utils.synchronized(instance['uuid'])
        def do_confirm_resize(context, instance, migration_id):
            # NOTE(wangpan): Get the migration status from db, if it has been
            #                confirmed, we do nothing and return here
            LOG.debug(_("Going to confirm migration %s") % migration_id,
                      context=context, instance=instance)
            try:
                # TODO(russellb) Why are we sending the migration object just
                # to turn around and look it up from the db again?
                migration = migration_obj.Migration.get_by_id(
                    context.elevated(), migration_id)
            except exception.MigrationNotFound:
                LOG.error(_("Migration %s is not found during confirmation") %
                          migration_id, context=context, instance=instance)
                return

            if migration.status == 'confirmed':
                LOG.info(_("Migration %s is already confirmed") %
                         migration_id, context=context, instance=instance)
                return
            elif migration.status not in ('finished', 'confirming'):
                LOG.warn(_("Unexpected confirmation status '%(status)s' of "
                           "migration %(id)s, exit confirmation process") %
                         {"status": migration.status, "id": migration_id},
                         context=context, instance=instance)
                return

            # NOTE(wangpan): Get the instance from db, if it has been
            #                deleted, we do nothing and return here
            expected_attrs = ['metadata', 'system_metadata']
            try:
                instance = instance_obj.Instance.get_by_uuid(
                    context,
                    instance.uuid,
                    expected_attrs=expected_attrs)
            except exception.InstanceNotFound:
                LOG.info(_("Instance is not found during confirmation"),
                         context=context, instance=instance)
                return

            self._confirm_resize(context, instance, reservations=reservations,
                                 migration=migration)

        do_confirm_resize(context, instance, migration.id)

    def _confirm_resize(self, context, instance, reservations=None,
                        migration=None):
        """Destroys the source instance."""
        self._notify_about_instance_usage(context, instance,
                                          "resize.confirm.start")

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            # NOTE(danms): delete stashed migration information
            #            sys_meta, instance_type = self._cleanup_stored_instance_types(
            #                migration, instance)
            #            sys_meta.pop('old_vm_state', None)
            #
            #            instance.system_metadata = sys_meta
            #            instance.save()

            # NOTE(tr3buchet): tear down networks on source host
            self.network_api.setup_networks_on_host(
                context,
                instance,
                migration.source_compute,
                teardown=True)

            network_info = self._get_instance_nw_info(context, instance)
            cascaded_instance_id = instance['mapping_uuid']
            if cascaded_instance_id is None:
                LOG.debug(_('Confirm resize can not find server %s.'),
                          instance['uuid'])
                return
            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            try:
                cascadedNovaCli.servers.confirm_resize(cascaded_instance_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to confirm resize server %s .'),
                              cascaded_instance_id)

            migration.status = 'confirmed'
            migration.save(context.elevated())

#            rt = self._get_resource_tracker(migration.source_node)
#            rt.drop_resize_claim(instance, prefix='old_')

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
                LOG.debug(_("Resized/migrated instance is powered off. "
                            "Setting vm_state to '%s'."), vm_state,
                          instance=instance)
            else:
                vm_state = vm_states.ACTIVE

            instance.vm_state = vm_state
            instance.task_state = None
            instance.save(expected_task_state=[None, task_states.DELETING])

            self._notify_about_instance_usage(
                context, instance, "resize.confirm.end",
                network_info=network_info)

            self._quota_commit(context, reservations)

    @messaging.expected_exceptions(NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_console_output(self, context, instance, tail_length):
        """Send the console output for the given instance."""
        instance = instance_obj.Instance._from_db_object(
            context, instance_obj.Instance(), instance)
        context = context.elevated()
        LOG.audit(_("Get console output"), context=context,
                  instance=instance)
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.debug(_('get_vnc_console can not find server %s in'
                        ' cascading_info_mapping %s .'),
                      instance['uuid'], self.cascading_info_mapping)
            return
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)

        try:
            output = cascadedNovaCli.servers.get_console_output(
                cascaded_instance_id, tail_length)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to get_vnc_console server %s .'),
                          cascaded_instance_id)
        return output

    @object_compat
    @wrap_exception()
    @wrap_instance_fault
    def get_vnc_console(self, context, console_type, instance):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug(_("Getting vnc console"), instance=instance)
        token = str(uuid.uuid4())

        if not CONF.vnc_enabled:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # access info token
            cascaded_instance_id = instance['mapping_uuid']
            if cascaded_instance_id is None:
                LOG.debug(_('Get vnc_console can not find server %s .'),
                          instance['uuid'])
                return
            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            try:
                bodyReps = cascadedNovaCli.servers.get_vnc_console(
                    cascaded_instance_id, console_type)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to get_vnc_console server %s .'),
                              cascaded_instance_id)
            if console_type != 'novnc' and console_type != 'xvpvnc':
                # For essex, novncproxy_base_url must include the full path
                # including the html file (like http://myhost/vnc_auto.html)
                raise exception.ConsoleTypeInvalid(console_type=console_type)
            connect_info = {}
            connect_info['token'] = token
            connect_info['access_url'] = bodyReps['console']['url']
            connect_info['host'] = CONF.vncserver_proxyclient_address
            connect_info['port'] = CONF.novncproxy_port
            connect_info['internal_access_path'] = None
        except exception.InstanceNotFound:
            if instance['vm_state'] != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        return connect_info

    def _cleanup_stored_instance_types(self, migration, instance,
                                       restore_old=False):
        """Clean up "old" and "new" instance_type information stored in
        instance's system_metadata. Optionally update the "current"
        instance_type to the saved old one first.

        Returns the updated system_metadata as a dict, as well as the
        post-cleanup current instance type.
        """
        sys_meta = instance.system_metadata
        if restore_old:
            instance_type = flavors.extract_flavor(instance, 'old_')
            sys_meta = flavors.save_flavor_info(sys_meta, instance_type)
        else:
            instance_type = flavors.extract_flavor(instance)

        flavors.delete_flavor_info(sys_meta, 'old_')
        flavors.delete_flavor_info(sys_meta, 'new_')

        return sys_meta, instance_type

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def finish_revert_resize(self, context, instance, reservations, migration):
        """Finishes the second half of reverting a resize.

        Bring the original source instance state back (active/shutoff) and
        revert the resized attributes in the database.

        """
        with self._error_out_instance_on_exception(context, instance.uuid,
                                                   reservations):
            self._get_instance_nw_info(context, instance)

            self._notify_about_instance_usage(
                context, instance, "resize.revert.start")

            sys_meta, instance_type = self._cleanup_stored_instance_types(
                migration, instance, True)

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

            self.network_api.setup_networks_on_host(
                context,
                instance,
                migration['source_compute'])

#            block_device_info = self._get_instance_volume_block_device_info(
#                    context, instance, refresh_conn_info=True)

            power_on = old_vm_state != vm_states.STOPPED
#            self.driver.finish_revert_migration(context, instance,
#                                       network_info,
#                                       block_device_info, power_on)
            cascaded_instance_id = instance['mapping_uuid']
            if cascaded_instance_id is None:
                LOG.debug(_('Revert resize can not find server %s.'),
                          instance['uuid'])
                return
            cascadedNovaCli = self._get_nova_pythonClient(
                context,
                cfg.CONF.proxy_region_name,
                cfg.CONF.cascaded_nova_url)
            try:
                cascadedNovaCli.servers.revert_resize(cascaded_instance_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Failed to resize server %s .'),
                              cascaded_instance_id)

            instance.launched_at = timeutils.utcnow()
            instance.save(expected_task_state=task_states.RESIZE_REVERTING)

            instance_p = obj_base.obj_to_primitive(instance)
            migration_p = obj_base.obj_to_primitive(migration)
            self.conductor_api.network_migrate_instance_finish(context,
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

            self._quota_commit(context, reservations)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def revert_resize(self, context, instance, migration, reservations):
        """Destroys the new instance on the destination machine.

        Reverts the model changes, and powers on the old instance on the
        source machine.

        """
        # NOTE(comstud): A revert_resize is essentially a resize back to
        # the old size, so we need to send a usage event here.
        self.conductor_api.notify_usage_exists(
            context, instance, current_period=True)

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            # NOTE(tr3buchet): tear down networks on destination host
            self.network_api.setup_networks_on_host(context, instance,
                                                    teardown=True)

            instance_p = obj_base.obj_to_primitive(instance)
            migration_p = obj_base.obj_to_primitive(migration)
            self.conductor_api.network_migrate_instance_start(context,
                                                              instance_p,
                                                              migration_p)

#            network_info = self._get_instance_nw_info(context, instance)
            bdms = (block_device_obj.BlockDeviceMappingList.
                    get_by_instance_uuid(context, instance.uuid))
#            block_device_info = self._get_instance_volume_block_device_info(
#                                context, instance, bdms=bdms)

#            self.driver.destroy(context, instance, network_info,
#                                block_device_info)

            self._terminate_volume_connections(context, instance, bdms)

            migration.status = 'reverted'
            migration.save(context.elevated())

            rt = self._get_resource_tracker(instance.node)
            rt.drop_resize_claim(instance)

            self.compute_rpcapi.finish_revert_resize(
                context,
                instance,
                migration,
                migration.source_compute,
                reservations=reservations)

    def _finish_resize(self, context, instance, migration, disk_info,
                       image):
        old_instance_type_id = migration['old_instance_type_id']
        new_instance_type_id = migration['new_instance_type_id']
        old_instance_type = flavors.extract_flavor(instance)
        sys_meta = instance.system_metadata
        # NOTE(mriedem): Get the old_vm_state so we know if we should
        # power on the instance. If old_vm_sate is not set we need to default
        # to ACTIVE for backwards compatibility
        sys_meta.get('old_vm_state', vm_states.ACTIVE)
        flavors.save_flavor_info(sys_meta,
                                 old_instance_type,
                                 prefix='old_')

        if old_instance_type_id != new_instance_type_id:
            instance_type = flavors.extract_flavor(instance, prefix='new_')
            flavors.save_flavor_info(sys_meta, instance_type)
            instance.instance_type_id = instance_type['id']
            instance.memory_mb = instance_type['memory_mb']
            instance.vcpus = instance_type['vcpus']
            instance.root_gb = instance_type['root_gb']
            instance.ephemeral_gb = instance_type['ephemeral_gb']
            instance.system_metadata = sys_meta
            instance.save()

        # NOTE(tr3buchet): setup networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                migration['dest_compute'])

        instance_p = obj_base.obj_to_primitive(instance)
        migration_p = obj_base.obj_to_primitive(migration)
        self.conductor_api.network_migrate_instance_finish(context,
                                                           instance_p,
                                                           migration_p)

        network_info = self._get_instance_nw_info(context, instance)

        instance.task_state = task_states.RESIZE_FINISH
        instance.system_metadata = sys_meta
#        instance.save(expected_task_state=task_states.RESIZE_MIGRATED)
        instance.save()

        self._notify_about_instance_usage(
            context, instance, "finish_resize.start",
            network_info=network_info)

#        block_device_info = self._get_instance_volume_block_device_info(
#                            context, instance, refresh_conn_info=True)

        # NOTE(mriedem): If the original vm_state was STOPPED, we don't
        # automatically power on the instance after it's migrated
#        power_on = old_vm_state != vm_states.STOPPED
#        self.driver.finish_migration(context, migration, instance,
#                                     disk_info,
#                                     network_info,
#                                     image, resize_instance,
#                                     block_device_info, power_on)
        cascaded_instance_id = instance['mapping_uuid']
        if cascaded_instance_id is None:
            LOG.error(_('Finish resize can not find server %s %s .'),
                      instance['uuid'])
            return

        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        try:
            cascadedNovaCli.servers.resize(
                cascaded_instance_id,
                instance.system_metadata['new_instance_type_flavorid'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to resize server %s .'),
                          cascaded_instance_id)

        migration.status = 'finished'
        migration.save(context.elevated())

#        instance.vm_state = vm_states.RESIZED
#        instance.task_state = None
#        instance.launched_at = timeutils.utcnow()
#        instance.save(expected_task_state=task_states.RESIZE_FINISH)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.end",
            network_info=network_info)

    def _quota_commit(self, context, reservations, project_id=None,
                      user_id=None):
        if reservations:
            self.conductor_api.quota_commit(context, reservations,
                                            project_id=project_id,
                                            user_id=user_id)

    def _heal_syn_flavor_info(self, context, instance_type):
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        try:
            flavors = cascadedNovaCli.flavors.get(instance_type['flavorid'])
        except Exception:
            with excutils.save_and_reraise_exception():
                flavors = cascadedNovaCli.flavors.create(
                    name=instance_type['name'],
                    ram=instance_type['memory_mb'],
                    vcpus=instance_type['vcpus'],
                    disk=instance_type['root_gb'],
                    flavorid=instance_type['flavorid'],
                    ephemeral=instance_type['ephemeral_gb'],
                    swap=instance_type['swap'],
                    rxtx_factor=instance_type['rxtx_factor']
                )
                LOG.debug(_('creat flavor %s .'), instance_type['flavorid'])

    def _heal_syn_keypair_info(self, context, instance):
        LOG.debug(_('Start to synchronize keypair %s to cascaded openstack'),
                  instance['key_name'])
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        keyPai = cascadedNovaCli.keypairs.list()
        keyNam = instance['key_name']
        keyDat = instance['key_data']
        keyExiFlag = False
        for key in keyPai:
            if keyNam == key.name:
                keyExiFlag = True
                break
        if keyExiFlag:
            LOG.debug(_('Keypair is not updated ,no need to synchronize'),
                      keyNam)
            return
        else:
            cascadedNovaCli.keypairs.create(keyNam, keyDat)
        LOG.debug(_('Finish to synchronize keypair %s to cascaded openstack'),
                  instance['key_name'])

    def _get_cascaded_image_uuid(self, context, image_uuid):
        try:
            glanceClient = glance.GlanceClientWrapper()
            image = glanceClient.call(context, 2, 'get', image_uuid)
            cascaded_image_uuid = None
            for location in image['locations']:
                if location['url'] and location['url'].startswith(
                        cfg.CONF.cascaded_glance_url):
                    cascaded_image_uuid = location['url'].split('/')[-1]
                    return cascaded_image_uuid
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error while trying to get cascaded"
                            " image and cascading uuid %s")
                          % image_uuid)

    def _proxy_run_instance(
            self,
            context,
            instance,
            request_spec=None,
            filter_properties=None,
            requested_networks=None,
            injected_files=None,
            admin_password=None,
            is_first_time=False,
            node=None,
            legacy_bdm_in_spec=True,
            physical_ports=None):
        cascadedNovaCli = self._get_nova_pythonClient(
            context,
            cfg.CONF.proxy_region_name,
            cfg.CONF.cascaded_nova_url)
        nicsList = []
        for port in physical_ports:
            nicsList.append({'port-id': port['port']['id']})
#        for net in requested_networks:
#            nicsList.append({'net-id':net[0]})
        metadata = request_spec['instance_properties']['metadata']
        metadata['mapping_uuid'] = instance['uuid']

        try:
            self._heal_syn_flavor_info(context, request_spec['instance_type'])
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
                                                   volume_id)
                            bdm.destroy(context)
                    try:
                        bodyReps = self.volume_api.get(
                            context,
                            block_device_mapping_value['volume_id'])
                        proxy_volume_id = \
                            bodyReps['volume_metadata']['mapping_uuid']
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

            bodyResponse = cascadedNovaCli.servers.create(
                name=request_spec['instance_properties']['display_name'],
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
            self._instance_update(context, instance['uuid'],
                                  vm_state=vm_states.BUILDING,
                                  mapping_uuid=bodyResponse.id,
                                  task_state=None)
        except Exception:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to create server for instance.'),
                          instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

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

    def _validate_instance_group_policy(self, context, instance,
                                        filter_properties):
        # NOTE(russellb) Instance group policy is enforced by the scheduler.
        # However, there is a race condition with the enforcement of
        # anti-affinity.  Since more than one instance may be scheduled at the
        # same time, it's possible that more than one instance with an
        # anti-affinity policy may end up here.  This is a validation step to
        # make sure that starting the instance here doesn't violate the policy.

        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        group_uuid = scheduler_hints.get('group')
        if not group_uuid:
            return

        @utils.synchronized(group_uuid)
        def _do_validation(context, instance, group_uuid):
            group = instance_group_obj.InstanceGroup.get_by_uuid(context,
                                                                 group_uuid)
            if 'anti-affinity' not in group.policies:
                return

            group_hosts = group.get_hosts(context, exclude=[instance['uuid']])
            if self.host in group_hosts:
                msg = _("Anti-affinity instance group policy was violated.")
                raise exception.RescheduledException(
                    instance_uuid=instance['uuid'],
                    reason=msg)

        _do_validation(context, instance, group_uuid)

    def _allocate_network_async(self, context, instance, requested_networks,
                                macs, security_groups, is_vpn, dhcp_options):
        """Method used to allocate networks in the background.

        Broken out for testing.
        """
        LOG.debug(_("Allocating IP information in the background."),
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
                LOG.debug(_('Instance network_info: |%s|'), nwinfo,
                          instance=instance)
                # NOTE(alaski): This can be done more cleanly once we're sure
                # we'll receive an object.
                sys_meta = utils.metadata_to_dict(instance['system_metadata'])
                sys_meta['network_allocated'] = 'True'
                self._instance_update(context, instance['uuid'],
                                      system_metadata=sys_meta)
                return nwinfo
            except Exception:
                exc_info = sys.exc_info()
                log_info = {'attempt': attempt,
                            'attempts': attempts}
                if attempt == attempts:
                    LOG.exception(_('Instance failed network setup '
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

    def _allocate_network(self, context, instance, requested_networks, macs,
                          security_groups, dhcp_options):
        """Start network allocation asynchronously.  Return an instance
        of NetworkInfoAsyncWrapper that can be used to retrieve the
        allocated networks when the operation has finished.
        """
        # NOTE(comstud): Since we're allocating networks asynchronously,
        # this task state has little meaning, as we won't be in this
        # state for very long.
        instance = self._instance_update(context, instance['uuid'],
                                         vm_state=vm_states.BUILDING,
                                         task_state=task_states.NETWORKING,
                                         expected_task_state=[None])
        is_vpn = pipelib.is_vpn_image(instance['image_ref'])
        return network_model.NetworkInfoAsyncWrapper(
            self._allocate_network_async, context, instance,
            requested_networks, macs, security_groups, is_vpn,
            dhcp_options)
