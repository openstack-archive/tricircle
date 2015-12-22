# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


def get_import_path(cls):
    return cls.__module__ + "." + cls.__name__


def get_ag_name(site_name):
    return 'ag_%s' % site_name


def get_az_name(site_name):
    return 'az_%s' % site_name


def get_node_name(site_name):
    return "cascade_%s" % site_name


def validate_required_fields_set(body, fields):
    for field in fields:
        if field not in body:
            return False
    return True
