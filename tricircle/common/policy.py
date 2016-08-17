# Copyright (c) Huawei Technologies Co., Ltd.
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

"""Policy Engine For Tricircle."""

# Policy controlled API access mainly for the Tricircle Admin API. Regarding
# to Nova API-GW and Cinder API-GW, the API access control should be done at
# bottom OpenStack as far as possible if the API request will be forwarded
# to bottom OpenStack directly for further processing; only these APIs which
# only can interact with database for example flavor and volume type, because
# these APIs processing will be terminated at the Tricircle layer, so policy
# control should be done by Nova API-GW or Cinder API-GW. No work is required
# to do in the Tricircle Neutron Plugin for Neutron API server is there,
# Neutron API server will be responsible for policy control.


from oslo_config import cfg
import oslo_log.log as logging
from oslo_policy import policy

from tricircle.common import exceptions as t_exec
from tricircle.common.i18n import _LE

_ENFORCER = None
CONF = cfg.CONF
LOG = logging.getLogger(__name__)

default_policies = [
    policy.RuleDefault('context_is_admin', 'role:admin'),
    policy.RuleDefault('admin_api', 'is_admin:True',
                       description='cloud admin allowed'),
    policy.RuleDefault('admin_or_owner',
                       'is_admin:True or project_id:%(project_id)s',
                       description='cloud admin or project owner allowed'),
    policy.RuleDefault('default', 'rule:admin_or_owner'),
]

ADMIN_API_PODS_CREATE = 'admin_api:pods:create'
ADMIN_API_PODS_DELETE = 'admin_api:pods:delete'
ADMIN_API_PODS_SHOW = 'admin_api:pods:show'
ADMIN_API_PODS_LIST = 'admin_api:pods:list'

ADMIN_API_BINDINGS_CREATE = 'admin_api:bindings:create'
ADMIN_API_BINDINGS_DELETE = 'admin_api:bindings:delete'
ADMIN_API_BINDINGS_SHOW = 'admin_api:bindings:show'
ADMIN_API_BINDINGS_LIST = 'admin_api:bindings:list'

tricircle_admin_api_policies = [
    policy.RuleDefault(ADMIN_API_PODS_CREATE,
                       'rule:admin_api',
                       description='Create pod'),
    policy.RuleDefault(ADMIN_API_PODS_DELETE,
                       'rule:admin_api',
                       description='Delete pod'),
    policy.RuleDefault(ADMIN_API_PODS_SHOW,
                       'rule:admin_api',
                       description='Show pod detail'),
    policy.RuleDefault(ADMIN_API_PODS_LIST,
                       'rule:admin_api',
                       description='List pods'),

    policy.RuleDefault(ADMIN_API_BINDINGS_CREATE,
                       'rule:admin_api',
                       description='Create pod binding'),
    policy.RuleDefault(ADMIN_API_BINDINGS_DELETE,
                       'rule:admin_api',
                       description='Delete pod binding'),
    policy.RuleDefault(ADMIN_API_BINDINGS_SHOW,
                       'rule:admin_api',
                       description='Show pod binding detail'),
    policy.RuleDefault(ADMIN_API_BINDINGS_LIST,
                       'rule:admin_api',
                       description='List pod bindings'),
]


def list_policies():
    policies = (default_policies +
                tricircle_admin_api_policies)
    return policies


# we can get a policy enforcer by this init.
# oslo policy supports change policy rule dynamically.
# at present, policy.enforce will reload the policy rules when it checks
# the policy file has been touched.
def init(policy_file=None, rules=None,
         default_rule=None, use_conf=True, overwrite=True):
    """Init an Enforcer class.

        :param policy_file: Custom policy file to use, if none is
                            specified, ``conf.policy_file`` will be
                            used.
        :param rules: Default dictionary / Rules to use. It will be
                      considered just in the first instantiation. If
                      :meth:`load_rules` with ``force_reload=True``,
                      :meth:`clear` or :meth:`set_rules` with
                      ``overwrite=True`` is called this will be overwritten.
        :param default_rule: Default rule to use, conf.default_rule will
                             be used if none is specified.
        :param use_conf: Whether to load rules from cache or config file.
        :param overwrite: Whether to overwrite existing rules when reload rules
                          from config file.
    """
    global _ENFORCER
    if not _ENFORCER:
        # http://docs.openstack.org/developer/oslo.policy/usage.html
        _ENFORCER = policy.Enforcer(CONF,
                                    policy_file=policy_file,
                                    rules=rules,
                                    default_rule=default_rule,
                                    use_conf=use_conf,
                                    overwrite=overwrite)
        _ENFORCER.register_defaults(list_policies())
    return _ENFORCER


def set_rules(rules, overwrite=True, use_conf=False):
    """Set rules based on the provided dict of rules.

       :param rules: New rules to use. It should be an instance of dict.
       :param overwrite: Whether to overwrite current rules or update them
                         with the new rules.
       :param use_conf: Whether to reload rules from config file.
    """
    init(use_conf=False)
    _ENFORCER.set_rules(rules, overwrite, use_conf)


def populate_default_rules():
    reset()
    init(use_conf=False)
    dict_rules = {}
    for default in list_policies():
        dict_rules[default.name] = default.check_str
    rules = policy.Rules.from_dict(dict_rules)
    set_rules(rules)


def reset():
    global _ENFORCER
    if _ENFORCER:
        _ENFORCER.clear()
        _ENFORCER = None


def enforce(context, rule=None, target=None, *args, **kwargs):
    """Check authorization of a rule against the target and credentials.

        :param dict context: As much information about the user performing the
                             action as possible.
        :param rule: The rule to evaluate.
        :param dict target: As much information about the object being operated
                            on as possible.
        :return: ``True`` if the policy allows the action.
                 ``False`` if the policy does not allow the action.
    """
    enforcer = init()
    credentials = context.to_dict()
    if target is None:
        target = {'project_id': context.project_id,
                  'user_id': context.user_id}

    exc = t_exec.PolicyNotAuthorized

    try:
        result = enforcer.enforce(rule, target, credentials,
                                  do_raise=True, exc=exc, *args, **kwargs)

    except t_exec.PolicyNotAuthorized as e:
        result = False
        LOG.exception(_LE("%(msg)s, %(rule)s, %(target)s"),
                      {'msg': str(e), 'rule': rule, 'target': target})
    return result
