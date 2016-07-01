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

    aggregates = sql.Table(
        'aggregates', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('name', sql.String(255), unique=True),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    aggregate_metadata = sql.Table(
        'aggregate_metadata', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('key', sql.String(255), nullable=False),
        sql.Column('value', sql.String(255), nullable=False),
        sql.Column('aggregate_id', sql.Integer, nullable=False),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        migrate.UniqueConstraint(
            'aggregate_id', 'key',
            name='uniq_aggregate_metadata0aggregate_id0key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    instance_types = sql.Table(
        'instance_types', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('name', sql.String(255), unique=True),
        sql.Column('memory_mb', sql.Integer, nullable=False),
        sql.Column('vcpus', sql.Integer, nullable=False),
        sql.Column('root_gb', sql.Integer),
        sql.Column('ephemeral_gb', sql.Integer),
        sql.Column('flavorid', sql.String(255), unique=True),
        sql.Column('swap', sql.Integer, nullable=False, default=0),
        sql.Column('rxtx_factor', sql.Float, default=1),
        sql.Column('vcpu_weight', sql.Integer),
        sql.Column('disabled', sql.Boolean, default=False),
        sql.Column('is_public', sql.Boolean, default=True),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    instance_type_projects = sql.Table(
        'instance_type_projects', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('instance_type_id', sql.Integer, nullable=False),
        sql.Column('project_id', sql.String(255)),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        migrate.UniqueConstraint(
            'instance_type_id', 'project_id',
            name='uniq_instance_type_projects0instance_type_id0project_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    instance_type_extra_specs = sql.Table(
        'instance_type_extra_specs', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('key', sql.String(255)),
        sql.Column('value', sql.String(255)),
        sql.Column('instance_type_id', sql.Integer, nullable=False),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        migrate.UniqueConstraint(
            'instance_type_id', 'key',
            name='uniq_instance_type_extra_specs0instance_type_id0key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    enum = sql.Enum('ssh', 'x509', metadata=meta, name='keypair_types')
    enum.create()

    key_pairs = sql.Table(
        'key_pairs', meta,
        sql.Column('id', sql.Integer, primary_key=True, nullable=False),
        sql.Column('name', sql.String(255), nullable=False),
        sql.Column('user_id', sql.String(255)),
        sql.Column('fingerprint', sql.String(255)),
        sql.Column('public_key', MediumText()),
        sql.Column('type', enum, nullable=False, server_default='ssh'),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        migrate.UniqueConstraint(
            'user_id', 'name',
            name='uniq_key_pairs0user_id0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    quotas = sql.Table(
        'quotas', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('project_id', sql.String(255), index=True),
        sql.Column('resource', sql.String(255), nullable=False),
        sql.Column('hard_limit', sql.Integer),
        sql.Column('allocated', sql.Integer, default=0),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    quota_classes = sql.Table(
        'quota_classes', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('class_name', sql.String(255), index=True),
        sql.Column('resource', sql.String(255), nullable=False),
        sql.Column('hard_limit', sql.Integer),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    quota_usages = sql.Table(
        'quota_usages', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('project_id', sql.String(255), index=True),
        sql.Column('user_id', sql.String(255), index=True),
        sql.Column('resource', sql.String(255), nullable=False),
        sql.Column('in_use', sql.Integer),
        sql.Column('reserved', sql.Integer),
        sql.Column('until_refresh', sql.Integer),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    reservations = sql.Table(
        'reservations', meta,
        sql.Column('id', sql.Integer(), primary_key=True),
        sql.Column('uuid', sql.String(length=36), nullable=False),
        sql.Column('usage_id', sql.Integer(),
                   sql.ForeignKey('quota_usages.id'),
                   nullable=False),
        sql.Column('project_id',
                   sql.String(length=255),
                   index=True),
        sql.Column('resource',
                   sql.String(length=255)),
        sql.Column('delta', sql.Integer(), nullable=False),
        sql.Column('expire', sql.DateTime),

        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Boolean(create_constraint=True,
                                          name=None)),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    volume_types = sql.Table(
        'volume_types', meta,
        sql.Column('id', sql.String(36), primary_key=True),
        sql.Column('name', sql.String(255), unique=True),
        sql.Column('description', sql.String(255)),
        sql.Column('qos_specs_id', sql.String(36)),
        sql.Column('is_public', sql.Boolean, default=True),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    volume_type_extra_specs = sql.Table(
        'volume_type_extra_specs', meta,
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('deleted', sql.Boolean),
        sql.Column('id', sql.Integer, primary_key=True, nullable=False),
        sql.Column('volume_type_id', sql.String(36),
                   sql.ForeignKey('volume_types.id'),
                   nullable=False),
        sql.Column('key', sql.String(length=255)),
        sql.Column('value', sql.String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    volume_type_projects = sql.Table(
        'volume_type_projects', meta,
        sql.Column('id', sql.Integer, primary_key=True, nullable=False),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        sql.Column('deleted_at', sql.DateTime),
        sql.Column('volume_type_id', sql.String(36),
                   sql.ForeignKey('volume_types.id'),
                   nullable=False),
        sql.Column('project_id', sql.String(length=255)),
        sql.Column('deleted', sql.Boolean(create_constraint=True, name=None)),
        migrate.UniqueConstraint(
            'volume_type_id', 'project_id', 'deleted',
            name='uniq_volume_type_projects0volume_type_id0project_id0deleted'
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    quality_of_service_specs = sql.Table(
        'quality_of_service_specs', meta,
        sql.Column('id', sql.String(36), primary_key=True),
        sql.Column('specs_id', sql.String(36)),
        sql.Column('key', sql.String(255)),
        sql.Column('value', sql.String(255)),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    cascaded_pods_resource_routing = sql.Table(
        'cascaded_pods_resource_routing', meta,
        sql.Column('id', sql.Integer, primary_key=True),
        sql.Column('top_id', sql.String(length=127), nullable=False),
        sql.Column('bottom_id', sql.String(length=36)),
        sql.Column('pod_id', sql.String(length=64), nullable=False),
        sql.Column('project_id', sql.String(length=36)),
        sql.Column('resource_type', sql.String(length=64), nullable=False),
        sql.Column('created_at', sql.DateTime),
        sql.Column('updated_at', sql.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    job = sql.Table(
        'job', meta,
        sql.Column('id', sql.String(length=36), primary_key=True),
        sql.Column('type', sql.String(length=36)),
        sql.Column('timestamp', sql.TIMESTAMP,
                   server_default=sql.text('CURRENT_TIMESTAMP')),
        sql.Column('status', sql.String(length=36)),
        sql.Column('resource_id', sql.String(length=127)),
        sql.Column('extra_id', sql.String(length=36)),
        migrate.UniqueConstraint(
            'type', 'status', 'resource_id', 'extra_id',
            name='job0type0status0resource_id0extra_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    tables = [aggregates, aggregate_metadata, instance_types,
              instance_type_projects, instance_type_extra_specs, key_pairs,
              quotas, quota_classes, quota_usages, reservations,
              volume_types, volume_type_extra_specs, volume_type_projects,
              job, quality_of_service_specs, cascaded_pods_resource_routing]
    for table in tables:
        table.create()

    cascaded_pods = sql.Table('cascaded_pods', meta, autoload=True)

    fkeys = [{'columns': [instance_type_projects.c.instance_type_id],
              'references': [instance_types.c.id]},
             {'columns': [instance_type_extra_specs.c.instance_type_id],
              'references': [instance_types.c.id]},
             {'columns': [reservations.c.usage_id],
              'references': [quota_usages.c.id]},
             {'columns': [volume_types.c.qos_specs_id],
              'references': [quality_of_service_specs.c.id]},
             {'columns': [volume_type_extra_specs.c.volume_type_id],
              'references': [volume_types.c.id]},
             {'columns': [volume_type_projects.c.volume_type_id],
              'references': [volume_types.c.id]},
             {'columns': [quality_of_service_specs.c.specs_id],
              'references': [quality_of_service_specs.c.id]},
             {'columns': [aggregate_metadata.c.aggregate_id],
              'references': [aggregates.c.id]},
             {'columns': [cascaded_pods_resource_routing.c.pod_id],
              'references': [cascaded_pods.c.pod_id]}]
    for fkey in fkeys:
        migrate.ForeignKeyConstraint(columns=fkey['columns'],
                                     refcolumns=fkey['references'],
                                     name=fkey.get('name')).create()


def downgrade(migrate_engine):
    raise NotImplementedError('downgrade not support')
