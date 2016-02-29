# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

import copy
import mock
import pecan
from pecan.configuration import set_config
from pecan.testing import load_test_app

from oslo_config import cfg
from oslo_config import fixture as fixture_config
from oslo_serialization import jsonutils

from tricircle.nova_apigw import app
from tricircle.nova_apigw.controllers import quota_sets

from tricircle.common import context
from tricircle.common import exceptions as t_exceptions
from tricircle.common import quota
from tricircle.db import core

from tricircle.tests.unit.common import test_quota

QUOTAS = quota.QUOTAS


def _make_body(tenant_id='foo', root=True, **kw):
    resources = copy.copy(kw)
    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_set': resources}
    else:
        result = resources
    return result


def _update_body(src_body, root=True, **kw):
    for k, v in kw.iteritems():
        if root:
            src_body['quota_set'][k] = v
        else:
            src_body[k] = v
    return src_body


def _update_subproject_body(src_body, root=True, **kw):
    for k, v in kw.iteritems():
        if root:
            src_body['quota_set'][k] = v
        else:
            src_body[k] = v

    if root:
        for k, v in src_body['quota_set'].iteritems():
            if not kw.get(k):
                src_body['quota_set'][k] = 0

    else:
        for k, v in src_body.iteritems():
            if not kw.get(k) and k != 'id':
                src_body[k] = 0

    return src_body


def _make_subproject_body(tenant_id='foo', root=True, **kw):
    return _make_body(tenant_id=tenant_id, root=root, **kw)


