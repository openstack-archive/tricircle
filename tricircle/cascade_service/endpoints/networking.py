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


import oslo_messaging

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class CascadeNetworkingServiceEndpoint(object):

    target = oslo_messaging.Target(namespace="networking",
                                   version='1.0')

    def create_network(self, ctx, payload):
        # TODO(gamepl, saggi): STUB
        LOG.info("(create_network) payload: %s", payload)
        return True

    def delete_network(self, ctx, payload):
        # TODO(gampel, saggi): STUB
        LOG.info("(delete_network) payload: %s", payload)
        return True

    def update_network(self, ctx, payload):
        # TODO(gampel, saggi): STUB
        LOG.info("(update_network) payload: %s", payload)
        return True

    def create_port(self, ctx, payload):
        # TODO(gampel, saggi): STUB
        LOG.info("(create_port) payload: %s", payload)
        return True

    def delete_port(self, ctx, payload):
        # TODO(gampel, saggi): STUB
        LOG.info("(delete_port) payload: %s", payload)
        return True
