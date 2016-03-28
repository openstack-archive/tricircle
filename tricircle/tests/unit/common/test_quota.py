
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
import datetime
import mock
import unittest

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
from oslotest import moxstubout

from tricircle.common import constants as cons
from tricircle.common import context
from tricircle.common import exceptions
from tricircle.common import quota
from tricircle.db import api as db_api
from tricircle.db import core
from tricircle.db import models
from tricircle.tests import base


CONF = cfg.CONF


class QuotaTestBase(unittest.TestCase):
    def setUp(self):
        super(QuotaTestBase, self).setUp()
        core.initialize()
        core.ModelBase.metadata.create_all(core.get_engine())

        # self.CONF = self.useFixture(fixture_config.Config()).conf
        self.ctx = context.get_admin_context()
        self.user_id = 'admin'
        self.project_id = 'admin'

        # Destroy the 'default' quota_class in the database to avoid
        # conflicts with the test cases here that are setting up their own
        # defaults.
        db_api.quota_class_destroy_all_by_name(self.ctx, 'default')

    def override_config(self, name, override, group=None):
        """Cleanly override CONF variables."""
        CONF.set_override(name, override, group)
        self.addCleanup(CONF.clear_override, name, group)

    def flags(self, **kw):
        """Override CONF variables for a test."""
        for k, v in kw.items():
            self.override_config(k, v, group='quota')

    # Useful assertions
    def assertDictMatch(self, d1, d2, approx_equal=False, tolerance=0.001):
        """Assert two dicts are equivalent.

        This is a 'deep' match in the sense that it handles nested
        dictionaries appropriately.

        NOTE:

            If you don't care (or don't know) a given value, you can specify
            the string DONTCARE as the value. This will cause that dict-item
            to be skipped.

        """
        def raise_assertion(msg):
            d1str = d1
            d2str = d2
            base_msg = ('Dictionaries do not match. %(msg)s d1: %(d1str)s '
                        'd2: %(d2str)s' %
                        {'msg': msg, 'd1str': d1str, 'd2str': d2str})
            raise AssertionError(base_msg)

        d1keys = set(d1.keys())
        d2keys = set(d2.keys())
        if d1keys != d2keys:
            d1only = d1keys - d2keys
            d2only = d2keys - d1keys
            raise_assertion('Keys in d1 and not d2: %(d1only)s. '
                            'Keys in d2 and not d1: %(d2only)s' %
                            {'d1only': d1only, 'd2only': d2only})

        for key in d1keys:
            d1value = d1[key]
            d2value = d2[key]
            try:
                error = abs(float(d1value) - float(d2value))
                within_tolerance = error <= tolerance
            except (ValueError, TypeError):
                # If both values aren't convertible to float, just ignore
                # ValueError if arg is a str, TypeError if it's something else
                # (like None)
                within_tolerance = False

            if hasattr(d1value, 'keys') and hasattr(d2value, 'keys'):
                self.assertDictMatch(d1value, d2value)
            elif 'DONTCARE' in (d1value, d2value):
                continue
            elif approx_equal and within_tolerance:
                continue
            elif d1value != d2value:
                raise_assertion("d1['%(key)s']=%(d1value)s != "
                                "d2['%(key)s']=%(d2value)s" %
                                {
                                    'key': key,
                                    'd1value': d1value,
                                    'd2value': d2value,
                                })

    def tearDown(self):
        super(QuotaTestBase, self).tearDown()
        core.ModelBase.metadata.drop_all(core.get_engine())


class FakeContext(context.Context):
    def __init__(self, project_id, quota_class):
        super(FakeContext, self).__init__(tenant=project_id,
                                          quota_class=quota_class)
        self.is_admin = False
        self.user_id = 'fake_user'

    def elevated(self):
        elevated = self.__class__(self.project_id, self.quota_class)
        elevated.is_admin = True
        return elevated


class FakeDriver(object):
    def __init__(self, by_project=None, by_class=None, reservations=None):
        self.called = []
        self.by_project = by_project or {}
        self.by_class = by_class or {}
        self.reservations = reservations or []

    def get_by_project(self, context, project_id, resource):
        self.called.append(('get_by_project', context, project_id, resource))
        try:
            return self.by_project[project_id][resource]
        except KeyError:
            raise exceptions.ProjectQuotaNotFound(project_id=project_id)

    def get_by_class(self, context, quota_class, resource):
        self.called.append(('get_by_class', context, quota_class, resource))
        try:
            return self.by_class[quota_class][resource]
        except KeyError:
            raise exceptions.QuotaClassNotFound(class_name=quota_class)

    def get_default(self, context, resource, parent_project_id=None):
        self.called.append(('get_default', context, resource,
                            parent_project_id))
        return resource.default

    def get_defaults(self, context, resources, parent_project_id=None):
        self.called.append(('get_defaults', context, resources,
                            parent_project_id))
        return resources

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        self.called.append(('get_class_quotas', context, resources,
                            quota_class, defaults))
        return resources

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True, usages=True,
                           parent_project_id=None):
        self.called.append(('get_project_quotas', context, resources,
                            project_id, quota_class, defaults, usages,
                            parent_project_id))
        return resources

    def limit_check(self, context, resources, values, project_id=None):
        self.called.append(('limit_check', context, resources,
                            values, project_id))

    def reserve(self, context, resources, deltas, expire=None,
                project_id=None):
        self.called.append(('reserve', context, resources, deltas,
                            expire, project_id))
        return self.reservations

    def commit(self, context, reservations, project_id=None):
        self.called.append(('commit', context, reservations, project_id))

    def rollback(self, context, reservations, project_id=None):
        self.called.append(('rollback', context, reservations, project_id))

    def destroy_by_project(self, context, project_id):
        self.called.append(('destroy_by_project', context, project_id))

    def expire(self, context):
        self.called.append(('expire', context))


