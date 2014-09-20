# Copyright (c) 2013 OpenStack Foundation.
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
#
# @author: Haojie Jia, Huawei
# @author: Sylvain Afchain, eNovance SAS
# @author: Francois Eleouet, Orange
# @author: Mathieu Rohon, Orange

from oslo.config import cfg


l2_population_options = [
    cfg.IntOpt('agent_boot_time', default=180,
               help=_('Delay within which agent is expected to update '
                      'existing ports whent it restarts')),
    cfg.StrOpt('cascaded_gateway', default='no_gateway',
               help=_('if not existing the gateway host Configure no_gateway'
                      'else configure admin_gateway or population_opt')),
]

cfg.CONF.register_opts(l2_population_options, "l2pop")
