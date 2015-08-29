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

from tricircle.db import core


def create_site(context, site_dict):
    with context.session.begin():
        return core.create_resource(context, Site, site_dict)


def delete_site(context, site_id):
    with context.session.begin():
        return core.delete_resource(context, Site, site_id)


def get_site(context, site_id):
    with context.session.begin():
        return core.get_resource(context, Site, site_id)


def list_sites(context, filters):
    with context.session.begin():
        return core.query_resource(context, Site, filters)


def update_site(context, site_id, update_dict):
    with context.session.begin():
        return core.update_resource(context, Site, site_id, update_dict)


def create_service_type(context, type_dict):
    with context.session.begin():
        return core.create_resource(context, ServiceType, type_dict)


def create_site_service_configuration(context, config_dict):
    with context.session.begin():
        return core.create_resource(context, SiteServiceConfiguration,
                                    config_dict)


def delete_site_service_configuration(context, config_id):
    with context.session.begin():
        return core.delete_resource(context,
                                    SiteServiceConfiguration, config_id)


def list_site_service_configuration(context, filters):
    with context.session.begin():
        return core.query_resource(context, SiteServiceConfiguration, filters)


def update_site_service_configuration(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, SiteServiceConfiguration, config_id, update_dict)


class Site(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_sites'
    attributes = ['site_id', 'site_name', 'az_id']
    site_id = sql.Column('site_id', sql.String(length=64), primary_key=True)
    site_name = sql.Column('site_name', sql.String(length=64), unique=True,
                           nullable=False)
    az_id = sql.Column('az_id', sql.String(length=64), nullable=False)


class SiteServiceConfiguration(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_site_service_configuration'
    attributes = ['service_id', 'site_id', 'service_name',
                  'service_type', 'service_url']
    service_id = sql.Column('service_id', sql.String(length=64),
                            primary_key=True)
    site_id = sql.Column('site_id', sql.String(length=64),
                         sql.ForeignKey('cascaded_sites.site_id'),
                         nullable=False)
    service_name = sql.Column('service_name', sql.String(length=64),
                              unique=True, nullable=False)
    service_type = sql.Column(
        'service_type', sql.String(length=64),
        sql.ForeignKey('cascaded_service_types.service_type'),
        nullable=False)
    service_url = sql.Column('service_url', sql.String(length=512),
                             nullable=False)


class ServiceType(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_service_types'
    attributes = ['id', 'service_type']
    id = sql.Column('id', sql.Integer, primary_key=True)
    service_type = sql.Column('service_type', sql.String(length=64),
                              unique=True)


class SiteService(core.ModelBase, core.DictBase):
    __tablename__ = 'cascaded_site_services'
    attributes = ['site_id']
    site_id = sql.Column('site_id', sql.String(length=64), primary_key=True)
