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

import re

from oslo.config import cfg
import six.moves.urllib.parse as urlparse

from glance.sync.clients import Clients as clients

CONF = cfg.CONF
CONF.import_opt('cascading_endpoint_url', 'glance.common.config', group='sync')
CONF.import_opt('sync_strategy', 'glance.common.config', group='sync')


def create_glance_client(auth_token, url):
    """
    create glance clients
    """
    return clients(auth_token).glance(url=url)


def create_self_glance_client(auth_token):
    return create_glance_client(auth_token, get_cascading_endpoint_url())


def get_mappings_from_image(auth_token, image_id):
    """
    get image's patched glance-locations
    """
    client = create_self_glance_client(auth_token)
    image = client.images.get(image_id)
    locations = image.locations
    if not locations:
        return {}
    return get_mappings_from_locations(locations)


def get_mappings_from_locations(locations):
    mappings = {}
    for loc in locations:
        if is_glance_location(loc['url']):
            id = loc['metadata'].get('image_id')
            if not id:
                continue
            ep_url = create_ep_by_loc(loc)
            mappings[ep_url] = id
    return mappings


def get_cascading_endpoint_url():
    return CONF.sync.cascading_endpoint_url


def get_host_from_ep(ep_url):
    if not ep_url:
        return None
    pieces = urlparse.urlparse(ep_url)
    return pieces.netloc.split(':')[0]

pattern = re.compile(r'^https?://\S+/v2/images/\S+$')


def get_default_location(locations):
    for location in locations:
        if is_default_location(location):
            return location
    return None


def is_glance_location(loc_url):
    return pattern.match(loc_url)


def is_snapshot_location(location):
    l_meta = location['metadata']
    return l_meta and l_meta.get('image_from', None) in['snapshot', 'volume']


def get_id_from_glance_loc(location):
    if not is_glance_location(location['url']):
        return None
    loc_meta = location['metadata']
    if not loc_meta:
        return None
    return loc_meta.get('image_id', None)


def is_default_location(location):
    try:
        return not is_glance_location(location['url']) \
            and location['metadata']['is_default'] == 'true'
    except:
        return False


def get_snapshot_glance_loc(locations):
    for location in locations:
        if is_snapshot_location(location):
            return location
    return None


def create_ep_by_loc(location):
    loc_url = location['url']
    if not is_glance_location(loc_url):
        return None
    piece = urlparse.urlparse(loc_url)
    return piece.scheme + '://' + piece.netloc + '/'


def generate_glance_location(ep, image_id, port=None):
    default_port = port or '9292'
    piece = urlparse.urlparse(ep)
    paths = []
    paths.append(piece.scheme)
    paths.append('://')
    paths.append(piece.netloc.split(':')[0])
    paths.append(':')
    paths.append(default_port)
    paths.append('/v2/images/')
    paths.append(image_id)
    return ''.join(paths)


def get_endpoints(auth_token=None, tenant_id=None, **kwargs):
    """
    find which glance should be sync by strategy config
    """
    strategy = CONF.sync.sync_strategy
    if strategy not in ['All', 'User']:
        return None

    openstack_clients = clients(auth_token, tenant_id)
    ksclient = openstack_clients.keystone()

    '''
    suppose that the cascading glance is 'public' endpoint type, and the
    cascaded glacne endpoints are 'internal'
    '''
    regions = kwargs.pop('region_names', [])
    if strategy == 'All' and not regions:
        urls = ksclient.service_catalog.get_urls(service_type='image',
                                                 endpoint_type='publicURL')
        if urls:
            result = [u for u in urls if u != get_cascading_endpoint_url()]
        else:
            result = []
        return result
    else:
        user_urls = []
        for region_name in regions:
            urls = ksclient.service_catalog.get_urls(service_type='image',
                                                     endpoint_type='publicURL',
                                                     region_name=region_name)
            if urls:
                user_urls.extend(urls)
        result = [u for u in set(user_urls) if u !=
                  get_cascading_endpoint_url()]
        return result


_V2_IMAGE_CREATE_PROPERTIES = ['container_format',
                               'disk_format', 'min_disk', 'min_ram', 'name',
                               'virtual_size', 'visibility', 'protected']


def get_core_properties(image):
    """
    when sync, create image object, get the sync info
    """
    _tags = list(image.tags) or []
    kwargs = {}
    for key in _V2_IMAGE_CREATE_PROPERTIES:
        try:
            value = getattr(image, key, None)
            if value and value != 'None':
                kwargs[key] = value
        except KeyError:
            pass
    if _tags:
        kwargs['tags'] = _tags
    return kwargs


def calculate_lack_endpoints(all_ep_urls, glance_urls):
    """
    calculate endpoints which exists in all_eps but not in glance_eps
    """
    if not glance_urls:
        return all_ep_urls

    def _contain(ep):
        _hosts = [urlparse.urlparse(_ep).netloc for _ep in glance_urls]
        return not urlparse.urlparse(ep).netloc in _hosts
    return filter(_contain, all_ep_urls)


def is_ep_contains(ep_url, glance_urls):
    _hosts = [urlparse.urlparse(_ep).netloc for _ep in glance_urls]
    return urlparse.urlparse(ep_url) in _hosts
