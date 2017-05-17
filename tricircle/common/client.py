# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
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

import collections
import functools
import inspect
import six
from six.moves import xrange
import uuid

import keystoneauth1.identity.generic as auth_identity
from keystoneauth1 import session
from keystoneclient.v3 import client as keystone_client
from oslo_config import cfg
from oslo_log import log as logging

import tricircle.common.context as tricircle_context
from tricircle.common import exceptions
from tricircle.common import resource_handle
from tricircle.db import api
from tricircle.db import models


client_opts = [
    cfg.StrOpt('auth_url',
               default='http://127.0.0.1/identity',
               help='keystone authorization url'),
    cfg.StrOpt('identity_url',
               default='http://127.0.0.1/identity/v3',
               help='keystone service url'),
    cfg.BoolOpt('auto_refresh_endpoint',
                default=False,
                help='if set to True, endpoint will be automatically'
                     'refreshed if timeout accessing endpoint'),
    cfg.StrOpt('top_region_name',
               help='name of top pod which client needs to access'),
    cfg.StrOpt('admin_username',
               help='username of admin account, needed when'
                    ' auto_refresh_endpoint set to True'),
    cfg.StrOpt('admin_password',
               help='password of admin account, needed when'
                    ' auto_refresh_endpoint set to True'),
    cfg.StrOpt('admin_tenant',
               help='tenant name of admin account, needed when'
                    ' auto_refresh_endpoint set to True'),
    cfg.StrOpt('admin_user_domain_name',
               default='Default',
               help='user domain name of admin account, needed when'
                    ' auto_refresh_endpoint set to True'),
    cfg.StrOpt('admin_tenant_domain_name',
               default='Default',
               help='tenant domain name of admin account, needed when'
                    ' auto_refresh_endpoint set to True'),
    cfg.StrOpt('bridge_cidr',
               default='100.0.0.0/9',
               help='cidr pool of the bridge network'),
    cfg.StrOpt('cross_pod_vxlan_mode', default='p2p',
               choices=['p2p', 'l2gw', 'noop'],
               help='Cross-pod VxLAN networking support mode'),
    cfg.IntOpt('max_shadow_port_bulk_size', default=100,
               help='max bulk size to create shadow ports'),
    cfg.IntOpt('max_trunk_subports_bulk_size', default=100,
               help='max bulk size to create trunk subports')
]
client_opt_group = cfg.OptGroup('client')
cfg.CONF.register_group(client_opt_group)
cfg.CONF.register_opts(client_opts, group=client_opt_group)

LOG = logging.getLogger(__name__)


def _safe_operation(operation_name):
    def handle_func(func):
        @six.wraps(func)
        def handle_args(*args, **kwargs):
            instance, resource, context = args[:3]
            if resource not in instance.operation_resources_map[
                    operation_name]:
                raise exceptions.ResourceNotSupported(resource, operation_name)
            retries = 1
            for i in xrange(retries + 1):
                try:
                    service = instance.resource_service_map[resource]
                    instance._ensure_endpoint_set(context, service)
                    instance._ensure_token_for_admin(context)
                    return func(*args, **kwargs)
                except exceptions.EndpointNotAvailable as e:
                    instance._unset_endpoint(service)
                    if i == retries:
                        raise
                    if cfg.CONF.client.auto_refresh_endpoint:
                        LOG.warning('%(exception)s, '
                                    'update endpoint and try again',
                                    {'exception': e.message})
                        instance._update_endpoint_from_keystone(context, True)
                    else:
                        raise
                except exceptions.EndpointNotFound as e:
                    # NOTE(zhiyuan) endpoints are not registered in Keystone
                    # for the given pod and service, we add default behaviours
                    # for the handle functions
                    if i < retries and cfg.CONF.client.auto_refresh_endpoint:
                        LOG.warning('%(exception)s, '
                                    'update endpoint and try again',
                                    {'exception': e.message})
                        instance._update_endpoint_from_keystone(context, True)
                        continue
                    if operation_name == 'list':
                        return []
                    else:
                        return None
        return handle_args
    return handle_func


