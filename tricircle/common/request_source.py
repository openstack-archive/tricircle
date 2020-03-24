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

from oslo_log import log as logging
from oslo_middleware import base
from tricircle.common import constants as cons
import webob

LOG = logging.getLogger(__name__)


class RequestSource(base.ConfigurableMiddleware):
    """RequestSource Middleware

    This middleware distinguishes the source of the requests. It can find out
    which request is from central Neutron and which is from local Neutron.

    This middleware updates the context to put the source of requests
    extracted from headers.

    In order to make RequestSource Middleware work, this middleware should
    place after keystoneContext(in etc/neutron/api-paste.ini).
    """

    def distinguish_requests_source(self, req):
        source_header = req.headers.get(cons.USER_AGENT, "")

        if source_header in cons.REQUEST_SOURCE_TYPE:
            ctx = req.environ['neutron.context']
            ctx.USER_AGENT = source_header
            req.environ['neutron.context'] = ctx

    @webob.dec.wsgify
    def __call__(self, req):
        self.distinguish_requests_source(req)

        response = req.get_response(self.application)
        return response