class BaseResourceTestCase(QuotaTestBase):
    def test_no_flag(self):
        resource = quota.BaseResource('test_resource')
        self.assertEqual('test_resource', resource.name)
        self.assertIsNone(resource.flag)
        self.assertEqual(-1, resource.default)

    def test_with_flag(self):
        # We know this flag exists, so use it...
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        self.assertEqual('test_resource', resource.name)
        self.assertEqual('quota_volumes', resource.flag)
        self.assertEqual(10, resource.default)

    def test_with_flag_no_quota(self):
        self.flags(quota_volumes=-1)
        resource = quota.BaseResource('test_resource', 'quota_volumes')

        self.assertEqual('test_resource', resource.name)
        self.assertEqual('quota_volumes', resource.flag)
        self.assertEqual(-1, resource.default)

    def test_quota_no_project_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver()
        context = FakeContext(None, None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(10, quota_value)

    def test_quota_with_project_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(
            by_project=dict(
                test_project=dict(test_resource=15), ))
        context = FakeContext('test_project', None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(15, quota_value)

    def test_quota_no_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(
            by_class=dict(
                test_class=dict(test_resource=20), ))
        context = FakeContext(None, 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(20, quota_value)

    def test_quota_with_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_project=dict(
            test_project=dict(test_resource=15), ),
            by_class=dict(test_class=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(15, quota_value)

    def test_quota_override_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_project=dict(
            test_project=dict(test_resource=15),
            override_project=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     project_id='override_project')

        self.assertEqual(20, quota_value)

    def test_quota_override_subproject_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes',
                                      parent_project_id='test_parent_project')
        driver = FakeDriver()
        context = FakeContext('test_project', None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(0, quota_value)

    def test_quota_with_project_override_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_class=dict(
            test_class=dict(test_resource=15),
            override_class=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     quota_class='override_class')

        self.assertEqual(20, quota_value)


class QuotaEngineTestCase(QuotaTestBase):
    def test_init(self):
        quota_obj = quota.QuotaEngine()

        self.assertEqual({}, quota_obj.resources)
        self.assertIsInstance(quota_obj._driver, quota.DbQuotaDriver)

    def test_init_override_obj(self):
        quota_obj = quota.QuotaEngine(quota_driver_class=FakeDriver)

        self.assertEqual({}, quota_obj.resources)
        self.assertEqual(FakeDriver, quota_obj._driver)

    def test_register_resource(self):
        quota_obj = quota.QuotaEngine()
        resource = quota.AbsoluteResource('test_resource')
        quota_obj.register_resource(resource)

        self.assertEqual(dict(test_resource=resource), quota_obj.resources)

    def test_register_resources(self):
        quota_obj = quota.QuotaEngine()
        resources = [
            quota.AbsoluteResource('test_resource1'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource3'), ]
        quota_obj.register_resources(resources)

        self.assertEqual(dict(test_resource1=resources[0],
                              test_resource2=resources[1],
                              test_resource3=resources[2], ),
                         quota_obj.resources)

    def test_get_by_project(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(
            by_project=dict(
                test_project=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_project(context, 'test_project',
                                          'test_resource')

        self.assertEqual([('get_by_project',
                           context,
                           'test_project',
                           'test_resource'), ], driver.called)
        self.assertEqual(42, result)

    def test_get_by_class(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(
            by_class=dict(
                test_class=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_class(context, 'test_class', 'test_resource')

        self.assertEqual([('get_by_class',
                           context,
                           'test_class',
                           'test_resource'), ], driver.called)
        self.assertEqual(42, result)

    def _make_quota_obj(self, driver):
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        resources = [
            quota.AbsoluteResource('test_resource4'),
            quota.AbsoluteResource('test_resource3'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource1'), ]
        quota_obj.register_resources(resources)

        return quota_obj

    def test_get_defaults(self):
        context = FakeContext(None, None)
        parent_project_id = None
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result = quota_obj.get_defaults(context)

        self.assertEqual([('get_defaults',
                          context,
                          quota_obj.resources,
                          parent_project_id), ], driver.called)
        self.assertEqual(quota_obj.resources, result)

    def test_get_class_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_class_quotas(context, 'test_class')
        result2 = quota_obj.get_class_quotas(context, 'test_class', False)

        self.assertEqual([
            ('get_class_quotas',
             context,
             quota_obj.resources,
             'test_class', True),
            ('get_class_quotas',
             context, quota_obj.resources,
             'test_class', False), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_get_project_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        parent_project_id = None
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_project_quotas(context, 'test_project')
        result2 = quota_obj.get_project_quotas(context, 'test_project',
                                               quota_class='test_class',
                                               defaults=False,
                                               usages=False)

        self.assertEqual([
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             None,
             True,
             True,
             parent_project_id),
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             'test_class',
             False,
             False,
             parent_project_id), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_get_subproject_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        parent_project_id = 'test_parent_project_id'
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_project_quotas(
            context, 'test_project',
            parent_project_id=parent_project_id)
        result2 = quota_obj.get_project_quotas(
            context, 'test_project',
            quota_class='test_class',
            defaults=False,
            usages=False,
            parent_project_id=parent_project_id)

        self.assertEqual([
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             None,
             True,
             True,
             parent_project_id),
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             'test_class',
             False,
             False,
             parent_project_id), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_count_no_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exceptions.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource5',
                          True, foo='bar')

    def test_count_wrong_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exceptions.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource1',
                          True, foo='bar')

    def test_count(self):
        def fake_count(context, *args, **kwargs):
            self.assertEqual((True,), args)
            self.assertEqual(dict(foo='bar'), kwargs)
            return 5

        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.register_resource(quota.CountableResource('test_resource5',
                                                            fake_count))
        result = quota_obj.count(context, 'test_resource5', True, foo='bar')

        self.assertEqual(5, result)

    def test_limit_check(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.limit_check(context, test_resource1=4, test_resource2=3,
                              test_resource3=2, test_resource4=1)

        self.assertEqual([
            ('limit_check',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=4,
                 test_resource2=3,
                 test_resource3=2,
                 test_resource4=1,),
             None), ],
            driver.called)

    def test_reserve(self):
        context = FakeContext(None, None)
        driver = FakeDriver(reservations=['resv-01',
                                          'resv-02',
                                          'resv-03',
                                          'resv-04', ])
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.reserve(context, test_resource1=4,
                                    test_resource2=3, test_resource3=2,
                                    test_resource4=1)
        result2 = quota_obj.reserve(context, expire=3600,
                                    test_resource1=1, test_resource2=2,
                                    test_resource3=3, test_resource4=4)
        result3 = quota_obj.reserve(context, project_id='fake_project',
                                    test_resource1=1, test_resource2=2,
                                    test_resource3=3, test_resource4=4)

        self.assertEqual([
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=4,
                 test_resource2=3,
                 test_resource3=2,
                 test_resource4=1, ),
             None,
             None),
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=1,
                 test_resource2=2,
                 test_resource3=3,
                 test_resource4=4, ),
             3600,
             None),
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=1,
                 test_resource2=2,
                 test_resource3=3,
                 test_resource4=4, ),
             None,
             'fake_project'), ],
            driver.called)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result1)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result2)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result3)

    def test_commit(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.commit(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual([('commit',
                           context,
                           ['resv-01',
                            'resv-02',
                            'resv-03'],
                           None), ],
                         driver.called)

    def test_rollback(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.rollback(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual([('rollback',
                           context,
                           ['resv-01',
                            'resv-02',
                            'resv-03'],
                           None), ],
                         driver.called)

    def test_destroy_by_project(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.destroy_by_project(context, 'test_project')

        self.assertEqual([('destroy_by_project',
                           context,
                           'test_project'), ],
                         driver.called)

    def test_expire(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.expire(context)

        self.assertEqual([('expire', context), ], driver.called)

    def test_resource_names(self):
        quota_obj = self._make_quota_obj(None)

        self.assertEqual(['test_resource1', 'test_resource2',
                          'test_resource3', 'test_resource4'],
                         quota_obj.resource_names)


class DbQuotaDriverTestCase(QuotaTestBase, base.TestCase):
    def setUp(self):
        super(DbQuotaDriverTestCase, self).setUp()

        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs

        self.test_class_quota = dict(instances=20, volumes=20,
                                     snapshots=20, backups=20,
                                     gigabytes=cons.MAX_INT)

        self.test_class_quota2 = dict(instances=10, volumes=10,
                                      snapshots=5, backups=5,
                                      gigabytes=500)

        self.default_quota = dict(
            instances=10, cores=20, ram=51200,
            floating_ips=10, fixed_ips=-1, metadata_items=128,
            injected_files=5, injected_file_path_bytes=255,
            injected_file_content_bytes=10240,
            security_groups=10, security_group_rules=20, key_pairs=100,
            server_groups=10, server_group_members=10,

            volumes=10, snapshots=10, consistencygroups=10,
            gigabytes=500, backups=10, backup_gigabytes=500,
            per_volume_gigabytes=-1)

        self.invalid_quota = {}
        for k in self.default_quota:
            self.invalid_quota[k] = 0

        self.flags(
            quota_instances=self.default_quota['instances'],
            quota_cores=self.default_quota['cores'],
            quota_ram=self.default_quota['ram'],
            quota_floating_ips=self.default_quota['floating_ips'],
            quota_fixed_ips=self.default_quota['fixed_ips'],
            quota_metadata_items=self.default_quota['metadata_items'],
            quota_injected_files=self.default_quota['injected_files'],
            quota_injected_file_path_length=self.default_quota[
                'injected_file_path_bytes'],
            quota_injected_file_content_bytes=self.default_quota[
                'injected_file_content_bytes'],
            quota_security_groups=self.default_quota['security_groups'],
            quota_security_group_rules=self.default_quota[
                'security_group_rules'],
            quota_key_pairs=self.default_quota['key_pairs'],
            quota_server_groups=self.default_quota['server_groups'],
            quota_server_group_members=self.default_quota[
                'server_group_members'],

            quota_volumes=self.default_quota['volumes'],
            quota_snapshots=self.default_quota['snapshots'],
            quota_consistencygroups=self.default_quota['consistencygroups'],
            quota_gigabytes=self.default_quota['gigabytes'],
            quota_backups=self.default_quota['backups'],
            quota_backup_gigabytes=self.default_quota['backup_gigabytes'],

            reservation_expire=86400,
            until_refresh=0,
            max_age=0,
        )

        self.test_class_expected_result = copy.copy(
            self.default_quota)
        for k in self.test_class_quota:
            self.test_class_expected_result[k] = \
                self.test_class_quota[k]

        self.test_subproject_expected_result = copy.copy(
            self.invalid_quota)
        for k in self.test_class_quota:
            self.test_subproject_expected_result[k] = \
                self.test_class_quota[k]

        self.test_subproject_expected_result2 = copy.copy(
            self.invalid_quota)
        for k in self.test_class_quota2:
            self.test_subproject_expected_result2[k] = \
                self.test_class_quota2[k]

        self.driver = quota.DbQuotaDriver()

        self.calls = []

        patcher = mock.patch.object(timeutils, 'utcnow')
        self.addCleanup(patcher.stop)
        self.mock_utcnow = patcher.start()
        self.mock_utcnow.return_value = datetime.datetime.utcnow()

    def test_get_defaults(self):
        # Use our pre-defined resources
        self._stub_quota_class_get_default()
        result = self.driver.get_defaults(None, quota.QUOTAS.resources)

        self.assertEqual(self.default_quota, result)

    def test_subproject_get_defaults(self):
        # Test subproject default values.
        parent_project_id = 'test_parent_project_id'
        result = self.driver.get_defaults(None,
                                          quota.QUOTAS.resources,
                                          parent_project_id)

        self.assertEqual(self.invalid_quota, result)

    def _stub_quota_class_get_default(self):
        # Stub out quota_class_get_default
        def fake_qcgd(context):
            self.calls.append('quota_class_get_default')
            return self.default_quota
        self.stubs.Set(db_api, 'quota_class_get_default', fake_qcgd)

    def _stub_quota_class_get_all_by_name(self):
        # Stub out quota_class_get_all_by_name
        def fake_qcgabn(context, quota_class):
            self.calls.append('quota_class_get_all_by_name')
            self.assertEqual('test_class', quota_class)
            return self.test_class_quota

        self.stubs.Set(db_api, 'quota_class_get_all_by_name', fake_qcgabn)

    def test_get_class_quotas(self):
        self._stub_quota_class_get_default()
        self._stub_quota_class_get_all_by_name()
        result = self.driver.get_class_quotas(self.ctx,
                                              quota.QUOTAS.resources,
                                              'test_class')

        self.assertEqual(['quota_class_get_all_by_name',
                          'quota_class_get_default'],
                         self.calls)
        self.assertEqual(self.test_class_expected_result, result)

    def test_get_class_quotas_no_defaults(self):
        self._stub_quota_class_get_all_by_name()
        result = self.driver.get_class_quotas(None, quota.QUOTAS.resources,
                                              'test_class', False)

        self.assertEqual(['quota_class_get_all_by_name'], self.calls)
        self.assertEqual(self.test_class_quota, result)

    def _stub_get_by_project(self):
        def fake_qgabp(context, project_id):
            self.calls.append('quota_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=10, gigabytes=50, reserved=0,
                        snapshots=10, backups=10,
                        backup_gigabytes=50)

        def fake_qugabp(context, project_id):
            self.calls.append('quota_usage_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=dict(in_use=2, reserved=0),
                        snapshots=dict(in_use=2, reserved=0),
                        gigabytes=dict(in_use=10, reserved=0),
                        backups=dict(in_use=2, reserved=0),
                        backup_gigabytes=dict(in_use=10, reserved=0)
                        )

        self.stubs.Set(db_api, 'quota_get_all_by_project', fake_qgabp)
        self.stubs.Set(db_api, 'quota_usage_get_all_by_project', fake_qugabp)

        self._stub_quota_class_get_all_by_name()
        self._stub_quota_class_get_default()

    def _stub_get_by_subproject(self):
        def fake_qgabp(context, project_id):
            self.calls.append('quota_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=10, gigabytes=50, reserved=0)

        def fake_qugabp(context, project_id):
            self.calls.append('quota_usage_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=dict(in_use=2, reserved=0),
                        gigabytes=dict(in_use=10, reserved=0))

        self.stubs.Set(db_api, 'quota_get_all_by_project', fake_qgabp)
        self.stubs.Set(db_api, 'quota_usage_get_all_by_project', fake_qugabp)

        self._stub_quota_class_get_all_by_name()

    def _stub_allocated_get_all_by_project(self, allocated_quota=False):
        def fake_qagabp(context, project_id):
            self.calls.append('quota_allocated_get_all_by_project')
            self.assertEqual('test_project', project_id)
            if allocated_quota:
                return dict(project_id=project_id, volumes=3)
            return dict(project_id=project_id)

        self.stubs.Set(db_api, 'quota_allocated_get_all_by_project',
                       fake_qagabp)

    def test_get_project_quotas(self):
        self._stub_get_by_project()
        self._stub_allocated_get_all_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_default', ], self.calls)

        expected = dict(volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        snapshots=dict(limit=10,
                                       in_use=2,
                                       reserved=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0, ),
                        backups=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        backup_gigabytes=dict(limit=50,
                                              in_use=10,
                                              reserved=0, ),
                        per_volume_gigabytes=dict(in_use=0,
                                                  limit=-1,
                                                  reserved=0))
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_root_project_with_subprojects_quotas(self):
        self._stub_get_by_project()
        self._stub_allocated_get_all_by_project(allocated_quota=True)
        result = self.driver.get_project_quotas(
            FakeContext('test_project', None),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project',
                          'quota_class_get_default', ], self.calls)

        expected = dict(volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0,
                                     allocated=3, ),
                        snapshots=dict(limit=10,
                                       in_use=2,
                                       reserved=0,
                                       allocated=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0,
                                       allocated=0, ),
                        backups=dict(limit=10,
                                     in_use=2,
                                     reserved=0,
                                     allocated=0, ),
                        backup_gigabytes=dict(limit=50,
                                              in_use=10,
                                              reserved=0,
                                              allocated=0, ),
                        per_volume_gigabytes=dict(in_use=0,
                                                  limit=-1,
                                                  reserved=0,
                                                  allocated=0))
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_subproject_quotas(self):
        self._stub_get_by_subproject()
        self._stub_allocated_get_all_by_project(allocated_quota=True)
        parent_project_id = 'test_parent_project_id'
        result = self.driver.get_project_quotas(
            FakeContext('test_project', None),
            quota.QUOTAS.resources, 'test_project',
            parent_project_id=parent_project_id)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project', ], self.calls)

        expected = dict(volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0,
                                     allocated=3, ),
                        snapshots=dict(limit=0,
                                       in_use=0,
                                       reserved=0,
                                       allocated=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0,
                                       allocated=0, ),
                        backups=dict(limit=0,
                                     in_use=0,
                                     reserved=0,
                                     allocated=0, ),
                        backup_gigabytes=dict(limit=0,
                                              in_use=0,
                                              reserved=0,
                                              allocated=0, ),
                        per_volume_gigabytes=dict(in_use=0,
                                                  limit=0,
                                                  reserved=0,
                                                  allocated=0))
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_project_quotas_alt_context_no_class(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_default', ], self.calls)

        expected = dict(volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        snapshots=dict(limit=10,
                                       in_use=2,
                                       reserved=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0, ),
                        backups=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        backup_gigabytes=dict(limit=50,
                                              in_use=10,
                                              reserved=0, ),
                        per_volume_gigabytes=dict(in_use=0,
                                                  limit=-1,
                                                  reserved=0)
                        )

        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_project_quotas_alt_context_with_class(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS.resources, 'test_project', quota_class='test_class')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_default', ], self.calls)

        expected = dict(volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        snapshots=dict(limit=10,
                                       in_use=2,
                                       reserved=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0, ),
                        backups=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        backup_gigabytes=dict(limit=50,
                                              in_use=10,
                                              reserved=0, ),
                        per_volume_gigabytes=dict(in_use=0,
                                                  limit=-1,
                                                  reserved=0))
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_project_quotas_no_defaults(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project', defaults=False)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_default', ], self.calls)

        expected = dict(backups=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),
                        backup_gigabytes=dict(limit=50,
                                              in_use=10,
                                              reserved=0, ),
                        gigabytes=dict(limit=50,
                                       in_use=10,
                                       reserved=0, ),
                        snapshots=dict(limit=10,
                                       in_use=2,
                                       reserved=0, ),
                        volumes=dict(limit=10,
                                     in_use=2,
                                     reserved=0, ),)
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def test_get_project_quotas_no_usages(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project', usages=False)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_default', ], self.calls)
        expected = dict(volumes=dict(limit=10, ),
                        snapshots=dict(limit=10, ),
                        backups=dict(limit=10, ),
                        gigabytes=dict(limit=50, ),
                        backup_gigabytes=dict(limit=50, ),
                        per_volume_gigabytes=dict(limit=-1, ))
        for k in expected:
            self.assertEqual(expected[k], result[k])

    def _stub_get_project_quotas(self):
        def fake_get_project_quotas(context, resources, project_id,
                                    quota_class=None, defaults=True,
                                    usages=True, parent_project_id=None):
            self.calls.append('get_project_quotas')
            return {k: dict(limit=v.default) for k, v in resources.items()}

        self.stubs.Set(self.driver, 'get_project_quotas',
                       fake_get_project_quotas)

    def test_get_quotas_has_sync_unknown(self):
        self._stub_get_project_quotas()
        self.assertRaises(exceptions.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['unknown'], True)
        self.assertEqual([], self.calls)

    def test_get_quotas_no_sync_unknown(self):
        self._stub_get_project_quotas()
        self.assertRaises(exceptions.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['unknown'], False)
        self.assertEqual([], self.calls)

    def test_get_quotas_has_sync_no_sync_resource(self):
        self._stub_get_project_quotas()
        self.assertRaises(exceptions.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['metadata_items'], True)
        self.assertEqual([], self.calls)

    def test_get_quotas_has_no_sync(self):
        self._stub_get_project_quotas()
        result = self.driver._get_quotas(FakeContext('test_project',
                                                     'test_class'),
                                         quota.QUOTAS.resources,
                                         ['volumes', 'gigabytes'],
                                         False)

        self.assertEqual(['get_project_quotas'], self.calls)
        self.assertEqual(self.default_quota['volumes'], result['volumes'])
        self.assertEqual(self.default_quota['gigabytes'], result['gigabytes'])

    def _stub_quota_reserve(self):
        def fake_quota_reserve(context, resources, quotas, deltas, expire,
                               until_refresh, max_age, project_id=None):
            self.calls.append(('quota_reserve', expire, until_refresh,
                               max_age))
            return ['resv-1', 'resv-2', 'resv-3']
        self.stubs.Set(db_api, 'quota_reserve', fake_quota_reserve)

    def test_reserve_bad_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.assertRaises(exceptions.InvalidReservationExpiration,
                          self.driver.reserve,
                          FakeContext('test_project', 'test_class'),
                          quota.QUOTAS.resources,
                          dict(volumes=2), expire='invalid')
        self.assertEqual([], self.calls)

    def test_reserve_default_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2))

        expire = timeutils.utcnow() + datetime.timedelta(seconds=86400)
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_int_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=3600)

        expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_timedelta_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        expire_delta = datetime.timedelta(seconds=60)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire_delta)

        expire = timeutils.utcnow() + expire_delta
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_datetime_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_until_refresh(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.flags(until_refresh=500)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 500, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_max_age(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.flags(max_age=86400)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 86400), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def _stub_quota_destroy_by_project(self):
        def fake_quota_destroy_by_project(context, project_id):
            self.calls.append(('quota_destroy_by_project', project_id))
            return None
        self.stubs.Set(db_api, 'quota_destroy_by_project',
                       fake_quota_destroy_by_project)

    def test_destroy_quota_by_project(self):
        self._stub_quota_destroy_by_project()
        self.driver.destroy_by_project(FakeContext('test_project',
                                                   'test_class'),
                                       'test_project')
        self.assertEqual([('quota_destroy_by_project', ('test_project')), ],
                         self.calls)


class FakeSession(object):
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        return False


class FakeUsage(models.QuotaUsages):
    def save(self, *args, **kwargs):
        pass


class QuotaReserveTestCase(QuotaTestBase, base.TestCase):
    # cinder.db.sqlalchemy.api.quota_reserve is so complex it needs its
    # own test case, and since it's a quota manipulator, this is the
    # best place to put it...

    def setUp(self):
        super(QuotaReserveTestCase, self).setUp()

        self.sync_called = set()

        def make_sync(res_name):
            def fake_sync(context, project_id, volume_type_id=None,
                          volume_type_name=None, session=None):
                self.sync_called.add(res_name)
                if res_name in self.usages:
                    if self.usages[res_name].in_use < 0:
                        return {res_name: 2}
                    else:
                        return {res_name: self.usages[res_name].in_use - 1}
                return {res_name: 0}
            return fake_sync

        self.resources = {}
        QUOTA_SYNC_FUNCTIONS = {}
        for res_name in ('volumes', 'gigabytes'):
            res = quota.ReservableResource(res_name, '_sync_%s' % res_name)
            QUOTA_SYNC_FUNCTIONS['_sync_%s' % res_name] = make_sync(res_name)
            self.resources[res_name] = res

        self.expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)

        self.usages = {}
        self.usages_created = {}
        self.reservations_created = {}

        def fake_get_quota_usages(context, session, project_id):
            return self.usages.copy()

        def fake_quota_usage_create(context, project_id, resource, in_use,
                                    reserved, until_refresh, session=None,
                                    save=True):
            quota_usage_ref = self._make_quota_usage(
                project_id, resource, in_use, reserved, until_refresh,
                timeutils.utcnow(), timeutils.utcnow())

            self.usages_created[resource] = quota_usage_ref

            return quota_usage_ref

        def fake_reservation_create(context, uuid, usage_id, project_id,
                                    resource, delta, expire, session=None):
            reservation_ref = self._make_reservation(
                uuid, usage_id, project_id, resource, delta, expire,
                timeutils.utcnow(), timeutils.utcnow())

            self.reservations_created[resource] = reservation_ref

            return reservation_ref

        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs

        self.stubs.Set(db_api, '_get_quota_usages', fake_get_quota_usages)
        self.stubs.Set(db_api, '_quota_usage_create', fake_quota_usage_create)
        self.stubs.Set(db_api, '_reservation_create', fake_reservation_create)

        patcher = mock.patch.object(timeutils, 'utcnow')
        self.addCleanup(patcher.stop)
        self.mock_utcnow = patcher.start()
        self.mock_utcnow.return_value = datetime.datetime.utcnow()

    def _make_quota_usage(self, project_id, resource, in_use, reserved,
                          until_refresh, created_at, updated_at):
        quota_usage_ref = FakeUsage()
        quota_usage_ref.id = len(self.usages) + len(self.usages_created)
        quota_usage_ref.project_id = project_id
        quota_usage_ref.resource = resource
        quota_usage_ref.in_use = in_use
        quota_usage_ref.reserved = reserved
        quota_usage_ref.until_refresh = until_refresh
        quota_usage_ref.created_at = created_at
        quota_usage_ref.updated_at = updated_at
        quota_usage_ref.deleted_at = None
        quota_usage_ref.deleted = False

        return quota_usage_ref

    def init_usage(self, project_id, resource, in_use, reserved,
                   until_refresh=None, created_at=None, updated_at=None):
        if created_at is None:
            created_at = timeutils.utcnow()
        if updated_at is None:
            updated_at = timeutils.utcnow()

        quota_usage_ref = self._make_quota_usage(project_id, resource, in_use,
                                                 reserved, until_refresh,
                                                 created_at, updated_at)

        self.usages[resource] = quota_usage_ref

    def compare_usage(self, usage_dict, expected):
        for usage in expected:
            resource = usage['resource']
            for key, value in usage.items():
                actual = getattr(usage_dict[resource], key)
                self.assertEqual(value, actual,
                                 "%s != %s on usage for resource %s" %
                                 (actual, value, resource))

    def _make_reservation(self, uuid, usage_id, project_id, resource,
                          delta, expire, created_at, updated_at):
        reservation_ref = models.Reservation()
        reservation_ref.id = len(self.reservations_created)
        reservation_ref.uuid = uuid
        reservation_ref.usage_id = usage_id
        reservation_ref.project_id = project_id
        reservation_ref.resource = resource
        reservation_ref.delta = delta
        reservation_ref.expire = expire
        reservation_ref.created_at = created_at
        reservation_ref.updated_at = updated_at
        reservation_ref.deleted_at = None
        reservation_ref.deleted = False

        return reservation_ref

    def compare_reservation(self, reservations, expected):
        reservations = set(reservations)
        for resv in expected:
            resource = resv['resource']
            resv_obj = self.reservations_created[resource]

            self.assertIn(resv_obj.uuid, reservations)
            reservations.discard(resv_obj.uuid)

            for key, value in resv.items():
                actual = getattr(resv_obj, key)
                self.assertEqual(value, actual,
                                 "%s != %s on reservation for resource %s" %
                                 (actual, value, resource))

        self.assertEqual(0, len(reservations))

    def test_quota_reserve_create_usages(self):
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5,
                      gigabytes=10 * 1024, )
        deltas = dict(volumes=2,
                      gigabytes=2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 0, 0)

        # no sync function in Tricircle
        # self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages_created,
                           [dict(resource='volumes',
                                 project_id='test_project',
                                 in_use=0,
                                 reserved=2,
                                 until_refresh=None),
                            dict(resource='gigabytes',
                                 project_id='test_project',
                                 in_use=0,
                                 reserved=2 * 1024,
                                 until_refresh=None), ])
        self.compare_reservation(
            result,
            [dict(resource='volumes',
                  usage_id=self.usages_created['volumes'],
                  project_id='test_project',
                  delta=2),
             dict(resource='gigabytes',
                  usage_id=self.usages_created['gigabytes'],
                  delta=2 * 1024), ])

    def test_quota_reserve_negative_in_use(self):
        self.init_usage('test_project', 'volumes', -1, 0, until_refresh=1)
        self.init_usage('test_project', 'gigabytes', -1, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5,
                      gigabytes=10 * 1024, )
        deltas = dict(volumes=2,
                      gigabytes=2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 5, 0)

        # no sync function in Tricircle
        # self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=-1,
                                              reserved=2,
                                              until_refresh=5),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=-1,
                                              reserved=2 * 1024,
                                              until_refresh=5), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_until_refresh(self):
        self.init_usage('test_project', 'volumes', 3, 0, until_refresh=1)
        self.init_usage('test_project', 'gigabytes', 3, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 5, 0)

        # no sync function in Tricircle
        # self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2,
                                              until_refresh=5),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2 * 1024,
                                              until_refresh=5), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_max_age(self):
        max_age = 3600
        record_created = (timeutils.utcnow() -
                          datetime.timedelta(seconds=max_age))
        self.init_usage('test_project', 'volumes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        self.init_usage('test_project', 'gigabytes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 0, max_age)

        # no sync function in Tricircle
        # self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2 * 1024,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_no_refresh(self):
        self.init_usage('test_project', 'volumes', 3, 0)
        self.init_usage('test_project', 'gigabytes', 3, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2 * 1024,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_unders(self):
        self.init_usage('test_project', 'volumes', 1, 0)
        self.init_usage('test_project', 'gigabytes', 1 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=-2, gigabytes=-2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=1,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=1 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=-2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=-2 * 1024), ])

    def test_quota_reserve_overs(self):
        self.init_usage('test_project', 'volumes', 4, 0)
        self.init_usage('test_project', 'gigabytes', 10 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self.assertRaises(exceptions.OverQuota,
                          db_api.quota_reserve,
                          context, self.resources, quotas,
                          deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=4,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=10 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.assertEqual({}, self.reservations_created)

    def test_quota_reserve_reduction(self):
        self.init_usage('test_project', 'volumes', 10, 0)
        self.init_usage('test_project', 'gigabytes', 20 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=-2, gigabytes=-2 * 1024, )
        result = db_api.quota_reserve(context, self.resources, quotas,
                                      deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=10,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=20 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=-2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       project_id='test_project',
                                       delta=-2 * 1024), ])


