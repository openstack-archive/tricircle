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


def list_sites(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.Site, filters or [],
                                   sorts or [])


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


def list_site_service_configurations(context, filters=None, sorts=None):
    with context.session.begin():
        return core.query_resource(context, models.SiteServiceConfiguration,
                                   filters or [], sorts or [])


def update_site_service_configuration(context, config_id, update_dict):
    with context.session.begin():
        return core.update_resource(
            context, models.SiteServiceConfiguration, config_id, update_dict)


def get_bottom_mappings_by_top_id(context, top_id, resource_type):
    """Get resource id and site name on bottom

    :param context: context object
    :param top_id: resource id on top
    :return: a list of tuple (site dict, bottom_id)
    """
    route_filters = [{'key': 'top_id', 'comparator': 'eq', 'value': top_id},
                     {'key': 'resource_type',
                      'comparator': 'eq',
                      'value': resource_type}]
    mappings = []
    with context.session.begin():
        routes = core.query_resource(
            context, models.ResourceRouting, route_filters, [])
        for route in routes:
            if not route['bottom_id']:
                continue
            site = core.get_resource(context, models.Site, route['site_id'])
            mappings.append((site, route['bottom_id']))
    return mappings


def get_next_bottom_site(context, current_site_id=None):
    sites = list_sites(context, sorts=[(models.Site.site_id, True)])
    # NOTE(zhiyuan) number of sites is small, just traverse to filter top site
    sites = [site for site in sites if site['az_id']]
    for index, site in enumerate(sites):
        if not current_site_id:
            return site
        if site['site_id'] == current_site_id and index < len(sites) - 1:
            return sites[index + 1]
    return None
