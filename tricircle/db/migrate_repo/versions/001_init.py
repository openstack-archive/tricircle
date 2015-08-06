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


import migrate
import sqlalchemy as sql


def upgrade(migrate_engine):
    meta = sql.MetaData()
    meta.bind = migrate_engine

    cascaded_sites = sql.Table(
        'cascaded_sites', meta,
        sql.Column('site_id', sql.String(length=64), primary_key=True),
        sql.Column('site_name', sql.String(length=64), unique=True,
                   nullable=False),
        sql.Column('az_id', sql.String(length=64), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8')
    cascaded_site_service_configuration = sql.Table(
        'cascaded_site_service_configuration', meta,
        sql.Column('service_id', sql.String(length=64), primary_key=True),
        sql.Column('site_id', sql.String(length=64), nullable=False),
        sql.Column('service_name', sql.String(length=64), unique=True,
                   nullable=False),
        sql.Column('service_type', sql.String(length=64), nullable=False),
        sql.Column('service_url', sql.String(length=512), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8')
    cascaded_service_types = sql.Table(
        'cascaded_service_types', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('service_type', sql.String(length=64), unique=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8')
    cascaded_site_services = sql.Table(
        'cascaded_site_services', meta,
        sql.Column('site_id', sql.String(length=64), primary_key=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    tables = [cascaded_sites, cascaded_site_service_configuration,
              cascaded_service_types, cascaded_site_services]
    for table in tables:
        table.create()

    fkeys = [
        {'columns': [cascaded_site_service_configuration.c.site_id],
         'references': [cascaded_sites.c.site_id]},
        {'columns': [cascaded_site_service_configuration.c.service_type],
         'references': [cascaded_service_types.c.service_type]}
    ]
    for fkey in fkeys:
        migrate.ForeignKeyConstraint(columns=fkey['columns'],
                                     refcolumns=fkey['references'],
                                     name=fkey.get('name')).create()


def downgrade(migrate_engine):
    raise NotImplementedError('can not downgrade from init repo.')
