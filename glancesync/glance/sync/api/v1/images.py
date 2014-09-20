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

from glance.common import exception
from glance.common import wsgi
import glance.openstack.common.log as logging
from glance.sync.base import SyncManagerV2 as sync_manager
from glance.sync import utils as utils


LOG = logging.getLogger(__name__)


class Controller(object):

    def __init__(self):
        self.sync_manager = sync_manager()
        self.sync_manager.start()

    def test(self, req):
        return {'body': 'for test'}

    def update(self, req, id, body):
        LOG.debug(_('sync client start run UPDATE metadata operation for'
                    'image_id: %s' % (id)))
        self.sync_manager.sync_image_metadata(id, req.context.auth_tok, 'SAVE',
                                              **body)
        return dict({'body': id})

    def remove(self, req, id, body):
        LOG.debug(_('sync client start run DELETE operation for image_id: %s'
                    % (id)))
        self.sync_manager.sync_image_metadata(id, req.context.auth_tok,
                                              'DELETE', **body)
        return dict({'body': id})

    def upload(self, req, id, body):
        LOG.debug(_('sync client start run UPLOAD operation for image_id: %s'
                    % (id)))
        self.sync_manager.sync_image_data(id, req.context.auth_tok, **body)
        return dict({'body': id})

    def sync_loc(self, req, id, body):
        action = body['action']
        locs = body['locations']
        LOG.debug(_('sync client start run SYNC-LOC operation for image_id: %s'
                    % (id)))
        if action == 'INSERT':
            self.sync_manager.adding_locations(id, req.context.auth_tok, locs,
                                               **body)
        elif action == 'DELETE':
            self.sync_manager.removing_locations(id,
                                                 req.context.auth_tok,
                                                 locs)
        elif action == 'CLEAR':
            self.sync_manager.clear_all_locations(id,
                                                  req.context.auth_tok,
                                                  locs)

        return dict({'body': id})

    def endpoints(self, req, body):
        regions = req.params.get('regions', [])
        if not regions:
            regions = body.pop('regions', [])
        if not isinstance(regions, list):
            regions = [regions]
        LOG.debug(_('get cacaded endpoints of user/tenant: %s'
                    % (req.context.user or req.context.tenant or 'NONE')))
        return dict(eps=utils.get_endpoints(req.context.auth_tok,
                                            req.context.tenant,
                                            region_names=regions) or [])


def create_resource():
    """Images resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(Controller(), deserializer, serializer)
