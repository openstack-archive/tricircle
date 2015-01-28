# Copyright (c) 2014 OpenStack Foundation.
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
#
# @author: Jia Dong, HuaWei

import copy
import httplib
import Queue
import threading
import time

import eventlet
from oslo.config import cfg
import six.moves.urllib.parse as urlparse

from glance.common import exception
from glance.openstack.common import jsonutils
from glance.openstack.common import timeutils
import glance.openstack.common.log as logging

from glance.sync import utils as s_utils
from glance.sync.clients import Clients as clients
from glance.sync.store.driver import StoreFactory as s_factory
from glance.sync.store.location import LocationFactory as l_factory
import glance.sync.store.glance_store as glance_store
from glance.sync.task import TaskObject
from glance.sync.task import PeriodicTask

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('sync_strategy', 'glance.common.config', group='sync')
CONF.import_opt('task_retry_times', 'glance.common.config', group='sync')
CONF.import_opt('snapshot_timeout', 'glance.common.config', group='sync')
CONF.import_opt('snapshot_sleep_interval', 'glance.common.config',
                group='sync')


_IMAGE_LOCS_MAP = {}


def get_copy_location_url(image):
    """
    choose a best location of an image for sync.
    """
    global _IMAGE_LOCS_MAP
    image_id = image.id
    locations = image.locations
    if not locations:
        return ''
    #First time store in the cache
    if image_id not in _IMAGE_LOCS_MAP.keys():
        _IMAGE_LOCS_MAP[image_id] = {
            'locations':
                [{'url': locations[0]['url'],
                  'count': 1,
                  'is_using':1
                 }]
        }
        return locations[0]['url']
    else:
        recorded_locs = _IMAGE_LOCS_MAP[image_id]['locations']
        record_urls = [loc['url'] for loc in recorded_locs]
        for location in locations:
            #the new, not-used location, cache and just return it.
            if location['url'] not in record_urls:
                recorded_locs.append({
                    'url': location['url'],
                    'count':1,
                    'is_using':1
                })
                return location['url']
        #find ever used and at present not used.
        not_used_locs = [loc for loc in recorded_locs
                         if not loc['is_using']]
        if not_used_locs:
            _loc = not_used_locs[0]
            _loc['is_using'] = 1
            _loc['count'] += 1
            return _loc['url']
        #the last case, just choose one that has the least using count.
        _my_loc = sorted(recorded_locs, key=lambda my_loc: my_loc['count'])[0]
        _my_loc['count'] += 1
        return _my_loc['url']


def remove_invalid_location(id, url):
    """
    when sync fail with a location, remove it from the cache.
    :param id: the image_id
    :param url: the location's url
    :return:
    """
    global _IMAGE_LOCS_MAP
    image_map = _IMAGE_LOCS_MAP[id]
    if not image_map:
        return
    locs = image_map['locations'] or []
    if not locs:
        return
    del_locs = [loc for loc in locs if loc['url'] == url]
    if not del_locs:
        return
    locs.remove(del_locs[0])


def return_sync_location(id, url):
    """
    when sync finish, modify the using count and state.
    """
    global _IMAGE_LOCS_MAP
    image_map = _IMAGE_LOCS_MAP[id]
    if not image_map:
        return
    locs = image_map['locations'] or []
    if not locs:
        return
    selectd_locs = [loc for loc in locs if loc['url'] == url]
    if not selectd_locs:
        return
    selectd_locs[0]['is_using'] = 0
    selectd_locs[0]['count'] -= 1


def choose_a_location(sync_f):
    """
    the wrapper for the method which need a location for sync.
    :param sync_f:
    :return:
    """
    def wrapper(*args, **kwargs):
        _id = args[1]
        _auth_token = args[2]
        _image = create_self_glance_client(_auth_token).images.get(_id)
        _url = get_copy_location_url(_image)
        kwargs['src_image_url'] = _url
        _sync_ok = False
        while not _sync_ok:
            try:
                sync_f(*args, **kwargs)
                _sync_ok = True
            except Exception:
                remove_invalid_location(_id, _url)
                _url = get_copy_location_url(_image)
                if not _url:
                    break
                kwargs['src_image_url'] = _url
    return wrapper


