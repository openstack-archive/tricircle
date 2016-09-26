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

import sqlalchemy as sql
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship
from sqlalchemy import schema

from oslo_db.sqlalchemy import models
from oslo_utils import timeutils

from tricircle.db import core


def MediumText():
    return sql.Text().with_variant(mysql.MEDIUMTEXT(), 'mysql')


# Resource Model
class Aggregate(core.ModelBase, core.DictBase, models.TimestampMixin):
    """Represents a cluster of hosts that exists in this zone."""
    __tablename__ = 'aggregates'
    attributes = ['id', 'name', 'created_at', 'updated_at']

    id = sql.Column(sql.Integer, primary_key=True)
    name = sql.Column(sql.String(255), unique=True)


class AggregateMetadata(core.ModelBase, core.DictBase, models.TimestampMixin):
    """Represents a metadata key/value pair for an aggregate."""
    __tablename__ = 'aggregate_metadata'
    __table_args__ = (
        sql.Index('aggregate_metadata_key_idx', 'key'),
        schema.UniqueConstraint(
            'aggregate_id', 'key',
            name='uniq_aggregate_metadata0aggregate_id0key'),
    )
    attributes = ['id', 'key', 'value', 'aggregate_id',
                  'created_at', 'updated_at']

    id = sql.Column(sql.Integer, primary_key=True)
    key = sql.Column(sql.String(255), nullable=False)
    value = sql.Column(sql.String(255), nullable=False)
    aggregate_id = sql.Column(sql.Integer,
                              sql.ForeignKey('aggregates.id'), nullable=False)


class InstanceTypes(core.ModelBase, core.DictBase, models.TimestampMixin):
    """Represents possible flavors for instances.

    Note: instance_type and flavor are synonyms and the term instance_type is
    deprecated and in the process of being removed.
    """
    __tablename__ = 'instance_types'
    attributes = ['id', 'name', 'memory_mb', 'vcpus', 'root_gb',
                  'ephemeral_gb', 'flavorid', 'swap', 'rxtx_factor',
                  'vcpu_weight', 'disabled', 'is_public', 'created_at',
                  'updated_at']

    # Internal only primary key/id
    id = sql.Column(sql.Integer, primary_key=True)
    name = sql.Column(sql.String(255), unique=True)
    memory_mb = sql.Column(sql.Integer, nullable=False)
    vcpus = sql.Column(sql.Integer, nullable=False)
    root_gb = sql.Column(sql.Integer)
    ephemeral_gb = sql.Column(sql.Integer)
    # Public facing id will be renamed public_id
    flavorid = sql.Column(sql.String(255), unique=True)
    swap = sql.Column(sql.Integer, nullable=False, default=0)
    rxtx_factor = sql.Column(sql.Float, default=1)
    vcpu_weight = sql.Column(sql.Integer)
    disabled = sql.Column(sql.Boolean, default=False)
    is_public = sql.Column(sql.Boolean, default=True)


class InstanceTypeProjects(core.ModelBase, core.DictBase,
                           models.TimestampMixin):
    """Represent projects associated instance_types."""
    __tablename__ = 'instance_type_projects'
    __table_args__ = (schema.UniqueConstraint(
        'instance_type_id', 'project_id',
        name='uniq_instance_type_projects0instance_type_id0project_id'),
    )
    attributes = ['id', 'instance_type_id', 'project_id', 'created_at',
                  'updated_at']

    id = sql.Column(sql.Integer, primary_key=True)
    instance_type_id = sql.Column(sql.Integer,
                                  sql.ForeignKey('instance_types.id'),
                                  nullable=False)
    project_id = sql.Column(sql.String(255))


class InstanceTypeExtraSpecs(core.ModelBase, core.DictBase,
                             models.TimestampMixin):
    """Represents additional specs as key/value pairs for an instance_type."""
    __tablename__ = 'instance_type_extra_specs'
    __table_args__ = (
        sql.Index('instance_type_extra_specs_instance_type_id_key_idx',
                  'instance_type_id', 'key'),
        schema.UniqueConstraint(
            'instance_type_id', 'key',
            name='uniq_instance_type_extra_specs0instance_type_id0key'),
        {'mysql_collate': 'utf8_bin'},
    )
    attributes = ['id', 'key', 'value', 'instance_type_id', 'created_at',
                  'updated_at']

    id = sql.Column(sql.Integer, primary_key=True)
    key = sql.Column(sql.String(255))
    value = sql.Column(sql.String(255))
    instance_type_id = sql.Column(sql.Integer,
                                  sql.ForeignKey('instance_types.id'),
                                  nullable=False)


