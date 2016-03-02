# Copyright 2015 Huawei Technologies Co., Ltd.
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


import os
import random
import sys


from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import service as srv

from tricircle.common.i18n import _
from tricircle.common.i18n import _LE
from tricircle.common.i18n import _LI

from tricircle.common import baserpc
from tricircle.common import context
from tricircle.common import rpc
from tricircle.common import version


from tricircle.common.serializer import TricircleSerializer as Serializer

from tricircle.common import topics
from tricircle.xjob.xmanager import XManager


_TIMER_INTERVAL = 30
_TIMER_INTERVAL_MAX = 60

common_opts = [
    cfg.StrOpt('host', default='tricircle.xhost',
               help=_("The host name for RPC server")),
    cfg.IntOpt('workers', default=1,
               help=_("Number of workers")),
    cfg.IntOpt('worker_handle_timeout', default=1800,
               help=_("Timeout for worker's one turn of processing, in"
                      " seconds")),
    cfg.IntOpt('job_run_expire', default=60,
               help=_("Running job is considered expires after this time, in"
                      " seconds")),
    cfg.FloatOpt('worker_sleep_time', default=0.1,
                 help=_("Seconds a worker sleeps after one run in a loop"))
]

service_opts = [
    cfg.IntOpt('report_interval',
               default=10,
               help='Seconds between nodes reporting state to datastore'),
    cfg.BoolOpt('periodic_enable',
                default=True,
                help='Enable periodic tasks'),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               help='Range of seconds to randomly delay when starting the'
                    ' periodic task scheduler to reduce stampeding.'
                    ' (Disable by setting to 0)'),
    ]

CONF = cfg.CONF
CONF.register_opts(service_opts)

LOG = logging.getLogger(__name__)


class XService(srv.Service):

    """class Service

    Service object for binaries running on hosts.
    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    its state to the database services table.
    """

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_enable=None, periodic_fuzzy_delay=None,
                 periodic_interval_max=None, serializer=None,
                 *args, **kwargs):
        super(XService, self).__init__()
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager = manager
        self.rpc_server = None
        self.report_interval = report_interval
        self.periodic_enable = periodic_enable
        self.periodic_fuzzy_delay = periodic_fuzzy_delay
        self.interval_max = periodic_interval_max
        self.serializer = serializer
        self.saved_args, self.saved_kwargs = args, kwargs

    def start(self):
        ver_str = version.version_info
        LOG.info(_LI('Starting %(topic)s node (version %(version)s)'),
                 {'topic': self.topic, 'version': ver_str})

        self.basic_config_check()
        self.manager.init_host()
        self.manager.pre_start_hook()

        LOG.debug(_("Creating RPC server for service %s"), self.topic)

        target = messaging.Target(topic=self.topic, server=self.host)

        endpoints = [
            self.manager,
            baserpc.BaseServerRPCAPI(self.manager.service_name)
        ]
        endpoints.extend(self.manager.additional_endpoints)

        self.rpc_server = rpc.get_server(target, endpoints, self.serializer)

        self.rpc_server.start()

        self.manager.post_start_hook()

        if self.periodic_enable:
            if self.periodic_fuzzy_delay:
                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
            else:
                initial_delay = None

            self.tg.add_dynamic_timer(self.periodic_tasks,
                                      initial_delay=initial_delay,
                                      periodic_interval_max=self.interval_max)

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_enable=None,
               periodic_fuzzy_delay=None, periodic_interval_max=None,
               serializer=None,):

        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_enable: defaults to CONF.periodic_enable
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay
        :param periodic_interval_max: if set, the max time to wait between runs
        """

        if not host:
            host = CONF.host
        if not binary:
            binary = os.path.basename(sys.argv[0])
        if not topic:
            topic = binary.rpartition('tricircle-')[2]
        if not manager:
            manager_cls = ('%s_manager' %
                           binary.rpartition('tricircle-')[2])
            manager = CONF.get(manager_cls, None)
        if report_interval is None:
            report_interval = CONF.report_interval
        if periodic_enable is None:
            periodic_enable = CONF.periodic_enable
        if periodic_fuzzy_delay is None:
            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay

        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_enable=periodic_enable,
                          periodic_fuzzy_delay=periodic_fuzzy_delay,
                          periodic_interval_max=periodic_interval_max,
                          serializer=serializer)

        return service_obj

    def kill(self):
        self.stop()

    def stop(self):
        try:
            self.rpc_server.stop()
        except Exception:
            pass

        try:
            self.manager.cleanup_host()
        except Exception:
            LOG.exception(_LE('Service error occurred during cleanup_host'))
            pass

        super(XService, self).stop()

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        return self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)

    def basic_config_check(self):
        """Perform basic config checks before starting processing."""
        # Make sure the tempdir exists and is writable
        # try:
        #    with utils.tempdir():
        #        pass
        # except Exception as e:
        #    LOG.error(_LE('Temporary directory is invalid: %s'), e)
        #    sys.exit(1)


def create_service():

    LOG.debug(_('create xjob server'))

    xmanager = XManager()
    xservice = XService(
        host=CONF.host,
        binary="xjob",
        topic=topics.TOPIC_XJOB,
        manager=xmanager,
        periodic_enable=True,
        report_interval=_TIMER_INTERVAL,
        periodic_interval_max=_TIMER_INTERVAL_MAX,
        serializer=Serializer()
    )

    xservice.start()

    return xservice


_launcher = None


def serve(xservice, workers=1):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = srv.launch(CONF, xservice, workers=workers)


def wait():
    _launcher.wait()
