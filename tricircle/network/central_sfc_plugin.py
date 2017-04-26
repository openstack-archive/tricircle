# Copyright 2017 Huawei Technologies Co., Ltd.
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


from oslo_log import log

from networking_sfc.extensions import sfc as sfc_ext
from networking_sfc.services.sfc import plugin as sfc_plugin
from neutron_lib import exceptions as n_exc
from neutron_lib.plugins import directory


LOG = log.getLogger(__name__)


class TricircleSfcPlugin(sfc_plugin.SfcPlugin):

    def __init__(self):
        super(TricircleSfcPlugin, self).__init__()

    # TODO(xiulin): Tricircle's top region can not get port's
    # binding information well now, so override this function,
    # we will improve this later.
    def _get_port(self, context, id):
        core_plugin = directory.get_plugin()
        try:
            return core_plugin.get_port(context, id)
        except n_exc.PortNotFound:
            raise sfc_ext.PortPairPortNotFound(id=id)