class KeyPair(core.ModelBase, core.DictBase, models.TimestampMixin):
    """Represents a public key pair for ssh / WinRM."""
    __tablename__ = 'key_pairs'
    __table_args__ = (
        schema.UniqueConstraint('user_id', 'name',
                                name='uniq_key_pairs0user_id0name'),
    )
    attributes = ['id', 'name', 'user_id', 'fingerprint', 'public_key', 'type',
                  'created_at', 'updated_at']

    id = sql.Column(sql.Integer, primary_key=True, nullable=False)
    name = sql.Column(sql.String(255), nullable=False)
    user_id = sql.Column(sql.String(255))
    fingerprint = sql.Column(sql.String(255))
    public_key = sql.Column(MediumText())
    type = sql.Column(sql.Enum('ssh', 'x509', name='keypair_types'),
                      nullable=False, server_default='ssh')


# Quota part are ported from Cinder for hierarchy multi-tenancy quota control
class QuotasBase(models.ModelBase, core.DictBase,
                 models.TimestampMixin, models.SoftDeleteMixin):
    """QuotasBase.

    provide base class for quota series tables. For it inherits from
    models.ModelBase, this is different from other tables
    """
    __table_args__ = {'mysql_engine': 'InnoDB'}

    metadata = None

    def delete(self, session):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)