def get_image_servcie():
    return ImageService


def create_glance_client(auth_token, url):
    return clients(auth_token).glance(url=url)


def create_self_glance_client(auth_token):
    return create_glance_client(auth_token,
                                s_utils.get_cascading_endpoint_url())


def create_restful_client(auth_token, url):
    pieces = urlparse.urlparse(url)
    return _create_restful_client(auth_token, pieces.netloc)


def create_self_restful_client(auth_token):
    return create_restful_client(auth_token,
                                 s_utils.get_cascading_endpoint_url())


def _create_restful_client(auth_token, url):
    server, port = url.split(':')
    try:
        port = int(port)
    except Exception:
        port = 9292
    conn = httplib.HTTPConnection(server.encode(), port)
    image_service = get_image_servcie()
    glance_client = image_service(conn, auth_token)
    return glance_client


def get_mappings_from_image(auth_token, image_id):
    client = create_self_glance_client(auth_token)
    image = client.images.get(image_id)
    locations = image.locations
    if not locations:
        return {}
    return get_mappings_from_locations(locations)


def get_mappings_from_locations(locations):
    mappings = {}
    for loc in locations:
        if s_utils.is_glance_location(loc['url']):
            id = loc['metadata'].get('image_id')
            if not id:
                continue
            ep_url = s_utils.create_ep_by_loc(loc)
            mappings[ep_url] = id
#            endpoints.append(utils.create_ep_by_loc(loc))
    return mappings


class AuthenticationException(Exception):
    pass


class ImageAlreadyPresentException(Exception):
    pass


class ServerErrorException(Exception):
    pass


class UploadException(Exception):
    pass


class ImageService(object):

    def __init__(self, conn, auth_token):
        """Initialize the ImageService.

        conn: a httplib.HTTPConnection to the glance server
        auth_token: authentication token to pass in the x-auth-token header
        """
        self.auth_token = auth_token
        self.conn = conn

    def _http_request(self, method, url, headers, body,
                      ignore_result_body=False):
        """Perform an HTTP request against the server.

        method: the HTTP method to use
        url: the URL to request (not including server portion)
        headers: headers for the request
        body: body to send with the request
        ignore_result_body: the body of the result will be ignored

        Returns: a httplib response object
        """
        if self.auth_token:
            headers.setdefault('x-auth-token', self.auth_token)

        LOG.debug(_('Request: %(method)s http://%(server)s:%(port)s'
                    '%(url)s with headers %(headers)s')
                  % {'method': method,
                     'server': self.conn.host,
                     'port': self.conn.port,
                     'url': url,
                     'headers': repr(headers)})
        self.conn.request(method, url, body, headers)

        response = self.conn.getresponse()
        headers = self._header_list_to_dict(response.getheaders())
        code = response.status
        code_description = httplib.responses[code]
        LOG.debug(_('Response: %(code)s %(status)s %(headers)s')
                  % {'code': code,
                     'status': code_description,
                     'headers': repr(headers)})

        if code in [400, 500]:
            raise ServerErrorException(response.read())

        if code in [401, 403]:
            raise AuthenticationException(response.read())

        if code == 409:
            raise ImageAlreadyPresentException(response.read())

        if ignore_result_body:
            # NOTE: because we are pipelining requests through a single HTTP
            # connection, httplib requires that we read the response body
            # before we can make another request. If the caller knows they
            # don't care about the body, they can ask us to do that for them.
            response.read()
        return response

    @staticmethod
    def _header_list_to_dict(headers):
        """Expand a list of headers into a dictionary.

        headers: a list of [(key, value), (key, value), (key, value)]

        Returns: a dictionary representation of the list
        """
        d = {}
        for (header, value) in headers:
            if header.startswith('x-image-meta-property-'):
                prop = header.replace('x-image-meta-property-', '')
                d.setdefault('properties', {})
                d['properties'][prop] = value
            else:
                d[header.replace('x-image-meta-', '')] = value
        return d

    @staticmethod
    def _dict_to_headers(d):
        """Convert a dictionary into one suitable for a HTTP request.

        d: a dictionary

        Returns: the same dictionary, with x-image-meta added to every key
        """
        h = {}
        for key in d:
            if key == 'properties':
                for subkey in d[key]:
                    if d[key][subkey] is None:
                        h['x-image-meta-property-%s' % subkey] = ''
                    else:
                        h['x-image-meta-property-%s' % subkey] = d[key][subkey]

            else:
                h['x-image-meta-%s' % key] = d[key]
        return h

    def add_location(self, image_uuid, path_val, metadata=None):
        """
        add an actual location
        """
        LOG.debug(_('call restful api to add location: url is %s' % path_val))
        metadata = metadata or {}
        url = '/v2/images/%s' % image_uuid
        hdrs = {'Content-Type': 'application/openstack-images-v2.1-json-patch'}
        body = []
        value = {'url': path_val, 'metadata': metadata}
        body.append({'op': 'add', 'path': '/locations/-', 'value': value})
        return self._http_request('PATCH', url, hdrs, jsonutils.dumps(body))

    def clear_locations(self, image_uuid):
        """
        clear all the location infos, make the image status be 'queued'.
        """
        LOG.debug(_('call restful api to clear image location: image id is %s'
                    % image_uuid))
        url = '/v2/images/%s' % image_uuid
        hdrs = {'Content-Type': 'application/openstack-images-v2.1-json-patch'}
        body = []
        body.append({'op': 'replace', 'path': '/locations', 'value': []})
        return self._http_request('PATCH', url, hdrs, jsonutils.dumps(body))


