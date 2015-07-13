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


from socket import gethostname

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging

from tricircle.common import topics
from tricircle.common.serializer import CascadeSerializer as Serializer

# import endpoints here
from tricircle.cascade_service.endpoints.networking import (
    CascadeNetworkingServiceEndpoint)

LOG = logging.getLogger(__name__)


class ServerControlEndpoint(object):
    target = oslo_messaging.Target(namespace='control',
                                   version='1.0')

    def __init__(self, server):
        self.server = server

    def stop(self, ctx):
        if self.server:
            self.server.stop()


def setup_server():
    transport = oslo_messaging.get_transport(cfg.CONF)
    target = oslo_messaging.Target(
        exchange="tricircle",
        topic=topics.CASCADING_SERVICE,
        server=gethostname(),
    )
    server_control_endpoint = ServerControlEndpoint(None)
    endpoints = [
        server_control_endpoint,
        CascadeNetworkingServiceEndpoint(),
    ]
    server = oslo_messaging.get_rpc_server(
        transport,
        target,
        endpoints,
        executor='eventlet',
        serializer=Serializer(),
    )
    server_control_endpoint.server = server
    return server
