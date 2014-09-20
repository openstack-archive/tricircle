# Copyright (c) 2014 OpenStack Foundation.
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
# @author: Jia Dong, HuaWei

from concurrent.futures import ThreadPoolExecutor

import glance.openstack.common.log as logging


LOG = logging.getLogger(__name__)


class ThreadPool(object):

    def __init__(self):
        self.pool = ThreadPoolExecutor(128)

    def execute(self, func, *args, **kwargs):
        LOG.info(_('execute %s in a thread pool') % (func.__name__))
        self.pool.submit(func, *args, **kwargs)