class MetadataHelper(object):

    def execute(self, auth_token, endpoint, action_name='CREATE',
                image_id=None, **kwargs):

        glance_client = create_glance_client(auth_token, endpoint)
        if action_name.upper() == 'CREATE':
            return self._do_create_action(glance_client, **kwargs)
        if action_name.upper() == 'SAVE':
            return self._do_save_action(glance_client, image_id, **kwargs)
        if action_name.upper() == 'DELETE':
            return self._do_delete_action(glance_client, image_id, **kwargs)

        return None

    @staticmethod
    def _fetch_params(keys, **kwargs):
        return tuple([kwargs.get(key, None) for key in keys])

    def _do_create_action(self, glance_client, **kwargs):
        body = kwargs['body']
        new_image = glance_client.images.create(**body)
        return new_image.id

    def _do_save_action(self, glance_client, image_id, **kwargs):
        keys = ['changes', 'removes', 'tags']
        changes, removes, tags = self._fetch_params(keys, **kwargs)
        if changes or removes:
            glance_client.images.update(image_id,
                                        remove_props=removes,
                                        **changes)
        if tags:
            if tags.get('add', None):
                added = tags.get('add')
                for tag in added:
                    glance_client.image_tags.update(image_id, tag)
            elif tags.get('delete', None):
                removed = tags.get('delete')
                for tag in removed:
                    glance_client.image_tags.delete(image_id, tag)
        return glance_client.images.get(image_id)

    def _do_delete_action(self, glance_client, image_id, **kwargs):
        return glance_client.images.delete(image_id)


_task_queue = Queue.Queue(maxsize=150)


