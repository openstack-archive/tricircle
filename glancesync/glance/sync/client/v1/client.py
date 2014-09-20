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

from glance.common.client import BaseClient
from glance.openstack.common import jsonutils
import glance.openstack.common.log as logging


LOG = logging.getLogger(__name__)


class SyncClient(BaseClient):

    DEFAULT_PORT = 9595

    def __init__(self, host=None, port=DEFAULT_PORT, identity_headers=None,
                 **kwargs):
        self.identity_headers = identity_headers
        BaseClient.__init__(self, host, port, configure_via_auth=False,
                            **kwargs)

    def do_request(self, method, action, **kwargs):
        try:
            kwargs['headers'] = kwargs.get('headers', {})
            res = super(SyncClient, self).do_request(method, action, **kwargs)
            status = res.status
            request_id = res.getheader('x-openstack-request-id')
            msg = (_("Sync request %(method)s %(action)s HTTP %(status)s"
                     " request id %(request_id)s") %
                   {'method': method, 'action': action,
                    'status': status, 'request_id': request_id})
            LOG.debug(msg)

        except Exception as exc:
            exc_name = exc.__class__.__name__
            LOG.info(_("Sync client request %(method)s %(action)s "
                       "raised %(exc_name)s"),
                     {'method': method, 'action': action,
                      'exc_name': exc_name})
            raise
        return res

    def _add_common_params(self, id, kwargs):
        pass

    def update_image_matedata(self, image_id, **kwargs):
        headers = {
            'Content-Type': 'application/json',
        }
        body = jsonutils.dumps(kwargs)
        res = self.do_request("PATCH", "/v1/images/%s" % (image_id), body=body,
                              headers=headers)
        return res

    def remove_image(self, image_id, **kwargs):
        headers = {
            'Content-Type': 'application/json',
        }
        body = jsonutils.dumps(kwargs)
        res = self.do_request("DELETE", "/v1/images/%s" %
                              (image_id), body=body, headers=headers)
        return res

    def sync_data(self, image_id, **kwargs):
        headers = {
            'Content-Type': 'application/json',
        }
        body = jsonutils.dumps(kwargs)
        res = self.do_request("PUT", "/v1/images/%s" % (image_id), body=body,
                              headers=headers)
        return res

    def sync_locations(self, image_id, action=None, locs=None, **kwargs):
        headers = {
            'Content-Type': 'application/json',
        }
        kwargs['action'] = action
        kwargs['locations'] = locs
        body = jsonutils.dumps(kwargs)
        res = self.do_request("PUT", "/v1/images/%s/location" % (image_id),
                              body=body, headers=headers)
        return res

    def get_cascaded_endpoints(self, regions=[]):
        headers = {
            'Content-Type': 'application/json',
        }

        body = jsonutils.dumps({'regions': regions})
        res = self.do_request('POST', '/v1/cascaded-eps', body=body,
                              headers=headers)
        return jsonutils.loads(res.read())['eps']
