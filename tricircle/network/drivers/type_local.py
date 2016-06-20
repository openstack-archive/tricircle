# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
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

from neutron.plugins.ml2 import driver_api

from tricircle.common import constants


class LocalTypeDriver(driver_api.TypeDriver):
    def get_type(self):
        return constants.NT_LOCAL

    def initialize(self):
        pass

    def is_partial_segment(self, segment):
        return False

    def validate_provider_segment(self, segment):
        pass

    def reserve_provider_segment(self, session, segment):
        return segment

    def allocate_tenant_segment(self, session):
        return {driver_api.NETWORK_TYPE: constants.NT_LOCAL}

    def release_segment(self, session, segment):
        pass

    def get_mtu(self, physical):
        pass
