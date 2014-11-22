#    Copyright 2013 IBM Corp.
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


from sqlalchemy import String, Column, MetaData, Table


def upgrade(migrate_engine):
    """Add mapping_uuid column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    mapping_uuid = Column('mapping_uuid', String(36))
    volumes.create_column(mapping_uuid)


def downgrade(migrate_engine):
    """Remove mapping_uuid column from volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    mapping_uuid = volumes.columns.mapping_uuid
    volumes.drop_column(mapping_uuid)
