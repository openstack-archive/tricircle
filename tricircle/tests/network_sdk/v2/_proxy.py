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

from openstack.network.v2 import _proxy

import tricircle.tests.network_sdk.v2.flow_classifier as _fc
import tricircle.tests.network_sdk.v2.port_chain as _pc
import tricircle.tests.network_sdk.v2.port_pair as _pp
import tricircle.tests.network_sdk.v2.port_pair_group as _ppg
import tricircle.tests.network_sdk.v2.trunk as _trunk


class Proxy(_proxy.Proxy):
    # trunk
    def create_trunk(self, **attrs):
        return self._create(_trunk.Trunk, **attrs)

    def delete_trunk(self, trunk, ignore_missing=True):
        self._delete(_trunk.Trunk, trunk, ignore_missing=ignore_missing)

    def update_trunk(self, trunk, **attrs):
        return self._update(_trunk.Trunk, trunk, **attrs)

    def trunks(self, **query):
        return self._list(_trunk.Trunk, pagination=False, **query)

    def add_subports(self, trunk, subports=[]):
        trunk = self._get_resource(_trunk.Trunk, trunk)
        body = {'sub_ports': subports}
        return trunk.add_subports(self._session, **body)

    def remove_subports(self, trunk, subports=[]):
        trunk = self._get_resource(_trunk.Trunk, trunk)
        body = {'sub_ports': subports}
        return trunk.remove_subports(self._session, **body)

    # port pair
    def create_port_pair(self, **attrs):
        return self._create(_pp.PortPair, **attrs)

    def delete_port_pair(self, pp, ignore_missing=True):
        self._delete(_pp.PortPair, pp, ignore_missing=ignore_missing)

    def update_port_pair(self, pp, **attrs):
        return self._update(_pp.PortPair, pp, **attrs)

    def port_pairs(self, **query):
        return self._list(_pp.PortPair, pagination=False, **query)

    # port pair group
    def create_port_pair_group(self, **attrs):
        return self._create(_ppg.PortPairGroup, **attrs)

    def delete_port_pair_group(self, ppg, ignore_missing=True):
        self._delete(_ppg.PortPairGroup, ppg, ignore_missing=ignore_missing)

    def update_port_pair_group(self, ppg, **attrs):
        return self._update(_ppg.PortPairGroup, ppg, **attrs)

    def port_pair_groups(self, **query):
        return self._list(_ppg.PortPairGroup, pagination=False, **query)

    # port chain
    def create_port_chain(self, **attrs):
        return self._create(_pc.PortChain, **attrs)

    def delete_port_chain(self, pc, ignore_missing=True):
        self._delete(_pc.PortChain, pc, ignore_missing=ignore_missing)

    def update_port_chain(self, pc, **attrs):
        return self._update(_pc.PortChain, pc, **attrs)

    def port_chains(self, **query):
        return self._list(_pc.PortChain, pagination=False, **query)

    # flow classifier
    def create_flow_classifier(self, **attrs):
        return self._create(_fc.FlowClassifier, **attrs)

    def delete_flow_classifier(self, fc, ignore_missing=True):
        self._delete(_fc.FlowClassifier, fc, ignore_missing=ignore_missing)

    def update_flow_classifier(self, fc, **attrs):
        return self._update(_fc.FlowClassifier, fc, **attrs)

    def flow_classifiers(self, **query):
        return self._list(_fc.FlowClassifier, pagination=False, **query)
