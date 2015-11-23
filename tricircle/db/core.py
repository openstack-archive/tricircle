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


from oslo_config import cfg
import oslo_db.options as db_options
from oslo_db.sqlalchemy import session as db_session
from oslo_utils import strutils
import sqlalchemy as sql
from sqlalchemy.ext import declarative
from sqlalchemy.inspection import inspect

import tricircle.db.exception as db_exception

_engine_facade = None
ModelBase = declarative.declarative_base()


def _filter_query(model, query, filters):
    """Apply filter to query

    :param model:
    :param query:
    :param filters: list of filter dict with key 'key', 'comparator', 'value'
    like {'key': 'site_id', 'comparator': 'eq', 'value': 'test_site_uuid'}
    :return:
    """
    filter_dict = {}
    for query_filter in filters:
        # only eq filter supported at first
        if query_filter['comparator'] != 'eq':
            continue

        key = query_filter['key']
        if key not in model.attributes:
            continue
        if isinstance(inspect(model).columns[key].type, sql.Boolean):
            filter_dict[key] = strutils.bool_from_string(query_filter['value'])
        else:
            filter_dict[key] = query_filter['value']
    if filter_dict:
        return query.filter_by(**filter_dict)
    else:
        return query


def _get_engine_facade():
    global _engine_facade

    if not _engine_facade:
        _engine_facade = db_session.EngineFacade.from_config(cfg.CONF)

    return _engine_facade


def _get_resource(context, model, pk_value):
    res_obj = context.session.query(model).get(pk_value)
    if not res_obj:
        raise db_exception.ResourceNotFound(model, pk_value)
    return res_obj


def create_resource(context, model, res_dict):
    res_obj = model.from_dict(res_dict)
    context.session.add(res_obj)
    context.session.flush()
    # retrieve auto-generated fields
    context.session.refresh(res_obj)
    return res_obj.to_dict()


def delete_resource(context, model, pk_value):
    res_obj = _get_resource(context, model, pk_value)
    context.session.delete(res_obj)


def get_engine():
    return _get_engine_facade().get_engine()


def get_resource(context, model, pk_value):
    return _get_resource(context, model, pk_value).to_dict()


def get_session(expire_on_commit=False):
    return _get_engine_facade().get_session(expire_on_commit=expire_on_commit)


def initialize():
    db_options.set_defaults(
        cfg.CONF,
        connection='sqlite:///:memory:')


def query_resource(context, model, filters):
    query = context.session.query(model)
    objs = _filter_query(model, query, filters)
    return [obj.to_dict() for obj in objs]


def update_resource(context, model, pk_value, update_dict):
    res_obj = _get_resource(context, model, pk_value)
    for key in update_dict:
        if key not in model.attributes:
            continue
        skip = False
        for pkey in inspect(model).primary_key:
            if pkey.name == key:
                skip = True
                break
        if skip:
            continue
        setattr(res_obj, key, update_dict[key])
    return res_obj.to_dict()


class DictBase(object):
    attributes = []

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def to_dict(self):
        d = {}
        for attr in self.__class__.attributes:
            d[attr] = getattr(self, attr)
        return d

    def __getitem__(self, key):
        return getattr(self, key)
