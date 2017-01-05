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
from sqlalchemy.dialects import mysql


def MediumText():
    return sql.Text().with_variant(mysql.MEDIUMTEXT(), 'mysql')


def upgrade(migrate_engine):
    meta = sql.MetaData()
    meta.bind = migrate_engine

    resource_routings = sql.Table(
        'resource_routings', meta,
        sql.Column('id', sql.BigInteger, primary_key=True),
        sql.Column('top_id', sql.String(length=127), nullable=False),
        sql.Column('bottom_id', sql.String(length=36)),
        sql.Column('pod_id', sql.String(length=64), nullable=False),
        sql.Column('project_id', sql.String(length=36)),
        sql.Column('resource_type', sql.String(length=64), nullable=False),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        migrate.UniqueConstraint(
            'top_id', 'pod_id', 'resource_type',
            name='resource_routings0top_id0pod_id0resource_type'
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    async_jobs = sql.Table(
        'async_jobs', meta,
        sql.Column('id', sql.String(length=36), primary_key=True),
        sql.Column('type', sql.String(length=36)),
        sql.Column('timestamp', sql.TIMESTAMP,
                   server_default=sql.text('CURRENT_TIMESTAMP'), index=True),
        sql.Column('status', sql.String(length=36)),
        sql.Column('resource_id', sql.String(length=127)),
        sql.Column('extra_id', sql.String(length=36)),
        migrate.UniqueConstraint(
            'type', 'status', 'resource_id', 'extra_id',
            name='async_jobs0type0status0resource_id0extra_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    async_job_logs = sql.Table(
        'async_job_logs', meta,
        sql.Column('id', sql.String(length=36), primary_key=True),
        sql.Column('resource_id', sql.String(length=127)),
        sql.Column('type', sql.String(length=36)),
        sql.Column('timestamp', sql.TIMESTAMP,
                   server_default=sql.text('CURRENT_TIMESTAMP'), index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    tables = [async_jobs, resource_routings, async_job_logs]
    for table in tables:
        table.create()

    pods = sql.Table('pods', meta, autoload=True)

    fkeys = [{'columns': [resource_routings.c.pod_id],
              'references': [pods.c.pod_id]}]
    for fkey in fkeys:
        migrate.ForeignKeyConstraint(columns=fkey['columns'],
                                     refcolumns=fkey['references'],
                                     name=fkey.get('name')).create()


def downgrade(migrate_engine):
    raise NotImplementedError('downgrade not support')
