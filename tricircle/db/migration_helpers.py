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


import os

from oslo_db.sqlalchemy import migration

from tricircle import db
from tricircle.db import core
from tricircle.db import migrate_repo


def find_migrate_repo(package=None, repo_name='migrate_repo'):
    package = package or db
    path = os.path.abspath(os.path.join(
        os.path.dirname(package.__file__), repo_name))
    # TODO(zhiyuan) handle path not valid exception
    return path


def sync_repo(version):
    repo_abs_path = find_migrate_repo()
    init_version = migrate_repo.DB_INIT_VERSION
    engine = core.get_engine()
    migration.db_sync(engine, repo_abs_path, version, init_version)
