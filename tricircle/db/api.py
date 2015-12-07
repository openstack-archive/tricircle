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


from tricircle.db import core
from tricircle.db import models


def create_site(context, site_dict):
    with context.session.begin():
        return core.create_resource(context, models.Site, site_dict)


def delete_site(context, site_id):
    with context.session.begin():
        return core.delete_resource(context, models.Site, site_id)


def get_site(context, site_id):
    with context.session.begin():
        return core.get_resource(context, models.Site, site_id)


def list_sites(context, filters):
    with context.session.begin():
        return core.query_resource(context, models.Site, filters)


def update_site(context, site_id, update_dict):
    with context.session.begin():
        return core.update_resource(context, models.Site, site_id, update_dict)


def create_site_service_configuration(context, config_dict):
    with context.session.begin():
        return core.create_resource(context, models.SiteServiceConfiguration,
                                    config_dict)


def delete_site_service_configuration(context, config_id):
    with context.session.begin():
        return core.delete_resource(context, models.SiteServiceConfiguration,
                                    config_id)


def get_site_service_configuration(context, config_id):
    with context.session.begin():
        return core.get_resource(context, models.SiteServiceConfiguration,
                                 config_id)


def list_site_service_configurations(context, filters):
    with context.session.begin():
        return core.query_resource(context, models.SiteServiceConfiguration,
                                   filters)


def update_site_service_configuration(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, models.SiteServiceConfiguration, config_id, update_dict)
