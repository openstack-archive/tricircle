# Copyright (c) 2015 Huawei Tech. Co., Ltd.
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

import six

from pecan import expose
from pecan import request
from pecan import response
from pecan import Response
from pecan import rest

from oslo_config import cfg
from oslo_log import log as logging

import tricircle.common.context as t_context
from tricircle.common import exceptions as t_exceptions
from tricircle.common.i18n import _
from tricircle.common import quota


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class QuotaSetsController(rest.RestController):

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    @expose()
    def _lookup(self, target_tenant_id, *remainder):
        return QuotaController(self.tenant_id, target_tenant_id), remainder


def build_absolute_limits(quotas):

    quota_map = {
        'maxTotalRAMSize': 'ram',
        'maxTotalInstances': 'instances',
        'maxTotalCores': 'cores',
        'maxTotalKeypairs': 'key_pairs',
        'maxTotalFloatingIps': 'floating_ips',
        'maxPersonality': 'injected_files',
        'maxPersonalitySize': 'injected_file_content_bytes',
        'maxSecurityGroups': 'security_groups',
        'maxSecurityGroupRules': 'security_group_rules',
        'maxServerMeta': 'metadata_items',
        'maxServerGroups': 'server_groups',
        'maxServerGroupMembers': 'server_group_members',
    }

    limits = {}
    for display_name, key in six.iteritems(quota_map):
        if key in quotas:
            limits[display_name] = quotas[key]['limit']
    return limits


def build_used_limits(quotas):

    quota_map = {
        'totalRAMUsed': 'ram',
        'totalCoresUsed': 'cores',
        'totalInstancesUsed': 'instances',
        'totalFloatingIpsUsed': 'floating_ips',
        'totalSecurityGroupsUsed': 'security_groups',
        'totalServerGroupsUsed': 'server_groups',
    }

    # need to refresh usage from the bottom pods? Now from the data in top
    used_limits = {}
    for display_name, key in six.iteritems(quota_map):
        if key in quotas:
            reserved = quotas[key]['reserved']
            used_limits[display_name] = quotas[key]['in_use'] + reserved

    return used_limits


class LimitsController(rest.RestController):

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    @staticmethod
    def _reserved(req):
        try:
            return int(req.GET['reserved'])
        except (ValueError, KeyError):
            return False

    @expose(generic=True, template='json')
    def get_all(self):

        # TODO(joehuang): add policy controll here

        context = t_context.extract_context_from_environ()
        context.project_id = self.tenant_id
        target_tenant_id = request.params.get('tenant_id', None)
        if target_tenant_id:
            target_tenant_id.strip()
        else:
            return Response('tenant_id not given', 400)

        qs = quota.QuotaSetOperation(target_tenant_id,
                                     None)
        try:
            quotas = qs.show_detail_quota(context, show_usage=True)
        except t_exceptions.NotFound as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 404)
        except (t_exceptions.AdminRequired,
                t_exceptions.NotAuthorized,
                t_exceptions.HTTPForbiddenError) as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 403)
        except Exception as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 400)

        # TODO(joehuang): add API rate limits later
        ret = {
            'limits': {
                'rate': {},
                'absolute': {},
            },
        }

        ret['limits']['absolute'].update(
            build_absolute_limits(quotas['quota_set']))
        ret['limits']['absolute'].update(
            build_used_limits(quotas['quota_set']))

        return ret


class QuotaController(rest.RestController):

    def __init__(self, owner_tenant_id, target_tenant_id):
        self.owner_tenant_id = owner_tenant_id
        self.target_tenant_id = target_tenant_id

    @expose(generic=True, template='json')
    def put(self, **kw):

        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            # TODO(joahuang): changed to policy control later
            # to support reseller admin mode
            return Response(_('Admin role required to update quota'), 409)

        return self._quota_action('put', **kw)

    @expose(generic=True, template='json')
    def delete(self):
        """Delete Quota for a particular tenant.

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform a delete.

        :param id: target project id that needs to be deleted
        """

        context = t_context.extract_context_from_environ()
        if not context.is_admin:
            # TODO(joahuang): changed to policy control later
            # to support reseller admin mode
            return Response(_('Admin role required to delete quota'), 409)

        kw = {}
        return self._quota_action('delete', **kw)

    @expose(generic=True, template='json')
    def get_one(self, show_what):
        kw = {}
        if show_what == 'defaults' or show_what == 'detail':
            return self._quota_action(show_what, **kw)
        else:
            return Response(_('Only show defaults or detail allowed'), 400)

    @expose(generic=True, template='json')
    def get_all(self):
        kw = {}
        return self._quota_action('quota-show', **kw)

    def _quota_action(self, action, **kw):

        context = t_context.extract_context_from_environ()
        context.project_id = self.owner_tenant_id
        target_tenant_id = self.target_tenant_id
        target_user_id = request.params.get('user_id', None)
        if target_user_id:
            target_user_id.strip()

        qs = quota.QuotaSetOperation(target_tenant_id,
                                     target_user_id)
        quotas = {}
        try:
            if action == 'put':
                quotas = qs.update(context, **kw)
            elif action == 'delete':
                qs.delete(context)
                response.status = 202
                return
            elif action == 'defaults':
                quotas = qs.show_default_quota(context)
            elif action == 'detail':
                quotas = qs.show_detail_quota(context, show_usage=True)

                # remove the allocated field which is not visible in Nova
                for k, v in quotas['quota_set'].iteritems():
                    if k != 'id':
                        v.pop('allocated', None)

            elif action == 'quota-show':
                quotas = qs.show_detail_quota(context, show_usage=False)
            else:
                return Response('Resource not found', 404)
        except t_exceptions.NotFound as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 404)
        except (t_exceptions.AdminRequired,
                t_exceptions.NotAuthorized,
                t_exceptions.HTTPForbiddenError) as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 403)
        except Exception as e:
            msg = str(e)
            LOG.exception(msg=msg)
            return Response(msg, 400)

        return {'quota_set': self._build_visible_quota(quotas['quota_set'])}

    def _build_visible_quota(self, quota_set):
        quota_map = [
            'id', 'instances', 'ram', 'cores', 'key_pairs',
            'floating_ips', 'fixed_ips',
            'injected_files', 'injected_file_path_bytes',
            'injected_file_content_bytes',
            'security_groups', 'security_group_rules',
            'metadata_items', 'server_groups', 'server_group_members',
        ]

        ret = {}
        # only return Nova visible quota items
        for k, v in quota_set.iteritems():
            if k in quota_map:
                ret[k] = v

        return ret
