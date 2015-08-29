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


class EndpointNotAvailable(Exception):
    def __init__(self, service, url):
        self.service = service
        self.url = url
        message = "Endpoint %(url)s for %(service)s is not available" % {
            'url': url,
            'service': service
        }
        super(EndpointNotAvailable, self).__init__(message)


class EndpointNotUnique(Exception):
    def __init__(self, site, service):
        self.site = site
        self.service = service
        message = "Endpoint for %(service)s in %(site)s not unique" % {
            'site': site,
            'service': service
        }
        super(EndpointNotUnique, self).__init__(message)


class EndpointNotFound(Exception):
    def __init__(self, site, service):
        self.site = site
        self.service = service
        message = "Endpoint for %(service)s in %(site)s not found" % {
            'site': site,
            'service': service
        }
        super(EndpointNotFound, self).__init__(message)


class ResourceNotFound(Exception):
    def __init__(self, model, unique_key):
        resource_type = model.__name__.lower()
        self.resource_type = resource_type
        self.unique_key = unique_key
        message = "Could not find %(resource_type)s: %(unique_key)s" % {
            'resource_type': resource_type,
            'unique_key': unique_key
        }
        super(ResourceNotFound, self).__init__(message)


class ResourceNotSupported(Exception):
    def __init__(self, resource, method):
        self.resource = resource
        self.method = method
        message = "%(method)s method not supported for %(resource)s" % {
            'resource': resource,
            'method': method
        }
        super(ResourceNotSupported, self).__init__(message)
