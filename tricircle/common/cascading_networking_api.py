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

from neutron.common import rpc as n_rpc
from tricircle.common import topics
from tricircle.common.serializer import CascadeSerializer as Serializer

LOG = logging.getLogger(__name__)


class CascadingNetworkingNotifyAPI(object):
    """API for to notify Cascading service for the networking API."""

    def __init__(self, topic=topics.CASCADING_SERVICE):
        target = oslo_messaging.Target(topic=topic,
                                       exchange="tricircle",
                                       namespace="networking",
                                       version='1.0',
                                       fanout=True)
        self.client = n_rpc.get_client(
            target,
            serializer=Serializer(),
        )

    def _cast_message(self, context, method, payload):
        """Cast the payload to the running cascading service instances."""

        cctx = self.client.prepare()
        LOG.debug('Fanout notify at %(topic)s.%(namespace)s the message '
                  '%(method)s for CascadingNetwork.  payload: %(payload)s',
                  {'topic': cctx.target.topic,
                   'namespace': cctx.target.namespace,
                   'payload': payload,
                   'method': method})
        cctx.cast(context, method, payload=payload)

    def create_network(self, context, network):
        self._cast_message(context, "create_network", network)

    def delete_network(self, context, network_id):
        self._cast_message(context,
                           "delete_network",
                           {'network_id': network_id})

    def update_network(self, context, network_id, network):
        payload = {
            'network_id': network_id,
            'network': network
        }
        self._cast_message(context, "update_network", payload)

    def create_port(self, context, port):
        self._cast_message(context, "create_port", port)

    def delete_port(self, context, port_id, l3_port_check=True):
        payload = {
            'port_id': port_id,
            'l3_port_check': l3_port_check
        }
        self._cast_message(context, "delete_port", payload)
