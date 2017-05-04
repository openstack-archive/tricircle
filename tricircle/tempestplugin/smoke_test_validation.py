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


import json
import sys


class ContainedString(object):
    def __init__(self, txt):
        self.content = txt

    def __eq__(self, other):
        return other.find(self.content) != -1

    def __ne__(self, other):
        return other.find(self.content) == -1


ALL_CONDITIONS = {
    '0': {'job': [{'status': 'SUCCESS'}]}
}

ANY_CONDITIONS = {
    '1': {'server': [{'Name': 'vm1', 'Status': 'ACTIVE'},
                     {'Name': 'vm3', 'Status': 'ACTIVE'}],
          'subnet': [{'Subnet': '100.0.0.0/24'}, {'Subnet': '10.0.1.0/24'},
                     {'Subnet': '10.0.4.0/24'}],
          'router_port': [{'Fixed IP Addresses': ContainedString('10.0.1')},
                          {'Fixed IP Addresses': ContainedString('100.0.0')}],
          'router': [
              {'routes': ContainedString(
                  "destination='0.0.0.0/0', gateway='100.0.0.1'")},
              {'routes': ContainedString("destination='10.0.2")}]},
    '2': {'server': [{'Name': 'vm2', 'Status': 'ACTIVE'}],
          'subnet': [{'Subnet': '100.0.0.0/24'}, {'Subnet': '10.0.1.0/24'},
                     {'Subnet': '10.0.2.0/24'}, {'Subnet': '163.3.124.0/24'}],
          'router_port': [{'Fixed IP Addresses': ContainedString('10.0.2')},
                          {'Fixed IP Addresses': ContainedString('100.0.0')}],
          'router': [
              {'routes': ContainedString(
                  "destination='0.0.0.0/0', gateway='100.0.0.1'")},
              {'routes': ContainedString("destination='10.0.1")}]}
}


def get_result_list(result):
    if isinstance(result, list):
        return result
    # not list, so result should be a dict
    if len(result) != 1:
        # dict for single resource
        return [result]
    value = list(result.values())[0]
    if isinstance(value, list):
        # dict for resource list
        return value
    else:
        return [result]


def validate_any_condition(result, condition):
    for res in get_result_list(result):
        if all(res[key] == value for (key, value) in condition.items()):
            return True
    return False


def validate_all_condition(result, condition):
    for res in get_result_list(result):
        if not all(res[key] == value for (key, value) in condition.items()):
            return False
    return True


def validate_result(result, region, res_type):
    if res_type in ANY_CONDITIONS.get(region, {}):
        for condition in ANY_CONDITIONS[region][res_type]:
            if not validate_any_condition(result, condition):
                return False
    if res_type in ALL_CONDITIONS.get(region, {}):
        for condition in ALL_CONDITIONS[region][res_type]:
            if not validate_all_condition(result, condition):
                return False
    return True


if __name__ == '__main__':
    res_type, region = sys.argv[1:]
    raw_result = ''.join([line for line in sys.stdin])
    result = json.loads(raw_result)
    passed = validate_result(result, region, res_type)
    # True is casted to 1, but 1 indicates error in shell
    sys.exit(1 - int(passed))