class SyncManagerV2():

    MAX_TASK_RETRY_TIMES = 1

    def __init__(self):
        global _task_queue
        self.mete_helper = MetadataHelper()
        self.location_factory = l_factory()
        self.store_factory = s_factory()
        self.task_queue = _task_queue
        self.task_handler = None
        self.unhandle_task_list = []
        self.periodic_add_id_list = []
        self.periodic_add_done = True
        self._load_glance_store_cfg()
        self.ks_client = clients().keystone()
        self.create_new_periodic_task = False

    def _load_glance_store_cfg(self):
        glance_store.setup_glance_stores()

    def sync_image_metadata(self, image_id, auth_token, action, **kwargs):
        if not action or CONF.sync.sync_strategy == 'None':
            return
        kwargs['image_id'] = image_id
        if action == 'SAVE':
            self.task_queue.put_nowait(TaskObject.get_instance('meta_update',
                                                               kwargs))
        elif action == 'DELETE':
            self.task_queue.put_nowait(TaskObject.get_instance('meta_remove',
                                                               kwargs))

    @choose_a_location
    def sync_image_data(self, image_id, auth_token, eps=None, **kwargs):
        if CONF.sync.sync_strategy in ['None', 'nova']:
            return

        kwargs['image_id'] = image_id
        cascading_ep = s_utils.get_cascading_endpoint_url()
        kwargs['cascading_ep'] = cascading_ep
        copy_url = kwargs.get('src_image_url', None)
        if not copy_url:
            LOG.warn(_('No copy url found, for image %s sync, Exit.'),
                     image_id)
            return
        LOG.info(_('choose the copy url %s for sync image %s'),
                 copy_url, image_id)
        if s_utils.is_glance_location(copy_url):
            kwargs['copy_ep'] = s_utils.create_ep_by_loc_url(copy_url)
            kwargs['copy_id'] = s_utils.get_id_from_glance_loc_url(copy_url)
        else:
            kwargs['copy_ep'] = cascading_ep
            kwargs['copy_id'] = image_id

        self.task_queue.put_nowait(TaskObject.get_instance('sync', kwargs))

    def adding_locations(self, image_id, auth_token, locs, **kwargs):
        if CONF.sync.sync_strategy == 'None':
            return
        for loc in locs:
            if s_utils.is_glance_location(loc['url']):
                if s_utils.is_snapshot_location(loc):
                    snapshot_ep = s_utils.create_ep_by_loc(loc)
                    snapshot_id = s_utils.get_id_from_glance_loc(loc)
                    snapshot_client = create_glance_client(auth_token,
                                                           snapshot_ep)
                    snapshot_image = snapshot_client.images.get(snapshot_id)
                    _pre_check_time = timeutils.utcnow()
                    _timout = CONF.sync.snapshot_timeout
                    while not timeutils.is_older_than(_pre_check_time,
                                                      _timout):
                        if snapshot_image.status == 'active':
                            break
                        LOG.debug(_('Check snapshot not active, wait for %i'
                                    'second.'
                                    % CONF.sync.snapshot_sleep_interval))
                        time.sleep(CONF.sync.snapshot_sleep_interval)
                        snapshot_image = snapshot_client.images.get(
                            snapshot_id)

                    if snapshot_image.status != 'active':
                        LOG.error(_('Snapshot status to active Timeout'))
                        return
                    kwargs['image_id'] = image_id
                    kwargs['snapshot_ep'] = snapshot_ep
                    kwargs['snapshot_id'] = snapshot_id
                    snapshot_task = TaskObject.get_instance('snapshot', kwargs)
                    self.task_queue.put_nowait(snapshot_task)
            else:
                LOG.debug(_('patch a normal location %s to image %s'
                            % (loc['url'], image_id)))
                input = {'image_id': image_id, 'location': loc}
                self.task_queue.put_nowait(TaskObject.get_instance('patch',
                                                                   input))

    def removing_locations(self, image_id, auth_token, locs):
        if CONF.sync.sync_strategy == 'None':
            return
        locs = filter(lambda loc: s_utils.is_glance_location(loc['url']), locs)
        if not locs:
            return
        input = {'image_id': image_id, 'locations': locs}
        remove_locs_task = TaskObject.get_instance('locs_remove', input)
        self.task_queue.put_nowait(remove_locs_task)

    def clear_all_locations(self, image_id, auth_token, locs):
        locs = filter(lambda loc: not s_utils.is_snapshot_location(loc), locs)
        self.removing_locations(image_id, auth_token, locs)

    def create_new_cascaded_task(self, last_run_time=None):
        LOG.debug(_('new_cascaded periodic task has been created.'))
        glance_client = create_self_glance_client(self.ks_client.auth_token)
        filters = {'status': 'active'}
        image_list = glance_client.images.list(filters=filters)
        input = {}
        run_images = {}
        cascading_ep = s_utils.get_cascading_endpoint_url()
        input['cascading_ep'] = cascading_ep
        input['image_id'] = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
        all_ep_urls = s_utils.get_endpoints()
        for image in image_list:
            glance_urls = [loc['url'] for loc in image.locations
                           if s_utils.is_glance_location(loc['url'])]
            lack_ep_urls = s_utils.calculate_lack_endpoints(all_ep_urls,
                                                            glance_urls)
            if lack_ep_urls:
                image_core_props = s_utils.get_core_properties(image)
                run_images[image.id] = {'body': image_core_props,
                                        'locations': lack_ep_urls}
        if not run_images:
            LOG.debug(_('No images need to sync to new cascaded glances.'))
        input['images'] = run_images
        return TaskObject.get_instance('periodic_add', input,
                                       last_run_time=last_run_time)

    @staticmethod
    def _fetch_params(keys, **kwargs):
        return tuple([kwargs.get(key, None) for key in keys])

    def _get_candidate_path(self, auth_token, from_ep, image_id,
                            scheme='file'):
        g_client = create_glance_client(auth_token, from_ep)
        image = g_client.images.get(image_id)
        locs = image.locations or []
        for loc in locs:
            if s_utils.is_glance_location(loc['url']):
                continue
            if loc['url'].startswith(scheme):
                if scheme == 'file':
                    return loc['url'][len('file://'):]
                return loc['url']
        return None

    def _do_image_data_copy(self, s_ep, d_ep, from_image_id, to_image_id,
                            candidate_path=None):
        from_scheme, to_scheme = glance_store.choose_best_store_schemes(s_ep,
                                                                        d_ep)
        store_driver = self.store_factory.get_instance(from_scheme['name'],
                                                       to_scheme['name'])
        from_params = from_scheme['parameters']
        from_params['image_id'] = from_image_id
        to_params = to_scheme['parameters']
        to_params['image_id'] = to_image_id
        from_location = self.location_factory.get_instance(from_scheme['name'],
                                                           **from_params)
        to_location = self.location_factory.get_instance(to_scheme['name'],
                                                         **to_params)
        return store_driver.copy_to(from_location, to_location,
                                    candidate_path=candidate_path)

    def _patch_cascaded_location(self, auth_token, image_id,
                                 cascaded_ep, cascaded_id, action=None):
        self_restful_client = create_self_restful_client(auth_token)
        path = s_utils.generate_glance_location(cascaded_ep, cascaded_id)
        # add the auth_token, so this url can be visited, otherwise 404 error
        path += '?auth_token=1'
        metadata = {'image_id': cascaded_id}
        if action:
            metadata['action'] = action
        self_restful_client.add_location(image_id, path, metadata)

    def meta_update(self, auth_token, cascaded_ep, image_id, **kwargs):

        return self.mete_helper.execute(auth_token, cascaded_ep, 'SAVE',
                                        image_id, **kwargs)

    def meta_delete(self, auth_token, cascaded_ep, image_id):

        return self.mete_helper.execute(auth_token, cascaded_ep, 'DELETE',
                                        image_id)

    def sync_image(self, auth_token, copy_ep=None, to_ep=None,
                   copy_image_id=None, cascading_image_id=None, **kwargs):
        # Firstly, crate an image object with cascading image's properties.
        LOG.debug(_('create an image metadata in ep: %s'), to_ep)
        cascaded_id = self.mete_helper.execute(auth_token, to_ep,
                                               **kwargs)
        try:
            c_path = self._get_candidate_path(auth_token, copy_ep,
                                              copy_image_id)
            LOG.debug(_('Chose candidate path: %s from ep %s'), c_path, copy_ep)
            # execute copy operation to copy the image data.
            copy_image_loc = self._do_image_data_copy(copy_ep,
                                                      to_ep,
                                                      copy_image_id,
                                                      cascaded_id,
                                                      candidate_path=c_path)
            LOG.debug(_('Sync image data, synced loc is %s'), copy_image_loc)
            # patch the copied image_data to the image
            glance_client = create_restful_client(auth_token, to_ep)
            glance_client.add_location(cascaded_id, copy_image_loc)
            # patch the glance location to cascading glance

            msg = _("patch glance location to cascading image, with cascaded "
                    "endpoint : %s, cascaded id: %s, cascading image id: %s." %
                    (to_ep, cascaded_id, cascading_image_id))
            LOG.debug(msg)
            self._patch_cascaded_location(auth_token,
                                          cascading_image_id,
                                          to_ep,
                                          cascaded_id,
                                          action='upload')
            return cascaded_id
        except exception.SyncStoreCopyError as e:
            LOG.error(_("Exception occurs when syncing store copy."))
            raise exception.SyncServiceOperationError(reason=e.msg)

    def do_snapshot(self, auth_token, snapshot_ep, cascaded_ep,
                    snapshot_image_id, cascading_image_id, **kwargs):

        return self.sync_image(auth_token, copy_ep=snapshot_ep,
                to_ep=cascaded_ep, copy_image_id=snapshot_image_id,
                cascading_image_id=cascading_image_id, **kwargs)

    def patch_location(self, image_id, cascaded_id, auth_token, cascaded_ep,
                       location):
        g_client = create_glance_client(auth_token, cascaded_ep)
        cascaded_image = g_client.images.get(cascaded_id)
        glance_client = create_restful_client(auth_token, cascaded_ep)
        try:
            glance_client.add_location(cascaded_id, location['url'])
            if cascaded_image.status == 'queued':
                self._patch_cascaded_location(auth_token,
                                              image_id,
                                              cascaded_ep,
                                              cascaded_id,
                                              action='patch')
        except:
            pass

    def remove_loc(self, cascaded_id, auth_token, cascaded_ep):
        glance_client = create_glance_client(auth_token, cascaded_ep)
        glance_client.images.delete(cascaded_id)

    def start(self):
        # lanuch a new thread to read the task_task to handle.
        _thread = threading.Thread(target=self.tasks_handle)
        _thread.setDaemon(True)
        _thread.start()

    def tasks_handle(self):
        while True:
            _task = self.task_queue.get()
            if not isinstance(_task, TaskObject):
                LOG.error(_('task type valid.'))
                continue
            LOG.debug(_('Task start to runs, task id is %s' % _task.id))
            _task.start_time = timeutils.strtime()
            self.unhandle_task_list.append(copy.deepcopy(_task))

            eventlet.spawn(_task.execute, self, self.ks_client.auth_token)

    def handle_tasks(self, task_result):
        t_image_id = task_result.get('image_id')
        t_type = task_result.get('type')
        t_start_time = task_result.get('start_time')
        t_status = task_result.get('status')

        handling_tasks = filter(lambda t: t.image_id == t_image_id and
                                t.start_time == t_start_time,
                                self.unhandle_task_list)
        if not handling_tasks or len(handling_tasks) > 1:
            LOG.error(_('The task not exist or duplicate, can not go  handle. '
                        'Info is image: %(id)s, op_type: %(type)s, run time: '
                        '%(time)s'
                        % {'id': t_image_id,
                           'type': t_type,
                           'time': t_start_time}
                        ))
            return

        task = handling_tasks[0]
        self.unhandle_task_list.remove(task)

        if isinstance(task, PeriodicTask):
            LOG.debug(_('The periodic task executed done, with op %(type)s '
                        'runs at time: %(start_time)s, the status is '
                        '%(status)s.' %
                        {'type': t_type,
                         'start_time': t_start_time,
                         'status': t_status
                         }))

        else:
            if t_status == 'terminal':
                LOG.debug(_('The task executed successful for image:'
                            '%(image_id)s with op %(type)s, which runs '
                            'at time: %(start_time)s' %
                            {'image_id': t_image_id,
                             'type': t_type,
                             'start_time': t_start_time
                             }))
            elif t_status == 'param_error':
                LOG.error(_('The task executed failed for params error. Image:'
                            '%(image_id)s with op %(type)s, which runs '
                            'at time: %(start_time)s' %
                            {'image_id': t_image_id,
                             'type': t_type,
                             'start_time': t_start_time
                             }))
            elif t_status == 'error':
                LOG.error(_('The task failed to execute. Detail info is: '
                            '%(image_id)s with op %(op_type)s run_time:'
                            '%(start_time)s' %
                            {'image_id': t_image_id,
                             'op_type': t_type,
                             'start_time': t_start_time
                             }))
