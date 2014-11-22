import logging
import sys

from oslo.config import cfg
import pxssh
import pexpect

from nova.openstack.common.gettextutils import _

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

sync_opt = [
    cfg.IntOpt('scp_copy_timeout', default=3600,
               help=_('when snapshot, max wait (second)time for snapshot '
                      'status become active.'),
               deprecated_opts=[cfg.DeprecatedOpt('scp_copy_timeout',
                                                  group='DEFAULT')]),
    ]
CONF.register_opts(sync_opt, group='sync')


def _get_ssh(hostname, username, password):
    s = pxssh.pxssh()
    s.login(hostname, username, password, original_prompt='[#$>]')
    s.logfile = sys.stdout
    return s


class Store(object):

    def copy_to(self, from_location, to_location, candidate_path=None):

        from_store_loc = from_location
        to_store_loc = to_location
        LOG.debug(_('from_store_loc is: %s'), from_store_loc)

        if from_store_loc['host'] == to_store_loc['host'] and \
                        from_store_loc['path'] == to_store_loc['path']:

            LOG.info(_('The from_loc is same to to_loc, no need to copy. the '
                       'host:path is %s:%s') % (from_store_loc['host'],
                                                from_store_loc['path']))
            return 'file://%s' % to_store_loc['path']

        to_host = r"""{username}@{host}""".format(
            username=to_store_loc['login_user'],
            host=to_store_loc['host'])

        to_path = r"""{to_host}:{path}""".format(to_host=to_host,
                                                 path=to_store_loc['path'])

        copy_path = from_store_loc['path']

        try:
            from_ssh = _get_ssh(from_store_loc['host'],
                                from_store_loc['login_user'],
                                from_store_loc['login_password'])
        except Exception:
            LOG.exception("ssh login failed.")
<<<<<<< HEAD
	    raise
=======
>>>>>>> 9458b6b... Transplant tricircle to Juno

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
                LOG.exception(msg)
<<<<<<< HEAD
		raise
=======
>>>>>>> 9458b6b... Transplant tricircle to Juno

        from_ssh.sendline('scp -P 22 %s %s' % (copy_path, to_path))
        while True:
            scp_index = from_ssh.expect(['.yes/no.', '.assword:.',
                                         pexpect.TIMEOUT])
            if scp_index == 0:
                from_ssh.sendline('yes')
                from_ssh.prompt()
            elif scp_index == 1:
                from_ssh.sendline(to_store_loc['login_password'])
                from_ssh.prompt(timeout=CONF.sync.scp_copy_timeout)
                break
            else:
                msg = _("scp commond execute failed, with copy_path %s and "
                        "to_path %s" % (copy_path, to_path))
                LOG.exception(msg)
<<<<<<< HEAD
		raise
=======
>>>>>>> 9458b6b... Transplant tricircle to Juno
                break

        if from_ssh:
            from_ssh.logout()

        return 'file://%s' % to_store_loc['path']
