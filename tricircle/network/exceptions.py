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
    message = _('Operation for %(resource)s on bottom pod %(pod_name)s fails')
