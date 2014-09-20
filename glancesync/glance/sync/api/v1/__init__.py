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

from glance.common import wsgi
from glance.sync.api.v1 import images


def init(mapper):

    images_resource = images.create_resource()

    mapper.connect("/cascaded-eps",
                   controller=images_resource,
                   action="endpoints",
                   conditions={'method': ['POST']})

    mapper.connect("/images/{id}",
                   controller=images_resource,
                   action="update",
                   conditions={'method': ['PATCH']})

    mapper.connect("/images/{id}",
                   controller=images_resource,
                   action="remove",
                   conditions={'method': ['DELETE']})

    mapper.connect("/images/{id}",
                   controller=images_resource,
                   action="upload",
                   conditions={'method': ['PUT']})

    mapper.connect("/images/{id}/location",
                   controller=images_resource,
                   action="sync_loc",
                   conditions={'method': ['PUT']})


class API(wsgi.Router):

    """WSGI entry point for all Registry requests."""

    def __init__(self, mapper):
        mapper = mapper or wsgi.APIMapper()
        init(mapper)
        super(API, self).__init__(mapper)
