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

from oslo.config import cfg

import glance.context
import glance.domain.proxy
import glance.openstack.common.log as logging
from glance.sync.clients import Clients as clients
from glance.sync import utils


LOG = logging.getLogger(__name__)

_V2_IMAGE_CREATE_PROPERTIES = ['container_format', 'disk_format', 'min_disk',
                               'min_ram', 'name', 'virtual_size', 'visibility',
                               'protected']

_V2_IMAGE_UPDATE_PROPERTIES = ['container_format', 'disk_format', 'min_disk',
                               'min_ram', 'name']


def _check_trigger_sync(pre_image, image):
    """
    check if it is the case that the cascaded glance has upload or first patch
    location.
    """
    return pre_image.status in ('saving', 'queued') and image.size and \
        [l for l in image.locations if not utils.is_glance_location(l['url'])]


def _from_snapshot_request(pre_image, image):
    """
    when patch location, check if it's snapshot-sync case.
    """
    if pre_image.status == 'queued' and len(image.locations) == 1:
        loc_meta = image.locations[0]['metadata']
        return loc_meta and loc_meta.get('image_from', None) in ['snapshot',
                                                                 'volume']


def get_adding_image_properties(image):
    _tags = list(image.tags) or []
    kwargs = {}
    kwargs['body'] = {}
    for key in _V2_IMAGE_CREATE_PROPERTIES:
        try:
            value = getattr(image, key, None)
            if value and value != 'None':
                kwargs['body'][key] = value
        except KeyError:
            pass
    _properties = getattr(image, 'extra_properties') or None

    if _properties:
        extra_keys = _properties.keys()
        for _key in extra_keys:
            kwargs['body'][_key] = _properties[_key]
    if _tags:
        kwargs['body']['tags'] = _tags
    return kwargs


def get_existing_image_locations(image):
    return {'locations': image.locations}


class ImageRepoProxy(glance.domain.proxy.Repo):

    def __init__(self, image_repo, context, sync_api):
        self.image_repo = image_repo
        self.context = context
        self.sync_client = sync_api.get_sync_client(context)
        proxy_kwargs = {'context': context, 'sync_api': sync_api}
        super(ImageRepoProxy, self).__init__(image_repo,
                                             item_proxy_class=ImageProxy,
                                             item_proxy_kwargs=proxy_kwargs)

    def _sync_saving_metadata(self, pre_image, image):
        kwargs = {}
        remove_keys = []
        changes = {}
        """
        image base properties
        """
        for key in _V2_IMAGE_UPDATE_PROPERTIES:
            pre_value = getattr(pre_image, key, None)
            my_value = getattr(image, key, None)

            if not my_value and not pre_value or my_value == pre_value:
                continue
            if not my_value and pre_value:
                remove_keys.append(key)
            else:
                changes[key] = my_value

        """
        image extra_properties
        """
        pre_props = pre_image.extra_properties or {}
        _properties = image.extra_properties or {}
        addset = set(_properties.keys()).difference(set(pre_props.keys()))
        removeset = set(pre_props.keys()).difference(set(_properties.keys()))
        mayrepset = set(pre_props.keys()).intersection(set(_properties.keys()))

        for key in addset:
            changes[key] = _properties[key]

        for key in removeset:
            remove_keys.append(key)

        for key in mayrepset:
            if _properties[key] == pre_props[key]:
                continue
            changes[key] = _properties[key]

        """
        image tags
        """
        tag_dict = {}
        pre_tags = pre_image.tags
        new_tags = image.tags

        added_tags = set(new_tags) - set(pre_tags)
        removed_tags = set(pre_tags) - set(new_tags)
        if added_tags:
            tag_dict['add'] = added_tags
        if removed_tags:
            tag_dict['delete'] = removed_tags
        if tag_dict:
            kwargs['tags'] = tag_dict

        kwargs['changes'] = changes
        kwargs['removes'] = remove_keys
        if not changes and not remove_keys and not tag_dict:
            return
        LOG.debug(_('In image %s, some properties changed, sync...')
                  % (image.image_id))
        self.sync_client.update_image_matedata(image.image_id, **kwargs)

    def _try_sync_locations(self, pre_image, image):
        image_id = image.image_id
        """
        image locations
        """
        locations_dict = {}
        pre_locs = pre_image.locations
        _locs = image.locations

        """
        if all locations of cascading removed, the image status become 'queued'
        so the cascaded images should be 'queued' too. we replace all locations
        with '[]'
        """
        if pre_locs and not _locs:
            LOG.debug(_('The image %s all locations removed, sync...')
                      % (image_id))
            self.sync_client.sync_locations(image_id,
                                            action='CLEAR',
                                            locs=pre_locs)
            return

        added_locs = []
        removed_locs = []
        for _loc in pre_locs:
            if _loc in _locs:
                continue
            removed_locs.append(_loc)

        for _loc in _locs:
            if _loc in pre_locs:
                continue
            added_locs.append(_loc)

        if added_locs:
            if _from_snapshot_request(pre_image, image):
                add_kwargs = get_adding_image_properties(image)
            else:
                add_kwargs = {}
            LOG.debug(_('The image %s add locations, sync...') % (image_id))
            self.sync_client.sync_locations(image_id,
                                            action='INSERT',
                                            locs=added_locs,
                                            **add_kwargs)
        elif removed_locs:
            LOG.debug(_('The image %s remove some locations, sync...')
                      % (image_id))
            self.sync_client.sync_locations(image_id,
                                            action='DELETE',
                                            locs=removed_locs)

    def save(self, image):
        pre_image = self.get(image.image_id)
        result = super(ImageRepoProxy, self).save(image)

        image_id = image.image_id
        if _check_trigger_sync(pre_image, image):
            add_kwargs = get_adding_image_properties(image)
            self.sync_client.sync_data(image_id, **add_kwargs)
            LOG.debug(_('Sync data when image status changes ACTIVE, the '
                        'image id is %s.' % (image_id)))
        else:
            """
            In case of add/remove/replace locations property.
            """
            self._try_sync_locations(pre_image, image)
            """
            In case of sync the glance's properties
            """
            if image.status == 'active':
                self._sync_saving_metadata(pre_image, image)

        return result

    def remove(self, image):
        result = super(ImageRepoProxy, self).remove(image)
        LOG.debug(_('Image %s removed, sync...') % (image.image_id))
        delete_kwargs = get_existing_image_locations(image)
        self.sync_client.remove_image(image.image_id, **delete_kwargs)
        return result


class ImageFactoryProxy(glance.domain.proxy.ImageFactory):

    def __init__(self, factory, context, sync_api):
        self.context = context
        self.sync_api = sync_api
        proxy_kwargs = {'context': context, 'sync_api': sync_api}
        super(ImageFactoryProxy, self).__init__(factory,
                                                proxy_class=ImageProxy,
                                                proxy_kwargs=proxy_kwargs)

    def new_image(self, **kwargs):
        return super(ImageFactoryProxy, self).new_image(**kwargs)


class ImageProxy(glance.domain.proxy.Image):

    def __init__(self, image, context, sync_api=None):
        self.image = image
        self.sync_api = sync_api
        self.context = context
        super(ImageProxy, self).__init__(image)
