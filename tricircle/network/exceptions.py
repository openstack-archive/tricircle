# Copyright 2015 Huawei Technologies Co., Ltd.
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

from neutron_lib import exceptions

from tricircle.common.i18n import _


class RemoteGroupNotSupported(exceptions.InvalidInput):
    message = _('Remote group not supported by Tricircle plugin')


class DefaultGroupUpdateNotSupported(exceptions.InvalidInput):
    message = _('Default group update not supported by Tricircle plugin')


class BottomPodOperationFailure(exceptions.NeutronException):
    message = _(
        'Operation for %(resource)s on bottom pod %(region_name)s fails')


class DhcpPortNotFound(exceptions.NotFound):
    message = _('Dhcp port for subnet %(subnet_id)s not found')


class GatewayPortNotFound(exceptions.NotFound):
    message = _('Gateway port for subnet %(subnet_id)s and region %(region)s '
                'not found')


class CentralizedSNATPortNotFound(exceptions.NotFound):
    message = _('Centralized snat port for subnet %(subnet_id)s not found')


class SecurityGroupNotFound(exceptions.NotFound):
    message = _('Security group for %(sg_id)s not found')


class SecurityGroupRuleNotFound(exceptions.NotFound):
    message = _('Security group rule for id %(rule_id)s not found')


class NetAttachedToNonLocalRouter(exceptions.Conflict):
    message = _('Network %(network_id)s has already been attached to non '
                'local router %(router_id)s')


class PortNotFound(exceptions.NotFound):
    message = _('Port for id %(port_id)s not found')


class PortPairsNotFoundForPortPairGroup(exceptions.NotFound):
    message = _(
        'Port pairs for port pair group %(portpairgroup_id)s not found')


class PortPairNotFound(exceptions.NotFound):
    message = _('Port pair for id %(portpair_id)s not found')


class PortChainNotFound(exceptions.NotFound):
    message = _('Port chain for id %(portchain_id)s not found')


class PortChainNotFoundForFlowClassifier(exceptions.NotFound):
    message = _(
        'Port chain for flow classifier %(flowclassifier_id)s not found')


class NetNotFoundForPortChain(exceptions.NotFound):
    message = _('Net for port chain %(portchain_id)s not found')