def _make_body(tenant_id='foo', root=True, **kw):
    resources = copy.copy(kw)
    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_set': resources}
    else:
        result = resources
    return result


def _make_subproject_body(tenant_id='foo', root=True, **kw):
    return _make_body(tenant_id=tenant_id, root=root, **kw)


class QuotaSetsOperationTest(DbQuotaDriverTestCase, base.TestCase):

    class FakeProject(object):

        def __init__(self, id='foo', parent_id=None):
            self.id = id
            self.parent_id = parent_id
            self.subtree = None

    def setUp(self):
        super(QuotaSetsOperationTest, self).setUp()

        self.flags(use_default_quota_class=True)
        self._create_project_hierarchy()
        self._create_default_class()

        self.subproject_defualt_quota = {}
        self.subproject_defualt_quota = copy.copy(self.default_quota)
        for k in self.subproject_defualt_quota:
            self.subproject_defualt_quota[k] = 0

    def _create_project_hierarchy(self):
        """Sets an environment used for nested quotas tests.

        Create a project hierarchy such as follows:
        +-----------++-----------++-----------+
        |           ||           ||           |
        |     A     ||     F     ||     G     |
        |    / \    ||           ||           |
        |   B   C   ||           ||           |
        |  /        ||           ||           |
        | D         ||           ||           |
        | |         ||           ||           |
        | E         ||           ||           |
        +-----------++-----------++-----------+
        """
        self.A = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=None)
        self.B = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=self.A.id)
        self.C = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=self.A.id)
        self.D = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=self.B.id)
        self.E = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=self.D.id)
        self.F = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=None)
        self.G = self.FakeProject(id=uuidutils.generate_uuid(),
                                  parent_id=None)

        # update projects subtrees
        self.D.subtree = {self.E.id: self.E.subtree}
        self.B.subtree = {self.D.id: self.D.subtree}
        self.A.subtree = {self.B.id: self.B.subtree, self.C.id: self.C.subtree}

        # project_by_id attribute is used to recover a project based on its id
        self.project_by_id = {self.A.id: self.A, self.B.id: self.B,
                              self.C.id: self.C, self.D.id: self.D,
                              self.E.id: self.E, self.F.id: self.F,
                              self.G.id: self.G, }

    def _create_default_class(self):
        for k, v in self.default_quota.items():
            db_api.quota_class_create(self.ctx, 'default', k, v)

    def _get_project(self, context, id, subtree_as_ids=False):
        return self.project_by_id.get(id, self.FakeProject())

    def _quota_reserve(self, context, project_id):
        """Create sample Quota, QuotaUsage and Reservation objects.

        There is no method api.quota_usage_create(), so we have to use
        api.quota_reserve() for creating QuotaUsage objects.

        Returns reservations uuids.

        """
        quotas = {}
        resources = {}
        deltas = {}
        for i, resource in enumerate(('volumes', 'gigabytes')):
            quota_obj = db_api.quota_create(context, project_id,
                                            resource, i + 1)
            quotas[resource] = quota_obj.hard_limit
            resources[resource] = quota.ReservableResource(resource, None)
            deltas[resource] = i + 1
        return db_api.quota_reserve(
            context, resources, quotas, deltas,
            datetime.datetime.utcnow(), datetime.datetime.utcnow(),
            datetime.timedelta(days=1), project_id
        )

    def tearDown(self):
        super(QuotaSetsOperationTest, self).tearDown()
        core.ModelBase.metadata.drop_all(core.get_engine())

    def test_defaults(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.parent_id
        result = qso.show_default_quota(self.ctx)
        expected = _make_body(tenant_id=self.A.id, root=True,
                              **self.default_quota)
        self.assertDictMatch(expected, result)

    def test_subproject_defaults(self):
        qso = quota.QuotaSetOperation(self.B.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.parent_id
        result = qso.show_default_quota(self.ctx)
        expected = _make_subproject_body(tenant_id=self.B.id, root=True,
                                         **self.subproject_defualt_quota)
        self.assertDictMatch(expected, result)

    def test_show(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id
        result = qso.show_detail_quota(self.ctx)
        expected = _make_body(tenant_id=self.A.id, root=True,
                              **self.default_quota)
        self.assertDictMatch(expected, result)

    def test_subproject_show(self):
        qso = quota.QuotaSetOperation(self.B.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.parent_id
        result = qso.show_detail_quota(self.ctx)
        expected = _make_subproject_body(tenant_id=self.B.id, root=True,
                                         **self.subproject_defualt_quota)
        self.assertDictMatch(expected, result)

    def test_subproject_show_in_hierarchy_1(self):
        qso = quota.QuotaSetOperation(self.D.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id
        result = qso.show_detail_quota(self.ctx)
        expected = _make_subproject_body(tenant_id=self.D.id, root=True,
                                         **self.subproject_defualt_quota)
        self.assertDictMatch(expected, result)

    def test_subproject_show_in_hierarchy_2(self):
        qso = quota.QuotaSetOperation(self.D.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.id
        result = qso.show_detail_quota(self.ctx)
        expected = _make_subproject_body(tenant_id=self.D.id, root=True,
                                         **self.subproject_defualt_quota)
        self.assertDictMatch(expected, result)

    def test_subproject_show_target_project_equals_to_context_project(self):
        qso = quota.QuotaSetOperation(self.B.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.id
        result = qso.show_detail_quota(self.ctx)
        expected = _make_subproject_body(tenant_id=self.B.id, root=True,
                                         **self.subproject_defualt_quota)
        self.assertDictMatch(expected, result)

    def test_show_not_authorized(self):
        qso = quota.QuotaSetOperation('bad_project', 'bad_project')
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = 'bad_project'
        self.ctx.is_admin = False
        self.assertRaises(exceptions.NotAuthorized,
                          qso.show_detail_quota,
                          self.ctx)

    def test_subproject_show_not_authorized_1(self):
        qso = quota.QuotaSetOperation(self.C.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.id
        self.ctx.is_admin = False
        self.assertRaises(exceptions.HTTPForbiddenError,
                          qso.show_detail_quota,
                          self.ctx)

    def test_subproject_show_not_authorized_2(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.B.id
        self.ctx.is_admin = False
        self.assertRaises(exceptions.HTTPForbiddenError,
                          qso.show_detail_quota,
                          self.ctx)

    def test_update(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

    def test_update_subproject(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # Update the quota of B to be equal to its parent quota
        qso.update_hierarchy(self.B.id)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_subproject_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # Update the quota of B to be equal to its parent quota
        # three times should be successful, the quota will not be
        # allocated to 'allocated' value of parent project
        for i in range(0, 3):
            result = qso.update(self.ctx, **updated)
            self.assertDictMatch(expected, result)

        # Try to update the quota of C, it will not be allowed, since the
        # project A doesn't have free quota available.
        qso.update_hierarchy(self.C.id)
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **updated)

        # Successfully update the quota of D by A, D is child of B.
        qso.update_hierarchy(self.D.id)
        quota_d = dict(instances=3, volumes=3, backups=3,
                       gigabytes=1000, snapshots=7)
        updated_d = _make_body(tenant_id=None, root=True, **quota_d)
        expected_quota_d = copy.copy(self.invalid_quota)
        for k in quota_d:
            expected_quota_d[k] = quota_d[k]
        expected_d = _make_body(tenant_id=None, root=True, **expected_quota_d)
        result_d = qso.update(self.ctx, **updated_d)
        self.assertDictMatch(expected_d, result_d)

        # An admin of B can also update the quota of D, since D is its an
        # immediate child.
        qso.update_hierarchy(self.D.id)
        self.ctx.project_id = self.B.id
        quota_d = dict(instances=5, volumes=5, backups=5,
                       gigabytes=2000, snapshots=6)
        updated_d = _make_body(tenant_id=None, root=True, **quota_d)
        expected_quota_d = copy.copy(self.invalid_quota)
        for k in quota_d:
            expected_quota_d[k] = quota_d[k]
        expected_d = _make_body(tenant_id=None, root=True, **expected_quota_d)
        result_d = qso.update(self.ctx, **updated_d)
        self.assertDictMatch(expected_d, result_d)

    def test_update_subproject_of_non_root(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # Update the quota of B to be equal to its parent quota
        qso.update_hierarchy(self.B.id)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_subproject_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # failed to update the quota of B by B.
        self.ctx.project_id = self.B.id
        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated)

        # failed to update the quota of E by B, E is child of D.
        qso.update_hierarchy(self.E.id)
        quota_e = dict(instances=3, volumes=3, backups=3, gigabytes=1000,
                       snapshots=7)
        updated_e = _make_body(tenant_id=None, root=True, **quota_e)
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated_e)

        # failed to show quota of E by B, E is child of D
        self.assertRaises(exceptions.HTTPForbiddenError,
                          qso.show_detail_quota,
                          self.ctx)

        # An admin of D can update the quota of E, since E is its an
        # immediate child.
        qso.update_hierarchy(self.E.id)
        self.ctx.project_id = self.D.id
        quota_e = dict(instances=5, volumes=5, backups=5, gigabytes=300,
                       snapshots=6)
        updated_e = _make_body(tenant_id=None, root=True, **quota_e)
        expected_quota_e = copy.copy(self.invalid_quota)
        for k in quota_e:
            expected_quota_e[k] = quota_e[k]
        expected_e = _make_body(tenant_id=None, root=True, **expected_quota_e)
        result_e = qso.update(self.ctx, **updated_e)
        self.assertDictMatch(expected_e, result_e)

    def test_update_subproject_not_in_hierarchy(self):

        # Create another project hierarchy
        E = self.FakeProject(id=uuidutils.generate_uuid(), parent_id=None)
        F = self.FakeProject(id=uuidutils.generate_uuid(), parent_id=E.id)
        E.subtree = {F.id: F.subtree}
        self.project_by_id[E.id] = E
        self.project_by_id[F.id] = F

        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # Update the quota of B to be equal to its parent quota
        qso.update_hierarchy(F.id)
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated)

    def test_update_subproject_not_in_hierarchy2(self):
        qso = quota.QuotaSetOperation(self.F.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)

        # Update the quota of F is not allowed
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated)

        self.ctx.project_id = self.B.id
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated)

        # only admin is allowed yet
        self.ctx.is_admin = False
        self.ctx.project_id = self.G.id
        self.assertRaises(exceptions.AdminRequired, qso.update,
                          self.ctx, **updated)

        self.ctx.is_admin = True
        self.ctx.project_id = self.G.id
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        self.ctx.is_admin = True
        self.ctx.project_id = self.F.id
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        self.ctx.is_admin = False
        self.ctx.project_id = self.F.id
        self.assertRaises(exceptions.AdminRequired, qso.update,
                          self.ctx, **updated)

    def test_update_subproject_with_not_root_context_project(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        # Try to update the quota of A, it will not be allowed, since the
        # project in the context (B) is not a root project.
        self.ctx.project_id = self.B.id
        self.ctx.is_admin = True
        qso.update_hierarchy(self.A.id)
        self.assertRaises(exceptions.HTTPForbiddenError, qso.update,
                          self.ctx, **updated)

    def test_update_subproject_quota_when_parent_has_default_quotas(self):
        qso = quota.QuotaSetOperation(self.B.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        # Update the quota of B to be equal to its parent quota
        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota2)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_subproject_expected_result2)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

    def test_update_limit_with_admin(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        body = {'quota_set': {'volumes': 10}}
        result = qso.update(self.ctx, **body)
        self.assertEqual(10, result['quota_set']['volumes'])

        # only admin is allowed yet
        self.ctx.is_admin = False
        self.assertRaises(exceptions.AdminRequired, qso.update,
                          self.ctx, **body)

    def test_update_wrong_validation(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        orig_updated = _make_body(tenant_id=None, root=True,
                                  **self.test_class_quota)
        orig_expected = _make_body(tenant_id=None, root=True,
                                   **self.test_class_expected_result)
        orig_result = qso.update(self.ctx, **orig_updated)
        self.assertDictMatch(orig_expected, orig_result)

        body = {'quota_set': {'bad': 'bad'}}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'quota_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'quota_set': {'gigabytes': None}}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = _make_body(gigabytes=2000, snapshots=15,
                          volumes="should_be_int",
                          backups=5, tenant_id=None)
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'quota_set': {'gigabytes': -1000}}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'quota_set': {'gigabytes': cons.MAX_INT + 1}}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'fake_quota_set': {'gigabytes': 100}}
        self.assertRaises(exceptions.InvalidInput, qso.update,
                          self.ctx, **body)

        body = {}
        self.assertRaises(exceptions.InvalidInput, qso.update,
                          self.ctx, **body)

        new_quota = qso.show_detail_quota(self.ctx)
        new_quota['quota_set'].pop('id')
        self.assertDictMatch(orig_result, new_quota)

    def _commit_quota_reservation(self, _id):
        # Create simple quota and quota usage.
        res = self._quota_reserve(self.ctx, _id)
        db_api.reservation_commit(self.ctx, res, _id)
        expected = {'project_id': _id,
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         db_api.quota_usage_get_all_by_project(
                             self.ctx, _id))

    def test_update_lower_than_existing_resources_when_skip_false(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        self._commit_quota_reservation(self.A.id)
        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'false'}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

        body = {'quota_set': {'gigabytes': 1},
                'skip_validation': 'false'}
        self.assertRaises(exceptions.ValidationError, qso.update,
                          self.ctx, **body)

    def test_update_lower_than_existing_resources_when_skip_true(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id
        self._commit_quota_reservation(self.A.id)

        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'true'}
        result = qso.update(self.ctx, **body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_update_lower_than_existing_resources_without_skip_argument(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id
        self._commit_quota_reservation(self.A.id)

        body = {'quota_set': {'volumes': 0}}
        result = qso.update(self.ctx, **body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_delete(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        result_show = qso.show_detail_quota(self.ctx)

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        qso.delete(self.ctx)

        result_show_after = qso.show_detail_quota(self.ctx)
        self.assertDictMatch(result_show, result_show_after)

    def test_delete_subproject_not_in_hierarchy2(self):
        qso = quota.QuotaSetOperation(self.F.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        # delete the quota of F is not allowed
        self.assertRaises(exceptions.HTTPForbiddenError, qso.delete,
                          self.ctx)

        self.ctx.project_id = self.B.id
        self.assertRaises(exceptions.HTTPForbiddenError, qso.delete,
                          self.ctx)

        # only admin is allowed yet
        self.ctx.project_id = self.G.id
        self.ctx.is_admin = False
        self.assertRaises(exceptions.AdminRequired, qso.delete,
                          self.ctx)

        self.ctx.project_id = self.G.id
        self.ctx.is_admin = True
        result_show = qso.show_detail_quota(self.ctx)
        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        self.ctx.is_admin = True
        self.ctx.project_id = self.G.id
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        qso.delete(self.ctx)
        result_show_after = qso.show_detail_quota(self.ctx)
        self.assertDictMatch(result_show, result_show_after)

        self.ctx.project_id = self.F.id
        self.ctx.is_admin = True
        qso.delete(self.ctx)
        result_show_after = qso.show_detail_quota(self.ctx)
        self.assertDictMatch(result_show, result_show_after)

        self.ctx.project_id = self.F.id
        self.ctx.is_admin = False
        self.assertRaises(exceptions.AdminRequired, qso.delete,
                          self.ctx)

    def test_subproject_delete(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        updated = _make_body(tenant_id=None, root=True,
                             **self.test_class_quota)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_class_expected_result)
        qso.update(self.ctx, **updated)
        result_show = qso.show_detail_quota(self.ctx, show_usage=True)

        # Update the quota of B to be equal to its parent quota
        qso.update_hierarchy(self.B.id)
        expected = _make_body(tenant_id=None, root=True,
                              **self.test_subproject_expected_result)
        result = qso.update(self.ctx, **updated)
        self.assertDictMatch(expected, result)

        qso.delete(self.ctx)
        qso.update_hierarchy(self.A.id)
        result_show_after = qso.show_detail_quota(self.ctx, show_usage=True)
        self.assertDictMatch(result_show, result_show_after)

    def test_subproject_delete_not_considering_default_quotas(self):
        """Test delete subprojects' quotas won't consider default quotas.

        Test plan:
        - Update the volume quotas of project A
        - Update the volume quotas of project B
        - Delete the quotas of project B

        Resources with default quotas aren't expected to be considered when
        updating the allocated values of the parent project. Thus, the delete
        operation should succeed.
        """
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        body = {'quota_set': {'volumes': 5}}
        result = qso.update(self.ctx, **body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

        body = {'quota_set': {'volumes': 2}}
        qso.update_hierarchy(self.B.id)
        result = qso.update(self.ctx, **body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])
        qso.delete(self.ctx)

    def test_delete_with_allocated_quota_different_from_zero(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        body = _make_body(gigabytes=2000, snapshots=15,
                          volumes=5, backups=5,
                          backup_gigabytes=1000, tenant_id=None)
        qso.update(self.ctx, **body)

        # Set usage param to True in order to see get allocated values.
        result_show = qso.show_detail_quota(self.ctx, show_usage=True)

        qso.update_hierarchy(self.B.id)
        qso.update(self.ctx, **body)
        qso.delete(self.ctx)

        qso.update_hierarchy(self.A.id)
        result_show_after = qso.show_detail_quota(self.ctx, show_usage=True)
        self.assertDictMatch(result_show, result_show_after)

    def test_delete_no_admin(self):
        qso = quota.QuotaSetOperation(self.A.id)
        qso._get_project = mock.Mock()
        qso._get_project.side_effect = self._get_project
        self.ctx.project_id = self.A.id

        # only admin is allowed yet
        self.ctx.is_admin = False
        self.assertRaises(exceptions.AdminRequired, qso.delete, self.ctx)
