# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from oslo_log import log as logging
import oslo_messaging

from tricircle.common import rpc
from tricircle.common import topics

LOG = logging.getLogger(__name__)


class CascadingSiteNotifyAPI(object):
    """API for to notify Cascading service for the site API."""

    def __init__(self, topic=topics.CASCADING_SERVICE):
        target = oslo_messaging.Target(topic=topic,
                                       exchange="tricircle",
                                       namespace="site",
                                       version='1.0',
                                       fanout=True)
        self.client = rpc.create_client(target)

    def _cast_message(self, context, method, payload):
        """Cast the payload to the running cascading service instances."""

        cctx = self.client.prepare()
        LOG.debug('Fanout notify at %(topic)s.%(namespace)s the message '
                  '%(method)s for CascadingSite.  payload: %(payload)s',
                  {'topic': cctx.target.topic,
                   'namespace': cctx.target.namespace,
                   'payload': payload,
                   'method': method})
        cctx.cast(context, method, payload=payload)

    def create_site(self, context, site_name):
        self._cast_message(context, "create_site", site_name)
