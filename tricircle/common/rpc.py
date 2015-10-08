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

from inspect import stack

import neutron.common.rpc as neutron_rpc
import neutron.common.topics as neutron_topics
import neutron.context as neutron_context
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging

from tricircle.common import topics
from tricircle.common.serializer import CascadeSerializer as Serializer

TRANSPORT = oslo_messaging.get_transport(cfg.CONF)

LOG = logging.getLogger(__name__)


class NetworkingRpcApi(object):
    def __init__(self):
        if not neutron_rpc.TRANSPORT:
            neutron_rpc.init(cfg.CONF)
        target = oslo_messaging.Target(topic=neutron_topics.PLUGIN,
                                       version='1.0')
        self.client = neutron_rpc.get_client(target)

    # adapt tricircle context to neutron context
    def _make_neutron_context(self, context):
        return neutron_context.ContextBase(context.user, context.tenant,
                                           auth_token=context.auth_token,
                                           is_admin=context.is_admin,
                                           request_id=context.request_id,
                                           user_name=context.user_name,
                                           tenant_name=context.tenant_name)

    def update_port_up(self, context, port_id):
        call_context = self.client.prepare()
        return call_context.call(self._make_neutron_context(context),
                                 'update_port_up', port_id=port_id)

    def update_port_down(self, context, port_id):
        call_context = self.client.prepare()
        return call_context.call(self._make_neutron_context(context),
                                 'update_port_down', port_id=port_id)


def create_client(component_name):
    topic = topics.CASCADING_SERVICE
    target = oslo_messaging.Target(
        exchange="tricircle",
        topic=topic,
        namespace=component_name,
        version='1.0',
    )

    return oslo_messaging.RPCClient(
        TRANSPORT,
        target,
        serializer=Serializer(),
    )


class AutomaticRpcWrapper(object):
    def __init__(self, send_message_callback):
        self._send_message = send_message_callback

    def _send_message(self, context, method, payload, cast=False):
        """Cast the payload to the running cascading service instances."""

        cctx = self._client.prepare(
            fanout=cast,
        )
        LOG.debug(
            '%(what)s at %(topic)s.%(namespace)s the message %(method)s',
            {
                'topic': cctx.target.topic,
                'namespace': cctx.target.namespace,
                'method': method,
                'what': {True: 'Fanout notify', False: 'Method call'}[cast],
            }
        )

        if cast:
            cctx.cast(context, method, payload=payload)
        else:
            return cctx.call(context, method, payload=payload)

    def send(self, cast):
        """ Autowrap an API call with a send_message() call

        This function uses python tricks to implement a passthrough call from
        the calling API to the cascade service
        """
        caller = stack()[1]
        frame = caller[0]
        method_name = caller[3]
        context = frame.f_locals.get('context', {})

        payload = {}
        for varname in frame.f_code.co_varnames:
            if varname in ("self", "context"):
                continue

            try:
                payload[varname] = frame.f_locals[varname]
            except KeyError:
                pass

        LOG.info(
            "Farwarding request to %s(%s)",
            method_name,
            payload,
        )
        return self._send_message(context, method_name, payload, cast)
