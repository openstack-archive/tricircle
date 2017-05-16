# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import pecan
from pecan import expose
from pecan import rest
import six

from oslo_log import log as logging

from tricircle.common import constants
import tricircle.common.context as t_context
import tricircle.common.exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common import policy
from tricircle.common import utils

from tricircle.db import api as db_api

LOG = logging.getLogger(__name__)


SUPPORTED_FILTERS = ['id', 'top_id', 'bottom_id', 'pod_id', 'project_id',
                     'resource_type', 'created_at', 'updated_at']


class RoutingController(rest.RestController):

    def __init__(self):
        pass

    @expose(generic=True, template='json')
    def post(self, **kw):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_ROUTINGS_CREATE):
            return utils.format_api_error(
                403, _("Unauthorized to create resource routing"))

        if 'routing' not in kw:
            return utils.format_api_error(
                400, _("Request body not found"))

        routing = kw['routing']

        for field in ('top_id', 'bottom_id', 'pod_id',
                      'project_id', 'resource_type'):
            value = routing.get(field)
            if value is None or len(value.strip()) == 0:
                return utils.format_api_error(
                    400, _("Field %(field)s can not be empty") % {
                        'field': field})

        # the resource type should be properly provisioned.
        resource_type = routing.get('resource_type').strip()
        if not constants.is_valid_resource_type(resource_type):
            return utils.format_api_error(
                400, _('There is no such resource type'))

        try:
            top_id = routing.get('top_id').strip()
            bottom_id = routing.get('bottom_id').strip()
            pod_id = routing.get('pod_id').strip()
            project_id = routing.get('project_id').strip()

            routing = db_api.create_resource_mapping(context, top_id,
                                                     bottom_id, pod_id,
                                                     project_id,
                                                     resource_type)
            if not routing:
                return utils.format_api_error(
                    409, _('Resource routing already exists'))
        except Exception as e:
            LOG.exception('Failed to create resource routing: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to create resource routing'))

        return {'routing': routing}

    def _get_filters(self, params):
        """Return a dictionary of query param filters from the request.

        :param params: the URI params coming from the wsgi layer
        :return (flag, filters), flag indicates whether the filters are valid,
        and the filters denote a list of key-value pairs.
        """
        filters = {}
        unsupported_filters = {}
        for filter_name in params:
            if filter_name in SUPPORTED_FILTERS:
                # map filter name
                filters[filter_name] = params.get(filter_name)
            else:
                unsupported_filters[filter_name] = params.get(filter_name)

        if unsupported_filters:
            return False, unsupported_filters
        return True, filters

    @expose(generic=True, template='json')
    def get_all(self, **kwargs):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_ROUTINGS_LIST):
            return utils.format_api_error(
                403, _('Unauthorized to show all resource routings'))

        is_valid_filter, filters = self._get_filters(kwargs)

        if not is_valid_filter:
            msg = (_('Unsupported filter type: %(filters)s') % {
                'filters': ', '.join([filter_name for filter_name in filters])
            })
            return utils.format_api_error(400, msg)

        filters = [{'key': key,
                    'comparator': 'eq',
                    'value': value} for key, value in six.iteritems(filters)]

        try:
            return {'routings': db_api.list_resource_routings(context,
                                                              filters)}
        except Exception as e:
            LOG.exception('Failed to show all resource routings: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to show all resource routings'))

    @expose(generic=True, template='json')
    def get_one(self, _id):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_ROUTINGS_SHOW):
            return utils.format_api_error(
                403, _('Unauthorized to show the resource routing'))

        try:
            return {'routing': db_api.get_resource_routing(context, _id)}
        except t_exceptions.ResourceNotFound:
            return utils.format_api_error(
                404, _('Resource routing not found'))

    @expose(generic=True, template='json')
    def delete(self, _id):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_ROUTINGS_DELETE):
            return utils.format_api_error(
                403, _('Unauthorized to delete the resource routing'))

        try:
            db_api.get_resource_routing(context, _id)
        except t_exceptions.ResourceNotFound:
            return utils.format_api_error(404,
                                          _('Resource routing not found'))
        try:
            db_api.delete_resource_routing(context, _id)
            pecan.response.status = 200
            return pecan.response
        except Exception as e:
            LOG.exception('Failed to delete the resource routing: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to delete the resource routing'))

    @expose(generic=True, template='json')
    def put(self, _id, **kw):
        context = t_context.extract_context_from_environ()

        if not policy.enforce(context, policy.ADMIN_API_ROUTINGS_PUT):
            return utils.format_api_error(
                403, _('Unauthorized to update resource routing'))

        try:
            db_api.get_resource_routing(context, _id)
        except t_exceptions.ResourceNotFound:
            return utils.format_api_error(404,
                                          _('Resource routing not found'))

        if 'routing' not in kw:
            return utils.format_api_error(
                400, _('Request body not found'))

        update_dict = kw['routing']

        # values to be updated should not be empty
        for field in update_dict:
            value = update_dict.get(field)
            if value is None or len(value.strip()) == 0:
                return utils.format_api_error(
                    400, _("Field %(field)s can not be empty") % {
                        'field': field})

        # the resource type should be properly provisioned.
        if 'resource_type' in update_dict:
            if not constants.is_valid_resource_type(
                    update_dict['resource_type']):
                return utils.format_api_error(
                    400, _('There is no such resource type'))

        # the pod with new pod_id should exist in pod table
        if 'pod_id' in update_dict:
            new_pod_id = update_dict.get('pod_id')
            try:
                # find the pod through the pod_id and verify whether it exists
                db_api.get_pod(context, new_pod_id)
            except t_exceptions.ResourceNotFound:
                return utils.format_api_error(
                    400, _("The pod %(new_pod_id)s doesn't"
                           " exist") % {'new_pod_id': new_pod_id})
            except Exception as e:
                LOG.exception('Failed to update resource routing: '
                              '%(exception)s ', {'exception': e})
                return utils.format_api_error(
                    500, _('Failed to update resource routing'))

        try:
            routing_updated = db_api.update_resource_routing(
                context, _id, update_dict)
            return {'routing': routing_updated}
        except Exception as e:
            LOG.exception('Failed to update resource routing: '
                          '%(exception)s ', {'exception': e})
            return utils.format_api_error(
                500, _('Failed to update resource routing'))