class Quotas(core.ModelBase, QuotasBase):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then the
    default for the quota class is used.  If there is no row for a
    given quota class and resource, then the default for the
    deployment is used. If the row is present but the hard limit is
    Null, then the resource is unlimited.
    """
    __tablename__ = 'quotas'
    __table_args__ = ()
    attributes = ['id', 'project_id', 'resource',
                  'hard_limit', 'allocated',
                  'created_at', 'updated_at', 'deleted_at', 'deleted']

    id = sql.Column(sql.Integer, primary_key=True)
    project_id = sql.Column(sql.String(255), index=True)
    resource = sql.Column(sql.String(255), nullable=False)
    hard_limit = sql.Column(sql.Integer)
    allocated = sql.Column(sql.Integer, default=0)


class QuotaClasses(core.ModelBase, QuotasBase):
    """Quota_classes.

    make default quota as a update-able quota.Mainly for the command
    quota-class-show and quota-class-update
    """
    __tablename__ = 'quota_classes'
    __table_args__ = ()
    attributes = ['id', 'class_name', 'resource', 'hard_limit',
                  'created_at', 'updated_at', 'deleted_at', 'deleted']

    id = sql.Column(sql.Integer, primary_key=True)
    class_name = sql.Column(sql.String(255), index=True)
    resource = sql.Column(sql.String(255), nullable=False)
    hard_limit = sql.Column(sql.Integer)


class QuotaUsages(core.ModelBase, QuotasBase):
    """Quota_uages.

    store quota usages for project resource
    """
    __tablename__ = 'quota_usages'
    __table_args__ = ()
    attributes = ['id', 'project_id', 'user_id', 'resource',
                  'in_use', 'reserved', 'until_refresh',
                  'created_at', 'updated_at', 'deleted_at', 'deleted']

    id = sql.Column(sql.Integer, primary_key=True)
    project_id = sql.Column(sql.String(255), index=True)
    user_id = sql.Column(sql.String(255), index=True)
    resource = sql.Column(sql.String(255), nullable=False)

    in_use = sql.Column(sql.Integer)
    reserved = sql.Column(sql.Integer, default=0)

    until_refresh = sql.Column(sql.Integer, default=0)

    @property
    def total(self):
        return self.in_use + self.reserved


class Reservation(core.ModelBase, QuotasBase):
    """Reservation.

    Represents a resource reservation for quotas
    """
    __tablename__ = 'reservations'
    __table_args__ = ()
    attributes = ['id', 'uuid', 'usage_id', 'project_id', 'resource',
                  'delta', 'expire',
                  'created_at', 'updated_at', 'deleted_at', 'deleted']

    id = sql.Column(sql.Integer, primary_key=True)
    uuid = sql.Column(sql.String(36), nullable=False)

    usage_id = sql.Column(sql.Integer,
                          sql.ForeignKey('quota_usages.id'),
                          nullable=False)

    project_id = sql.Column(sql.String(255), index=True)
    resource = sql.Column(sql.String(255))

    delta = sql.Column(sql.Integer)
    expire = sql.Column(sql.DateTime, nullable=False)

    usage = relationship(
        "QuotaUsages",
        foreign_keys=usage_id,
        primaryjoin='and_(Reservation.usage_id == QuotaUsages.id,'
                    'QuotaUsages.deleted == 0)')


class VolumeTypeBase(models.ModelBase, core.DictBase,
                     models.TimestampMixin, models.SoftDeleteMixin):
    """VolumeTypeBase.

    provide base class for volume type series tables. For it inherits from
    models.ModelBase, this is different from other tables
    """
    __table_args__ = {'mysql_engine': 'InnoDB'}

    metadata = None

    def delete(self, session):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)


class VolumeTypes(core.ModelBase, VolumeTypeBase):
    """Represent possible volume_types of volumes offered."""
    __tablename__ = 'volume_types'
    attributes = ['id', 'name', 'description', 'qos_specs_id', 'is_public',
                  'created_at', 'updated_at', 'deleted_at', 'deleted']

    id = sql.Column(sql.String(36), primary_key=True)
    name = sql.Column(sql.String(255), unique=True)
    description = sql.Column(sql.String(255))
    # A reference to qos_specs entity
    qos_specs_id = sql.Column(sql.String(36),
                              sql.ForeignKey('quality_of_service_specs.id'))
    is_public = sql.Column(sql.Boolean, default=True)


class VolumeTypeProjects(core.ModelBase, VolumeTypeBase):
    """Represent projects associated volume_types."""
    __tablename__ = 'volume_type_projects'
    __table_args__ = (schema.UniqueConstraint(
        'volume_type_id', 'project_id', 'deleted',
        name="uniq_volume_type_projects0volume_type_id0project_id0deleted"),
    )
    attributes = ['id', 'volume_type_id', 'project_id', 'created_at',
                  'updated_at', 'deleted_at', 'deleted']
    id = sql.Column(sql.Integer, primary_key=True)
    volume_type_id = sql.Column(sql.String(36),
                                sql.ForeignKey('volume_types.id'),
                                nullable=False)
    project_id = sql.Column(sql.String(255))
    deleted = sql.Column(sql.Boolean, default=False)

    volume_type = relationship(
        VolumeTypes,
        backref="projects",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'VolumeTypeProjects.volume_type_id == VolumeTypes.id,'
        'VolumeTypeProjects.deleted == False)')


class VolumeTypeExtraSpecs(core.ModelBase, VolumeTypeBase):
    """Represents additional specs as key/value pairs for a volume_type."""
    __tablename__ = 'volume_type_extra_specs'
    attributes = ['id', 'key', 'value', 'volume_type_id', 'created_at',
                  'updated_at', 'deleted', 'deleted_at']

    id = sql.Column(sql.Integer, primary_key=True)
    key = sql.Column(sql.String(255))
    value = sql.Column(sql.String(255))
    volume_type_id = sql.Column(sql.String(36),
                                sql.ForeignKey('volume_types.id'),
                                nullable=False)
    volume_type = relationship(
        VolumeTypes,
        backref="extra_specs",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
                    'VolumeTypeExtraSpecs.volume_type_id == VolumeTypes.id,'
                    'VolumeTypeExtraSpecs.deleted == False)'
    )


class QualityOfServiceSpecs(core.ModelBase, core.DictBase,
                            models.TimestampMixin):
    """Represents QoS specs as key/value pairs.

    QoS specs is standalone entity that can be associated/disassociated
    with volume types (one to many relation).  Adjacency list relationship
    pattern is used in this model in order to represent following hierarchical
    data with in flat table, e.g, following structure

    qos-specs-1  'Rate-Limit'
         |
         +------>  consumer = 'front-end'
         +------>  total_bytes_sec = 1048576
         +------>  total_iops_sec = 500

    qos-specs-2  'QoS_Level1'
         |
         +------>  consumer = 'back-end'
         +------>  max-iops =  1000
         +------>  min-iops = 200

    is represented by:

      id       specs_id       key                  value
    ------     --------   -------------            -----
    UUID-1     NULL       QoSSpec_Name           Rate-Limit
    UUID-2     UUID-1       consumer             front-end
    UUID-3     UUID-1     total_bytes_sec        1048576
    UUID-4     UUID-1     total_iops_sec           500
    UUID-5     NULL       QoSSpec_Name           QoS_Level1
    UUID-6     UUID-5       consumer             back-end
    UUID-7     UUID-5       max-iops               1000
    UUID-8     UUID-5       min-iops               200
    """
    __tablename__ = 'quality_of_service_specs'
    attributes = ['id', 'specs_id', 'key', 'value', 'created_at', 'updated_at']

    id = sql.Column(sql.String(36), primary_key=True)
    specs_id = sql.Column(sql.String(36), sql.ForeignKey(id))
    key = sql.Column(sql.String(255))
    value = sql.Column(sql.String(255))


# Pod Model
class Pod(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_pods'
    attributes = ['pod_id', 'pod_name', 'pod_az_name', 'dc_name', 'az_name']

    pod_id = sql.Column('pod_id', sql.String(length=36), primary_key=True)
    pod_name = sql.Column('pod_name', sql.String(length=255), unique=True,
                          nullable=False)
    pod_az_name = sql.Column('pod_az_name', sql.String(length=255),
                             nullable=True)
    dc_name = sql.Column('dc_name', sql.String(length=255), nullable=True)
    az_name = sql.Column('az_name', sql.String(length=255), nullable=False)


class PodServiceConfiguration(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_pod_service_configuration'
    attributes = ['service_id', 'pod_id', 'service_type', 'service_url']

    service_id = sql.Column('service_id', sql.String(length=64),
                            primary_key=True)
    pod_id = sql.Column('pod_id', sql.String(length=64),
                        sql.ForeignKey('cascaded_pods.pod_id'),
                        nullable=False)
    service_type = sql.Column('service_type', sql.String(length=64),
                              nullable=False)
    service_url = sql.Column('service_url', sql.String(length=512),
                             nullable=False)


# Tenant and pod binding model
class PodBinding(core.ModelBase, core.DictBase, models.TimestampMixin):
    __tablename__ = 'pod_binding'
    __table_args__ = (
        schema.UniqueConstraint(
            'tenant_id', 'pod_id',
            name='pod_binding0tenant_id0pod_id'),
    )
    attributes = ['id', 'tenant_id', 'pod_id', 'is_binding',
                  'created_at', 'updated_at']

    id = sql.Column(sql.String(36), primary_key=True)
    tenant_id = sql.Column('tenant_id', sql.String(36), nullable=False)
    pod_id = sql.Column('pod_id', sql.String(36),
                        sql.ForeignKey('cascaded_pods.pod_id'),
                        nullable=False)
    is_binding = sql.Column('is_binding', sql.Boolean, nullable=False)


# Routing Model
class ResourceRouting(core.ModelBase, core.DictBase, models.TimestampMixin):
    __tablename__ = 'cascaded_pods_resource_routing'
    __table_args__ = (
        schema.UniqueConstraint(
            'top_id', 'pod_id',
            name='cascaded_pods_resource_routing0top_id0pod_id'),
    )
    attributes = ['id', 'top_id', 'bottom_id', 'pod_id', 'project_id',
                  'resource_type', 'created_at', 'updated_at']

    id = sql.Column('id', sql.Integer, primary_key=True)
    top_id = sql.Column('top_id', sql.String(length=127), nullable=False)
    bottom_id = sql.Column('bottom_id', sql.String(length=36))
    pod_id = sql.Column('pod_id', sql.String(length=64),
                        sql.ForeignKey('cascaded_pods.pod_id'),
                        nullable=False)
    project_id = sql.Column('project_id', sql.String(length=36))
    resource_type = sql.Column('resource_type', sql.String(length=64),
                               nullable=False)


class Job(core.ModelBase, core.DictBase):
    __tablename__ = 'job'
    __table_args__ = (
        schema.UniqueConstraint(
            'type', 'status', 'resource_id', 'extra_id',
            name='job0type0status0resource_id0extra_id'),
    )

    attributes = ['id', 'type', 'timestamp', 'status', 'resource_id',
                  'extra_id']

    id = sql.Column('id', sql.String(length=36), primary_key=True)
    type = sql.Column('type', sql.String(length=36))
    timestamp = sql.Column('timestamp', sql.TIMESTAMP,
                           server_default=sql.text('CURRENT_TIMESTAMP'))
    status = sql.Column('status', sql.String(length=36))
    resource_id = sql.Column('resource_id', sql.String(length=127))
    extra_id = sql.Column('extra_id', sql.String(length=36))
