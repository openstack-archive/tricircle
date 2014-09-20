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

import threading
import Queue
import uuid

import eventlet
from oslo.config import cfg

import glance.openstack.common.log as logging
from glance.openstack.common import timeutils
from glance.sync import utils as s_utils

LOG = logging.getLogger(__name__)


snapshot_opt = [
    cfg.ListOpt('snapshot_region_names',
                default=[],
                help=_("for what regions the snapshot sync to"),
                deprecated_opts=[cfg.DeprecatedOpt('snapshot_region_names',
                                                   group='DEFAULT')]),
]

CONF = cfg.CONF
CONF.register_opts(snapshot_opt)


class TaskObject(object):

    def __init__(self, type, input, retry_times=0):
        self.id = str(uuid.uuid4())
        self.type = type
        self.input = input
        self.image_id = self.input.get('image_id')
        self.status = 'new'
        self.retry_times = retry_times
        self.start_time = None

    @classmethod
    def get_instance(cls, type, input, **kwargs):
        _type_cls_dict = {'meta_update': MetaUpdateTask,
                          'meta_remove': MetaDeleteTask,
                          'sync': ImageActiveTask,
                          'snapshot': PatchSnapshotLocationTask,
                          'patch': PatchLocationTask,
                          'locs_remove': RemoveLocationsTask,
                          'periodic_add': ChkNewCascadedsPeriodicTask}

        if _type_cls_dict.get(type):
            return _type_cls_dict[type](input, **kwargs)

        return None

    def _handle_result(self, sync_manager):
        return sync_manager.handle_tasks({'image_id': self.image_id,
                                          'type': self.type,
                                          'start_time': self.start_time,
                                          'status': self.status
                                          })

    def execute(self, sync_manager, auth_token):
        if not self.checkInput():
            self.status = 'param_error'
            LOG.error(_('the input content not valid: %s.' % (self.input)))
            return self._handle_result(sync_manager)

        try:
            self.status = 'running'
            green_threads = self.create_green_threads(sync_manager, auth_token)
            for gt in green_threads:
                gt.wait()
        except Exception as e:
            msg = _("Unable to execute task of image %(image_id)s: %(e)s") % \
                {'image_id': self.image_id, 'e': unicode(e)}
            LOG.exception(msg)
            self.status = 'error'
        else:
            self.status = 'terminal'

        return self._handle_result(sync_manager)

    def checkInput(self):
        if not self.input.pop('image_id', None):
            LOG.warn(_('No cascading image_id specified.'))
            return False
        return self.do_checkInput()


class MetaUpdateTask(TaskObject):

    def __init__(self, input):
        super(MetaUpdateTask, self).__init__('meta_update', input)

    def do_checkInput(self):
        params = self.input
        changes = params.get('changes')
        removes = params.get('removes')
        tags = params.get('tags')
        if not changes and not removes and not tags:
            LOG.warn(_('No changes and removes and tags with the glance.'))
        return True

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        cascaded_mapping = s_utils.get_mappings_from_image(auth_token,
                                                           self.image_id)
        for cascaded_ep in cascaded_mapping:
            cascaded_id = cascaded_mapping[cascaded_ep]
            green_threads.append(eventlet.spawn(sync_manager.meta_update,
                                                auth_token,
                                                cascaded_ep,
                                                image_id=cascaded_id,
                                                **self.input))

        return green_threads


class MetaDeleteTask(TaskObject):

    def __init__(self, input):
        super(MetaDeleteTask, self).__init__('meta_remove', input)

    def do_checkInput(self):
        self.locations = self.input.get('locations')
        return self.locations is not None

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        cascaded_mapping = s_utils.get_mappings_from_locations(self.locations)
        for cascaded_ep in cascaded_mapping:
            cascaded_id = cascaded_mapping[cascaded_ep]
            green_threads.append(eventlet.spawn(sync_manager.meta_delete,
                                                auth_token,
                                                cascaded_ep,
                                                image_id=cascaded_id))

        return green_threads


class ImageActiveTask(TaskObject):

    def __init__(self, input):
        super(ImageActiveTask, self).__init__('sync', input)

    def do_checkInput(self):
        image_data = self.input.get('body')
        self.cascading_endpoint = self.input.get('cascading_ep')
        return image_data and self.cascading_endpoint

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        cascaded_eps = s_utils.get_endpoints(auth_token)
        for cascaded_ep in cascaded_eps:
            green_threads.append(eventlet.spawn(sync_manager.sync_image,
                                                auth_token,
                                                self.cascading_endpoint,
                                                cascaded_ep,
                                                self.image_id,
                                                self.image_id,
                                                **self.input))

        return green_threads