class QuotaControllerTest(test_quota.QuotaSetsOperationTest):

    def setUp(self):
        super(QuotaControllerTest, self).setUp()

        self.addCleanup(set_config, {}, overwrite=True)

        cfg.CONF.register_opts(app.common_opts)
        self.CONF = self.useFixture(fixture_config.Config()).conf
        self.CONF.set_override('auth_strategy', 'noauth')

        self.exception_string = 'NotFound'
        self.test_exception = [
            {'exception_raise': 'NotFound',
             'expected_error': 404},
            {'exception_raise': 'AdminRequired',
             'expected_error': 403},
            {'exception_raise': 'NotAuthorized',
             'expected_error': 403},
            {'exception_raise': 'HTTPForbiddenError',
             'expected_error': 403},
            {'exception_raise': 'Conflict',
             'expected_error': 400}, ]

        self._flags_rest(use_default_quota_class=True)

        self.app = self._make_app()

    def _make_app(self, enable_acl=False):
        self.config = {
            'app': {
                'root':
                    'tricircle.nova_apigw.controllers.root.RootController',
                'modules': ['tricircle.nova_apigw'],
                'enable_acl': enable_acl,
                'errors': {
                    400: '/error',
                    '__force_dict__': True
                }
            },
        }

        return load_test_app(self.config)

    def _override_config_rest(self, name, override, group=None):
        """Cleanly override CONF variables."""
        self.CONF.set_override(name, override, group)
        self.addCleanup(self.CONF.clear_override, name, group)

    def _flags_rest(self, **kw):
        """Override CONF variables for a test."""
        for k, v in kw.items():
            self._override_config_rest(k, v, group='quota')

    def tearDown(self):
        super(QuotaControllerTest, self).tearDown()
        pecan.set_config({}, overwrite=True)
        cfg.CONF.unregister_opts(app.common_opts)
        core.ModelBase.metadata.drop_all(core.get_engine())

    def _get_mock_ctx(self):
        return self.ctx

    def _mock_func_and_obj(self):
        quota.QuotaSetOperation._get_project = mock.Mock()
        quota.QuotaSetOperation._get_project.side_effect = self._get_project
        context.extract_context_from_environ = mock.Mock()
        context.extract_context_from_environ.side_effect = self._get_mock_ctx

    def test_quota_set_update_show_defaults(self):
        self._mock_func_and_obj()

        # show quota before update, should be equal to defaults
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url, expect_errors=True)
        self.assertEqual(res.status_int, 200)
        json_body = jsonutils.loads(res.body)
        default_body = _make_body(tenant_id=self.A.id, root=True,
                                  **self.default_quota)
        result = self._DictIn(json_body['quota_set'],
                              default_body['quota_set'])
        self.assertEqual(result, True)

        # quota update with wrong parameter
        quota_a = dict(instances=5, cores=10, ram=25600)
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.put_json(url,
                                {'quota_s': quota_a},
                                expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])

        # quota update with non-admin
        self.ctx.is_admin = False
        quota_a = dict(instances=5, cores=10, ram=25600)
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.put_json(url,
                                {'quota_set': quota_a},
                                expect_errors=True)
        self.assertIn(res.status_int, [409])
        self.ctx.is_admin = True

        # show quota after update
        quota_a = dict(instances=5, cores=10, ram=25600)
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.put_json(url,
                                {'quota_set': quota_a},
                                expect_errors=True)
        json_body = jsonutils.loads(res.body)
        updated_a = _make_body(tenant_id=self.A.id, root=True,
                               **self.default_quota)
        updated_a = _update_body(updated_a, root=True, **quota_a)
        result = self._DictIn(json_body['quota_set'], updated_a['quota_set'])
        self.assertEqual(result, True)

        self.ctx.is_admin = False
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url, expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])
        self.ctx.is_admin = True

        # show quota after update for child
        quota_b = dict(instances=3, cores=5, ram=12800)
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.put_json(url,
                                {'quota_set': quota_b},
                                expect_errors=True)
        json_body = jsonutils.loads(res.body)
        updated_b = _make_body(tenant_id=self.B.id, root=False,
                               **self.default_quota)
        updated_b = _update_subproject_body(updated_b, root=False, **quota_b)
        result = self._DictIn(json_body['quota_set'], updated_b)
        self.assertEqual(result, True)

        # show default quota after update
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url + '/defaults', expect_errors=True)
        json_body = jsonutils.loads(res.body)
        result = self._DictIn(json_body['quota_set'],
                              default_body['quota_set'])
        self.assertEqual(result, True)

        # show default quota for child, should be all 0
        quota_c = {}
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.get(url + '/defaults', expect_errors=True)
        json_body = jsonutils.loads(res.body)
        updated_c = _make_body(tenant_id=self.B.id, root=False,
                               **self.default_quota)
        updated_c = _update_subproject_body(updated_c, root=False, **quota_c)
        result = self._DictIn(json_body['quota_set'], updated_c)
        self.assertEqual(result, True)

        # show quota after update
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url, expect_errors=True)
        json_body = jsonutils.loads(res.body)
        result = self._DictIn(json_body['quota_set'], updated_a['quota_set'])
        self.assertEqual(result, True)

        # show quota for child, should be equal to update_b
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.get(url, expect_errors=True)
        json_body = jsonutils.loads(res.body)
        result = self._DictIn(json_body['quota_set'], updated_b)
        self.assertEqual(result, True)

        # delete with non-admin
        self.ctx.is_admin = False
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.delete(url, expect_errors=True)
        self.assertIn(res.status_int, [409])
        self.ctx.is_admin = True

        # delete parent quota when child quota is not zero
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.delete(url, expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])

        # delete child quota
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.delete(url, expect_errors=True)
        self.assertEqual(res.status_int, 202)

        # delete parent quota when child quota is deleted
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.delete(url, expect_errors=True)
        self.assertEqual(res.status_int, 202)

        # show quota for parent after delete, equal to defaults
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url, expect_errors=True)
        json_body = jsonutils.loads(res.body)
        result = self._DictIn(json_body['quota_set'],
                              default_body['quota_set'])
        self.assertEqual(result, True)

        # show quota for child after delete, should be all 0
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.get(url, expect_errors=True)
        json_body = jsonutils.loads(res.body)
        result = self._DictIn(json_body['quota_set'], updated_c)
        self.assertEqual(result, True)

    def test_quota_detail_limits(self):
        self._mock_func_and_obj()

        def _make_default_detail_body(tenant_id='foo'):
            resources = copy.copy(self.default_quota)

            for k, v in self.default_quota.iteritems():
                resources[k] = {}
                resources[k]['limit'] = v
                resources[k]['reserved'] = 0
                resources[k]['in_use'] = 0

            if tenant_id:
                resources['id'] = tenant_id

            return resources

        def _update_usage_in_default_detail(quota_item,
                                            reserved, in_use, **kw):
            kw[quota_item]['reserved'] = reserved
            kw[quota_item]['in_use'] = in_use
            return kw

        # show quota usage before update, should be equal to defaults
        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url + '/detail', expect_errors=True)
        self.assertEqual(res.status_int, 200)
        json_body = jsonutils.loads(res.body)
        default_detail = _make_default_detail_body(self.A.id)
        result = self._DictIn(json_body['quota_set'], default_detail)
        self.assertEqual(result, True)

        # show quota usage after reserve and in_use update
        inuse_opts = {'instances': 2, 'cores': 5}
        reserve_opts = {'instances': 3, 'cores': 3}
        self.ctx.project_id = self.A.id
        reservations = QUOTAS.reserve(self.ctx,
                                      project_id=self.A.id,
                                      **inuse_opts)
        QUOTAS.commit(self.ctx, reservations, self.A.id)
        QUOTAS.reserve(self.ctx, project_id=self.A.id, **reserve_opts)

        url = self._url_for_quota_set(self.A.id, self.A.id)
        res = self.app.get(url + '/detail', expect_errors=True)
        self.assertEqual(res.status_int, 200)
        json_body = jsonutils.loads(res.body)
        default_detail = _make_default_detail_body(self.A.id)
        update_detail = _update_usage_in_default_detail(
            'instances',
            reserve_opts['instances'],
            inuse_opts['instances'],
            **default_detail)
        update_detail = _update_usage_in_default_detail(
            'cores',
            reserve_opts['cores'],
            inuse_opts['cores'],
            **update_detail)
        result = self._DictIn(json_body['quota_set'], update_detail)
        self.assertEqual(result, True)

        # Wrong parameter
        url = '/v2.1/' + self.A.id + '/limits?_id=' + self.A.id
        res = self.app.get(url, expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])

        url = '/v2.1/' + self.A.id + '/limits'
        res = self.app.get(url, expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])

        self.ctx.is_admin = False
        url = '/v2.1/' + self.B.id + '/limits?tenant_id=' + self.C.id
        res = self.app.get(url, expect_errors=True)
        self.assertIn(res.status_int, [400, 403, 404])
        self.ctx.is_admin = True

        # test absolute limits and usage
        url = '/v2.1/' + self.A.id + '/limits?tenant_id=' + self.A.id
        res = self.app.get(url, expect_errors=True)
        self.assertEqual(res.status_int, 200)
        json_body = jsonutils.loads(res.body)
        ret_limits = json_body['limits']['absolute']

        absolute = {}
        absolute.update(quota_sets.build_absolute_limits(update_detail))
        absolute.update(quota_sets.build_used_limits(update_detail))

        result = self._DictIn(absolute, ret_limits)
        self.assertEqual(result, True)

        # test child limits, set child quota
        quota_b = dict(instances=3, cores=5)
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.put_json(url,
                                {'quota_set': quota_b},
                                expect_errors=True)
        json_body = jsonutils.loads(res.body)
        updated_b = _make_body(tenant_id=self.B.id, root=False,
                               **self.default_quota)
        updated_b = _update_subproject_body(updated_b, root=False, **quota_b)
        result = self._DictIn(json_body['quota_set'], updated_b)
        self.assertEqual(result, True)

        # test child limits, use and reserve child quota
        inuse_opts = {'instances': 1, 'cores': 1}
        reserve_opts = {'instances': 1, 'cores': 2}
        self.ctx.project_id = self.A.id
        reservations = QUOTAS.reserve(self.ctx,
                                      project_id=self.B.id,
                                      **inuse_opts)
        QUOTAS.commit(self.ctx, reservations, self.B.id)
        QUOTAS.reserve(self.ctx, project_id=self.B.id, **reserve_opts)
        url = self._url_for_quota_set(self.A.id, self.B.id)
        res = self.app.get(url + '/detail', expect_errors=True)
        self.assertEqual(res.status_int, 200)
        child_json_body = jsonutils.loads(res.body)

        self.assertEqual(
            child_json_body['quota_set']['instances']['limit'],
            quota_b['instances'])
        self.assertEqual(
            child_json_body['quota_set']['instances']['in_use'],
            inuse_opts['instances'])
        self.assertEqual(
            child_json_body['quota_set']['instances']['reserved'],
            reserve_opts['instances'])

        self.assertEqual(
            child_json_body['quota_set']['cores']['limit'],
            quota_b['cores'])
        self.assertEqual(
            child_json_body['quota_set']['cores']['in_use'],
            inuse_opts['cores'])
        self.assertEqual(
            child_json_body['quota_set']['cores']['reserved'],
            reserve_opts['cores'])

        # test child limits, get child quota limits and compare
        url = '/v2.1/' + self.A.id + '/limits?tenant_id=' + self.B.id
        res = self.app.get(url, expect_errors=True)
        self.assertEqual(res.status_int, 200)
        json_body = jsonutils.loads(res.body)
        ret_limits = json_body['limits']['absolute']

        self.assertEqual(
            ret_limits['maxTotalInstances'],
            quota_b['instances'])
        self.assertEqual(
            ret_limits['maxTotalCores'],
            quota_b['cores'])
        self.assertEqual(
            ret_limits['totalInstancesUsed'],
            inuse_opts['instances'] + reserve_opts['instances'])
        self.assertEqual(
            ret_limits['totalCoresUsed'],
            inuse_opts['cores'] + reserve_opts['cores'])

    def _show_detail_exception(self, context, show_usage=False):
        for todo_exception in self.test_exception:
            if todo_exception['exception_raise'] == self.exception_string:
                e = getattr(t_exceptions, self.exception_string)
                raise e()

    def test_quota_sets_exception_catch(self):

        orig_show = quota.QuotaSetOperation.show_detail_quota
        quota.QuotaSetOperation.show_detail_quota = mock.Mock()
        quota.QuotaSetOperation.show_detail_quota.side_effect = \
            self._show_detail_exception

        # show quota usage before update, should be equal to defaults
        for todo_exception in self.test_exception:
            self.exception_string = todo_exception['exception_raise']

            url = self._url_for_quota_set(self.A.id, self.A.id)

            # exception raised in LimitsController
            res = self.app.get(url + '/detail', expect_errors=True)
            self.assertEqual(res.status_int, todo_exception['expected_error'])

            # exception raised in QuotaSetController
            res = self.app.get(url, expect_errors=True)
            self.assertEqual(res.status_int, todo_exception['expected_error'])

        quota.QuotaSetOperation.show_detail_quota = orig_show

    def _url_for_quota_set(self, owner_tenant_id, target_tenant_id):
        return '/v2.1/' + owner_tenant_id + \
               '/os-quota-sets/' + target_tenant_id

    def _DictIn(self, dict_small, dict_full):
        for k, v in dict_small.iteritems():
            if dict_full[k] != v:
                return False
        return True
