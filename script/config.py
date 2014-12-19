# Copyright (c) 2014 OpenStack Foundation.
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
#
# @author: Jia Dong, HuaWei

import ConfigParser
import os
import sys

DEFAULT_CFG_FILE_PATHS = {
    'nova': {'nova': '/etc/nova/nova.conf'},
    'glance': {
        'api': '/etc/glance/glance-api.conf',
        'registry': '/etc/glance/glance-registry.conf',
        'sync': '/etc/glance/glance-sync.conf'
    },
    'cinder': {'cinder': '/etc/cinder/cinder.conf'}
}


class TricircleConfig(object):
    CFG_FILE = "tricircle.cfg"

    def __init__(self):
        self.cf = ConfigParser.ConfigParser()
        self.cf.read(self.CFG_FILE)

    def update_options(self, module_name, module_cfg_file_paths=None):
        """
        module_name like 'nova', 'glance-api' etc.
        """
        cfg_mapping = module_cfg_file_paths if module_cfg_file_paths \
                            else DEFAULT_CFG_FILE_PATHS.get(module_name, None)

        if not cfg_mapping:
            print 'Abort, no cfg_file for module %s' \
                  ' has configured.' % module_name
            return
        options = {}
        for cfg_mod in cfg_mapping:

            sub_mod = cfg_mod
            sub_file_path = cfg_mapping[sub_mod]
            sub_module_name = module_name + '-' + sub_mod if module_name != sub_mod \
                else module_name
            options[sub_module_name] = {}

            sections = filter(lambda x: x.startswith(sub_module_name),
                              self.cf.sections())
            for section in sections:
                module_section = section[len(sub_module_name):] or 'DEFAULT'
                module_section = module_section[1:] \
                    if module_section[0] == '_' else module_section

                _options = {}
                module_options = self.cf.items(section, raw=True)
                for pair in module_options:
                    _options[pair[0]] = pair[1]
                options[sub_module_name][module_section] = _options

            if options[sub_module_name]:
                print '>>> Start updating %s config: ' % sub_module_name
                TricircleConfig._replace_cfg(options[sub_module_name], sub_file_path)
                print 'Finish updating %s config. <<< ' % sub_module_name

    @staticmethod
    def _replace_cfg(options, file_path):
        if not (file_path and os.path.isfile(file_path)):
            print 'file_path %s not exists or not a file' % file_path
        mod_cf = ConfigParser.SafeConfigParser()
        mod_cf.read(file_path)
        sections = mod_cf.sections()
        for _section in options:
            if _section not in sections and _section != 'DEFAULT':
                mod_cf.add_section(_section)

            for option in options[_section]:
                mod_cf.set(_section, option, options[_section][option])

        mod_cf.write(open(file_path, 'w'))
        print 'Done'


def main():
    module = sys.argv[1]
    print module
    if not module:
        print 'The input parameters not exists.'
    try:
        config = TricircleConfig()
        if module.upper() == 'ALL':
            for mod in ('nova', 'glance', 'cinder', 'neutron'):
                config.update_options(mod)
        else:
            config.update_options(module)
    except Exception as e:
        print e
        print 'Update tricircle %s config options fails' % module

if __name__ == '__main__':
    main()