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


import sys

from oslo_config import cfg

from tricircle.db import core
from tricircle.db import migration_helpers


def main(argv=None, config_files=None):
    core.initialize()
    cfg.CONF(args=argv[2:],
             project='tricircle',
             default_config_files=config_files)
    migration_helpers.find_migrate_repo()
    migration_helpers.sync_repo(2)


if __name__ == '__main__':
    config_file = sys.argv[1]
    main(argv=sys.argv, config_files=[config_file])
