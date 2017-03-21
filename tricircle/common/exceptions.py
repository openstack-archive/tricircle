# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

"""
Tricircle base exception handling.
"""

import six

from neutron_lib import exceptions
from oslo_log import log as logging

from tricircle.common.i18n import _


LOG = logging.getLogger(__name__)


class TricircleException(Exception):
    """Base Tricircle Exception.

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.
    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):

        self.kwargs = kwargs
        self.kwargs['message'] = message

        if 'code' not in self.kwargs:
            self.kwargs['code'] = self.code

        for k, v in self.kwargs.items():
            if isinstance(v, Exception):
                self.kwargs[k] = six.text_type(v)

        if self._should_format():
            try:
                message = self.message % kwargs
            except Exception:

                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                exc_info = _('Exception class %s in string '
                             'format operation') % type(self).__name__
                format_str = _('%(exception_info)s ; %(format_key)s : '
                               '%(format_value)s')
                for name, value in kwargs.items():
                    exc_info = format_str % {
                        'exception_info': exc_info,
                        'format_key': name,
                        'format_value': six.text_type(value)}

                exc_info = _('%(message)s ; %(exception_info)s') % {
                    'message': self.message, 'exception_info': exc_info}
                LOG.exception(exc_info)

                # no rerasie
                # exc_info = sys.exc_info()
                # if CONF.fatal_exception_format_errors:
                #    six.reraise(*exc_info)

                # at least get the core message out if something happened
                message = self.message

        elif isinstance(message, Exception):
            message = six.text_type(message)

        self.msg = message
        super(TricircleException, self).__init__(message)

    def _should_format(self):

        if self.kwargs['message'] is None and '%(message)' in self.message:
            LOG.error('\%(message)s in message '
                      'but init parameter is None')

        return self.kwargs['message'] is None or '%(message)' in self.message

    def __unicode__(self):
        return six.text_type(self.msg)


class BadRequest(TricircleException):
    message = _('Bad %(resource)s request: %(msg)s')


class NotFound(TricircleException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class Conflict(TricircleException):
    pass


class NotAuthorized(TricircleException):
    message = _("Not authorized.")


class ServiceUnavailable(TricircleException):
    message = _("The service is unavailable")


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy doesn't allow this operation to be performed.")


class InUse(TricircleException):
    message = _("The resource is inuse")


class InvalidConfigurationOption(TricircleException):
    message = _("An invalid value was provided for %(opt_name)s: "
                "%(opt_value)s")


class EndpointNotAvailable(TricircleException):
    message = "Endpoint %(url)s for %(service)s is not available"

    def __init__(self, service, url):
        super(EndpointNotAvailable, self).__init__(service=service, url=url)


class EndpointNotUnique(TricircleException):
    message = "Endpoint for %(service)s in %(pod)s not unique"

    def __init__(self, pod, service):
        super(EndpointNotUnique, self).__init__(pod=pod, service=service)


class EndpointNotFound(TricircleException):
    message = "Endpoint for %(service)s in %(pod)s not found"

    def __init__(self, pod, service):
        super(EndpointNotFound, self).__init__(pod=pod, service=service)


class ResourceNotFound(TricircleException):
    message = "Could not find %(resource_type)s: %(unique_key)s"

    def __init__(self, model, unique_key):
        resource_type = model.__name__.lower()
        super(ResourceNotFound, self).__init__(resource_type=resource_type,
                                               unique_key=unique_key)


class ResourceNotSupported(TricircleException):
    message = "%(method)s method not supported for %(resource)s"

    def __init__(self, resource, method):
        super(ResourceNotSupported, self).__init__(resource=resource,
                                                   method=method)


class Invalid(TricircleException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidInput(Invalid):
    message = _("Invalid input received: %(reason)s")


class ExternalNetPodNotSpecify(TricircleException):
    message = "Pod for external network not specified"

    def __init__(self):
        super(ExternalNetPodNotSpecify, self).__init__()


class PodNotFound(NotFound):
    message = "Pod %(region_name)s could not be found."

    def __init__(self, region_name):
        super(PodNotFound, self).__init__(region_name=region_name)


# parameter validation error
class ValidationError(TricircleException):
    message = _("%(msg)s")
    code = 400


# parameter validation error
class HTTPForbiddenError(TricircleException):
    message = _("%(msg)s")
    code = 403


class Duplicate(TricircleException):
    pass


class ServerMappingsNotFound(NotFound):
    message = _('Instance %(server_id)s could not be found.')


class VolumeMappingsNotFound(NotFound):
    message = _('Volume %(volume_id)s could not be found')


class RoutingCreateFail(TricircleException):
    message = _("Fail to create %s routing entry %(_type)s")

    def __init__(self, _type):
        super(RoutingCreateFail, self).__init__(_type=_type)


class RoutingBindFail(TricircleException):
    message = _("Fail to bind top and bottom %(_type)s")

    def __init__(self, _type):
        super(RoutingBindFail, self).__init__(_type=_type)


class RouterNetworkLocationMismatch(exceptions.InvalidInput):
    message = _("router located in %(router_az_hint)s, but network located "
                "in %(net_az_hints)s, location mismatch.")

    def __init__(self, router_az_hints, net_az_hints):
        super(RouterNetworkLocationMismatch, self).__init__(
            router_az_hint=router_az_hints, net_az_hints=net_az_hints)
