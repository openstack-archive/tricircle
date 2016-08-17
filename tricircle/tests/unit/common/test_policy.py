# Copyright 2016 Huawei Technologies Co., Ltd.
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

import unittest

from oslo_policy import policy as oslo_policy

from tricircle.common import context
from tricircle.common import policy


class PolicyTestCase(unittest.TestCase):
    def setUp(self):
        super(PolicyTestCase, self).setUp()
        rules = oslo_policy.Rules.from_dict({
            "true": '@',
            "example:allowed": '@',
            "example:denied": "!",
            "example:my_file": "role:admin or "
                               "project_id:%(project_id)s",
            "example:early_and_fail": "! and @",
            "example:early_or_success": "@ or !",
            "example:lowercase_admin": "role:admin or role:sysadmin",
            "example:uppercase_admin": "role:ADMIN or role:sysadmin",
        })
        policy.reset()
        policy.init()
        policy.set_rules(rules)
        self.context = context.Context(user_id='fake',
                                       tenant_id='fake',
                                       roles=['member'])
        self.target = None

    def test_enforce_nonexistent_action_throws(self):
        action = "example:non_exist"
        result = policy.enforce(self.context, action, self.target)
        self.assertEqual(result, False)

    def test_enforce_bad_action_throws(self):
        action = "example:denied"
        result = policy.enforce(self.context, action, self.target)
        self.assertEqual(result, False)

    def test_enforce_good_action(self):
        action = "example:allowed"
        result = policy.enforce(self.context, action, self.target)
        self.assertEqual(result, True)

    def test_templatized_enforcement(self):
        target_mine = {'project_id': 'fake'}
        target_not_mine = {'project_id': 'another'}
        action = "example:my_file"
        result = policy.enforce(self.context, action, target_mine)
        self.assertEqual(result, True)
        result = policy.enforce(self.context, action, target_not_mine)
        self.assertEqual(result, False)

    def test_early_AND_enforcement(self):
        action = "example:early_and_fail"
        result = policy.enforce(self.context, action, self.target)
        self.assertEqual(result, False)

    def test_early_OR_enforcement(self):
        action = "example:early_or_success"
        result = policy.enforce(self.context, action, self.target)
        self.assertEqual(result, True)

    def test_ignore_case_role_check(self):
        lowercase_action = "example:lowercase_admin"
        uppercase_action = "example:uppercase_admin"
        admin_context = context.Context(user_id='fake',
                                        tenant_id='fake',
                                        roles=['AdMiN'])
        result = policy.enforce(admin_context, lowercase_action, self.target)
        self.assertEqual(result, True)
        result = policy.enforce(admin_context, uppercase_action, self.target)
        self.assertEqual(result, True)


class DefaultPolicyTestCase(unittest.TestCase):

    def setUp(self):
        super(DefaultPolicyTestCase, self).setUp()

        self.rules = oslo_policy.Rules.from_dict({
            "default": '',
            "example:exist": "!",
        })

        self._set_rules('default')

        self.context = context.Context(user_id='fake',
                                       tenant_id='fake')

    def _set_rules(self, default_rule):
        policy.reset()
        policy.init(rules=self.rules, default_rule=default_rule,
                    use_conf=False)

    def test_policy_called(self):
        result = policy.enforce(self.context, "example:exist", {})
        self.assertEqual(result, False)

    def test_not_found_policy_calls_default(self):
        result = policy.enforce(self.context, "example:noexist", {})
        self.assertEqual(result, True)

    def test_default_not_found(self):
        self._set_rules("default_noexist")
        result = policy.enforce(self.context, "example:noexist", {})
        self.assertEqual(result, False)
