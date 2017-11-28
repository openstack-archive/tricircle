# Copyright 2017 Hunan University Co., Ltd.
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

from neutron_lib.api.definitions import portbindings
from neutron_lib import constants
from neutron_lib.db import constants as db_constants
from neutron_lib.services.qos import base
from neutron_lib.services.qos import constants as qos_consts

from oslo_log import log as logging

from tricircle.common import constants as t_constants
from tricircle.common import context
from tricircle.common import xrpcapi
from tricircle.db import api as db_api

LOG = logging.getLogger(__name__)

DRIVER = None

SUPPORTED_RULES = {
    qos_consts.RULE_TYPE_BANDWIDTH_LIMIT: {
        qos_consts.MAX_KBPS: {
            'type:range': [0, db_constants.DB_INTEGER_MAX_VALUE]},
        qos_consts.MAX_BURST: {
            'type:range': [0, db_constants.DB_INTEGER_MAX_VALUE]},
        qos_consts.DIRECTION: {
            'type:values': constants.VALID_DIRECTIONS}
    },
    qos_consts.RULE_TYPE_DSCP_MARKING: {
        qos_consts.DSCP_MARK: {'type:values': constants.VALID_DSCP_MARKS}
    },
    qos_consts.RULE_TYPE_MINIMUM_BANDWIDTH: {
        qos_consts.MIN_KBPS: {
            'type:range': [0, db_constants.DB_INTEGER_MAX_VALUE]},
        qos_consts.DIRECTION: {'type:values': [constants.EGRESS_DIRECTION]}
    }
}

VIF_TYPES = [portbindings.VIF_TYPE_OVS,
             portbindings.VIF_TYPE_VHOST_USER,
             portbindings.VIF_TYPE_UNBOUND]


class TricircleQoSDriver(base.DriverBase):
    def __init__(self, name, vif_types, vnic_types,
                 supported_rules,
                 requires_rpc_notifications):
        super(TricircleQoSDriver, self).__init__(name, vif_types, vnic_types,
                                                 supported_rules,
                                                 requires_rpc_notifications)
        self.xjob_handler = xrpcapi.XJobAPI()

    @staticmethod
    def create():
        return TricircleQoSDriver(
            name='tricircle',
            vif_types=VIF_TYPES,
            vnic_types=portbindings.VNIC_TYPES,
            supported_rules=SUPPORTED_RULES,
            requires_rpc_notifications=False)

    def create_policy(self, q_context, policy):
        """Create policy invocation.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being created, which will have no
                      rules.
        """
        pass

    def create_policy_precommit(self, q_context, policy):
        """Create policy precommit.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being created, which will have no
                      rules.
        """
        pass

    def update_policy(self, q_context, policy):
        """Update policy invocation.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being updated.
        """
        pass

    def update_policy_precommit(self, q_context, policy):
        """Update policy precommit.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being updated.
        """
        t_context = context.get_context_from_neutron_context(q_context)
        policy_id = policy['id']
        mappings = db_api.get_bottom_mappings_by_top_id(
            t_context, policy_id, t_constants.RT_QOS)

        if mappings:
            self.xjob_handler.update_qos_policy(
                t_context, t_context.project_id, policy_id,
                t_constants.POD_NOT_SPECIFIED)
            self.xjob_handler.sync_qos_policy_rules(
                t_context, t_context.project_id, policy_id)

    def delete_policy(self, q_context, policy):
        """Delete policy invocation.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being deleted
        """

    def delete_policy_precommit(self, q_context, policy):
        """Delete policy precommit.

        :param q_context: current running context information
        :param policy: a QoSPolicy object being deleted
        """
        t_context = context.get_context_from_neutron_context(q_context)
        policy_id = policy['id']
        self.xjob_handler.delete_qos_policy(
            t_context, t_context.project_id, policy_id,
            t_constants.POD_NOT_SPECIFIED)


def register():
    """Register the driver."""
    global DRIVER
    if not DRIVER:
        DRIVER = TricircleQoSDriver.create()
    LOG.debug('Tricircle QoS driver registered')
