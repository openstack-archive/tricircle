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

import migrate
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    resource_routings = Table('resource_routings', meta, autoload=True)
    pods = Table('pods', meta, autoload=True)

    col_pod_id_fkey = getattr(resource_routings.c, 'pod_id')
    col_pod_id_pkey = getattr(pods.c, 'pod_id')

    # In the migration script 002_resource.py, the pod_id string length in
    # resource_routings table is 64, but pod_id string length in pods table
    # is 36. The string length in foreign key and primary key isn't the same
    if col_pod_id_fkey.type.length != col_pod_id_pkey.type.length:
        # Delete the old constraint. If it exists, we can't modify the
        # pod_id length.
        migrate.ForeignKeyConstraint(columns=[resource_routings.c.pod_id],
                                     refcolumns=[pods.c.pod_id]).drop()

        col_pod_id_fkey.alter(type=String(col_pod_id_pkey.type.length))

        # Create the foreign key constraint
        migrate.ForeignKeyConstraint(columns=[resource_routings.c.pod_id],
                                     refcolumns=[pods.c.pod_id]).create()
