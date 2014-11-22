'''
Created on 2014-8-5

@author: j00209498
'''
from oslo.db import exception as db_exc

import sqlalchemy as sa
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api

from neutron.common import exceptions as q_exc
from neutron.common import log
from neutron.common import utils
from neutron.db import model_base
from neutron.extensions import dvr as ext_dvr
from neutron import manager
from neutron.openstack.common import log as logging
from oslo.config import cfg
from sqlalchemy.orm import exc

LOG = logging.getLogger(__name__)

big2layer_vni_opts = [
    cfg.StrOpt('big2layer_vni_range',
               default="4097:20000",
               help=_('The big 2 layer vxlan vni range used for '
                      'CascadeDBMixin instances by Neutron')),
]
cfg.CONF.register_opts(big2layer_vni_opts)


class CascadeAZNetworkBinding(model_base.BASEV2):

    """Represents a v2 neutron distributed virtual router mac address."""

    __tablename__ = 'cascade_az_network_bind'

    network_id = sa.Column(sa.String(36), primary_key=True, nullable=False)
    host = sa.Column(sa.String(255), primary_key=True, nullable=False)


class CascadeRouterAZExternipMapping(model_base.BASEV2):

    """Represents a v2 neutron distributed virtual router mac address."""

    __tablename__ = 'cascade_router_az_externip_map'

    router_id = sa.Column(sa.String(36), primary_key=True, nullable=False)
    host = sa.Column(sa.String(255), primary_key=True, nullable=False)
    extern_ip = sa.Column(sa.String(64), nullable=False)


class CascadeDBMixin(object):

    @property
    def l3_rpc_notifier(self):
        if not hasattr(self, '_l3_rpc_notifier'):
            self._l3_rpc_notifier = l3_rpc_agent_api.L3AgentNotifyAPI()
        return self._l3_rpc_notifier

    def is_big2layer_vni(self, seg_id):
        vni = cfg.CONF.big2layer_vni_range.split(':')
        if(seg_id >= int(vni[0]) and seg_id <= int(vni[1])):
            return True
        else:
            return False

    def get_binding_az_by_network_id(self, context, net_id):
        try:
            query = context.session.query(CascadeAZNetworkBinding)
            ban = query.filter(
                CascadeAZNetworkBinding.network_id == net_id).one()
        except exc.NoResultFound:
            return None
        return ban['host']

    def add_binding_az_network_id(self, context, binding_host, net_id):
        try:
            with context.session.begin(subtransactions=True):
                dvr_mac_binding = CascadeAZNetworkBinding(
                    network_id=net_id, host=binding_host)
                context.session.add(dvr_mac_binding)
                LOG.debug("add az_host %(host)s for network %(network_id)s ",
                          {'host': binding_host, 'network_id': net_id})
        except db_exc.DBDuplicateEntry:
            LOG.debug("az_host %(host)s exists for network %(network_id)s,"
                      " DBDuplicateEntry error.",
                      {'host': binding_host, 'network_id': net_id})

    def get_extern_ip_by_router_id_and_host(self, context, router_id, host):
        rae = self.get_router_az_extern_ip_mapping(context, router_id, host)
        if(rae):
            return rae['extern_ip']
        return None
#        try:
#            query = context.session.query(CascadeRouterAZExternipMapping)
#            erh = query.filter(
#                CascadeRouterAZExternipMapping.router_id == router_id,
#                CascadeRouterAZExternipMapping.host == host).one()
#        except exc.NoResultFound:
#            return None
#        return erh['extern_ip']

    def get_router_az_extern_ip_mapping(self, context, router_id, host):
        try:
            query = context.session.query(CascadeRouterAZExternipMapping)
            erh = query.filter(
                CascadeRouterAZExternipMapping.router_id == router_id,
                CascadeRouterAZExternipMapping.host == host).one()
        except exc.NoResultFound:
            return None
        return erh

    def update_router_az_extern_ip_mapping(self, context, router_id,
                                           host, extern_ip):
        if extern_ip is None:
            self.del_router_az_extern_ip_mapping(context, router_id, host)
            self.l3_rpc_notifier.routers_updated(context, [router_id],
                                                 None, None)
            return
        rae = self.get_router_az_extern_ip_mapping(context, router_id, host)
        if(rae and rae['extern_ip'] != extern_ip):
            update_rae = {}
            update_rae['router_id'] = rae['router_id']
            update_rae['host'] = rae['host']
            update_rae['extern_ip'] = extern_ip
            rae.update(update_rae)
            LOG.debug("update extern_ip %(extern_ip)s for az_host %(host)s "
                      "and router %(router_id)s ",
                      {'extern_ip': extern_ip,
                       'host': host,
                       'network_id': router_id})
            self.l3_rpc_notifier.routers_updated(context, [router_id],
                                                 None, None)
            return
        try:
            with context.session.begin(subtransactions=True):
                router_az_extern_ip_map = CascadeRouterAZExternipMapping(
                    router_id=router_id, host=host, extern_ip=extern_ip)
                context.session.add(router_az_extern_ip_map)
                LOG.debug("add extern_ip %(extern_ip)s for az_host %(host)s "
                          "and router %(router_id)s ",
                          {'extern_ip': extern_ip,
                           'host': host,
                           'network_id': router_id})
            self.l3_rpc_notifier.routers_updated(context, [router_id],
                                                 None, None)
        except db_exc.DBDuplicateEntry:
            LOG.debug("DBDuplicateEntry ERR:update extern_ip %(extern_ip)s "
                      "for az_host %(host)s  and router %(router_id)s ",
                      {'extern_ip': extern_ip,
                       'host': host,
                       'network_id': router_id})

    def del_router_az_extern_ip_mapping(self, context, router_id, host):
        try:
            query = context.session.query(CascadeRouterAZExternipMapping)
            query.filter(
                CascadeRouterAZExternipMapping.router_id == router_id,
                CascadeRouterAZExternipMapping.host == host).delete()
        except exc.NoResultFound:
            return None
