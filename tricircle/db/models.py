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

from oslo_db.sqlalchemy import models

import sqlalchemy as sql
from sqlalchemy.dialects import mysql
from sqlalchemy import schema

from tricircle.db import core


def MediumText():
    return sql.Text().with_variant(mysql.MEDIUMTEXT(), 'mysql')


# Pod Model
class Pod(core.ModelBase, core.DictBase):
    __tablename__ = 'pods'
    attributes = ['pod_id', 'region_name', 'pod_az_name', 'dc_name', 'az_name']

    pod_id = sql.Column('pod_id', sql.String(length=36), primary_key=True)
    region_name = sql.Column('region_name', sql.String(length=255),
                             unique=True, nullable=False)
    pod_az_name = sql.Column('pod_az_name', sql.String(length=255),
                             nullable=True)
    dc_name = sql.Column('dc_name', sql.String(length=255), nullable=True)
    az_name = sql.Column('az_name', sql.String(length=255), nullable=False)


class CachedEndpoint(core.ModelBase, core.DictBase):
    __tablename__ = 'cached_endpoints'
    attributes = ['service_id', 'pod_id', 'service_type', 'service_url']

    service_id = sql.Column('service_id', sql.String(length=64),
                            primary_key=True)
    pod_id = sql.Column('pod_id', sql.String(length=36),
                        sql.ForeignKey('pods.pod_id'),
                        nullable=False)
    service_type = sql.Column('service_type', sql.String(length=64),
                              nullable=False)
    service_url = sql.Column('service_url', sql.String(length=512),
                             nullable=False)


# Routing Model
class ResourceRouting(core.ModelBase, core.DictBase, models.TimestampMixin):
    __tablename__ = 'resource_routings'
    __table_args__ = (
        schema.UniqueConstraint(
            'top_id', 'pod_id', 'resource_type',
            name='resource_routings0top_id0pod_id0resource_type'),
    )
    attributes = ['id', 'top_id', 'bottom_id', 'pod_id', 'project_id',
                  'resource_type', 'created_at', 'updated_at']

    # sqlite doesn't support auto increment on big integers so we use big int
    # for everything but sqlite
    id = sql.Column(sql.BigInteger().with_variant(sql.Integer(), 'sqlite'),
                    primary_key=True, autoincrement=True)
    top_id = sql.Column('top_id', sql.String(length=127), nullable=False)
    bottom_id = sql.Column('bottom_id', sql.String(length=36))
    pod_id = sql.Column('pod_id', sql.String(length=36),
                        sql.ForeignKey('pods.pod_id'),
                        nullable=False)
    project_id = sql.Column('project_id', sql.String(length=36))
    resource_type = sql.Column('resource_type', sql.String(length=64),
                               nullable=False)


class AsyncJob(core.ModelBase, core.DictBase):
    __tablename__ = 'async_jobs'
    __table_args__ = (
        schema.UniqueConstraint(
            'type', 'status', 'resource_id', 'extra_id',
            name='async_jobs0type0status0resource_id0extra_id'),
    )

    attributes = ['id', 'project_id', 'type', 'timestamp', 'status',
                  'resource_id', 'extra_id']

    id = sql.Column('id', sql.String(length=36), primary_key=True)
    project_id = sql.Column('project_id', sql.String(length=36))
    type = sql.Column('type', sql.String(length=36))
    timestamp = sql.Column('timestamp', sql.TIMESTAMP,
                           server_default=sql.text('CURRENT_TIMESTAMP'),
                           index=True)
    status = sql.Column('status', sql.String(length=36))
    resource_id = sql.Column('resource_id', sql.String(length=127))
    extra_id = sql.Column('extra_id', sql.String(length=36))


class AsyncJobLog(core.ModelBase, core.DictBase):
    __tablename__ = 'async_job_logs'

    attributes = ['id', 'project_id', 'resource_id', 'type', 'timestamp']

    id = sql.Column('id', sql.String(length=36), primary_key=True)
    project_id = sql.Column('project_id', sql.String(length=36))
    resource_id = sql.Column('resource_id', sql.String(length=127))
    type = sql.Column('type', sql.String(length=36))
    timestamp = sql.Column('timestamp', sql.TIMESTAMP,
                           server_default=sql.text('CURRENT_TIMESTAMP'),
                           index=True)


class ShadowAgent(core.ModelBase, core.DictBase):
    __tablename__ = 'shadow_agents'
    __table_args__ = (
        schema.UniqueConstraint(
            'host', 'type',
            name='host0type'),
    )

    attributes = ['id', 'pod_id', 'host', 'type', 'tunnel_ip']

    id = sql.Column('id', sql.String(length=36), primary_key=True)
    pod_id = sql.Column('pod_id', sql.String(length=36),
                        sql.ForeignKey('pods.pod_id'),
                        nullable=False)
    host = sql.Column('host', sql.String(length=255), nullable=False)
    type = sql.Column('type', sql.String(length=36), nullable=False)
    # considering IPv6 address, set the length to 48
    tunnel_ip = sql.Column('tunnel_ip', sql.String(length=48), nullable=False)
