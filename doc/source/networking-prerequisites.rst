=============
Prerequisites
=============
One CentralRegion in which central Neutron and Tricircle services
are started, and central Neutron is configured with Tricircle Central Neutron
plugin properly. And at least two regions(RegionOne, RegionTwo) in which
Tricircle Local Neutron plugin is configured properly in local Neutron.

RegionOne is mapped to az1, and RegionTwo is mapped to az2 by pod management
through Tricircle Admin API.

You can use az1 or RegionOne as the value of availability-zone-hint when
creating a network. Although in this document only one region in one
availability zone, one availability zone can include more than one region in
Tricircle pod management, so if you specify az1 as the value, then it means
the network will reside in az1, and az1 is mapped to RegionOne, if you add
more regions into az1, then the network can spread into these regions too.

Please refer to the installation guide and configuration guide how to setup
multi-region environment with Tricircle service enabled.

If you setup the environment through devstack, you can get these settings
which are used in this document as follows:

Suppose that each node has 3 interfaces, and eth1 for tenant vlan network,
eth2 for external vlan network. If you want to verify the data plane
connectivity, please make sure the bridges "br-vlan" and "br-ext" are
connected to regarding interface. Using following command to connect
the bridge to physical ethernet interface, as shown below, "br-vlan" is
wired to eth1, and "br-ext" to eth2::

    sudo ovs-vsctl add-br br-vlan
    sudo ovs-vsctl add-port br-vlan eth1
    sudo ovs-vsctl add-br br-ext
    sudo ovs-vsctl add-port br-ext eth2

Suppose the vlan range for tenant network is 101~150, external network is
151~200, in the node which will run central Neutron and Tricircle services,
configure the local.conf like this::

    Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:101:150,extern:151:200)
    OVS_BRIDGE_MAPPINGS=bridge:br-vlan,extern:br-ext

    TRICIRCLE_START_SERVICES=True
    enable_plugin tricircle https://github.com/openstack/tricircle/

In the node which will run local Neutron without Tricircle services, configure
the local.conf like this::

    Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:101:150,extern:151:200)
    OVS_BRIDGE_MAPPINGS=bridge:br-vlan,extern:br-ext

    TRICIRCLE_START_SERVICES=False
    enable_plugin tricircle https://github.com/openstack/tricircle/

You may have noticed that the only difference is TRICIRCLE_START_SERVICES
is True or False. All examples given in this document will be based on these
settings.

If you also want to configure vxlan network, suppose the vxlan range for tenant
network is 1001~2000, add the following configuration to the above local.conf::

    Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS=(vni_ranges=1001:2000)

If you also want to configure flat network, suppose you use the same physical
network as the vlan network, configure the local.conf like this::

    Q_ML2_PLUGIN_FLAT_TYPE_OPTIONS=(flat_networks=bridge,extern)

In both RegionOne and RegionTwo, external network is able to be provisioned,
the settings will look like this in /etc/neutron/plugins/ml2/ml2_conf.ini::

    network_vlan_ranges = bridge:101:150,extern:151:200

    vni_ranges = 1001:2000(or the range that you configure)

    flat_networks = bridge,extern

    bridge_mappings = bridge:br-vlan,extern:br-ext

Please be aware that the physical network name for tenant VLAN network is
"bridge", and the external network physical network name is "extern".

In central Neutron's configuration file, the default settings look like as
follows::

    bridge_network_type = vxlan
    network_vlan_ranges = bridge:101:150,extern:151:200
    vni_ranges = 1001:2000
    flat_networks = bridge,extern
    tenant_network_types = vxlan,vlan,flat,local
    type_drivers = vxlan,vlan,flat,local

If you want to create a local network, it is recommend that you specify
availability_zone_hint as region name when creating the network, instead of
specifying the network type as "local". The "local" type has two drawbacks.
One is that you can not control the exact type of the network in local Neutron,
it's up to your local Neutron's configuration. The other is that the segment
ID of the network is allocated by local Neutron, so it may conflict with a
segment ID that is allocated by central Neutron. Considering such problems, we
have plan to deprecate "local" type.

If you want to create a L2 network across multiple Neutron servers, then you
have to speficy --provider-network-type vlan in network creation
command for vlan network type, or --provider-network-type vxlan for vxlan
network type. Both vlan and vxlan network type could work as the bridge
network. The default bridge network type is vxlan.

If you want to create a flat network, which is usually used as the external
network type, then you have to specify --provider-network-type flat in network
creation command.

You can create L2 network for different purposes, and the supported network
types for different purposes are summarized as follows.

    .. _supported_network_types:

    .. list-table::
       :header-rows: 1

       * - Networking purpose
         - Supported
       * - Local L2 network for instances
         - FLAT, VLAN, VxLAN
       * - Cross Neutron L2 network for instances
         - FLAT, VLAN, VxLAN
       * - Bridge network for routers
         - FLAT, VLAN, VxLAN
       * - External network
         - FLAT, VLAN
