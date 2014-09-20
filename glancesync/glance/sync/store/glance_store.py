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

import fnmatch
import operator
import os

from oslo.config import cfg
import yaml

from glance.sync import utils as s_utils


OPTS = [
    cfg.StrOpt('glance_store_cfg_file',
               default="glance_store.yaml",
               help="Configuration file for glance's store location "
                    "definition."
               ),
]

PRIOR_SOTRE_SCHEMES = ['filesystem', 'http', 'swift']

cfg.CONF.register_opts(OPTS)


def choose_best_store_schemes(source_endpoint, dest_endpoint):
    global GLANCE_STORES
    source_host = s_utils.get_host_from_ep(source_endpoint)
    dest_host = s_utils.get_host_from_ep(dest_endpoint)
    source_store = GLANCE_STORES.get_glance_store(source_host)
    dest_store = GLANCE_STORES.get_glance_store(dest_host)
    tmp_dict = {}
    for s_scheme in source_store.schemes:
        s_scheme_name = s_scheme['name']
        for d_scheme in dest_store.schemes:
            d_scheme_name = d_scheme['name']
            if s_scheme_name == d_scheme_name:
                tmp_dict[s_scheme_name] = (s_scheme, d_scheme)
    if tmp_dict:
        return tmp_dict[sorted(tmp_dict, key=lambda scheme:
                               PRIOR_SOTRE_SCHEMES.index(scheme))[0]]

    return (source_store.schemes[0], dest_store.schemes[0])


class GlanceStore(object):

    def __init__(self, service_ip, name, schemes):
        self.service_ip = service_ip
        self.name = name
        self.schemes = schemes


class ImageObject(object):

    def __init__(self, image_id, glance_store):
        self.image_id = image_id
        self.glance_store = glance_store


class GlanceStoreManager(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self.g_stores = []

        cfg_items = cfg['glances']
        for item in cfg_items:
            self.g_stores.append(GlanceStore(item['service_ip'],
                                             item['name'],
                                             item['schemes']))

    def get_glance_store(self, service_ip):
        for g_store in self.g_stores:
            if service_ip == g_store.service_ip:
                return g_store
        return None

    def generate_Image_obj(self, image_id, endpoint):
        g_store = self.get_glance_store(s_utils.get_host_from_ep(endpoint))
        return ImageObject(image_id, g_store)


GLANCE_STORES = None


def setup_glance_stores():
    global GLANCE_STORES
    cfg_file = cfg.CONF.glance_store_cfg_file
    if not os.path.exists(cfg_file):
        cfg_file = cfg.CONF.find_file(cfg_file)
    with open(cfg_file) as fap:
        data = fap.read()

    locs_cfg = yaml.safe_load(data)
    GLANCE_STORES = GlanceStoreManager(locs_cfg)
