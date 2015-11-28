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

import base64
import contextlib
import functools
import six
import sys
import time
import traceback

from oslo_config import cfg
import oslo_log.log as logging
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import strutils

from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common.i18n import _LW
from tricircle.common.nova_lib import block_device
from tricircle.common.nova_lib import compute_manager
from tricircle.common.nova_lib import compute_utils
from tricircle.common.nova_lib import conductor
from tricircle.common.nova_lib import driver_block_device
from tricircle.common.nova_lib import exception
from tricircle.common.nova_lib import manager
from tricircle.common.nova_lib import network
from tricircle.common.nova_lib import network_model
from tricircle.common.nova_lib import objects
from tricircle.common.nova_lib import openstack_driver
from tricircle.common.nova_lib import pipelib
from tricircle.common.nova_lib import rpc
from tricircle.common.nova_lib import task_states
from tricircle.common.nova_lib import utils
from tricircle.common.nova_lib import vm_states
from tricircle.common.nova_lib import volume
import tricircle.common.utils as t_utils


CONF = cfg.CONF

compute_opts = [
    cfg.StrOpt('default_access_ip_network_name',
               help='Name of network to use to set access IPs for instances'),
    cfg.IntOpt('network_allocate_retries',
               default=0,
               help="Number of times to retry network allocation on failures"),
]
CONF.register_opts(compute_opts)


LOG = logging.getLogger(__name__)

SERVICE_NAME = 'proxy_compute'

get_notifier = functools.partial(rpc.get_notifier, service=SERVICE_NAME)
wrap_exception = functools.partial(exception.wrap_exception,
                                   get_notifier=get_notifier)
reverts_task_state = compute_manager.reverts_task_state
wrap_instance_fault = compute_manager.wrap_instance_fault
wrap_instance_event = compute_manager.wrap_instance_event


