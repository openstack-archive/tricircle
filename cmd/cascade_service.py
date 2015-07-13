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


import eventlet

if __name__ == "__main__":
    eventlet.monkey_patch()

import sys

from oslo_log import log as logging
from oslo_config import cfg

import tricircle.cascade_service.service as service


def process_command_line_arguments():
    conf = cfg.ConfigOpts()
    logging.register_options(conf)
    logging.set_defaults()
    conf(sys.argv[1:])
    logging.setup(conf, "cascade_service", version='0.1')

if __name__ == "__main__":
    process_command_line_arguments()
    server = service.setup_server()
    server.start()
    server.wait()
