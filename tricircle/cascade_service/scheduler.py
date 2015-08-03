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

from socket import gethostname

from oslo_config import cfg

from nova import exception
from nova import objects
from nova.scheduler import driver
from nova.scheduler.manager import SchedulerManager

from tricircle.common.utils import get_import_path

from tricircle.cascade_service import site_manager
from tricircle.cascade_service.compute import NovaService

cfg.CONF.import_opt('scheduler_topic', 'nova.scheduler.rpcapi')

_REPORT_INTERVAL = 30
_REPORT_INTERVAL_MAX = 60


def _get_import_path(klass):
    return "%s.%s" % (klass.__module__, klass.__name__)


def create_server():
    return NovaService(
        host=gethostname(),
        binary="nova-scheduler",
        topic="scheduler",  # TODO(saggi): get from conf
        db_allowed=False,
        periodic_enable=True,
        report_interval=_REPORT_INTERVAL,
        periodic_interval_max=_REPORT_INTERVAL_MAX,
        manager=get_import_path(SchedulerManager),
        scheduler_driver=get_import_path(TricircleSchedulerDriver),
    )


class _AvailabilityZone(object):
    def __init__(self, name, host_manager):
        self.name = name
        self._host_manager = host_manager
        self._site_manager = site_manager.get_instance()

    @property
    def host_aggregates(self):
        for aggregate in self._host_manager.aggregates:
            if aggregate.metadata[u'availability_zone'] == self.name:
                yield aggregate

    @property
    def member_hosts(self):
        for aggregate in self.host_aggregates:
            for host in aggregate.hosts:
                yield host

    @property
    def valid_sites(self):
        for host in self.member_hosts:
            yield self._site_manager.get_site(host)


class _HostManager(object):
    def __init__(self):
        self.aggregates = []

    # Required methods from OpenStack interface

    def update_aggregates(self, aggregates):
        # This is not called reliably enough to trust
        # we just reload the aggregates on every call
        pass

    def delete_aggregate(self, aggregate):
        # This is not called reliably enough to trust
        # we just reload the aggregates on every call
        pass

    def update_instance_info(self, context, host_name, instance_info):
        pass

    def delete_instance_info(self, context, host_name, instance_uuid):
        pass

    def sync_instance_info(self, context, host_name, instance_uuids):
        pass

    # Tricircle only methods

    def get_availability_zone(self, az_name):
        return _AvailabilityZone(az_name, self)

    def reload_aggregates(self, context):
        self.aggregates = objects.AggregateList.get_all(context)


class TricircleSchedulerDriver(driver.Scheduler):
    def __init__(self):
        super(TricircleSchedulerDriver, self).__init__()
        self.host_manager = _HostManager()
        self._site_manager = site_manager.get_instance()

    def select_destinations(self, ctxt, request_spec, filter_properties):
        self.host_manager.reload_aggregates(ctxt)
        availability_zone = self.host_manager.get_availability_zone(
            request_spec[u'instance_properties'][u'availability_zone'])

        for site in availability_zone.valid_sites:
            site.prepare_for_instance(request_spec, filter_properties)
            return [{
                'host': site.name,
                'nodename': site.get_nodes()[0].hypervisor_hostname,
                'limits': None,
            }]
        else:
            raise exception.NoValidHost(
                "No sites match requested availability zone")