class Client(object):
    """Wrapper of all OpenStack service clients

    Client works as a wrapper of all OpenStack service clients so you can
    operate all kinds of resources by only interacting with Client. Client
    provides five methods to operate resources:
        create_resources
        delete_resources
        get_resources
        list_resources
        action_resources

    Take create_resources as an example to show how Client works. When
    create_resources is called, it gets the corresponding service handler
    according to the resource type. Service handlers are defined in
    resource_handle.py and each service has one. Each handler has the
    following methods:
        handle_create
        handle_delete
        handle_get
        handle_list
        handle_action
    It's obvious that create_resources is mapped to handle_create(for port,
    handle_create in NeutronResourceHandle is called).

    Not all kinds of resources support the above five operations(or not
    supported yet by Tricircle), so each service handler has a
    support_resource field to specify the resources and operations it
    supports, like:
        'port': LIST | CREATE | DELETE | GET
    This line means that NeutronResourceHandle supports list, create, delete
    and get operations for port resource. To support more resources or make a
    resource support more operations, register them in support_resource.

    Dig into "handle_xxx" you can find that it will call methods in each
    OpenStack service client finally. Calling handle_create for port will
    result in calling create_port in neutronclient module.

    Current "handle_xxx" implementation constructs method name by resource
    and operation type and uses getattr to dynamically load method from
    OpenStack service client so it can cover most of the cases. Supporting a
    new kind of resource or making a resource support a new kind of operation
    is simply to register an entry in support_resource as described above.
    But if some special cases occur later, modifying "handle_xxx" is needed.

    Also, pay attention to action operation since you need to check the
    implementation of the OpenStack service client to know what the method
    name of the action is and what parameters the method has. In the comment of
    action_resources you can find that for each action, there is one line to
    describe the method name and parameters like:
        aggregate -> add_host -> aggregate, host -> none
    This line means that for aggregate resource, novaclient module has an
    add_host method and it has two position parameters and no key parameter.
    For simplicity, action name and method name are the same.

    One more thing to mention, Client registers a partial function
    (operation)_(resource)s for each operation and each resource. For example,
    you can call create_resources(self, resource, cxt, body) directly to create
    a network, or use create_networks(self, cxt, body) for short.
    """
    def __init__(self, region_name=None):
        self.auth_url = cfg.CONF.client.auth_url
        self.resource_service_map = {}
        self.operation_resources_map = collections.defaultdict(set)
        self.service_handle_map = {}
        self.region_name = region_name
        if not self.region_name:
            self.region_name = cfg.CONF.client.top_region_name
        for _, handle_class in inspect.getmembers(resource_handle):
            if not inspect.isclass(handle_class):
                continue
            if not hasattr(handle_class, 'service_type'):
                continue
            handle_obj = handle_class(self.auth_url)
            self.service_handle_map[handle_obj.service_type] = handle_obj
            for resource in handle_obj.support_resource:
                self.resource_service_map[resource] = handle_obj.service_type
                self.operation_resources_map['client'].add(resource)
                for operation, index in six.iteritems(
                        resource_handle.operation_index_map):
                    # add parentheses to emphasize we mean to do bitwise and
                    if (handle_obj.support_resource[resource] & index) == 0:
                        continue
                    self.operation_resources_map[operation].add(resource)
                    setattr(self, '%s_%ss' % (operation, resource),
                            functools.partial(
                                getattr(self, '%s_resources' % operation),
                                resource))

    @staticmethod
    def _get_keystone_session(project_id=None):
        return resource_handle.ResourceHandle.get_keystone_session(project_id)

    @staticmethod
    def get_admin_token(project_id=None):
        return Client._get_admin_token(project_id)

    @staticmethod
    def _get_admin_token(project_id=None):
        return Client._get_keystone_session(project_id).get_token()

    def _get_admin_project_id(self):
        return self._get_keystone_session().get_project_id()

    def _get_endpoint_from_keystone(self, cxt):
        auth = auth_identity.Token(cfg.CONF.client.auth_url,
                                   cxt.auth_token, tenant_id=cxt.tenant)
        sess = session.Session(auth=auth)
        cli = keystone_client.Client(session=sess)

        service_id_name_map = {}
        for service in cli.services.list():
            service_dict = service.to_dict()
            service_id_name_map[service_dict['id']] = service_dict['name']

        region_service_endpoint_map = {}
        for endpoint in cli.endpoints.list():
            endpoint_dict = endpoint.to_dict()
            if endpoint_dict['interface'] != 'public':
                continue
            region_id = endpoint_dict['region']
            service_id = endpoint_dict['service_id']
            url = endpoint_dict['url']
            service_name = service_id_name_map[service_id]
            if region_id not in region_service_endpoint_map:
                region_service_endpoint_map[region_id] = {}
            region_service_endpoint_map[region_id][service_name] = url
        return region_service_endpoint_map

    def _get_config_with_retry(self, cxt, filters, pod, service, retry):
        conf_list = api.list_cached_endpoints(cxt, filters)
        if len(conf_list) == 0:
            if not retry:
                raise exceptions.EndpointNotFound(pod, service)
            self._update_endpoint_from_keystone(cxt, True)
            return self._get_config_with_retry(cxt,
                                               filters, pod, service, False)
        return conf_list

    def _unset_endpoint(self, service):
        handle = self.service_handle_map[service]
        handle.clear_endpoint_url()

    def _ensure_endpoint_set(self, cxt, service):
        handle = self.service_handle_map[service]
        if not handle.is_endpoint_url_set():
            pod_filters = [{'key': 'region_name',
                            'comparator': 'eq',
                            'value': self.region_name}]
            pod_list = api.list_pods(cxt, pod_filters)
            if len(pod_list) == 0:
                raise exceptions.ResourceNotFound(models.Pod,
                                                  self.region_name)
            # region_name is unique key, safe to get the first element
            pod_id = pod_list[0]['pod_id']
            config_filters = [
                {'key': 'pod_id', 'comparator': 'eq', 'value': pod_id},
                {'key': 'service_type', 'comparator': 'eq', 'value': service}]
            conf_list = self._get_config_with_retry(
                cxt, config_filters, pod_id, service,
                cfg.CONF.client.auto_refresh_endpoint)
            url = conf_list[0]['service_url']
            handle.update_endpoint_url(url)

    def _update_endpoint_from_keystone(self, cxt, is_internal):
        """Update the database by querying service endpoint url from Keystone

        :param cxt: context object
        :param is_internal: if True, this method utilizes pre-configured admin
        username and password to apply an new admin token, this happens only
        when auto_refresh_endpoint is set to True. if False, token in cxt is
        directly used, users should prepare admin token themselves
        :return: None
        """
        if is_internal:
            admin_context = tricircle_context.get_admin_context()
            self._ensure_token_for_admin(admin_context)
            endpoint_map = self._get_endpoint_from_keystone(admin_context)
        else:
            endpoint_map = self._get_endpoint_from_keystone(cxt)

        for region in endpoint_map:
            # use region name to query pod
            pod_filters = [{'key': 'region_name', 'comparator': 'eq',
                            'value': region}]
            pod_list = api.list_pods(cxt, pod_filters)
            # skip region/pod not registered in cascade service
            if len(pod_list) != 1:
                continue
            for service in endpoint_map[region]:
                pod_id = pod_list[0]['pod_id']
                config_filters = [{'key': 'pod_id', 'comparator': 'eq',
                                   'value': pod_id},
                                  {'key': 'service_type', 'comparator': 'eq',
                                   'value': service}]
                config_list = api.list_cached_endpoints(
                    cxt, config_filters)

                if len(config_list) > 1:
                    continue
                if len(config_list) == 1:
                    config_id = config_list[0]['service_id']
                    update_dict = {
                        'service_url': endpoint_map[region][service]}
                    api.update_cached_endpoints(
                        cxt, config_id, update_dict)
                else:
                    config_dict = {
                        'service_id': str(uuid.uuid4()),
                        'pod_id': pod_id,
                        'service_type': service,
                        'service_url': endpoint_map[region][service]
                    }
                    api.create_cached_endpoints(
                        cxt, config_dict)

    def get_endpoint(self, cxt, pod_id, service):
        """Get endpoint url of given pod and service

        :param cxt: context object
        :param pod_id: pod id
        :param service: service type
        :return: endpoint url for given pod and service
        :raises: EndpointNotUnique, EndpointNotFound
        """
        config_filters = [
            {'key': 'pod_id', 'comparator': 'eq', 'value': pod_id},
            {'key': 'service_type', 'comparator': 'eq', 'value': service}]
        conf_list = self._get_config_with_retry(
            cxt, config_filters, pod_id, service,
            cfg.CONF.client.auto_refresh_endpoint)
        return conf_list[0]['service_url']

    def update_endpoint_from_keystone(self, cxt):
        """Update the database by querying service endpoint url from Keystone

        Only admin should invoke this method since it requires admin token

        :param cxt: context object containing admin token
        :return: None
        """
        self._update_endpoint_from_keystone(cxt, False)

    def get_keystone_client_by_context(self, ctx):
        client_session = self._get_keystone_session()
        return keystone_client.Client(auth_url=cfg.CONF.client.auth_url,
                                      session=client_session)

    def _ensure_token_for_admin(self, cxt):
        if cxt.is_admin and not cxt.auth_token:
            if cxt.tenant:
                cxt.auth_token = self._get_admin_token(cxt.tenant)
            else:
                cxt.auth_token = self._get_admin_token()
                cxt.tenant = self._get_admin_project_id()

    @_safe_operation('client')
    def get_native_client(self, resource, cxt):
        """Get native python client instance

        Use this function only when for complex operations

        :param resource: resource type
        :param cxt: resource type
        :return: client instance
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle._get_client(cxt)

    @_safe_operation('list')
    def list_resources(self, resource, cxt, filters=None):
        """Query resource in pod of top layer

        Directly invoke this method to query resources, or use
        list_(resource)s (self, cxt, filters=None), for example,
        list_servers (self, cxt, filters=None). These methods are
        automatically generated according to the supported resources
        of each ResourceHandle class.

        :param resource: resource type
        :param cxt: resource type
        :param filters: list of dict with key 'key', 'comparator', 'value'
        like {'key': 'name', 'comparator': 'eq', 'value': 'private'}, 'key'
        is the field name of resources
        :return: list of dict containing resources information
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        filters = filters or []
        return handle.handle_list(cxt, resource, filters)

    @_safe_operation('create')
    def create_resources(self, resource, cxt, *args, **kwargs):
        """Create resource in pod of top layer

        Directly invoke this method to create resources, or use
        create_(resource)s (self, cxt, *args, **kwargs). These methods are
        automatically generated according to the supported resources of each
        ResourceHandle class.

        :param resource: resource type
        :param cxt: context object
        :param args, kwargs: passed according to resource type
               --------------------------
               resource -> args -> kwargs
               --------------------------
               aggregate -> name, availability_zone_name -> none
               server -> name, image, flavor -> nics
               network -> body -> none
               subnet -> body -> none
               port -> body -> none
               floatingip -> body -> none
               --------------------------
        :return: a dict containing resource information
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle.handle_create(cxt, resource, *args, **kwargs)

    @_safe_operation('update')
    def update_resources(self, resource, cxt, *args, **kwargs):
        """Update resource in pod of top layer

        Directly invoke this method to update resources, or use
        update_(resource)s (self, cxt, *args, **kwargs). These methods are
        automatically generated according to the supported resources of each
        ResourceHandle class.

        :param resource: resource type
        :param cxt: context object
        :param args, kwargs: passed according to resource type
               --------------------------
               resource -> args -> kwargs
               --------------------------
               router -> body -> none
               subnet -> body -> none
               --------------------------
        :return: a dict containing resource information
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle.handle_update(cxt, resource, *args, **kwargs)

    @_safe_operation('delete')
    def delete_resources(self, resource, cxt, resource_id):
        """Delete resource in pod of top layer

        Directly invoke this method to delete resources, or use
        delete_(resource)s (self, cxt, obj_id). These methods are
        automatically generated according to the supported resources
        of each ResourceHandle class.
        :param resource: resource type
        :param cxt: context object
        :param resource_id: id of resource
        :return: None
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle.handle_delete(cxt, resource, resource_id)

    @_safe_operation('get')
    def get_resources(self, resource, cxt, resource_id):
        """Get resource in pod of top layer

        Directly invoke this method to get resources, or use
        get_(resource)s (self, cxt, obj_id). These methods are
        automatically generated according to the supported resources
        of each ResourceHandle class.
        :param resource: resource type
        :param cxt: context object
        :param resource_id: id of resource
        :return: a dict containing resource information
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle.handle_get(cxt, resource, resource_id)

    @_safe_operation('action')
    def action_resources(self, resource, cxt, action, *args, **kwargs):
        """Apply action on resource in pod of top layer

        Directly invoke this method to apply action, or use
        action_(resource)s (self, cxt, action, *args, **kwargs). These methods
        are automatically generated according to the supported resources of
        each ResourceHandle class.

        :param resource: resource type
        :param cxt: context object
        :param action: action applied on resource
        :param args, kwargs: passed according to resource type
               --------------------------
               resource -> action -> args -> kwargs
               --------------------------
               aggregate -> add_host -> aggregate, host -> none
               volume -> set_bootable -> volume, flag -> none
               router -> add_interface -> router, body -> none
               router -> add_gateway -> router, body -> none
               router -> remove_gateway -> router -> none
               server_volume -> create_server_volume
                             -> server_id, volume_id, device=None
                             -> none
               server -> start -> server_id -> none
               server -> stop -> server_id -> none
               --------------------------
        :return: None
        :raises: EndpointNotAvailable
        """
        service = self.resource_service_map[resource]
        handle = self.service_handle_map[service]
        return handle.handle_action(cxt, resource, action, *args, **kwargs)
