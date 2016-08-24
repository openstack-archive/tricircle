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

from novaclient import api_versions
from novaclient import exceptions

from oslo_serialization import jsonutils
from oslo_service import wsgi
from oslo_utils import encodeutils

import webob.dec

from tricircle.common import constants


class MicroVersion(object):

    @staticmethod
    def _format_error(code, message, error_type='computeFault'):
        return {error_type: {'message': message, 'code': code}}

    @classmethod
    def factory(cls, global_config, **local_config):
        return cls(app=None)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Get the nova micro version number

        * If neither "X-OpenStack-Nova-API-Version" nor
          "OpenStack-API-Version" (specifying "compute") is provided,
          act as if the minimum supported microversion was specified.

        * If both headers are provided,
          "OpenStack-API-Version" will be preferred.

        * If "X-OpenStack-Nova-API-Version" or "OpenStack-API-Version"
          is provided, respond with the API at that microversion.
          If that's outside of the range of microversions supported,
          return 406 Not Acceptable.

        * If "X-OpenStack-Nova-API-Version" or "OpenStack-API-Version"
          has a value of "latest" (special keyword),
          act as if maximum was specified.
        """
        version_num = req.environ.get(
            constants.HTTP_NOVA_API_VERSION_REQUEST_HEADER)
        legacy_version_num = req.environ.get(
            constants.HTTP_LEGACY_NOVA_API_VERSION_REQUEST_HEADER)
        message = None
        api_version = None

        if version_num is None and legacy_version_num is None:
            micro_version = constants.NOVA_APIGW_MIN_VERSION
        elif version_num is not None:
            err_msg = ("Invalid format of client version '%s'. "
                       "Expected format 'compute X.Y',"
                       "where X is a major part and Y "
                       "is a minor part of version.") % version_num
            try:
                nova_version_prefix = version_num.split()[0]
                micro_version = ''.join(version_num.split()[1:])
                if nova_version_prefix != 'compute':
                    message = err_msg
            except Exception:
                message = err_msg
        else:
            micro_version = legacy_version_num

        if message is None:
            try:
                # Returns checked APIVersion object,
                # or raise UnsupportedVersion exceptions.
                api_version = api_versions.get_api_version(micro_version)
            except exceptions.UnsupportedVersion as e:
                message = e.message

        if message is None and api_version is not None:
            min_minor = int(constants.NOVA_APIGW_MIN_VERSION.split('.')[1])
            max_minor = int(constants.NOVA_APIGW_MAX_VERSION.split('.')[1])
            if api_version.is_latest():
                micro_version = constants.NOVA_APIGW_MAX_VERSION
                api_version.ver_minor = max_minor

            if api_version.ver_minor < min_minor or \
                    api_version.ver_minor > max_minor:
                message = ("Version %s is not supported by the API. "
                           "Minimum is %s, and maximum is %s"
                           % (micro_version, constants.NOVA_APIGW_MIN_VERSION,
                              constants.NOVA_APIGW_MAX_VERSION))

        if message is None:
            req.environ[constants.NOVA_API_VERSION_REQUEST_HEADER] = \
                micro_version
            if self.app:
                return req.get_response(self.app)
        else:
            content_type = 'application/json'
            body = jsonutils.dumps(
                self._format_error('406', message, 'computeFault'))
            response = webob.Response()
            response.content_type = content_type
            response.body = encodeutils.to_utf8(body)
            response.status_code = 406
            return response

    def __init__(self, app):
        self.app = app