class ProxyComputeManager(manager.Manager):

    target = messaging.Target(version='4.0')

    def __init__(self, *args, **kwargs):
        self.is_neutron_security_groups = (
            openstack_driver.is_neutron_security_groups())
        self.use_legacy_block_device_info = False

        self.network_api = network.API()
        self.volume_api = volume.API()
        self.conductor_api = conductor.API()
        self.compute_task_api = conductor.ComputeTaskAPI()

        super(ProxyComputeManager, self).__init__(
            service_name=SERVICE_NAME, *args, **kwargs)

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
            pass

    def _deallocate_network(self, context, instance,
                            requested_networks=None):
        LOG.debug('Deallocating network for instance', instance=instance)
        self.network_api.deallocate_for_instance(
            context, instance, requested_networks=requested_networks)

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

    def _instance_update(self, context, instance, **kwargs):
        """Update an instance in the database using kwargs as value."""

        for k, v in kwargs.items():
            setattr(instance, k, v)
        instance.save()

    def _set_instance_obj_error_state(self, context, instance,
                                      clean_task_state=False):
        try:
            instance.vm_state = vm_states.ERROR
            if clean_task_state:
                instance.task_state = None
            instance.save()
        except exception.InstanceNotFound:
            LOG.debug('Instance has been destroyed from under us while '
                      'trying to set it to ERROR', instance=instance)

    def _notify_about_instance_usage(self, context, instance, event_suffix,
                                     network_info=None, system_metadata=None,
                                     extra_usage_info=None, fault=None):
        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, event_suffix,
            network_info=network_info,
            system_metadata=system_metadata,
            extra_usage_info=extra_usage_info, fault=fault)

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
            if 'anti-affinity' not in group.policies and (
                    'affinity' not in group.policies):
                return

            group_hosts = group.get_hosts(context, exclude=[instance.uuid])
            if self.host in group_hosts:
                if 'anti-affinity' in group.policies:
                    msg = _("Anti-affinity instance group policy "
                            "was violated.")
                    raise exception.RescheduledException(
                        instance_uuid=instance.uuid,
                        reason=msg)
            elif group_hosts and [self.host] != group_hosts:
                # NOTE(huawei) Native code only considered anti-affinity
                # policy, but affinity policy also have the same problem.
                # so we add checker for affinity policy instance.
                if 'affinity' in group.policies:
                    msg = _("affinity instance group policy was violated.")
                    raise exception.RescheduledException(
                        instance_uuid=instance.uuid,
                        reason=msg)

        _do_validation(context, instance, group_hint)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def build_and_run_instance(
            self, context, host, instance, image, request_spec,
            filter_properties, admin_password=None, injected_files=None,
            requested_networks=None, security_groups=None,
            block_device_mapping=None, node=None, limits=None):

        if (requested_networks and
                not isinstance(requested_networks,
                               objects.NetworkRequestList)):
            requested_networks = objects.NetworkRequestList(
                objects=[objects.NetworkRequest.from_tuple(t)
                         for t in requested_networks])

        @utils.synchronized(instance.uuid)
        def _locked_do_build_and_run_instance(*args, **kwargs):
            self._do_build_and_run_instance(*args, **kwargs)

        utils.spawn_n(_locked_do_build_and_run_instance,
                      context, host, instance, image, request_spec,
                      filter_properties, admin_password, injected_files,
                      requested_networks, security_groups,
                      block_device_mapping, node, limits)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def _do_build_and_run_instance(self, context, host, instance, image,
                                   request_spec, filter_properties,
                                   admin_password, injected_files,
                                   requested_networks, security_groups,
                                   block_device_mapping, node=None,
                                   limits=None):

        try:
            LOG.debug(_('Starting instance...'), context=context,
                      instance=instance)
            instance.vm_state = vm_states.BUILDING
            instance.task_state = None
            instance.save(expected_task_state=(task_states.SCHEDULING, None))
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
            node = t_utils.get_node_name(host)
            LOG.debug('No node specified, defaulting to %s', node,
                      instance=instance)

        try:
            self._build_and_run_instance(
                context, host, instance, image, request_spec, decoded_files,
                admin_password, requested_networks, security_groups,
                block_device_mapping, node, limits, filter_properties)
        except exception.RescheduledException as e:
            LOG.debug(e.format_message(), instance=instance)
            retry = filter_properties.get('retry', None)
            if not retry:
                # no retry information, do not reschedule.
                LOG.debug("Retry info not present, will not reschedule",
                          instance=instance)
                self._cleanup_allocated_networks(context, instance,
                                                 requested_networks)
                compute_utils.add_instance_fault_from_exc(
                    context, instance, e, sys.exc_info())
                self._set_instance_obj_error_state(context, instance,
                                                   clean_task_state=True)
                return
            retry['exc'] = traceback.format_exception(*sys.exc_info())

            self.network_api.cleanup_instance_network_on_host(
                context, instance, self.host)

            instance.task_state = task_states.SCHEDULING
            instance.save()

            self.compute_task_api.build_instances(
                context, [instance], image, filter_properties, admin_password,
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
            compute_utils.add_instance_fault_from_exc(
                context, instance, e, sys.exc_info())
            self._set_instance_obj_error_state(context, instance,
                                               clean_task_state=True)
        except Exception as e:
            # should not reach here.
            msg = _LE('Unexpected build failure, not rescheduling build.')
            LOG.exception(msg, instance=instance)
            self._cleanup_allocated_networks(context, instance,
                                             requested_networks)
            self._cleanup_volumes(context, instance.uuid,
                                  block_device_mapping, raise_exc=False)
            compute_utils.add_instance_fault_from_exc(context, instance,
                                                      e, sys.exc_info())
            self._set_instance_obj_error_state(context, instance,
                                               clean_task_state=True)

    def _get_instance_nw_info(self, context, instance, use_slave=False):
        """Get a list of dictionaries of network data of an instance."""
        return self.network_api.get_instance_nw_info(context, instance,
                                                     use_slave=use_slave)

    def _allocate_network(self, context, instance, requested_networks, macs,
                          security_groups, dhcp_options):
        """Start network allocation asynchronously.

        Return an instance of NetworkInfoAsyncWrapper that can be used to
        retrieve the allocated networks when the operation has finished.
        """
        # NOTE(comstud): Since we're allocating networks asynchronously,
        # this task state has little meaning, as we won't be in this
        # state for very long.
        instance.vm_state = vm_states.BUILDING
        instance.task_state = task_states.NETWORKING
        instance.save(expected_task_state=[None])

        is_vpn = pipelib.is_vpn_image(instance.image_ref)
        return network_model.NetworkInfoAsyncWrapper(
            self._allocate_network_async, context, instance,
            requested_networks, macs, security_groups, is_vpn, dhcp_options)

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
                    macs=macs, security_groups=security_groups,
                    dhcp_options=dhcp_options)
                LOG.debug('Instance network_info: |%s|', nwinfo,
                          instance=instance)
                instance.system_metadata['network_allocated'] = 'True'
                # NOTE(JoshNang) do not save the instance here, as it can cause
                # races. The caller shares a reference to instance and waits
                # for this async greenthread to finish before calling
                # instance.save().
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
            # NOTE(alex_xu): The network_allocated is True means the network
            # resource already allocated at previous scheduling, and the
            # network setup is cleanup at previous. After rescheduling, the
            # network resource need setup on the new host.
            self.network_api.setup_instance_network_on_host(
                context, instance, instance.host)
            return self._get_instance_nw_info(context, instance)

        if not self.is_neutron_security_groups:
            security_groups = []

        # NOTE(zhiyuan) in ComputeManager, driver method "macs_for_instance"
        # and "dhcp_options_for_instance" are called to get macs and
        # dhcp_options, here we just set them to None
        macs = None
        dhcp_options = None
        network_info = self._allocate_network(context, instance,
                                              requested_networks, macs,
                                              security_groups, dhcp_options)

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

    # NOTE(zhiyuan) the task of this function is to do some preparation job
    # for driver and cinder volume, but in nova proxy _proxy_run_instance will
    # do such job, remove this function after cinder proxy is ready and we
    # confirm it is useless
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

    def _default_block_device_names(self, context, instance,
                                    image_meta, block_devices):
        """Verify that all the devices have the device_name set.

        If not, provide a default name. It also ensures that there is a
        root_device_name and is set to the first block device in the boot
        sequence (boot_index=0).
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
            # NOTE(zhiyuan) if driver doesn't implement related function,
            # function in compute_utils will be called
            root_device_name = compute_utils.get_next_device_name(instance, [])

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

        # NOTE(zhiyuan) if driver doesn't implement related function,
        # function in compute_utils will be called
        compute_utils.default_device_names_for_instance(
            instance, root_device_name, ephemerals, swap, block_device_mapping)

    @contextlib.contextmanager
    def _build_resources(self, context, instance, requested_networks,
                         security_groups, image, block_device_mapping):
        resources = {}
        network_info = None
        try:
            network_info = self._build_networks_for_instance(
                context, instance, requested_networks, security_groups)
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

            # NOTE(zhiyuan) remove this commented code after cinder proxy is
            # ready and we confirm _prep_block_device is useless
            #
            # block_device_info = self._prep_block_device(
            #     context, instance, block_device_mapping)
            #
            block_device_info = None
            resources['block_device_info'] = block_device_info
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

        self._heal_proxy_networks(context, instance, network_info)
        cascaded_ports = self._heal_proxy_ports(
            context, instance, network_info)
        resources['cascaded_ports'] = cascaded_ports

        try:
            yield resources
        except Exception as exc:
            with excutils.save_and_reraise_exception() as ctxt:
                if not isinstance(exc, (
                        exception.InstanceNotFound,
                        exception.UnexpectedDeletingTaskStateError)):
                    LOG.exception(_LE('Instance failed to spawn'),
                                  instance=instance)
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
                try:
                    self._shutdown_instance(context, instance,
                                            block_device_mapping,
                                            requested_networks,
                                            try_deallocate_networks=False)
                except Exception:
                    ctxt.reraise = False
                    msg = _('Could not clean up failed build,'
                            ' not rescheduling')
                    raise exception.BuildAbortException(
                        instance_uuid=instance.uuid, reason=msg)

    def _build_and_run_instance(self, context, host, instance, image,
                                request_spec, injected_files, admin_password,
                                requested_networks, security_groups,
                                block_device_mapping, node, limits,
                                filter_properties):

        image_name = image.get('name')
        self._notify_about_instance_usage(context, instance, 'create.start',
                                          extra_usage_info={
                                              'image_name': image_name})
        try:
            self._validate_instance_group_policy(context, instance,
                                                 filter_properties)
            with self._build_resources(context, instance, requested_networks,
                                       security_groups, image,
                                       block_device_mapping) as resources:
                instance.vm_state = vm_states.BUILDING
                instance.task_state = task_states.SPAWNING
                instance.save(
                    expected_task_state=task_states.BLOCK_DEVICE_MAPPING)
                cascaded_ports = resources['cascaded_ports']
                request_spec['block_device_mapping'] = block_device_mapping
                request_spec['security_group'] = security_groups
                self._proxy_run_instance(
                    context, instance, request_spec, filter_properties,
                    requested_networks, injected_files, admin_password,
                    None, host, node, None, cascaded_ports)

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

    def _shutdown_instance(self, context, instance, bdms,
                           requested_networks=None, notify=True,
                           try_deallocate_networks=True):
        LOG.debug('Proxy stop instance')

    # proxy new function below

    def _heal_proxy_networks(self, context, instance, network_info):
        pass

    def _heal_proxy_ports(self, context, instance, network_info):
        return []

    def _proxy_run_instance(self, context, instance, request_spec=None,
                            filter_properties=None, requested_networks=None,
                            injected_files=None, admin_password=None,
                            is_first_time=False, host=None, node=None,
                            legacy_bdm_in_spec=True, physical_ports=None):
        LOG.debug('Proxy run instance')
