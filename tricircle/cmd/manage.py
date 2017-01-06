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
from oslo_log import log as logging

from tricircle.db import core
from tricircle.db import migration_helpers

import pbr.version

CONF = cfg.CONF


def do_db_version():
    print(migration_helpers.db_version())


def do_db_sync():
    migration_helpers.sync_repo(CONF.command.version)


def add_command_parsers(subparsers):
    parser = subparsers.add_parser('db_version')
    parser.set_defaults(func=do_db_version)

    parser = subparsers.add_parser('db_sync')
    parser.set_defaults(func=do_db_sync)
    parser.add_argument('version', nargs='?')

command_opt = cfg.SubCommandOpt('command',
                                title='Commands',
                                help='Show available commands.',
                                handler=add_command_parsers)


def main():
    core.initialize()
    logging.register_options(CONF)
    logging.setup(CONF, 'tricircle-db-manage')
    CONF.register_cli_opt(command_opt)
    version_info = pbr.version.VersionInfo('tricircle')

    try:
        CONF(sys.argv[1:], project='tricircle', prog='tricircle-db-manage',
             version=version_info.version_string())
    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)

    try:
        CONF.command.func()
    except Exception as e:
        sys.exit("ERROR: %s" % e)