class PatchSnapshotLocationTask(TaskObject):

    def __init__(self, input):
        super(PatchSnapshotLocationTask, self).__init__('snapshot', input)

    def do_checkInput(self):
        image_metadata = self.input.get('body')
        self.snapshot_endpoint = self.input.pop('snapshot_ep', None)
        self.snapshot_id = self.input.pop('snapshot_id', None)
        return image_metadata and self.snapshot_endpoint and self.snapshot_id

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        _region_names = CONF.snapshot_region_names
        cascaded_mapping = s_utils.get_endpoints(auth_token,
                                                 region_names=_region_names)
        try:
            if self.snapshot_endpoint in cascaded_mapping:
                cascaded_mapping.remove(self.snapshot_endpoint)
        except TypeError:
            pass
        for cascaded_ep in cascaded_mapping:
            green_threads.append(eventlet.spawn(sync_manager.do_snapshot,
                                                auth_token,
                                                self.snapshot_endpoint,
                                                cascaded_ep,
                                                self.snapshot_id,
                                                self.image_id,
                                                **self.input))

        return green_threads


class PatchLocationTask(TaskObject):

    def __init__(self, input):
        super(PatchLocationTask, self).__init__('patch', input)

    def do_checkInput(self):
        self.location = self.input.get('location')
        return self.location is not None

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        cascaded_mapping = s_utils.get_mappings_from_image(auth_token,
                                                           self.image_id)
        for cascaded_ep in cascaded_mapping:
            cascaded_id = cascaded_mapping[cascaded_ep]
            green_threads.append(eventlet.spawn(sync_manager.patch_location,
                                                self.image_id,
                                                cascaded_id,
                                                auth_token,
                                                cascaded_ep,
                                                self.location))
        return green_threads


class RemoveLocationsTask(TaskObject):

    def __init__(self, input):
        super(RemoveLocationsTask, self).__init__('locs_remove', input)

    def do_checkInput(self):
        self.locations = self.input.get('locations')
        return self.locations is not None

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        cascaded_mapping = s_utils.get_mappings_from_locations(self.locations)
        for cascaded_ep in cascaded_mapping:
            cascaded_id = cascaded_mapping[cascaded_ep]
            green_threads.append(eventlet.spawn(sync_manager.remove_loc,
                                                cascaded_id,
                                                auth_token,
                                                cascaded_ep))
        return green_threads


class PeriodicTask(TaskObject):

    MAX_SLEEP_SECONDS = 15

    def __init__(self, type, input, interval, last_run_time, run_immediately):
        super(PeriodicTask, self).__init__(type, input)
        self.interval = interval
        self.last_run_time = last_run_time
        self.run_immediately = run_immediately

    def do_checkInput(self):
        if not self.interval or self.interval < 0:
            LOG.error(_('The Periodic Task interval invaild.'))
            return False

        return True

    def ready(self):
        # first time to run
        if self.last_run_time is None:
            self.last_run_time = timeutils.strtime()
            return self.run_immediately
        return timeutils.is_older_than(self.last_run_time, self.interval)

    def execute(self, sync_manager, auth_token):
        while not self.ready():
            LOG.debug(_('the periodic task has not ready yet, sleep a while.'
                        'current_start_time is %s, last_run_time is %s, and '
                        'the interval is %i.' % (self.start_time,
                                                 self.last_run_time,
                                                 self.interval)))
            _max_sleep_time = self.MAX_SLEEP_SECONDS
            eventlet.sleep(seconds=max(self.interval / 10, _max_sleep_time))

        super(PeriodicTask, self).execute(sync_manager, auth_token)


class ChkNewCascadedsPeriodicTask(PeriodicTask):

    def __init__(self, input, interval=60, last_run_time=None,
                 run_immediately=False):

        super(ChkNewCascadedsPeriodicTask, self).__init__('periodic_add',
                                                          input, interval,
                                                          last_run_time,
                                                          run_immediately)
        LOG.debug(_('create ChkNewCascadedsPeriodicTask.'))

    def do_checkInput(self):
        self.images = self.input.get('images')
        self.cascading_endpoint = self.input.get('cascading_ep')
        if self.images is None or not self.cascading_endpoint:
            return False
        return super(ChkNewCascadedsPeriodicTask, self).do_checkInput()

    def _stil_need_synced(self, cascaded_ep, image_id, auth_token):
        g_client = s_utils.create_self_glance_client(auth_token)
        try:
            image = g_client.images.get(image_id)
        except Exception:
            LOG.warn(_('The add cascaded periodic task checks that the image '
                       'has deleted, no need to sync. id is %s' % image_id))
            return False
        else:
            if image.status != 'active':
                LOG.warn(_('The add cascaded period task checks image status '
                           'not active, no need to sync.'
                           'image id is %s.' % image_id))
                return False
            ep_list = [loc['url'] for loc in image.locations
                       if s_utils.is_glance_location(loc['url'])]
            return not s_utils.is_ep_contains(cascaded_ep, ep_list)

    def create_green_threads(self, sync_manager, auth_token):
        green_threads = []
        for image_id in self.images:
            cascaded_eps = self.images[image_id].get('locations')
            kwargs = {'body': self.images[image_id].get('body')}
            for cascaded_ep in cascaded_eps:
                if not self._stil_need_synced(cascaded_ep,
                                              image_id, auth_token):
                    continue
                green_threads.append(eventlet.spawn(sync_manager.sync_image,
                                                    auth_token,
                                                    self.cascading_endpoint,
                                                    cascaded_ep,
                                                    image_id,
                                                    image_id,
                                                    **kwargs))

        return green_threads
