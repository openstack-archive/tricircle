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

"""
A simple filesystem-backed store
"""

import logging
import os
import sys

from oslo.config import cfg
import pxssh
import pexpect

from glance.common import exception
import glance.sync.store.driver
import glance.sync.store.location
from glance.sync.store.location import Location
from glance.sync import utils as s_utils

LOG = logging.getLogger(__name__)


CONF = cfg.CONF
CONF.import_opt('scp_copy_timeout', 'glance.common.config', group='sync')


def _login_ssh(host, passwd):
    child_ssh = pexpect.spawn('ssh -p 22 %s' % (host))
    child_ssh.logfile = sys.stdout
    login_flag = True
    while True:
        ssh_index = child_ssh.expect(['.yes/no.', '.assword:.',
                                      pexpect.TIMEOUT])
        if ssh_index == 0:
            child_ssh.sendline('yes')
        elif ssh_index == 1:
            child_ssh.sendline(passwd)
            break
        else:
            login_flag = False
            break
    if not login_flag:
        return None

    return child_ssh


def _get_ssh(hostname, username, password):
    s = pxssh.pxssh()
    s.login(hostname, username, password, original_prompt='[#$>]')
    s.logfile = sys.stdout
    return s


class LocationCreator(glance.sync.store.location.LocationCreator):

    def __init__(self):
        self.scheme = 'file'

    def create(self, **kwargs):
        image_id = kwargs.get('image_id')
        image_file_name = kwargs.get('image_name', None) or image_id
        datadir = kwargs.get('datadir')
        path = os.path.join(datadir, str(image_file_name))
        login_user = kwargs.get('login_user')
        login_password = kwargs.get('login_password')
        host = kwargs.get('host')
        store_specs = {'scheme': self.scheme, 'path': path, 'host': host,
                       'login_user': login_user,
                       'login_password': login_password}
        return Location(self.scheme, StoreLocation, image_id=image_id,
                        store_specs=store_specs)


class StoreLocation(glance.sync.store.location.StoreLocation):

    def process_specs(self):
        self.scheme = self.specs.get('scheme', 'file')
        self.path = self.specs.get('path')
        self.host = self.specs.get('host')
        self.login_user = self.specs.get('login_user')
        self.login_password = self.specs.get('login_password')


class Store(glance.sync.store.driver.Store):

    def copy_to(self, from_location, to_location, candidate_path=None):

        from_store_loc = from_location.store_location
        to_store_loc = to_location.store_location

        if from_store_loc.host == to_store_loc.host and \
                from_store_loc.path == to_store_loc.path:

            LOG.info(_('The from_loc is same to to_loc, no need to copy. the '
                       'host:path is %s:%s') % (from_store_loc.host,
                                                from_store_loc.path))
            return 'file://%s' % to_store_loc.path

        from_host = r"""{username}@{host}""".format(
            username=from_store_loc.login_user,
            host=from_store_loc.host)

        to_host = r"""{username}@{host}""".format(
            username=to_store_loc.login_user,
            host=to_store_loc.host)

        to_path = r"""{to_host}:{path}""".format(to_host=to_host,
                                                 path=to_store_loc.path)

        copy_path = from_store_loc.path

        try:
            from_ssh = _get_ssh(from_store_loc.host,
                                from_store_loc.login_user,
                                from_store_loc.login_password)
        except Exception:
            raise exception.SyncStoreCopyError(reason="ssh login failed.")

        from_ssh.sendline('ls %s' % copy_path)
        from_ssh.prompt()
        if 'cannot access' in from_ssh.before or \
                'No such file' in from_ssh.before:
            if candidate_path:
                from_ssh.sendline('ls %s' % candidate_path)
                from_ssh.prompt()
                if 'cannot access' not in from_ssh.before and \
                   'No such file' not in from_ssh.before:
                    copy_path = candidate_path
            else:
                msg = _("the image path for copy to is not exists, file copy"
                        "failed: path is %s" % (copy_path))
                raise exception.SyncStoreCopyError(reason=msg)

        from_ssh.sendline('scp -P 22 %s %s' % (copy_path, to_path))
        while True:
            scp_index = from_ssh.expect(['.yes/no.', '.assword:.',
                                         pexpect.TIMEOUT])
            if scp_index == 0:
                from_ssh.sendline('yes')
                from_ssh.prompt()
            elif scp_index == 1:
                from_ssh.sendline(to_store_loc.login_password)
                from_ssh.prompt(timeout=CONF.sync.scp_copy_timeout)
                break
            else:
                msg = _("scp commond execute failed, with copy_path %s and "
                        "to_path %s" % (copy_path, to_path))
                raise exception.SyncStoreCopyError(reason=msg)
                break

        if from_ssh:
            from_ssh.logout()

        return 'file://%s' % to_store_loc.path
