================
Networking Terms
================

There are four important networking terms will be used in networking
automation across Neutron.

Local Network
  - Local Network is a network which can only reside in one OpenStack cloud.
  - Network type could be VLAN, VxLAN, Flat.
  - If you specify a region name as the value of availability-zone-hint
    during network creation, then the network will be created as local
    network in that region.
  - If the default network type to be created is configured to "local" in
    central Neutron, then no matter you specify availability-zone-hint or
    not, the network will be local network if the network was created
    without explicitly given non-local provider network type.
  - External network should be created as local network, that means external
    network is explicitly existing in some specified region. It's possible
    that each region provides multiple external networks, that means there
    is no limitation on how many external networks can be created.
  - For example, local network could be created as follows:

    .. code-block:: console

       openstack --os-region-name=CentralRegion network create --availability-zone-hint=RegionOne net1

Local Router
  - Local Router is a logical router which can only reside in one OpenStack
    cloud.
  - If you specify a region name as the value of availability-zone-hint
    during router creation, then the router will be created as local
    router in that region.
  - For example, local router could be created as follows:

    .. code-block:: console

       neutron --os-region-name=CentralRegion router-create --availability-zone-hint RegionOne R1

Cross Neutron L2 Network
  - Cross Neutron L2 Network is a network which can be stretched into more
    than one Neutron servers, these Neutron servers may work in one
    OpenStack cloud or multiple OpenStack clouds.
  - Network type could be VLAN, VxLAN, Flat.
  - During the network creation, if availability-zone-hint is not specified,
    or specified with availability zone name, or more than one region name,
    or more than one availability zone name, then the network will be created
    as cross Neutron L2 network.
  - If the default network type to be created is not configured to "local" in
    central Neutron, then the network will be cross Neutron L2 network if
    the network was created without specified provider network type and single
    region name in availability-zone-hint.
  - For example, cross Neutron L2 network could be created as follows:

    .. code-block:: console

       neutron --os-region-name=CentralRegion net-create --provider:network_type vxlan --availability-zone-hint RegionOne --availability-zone-hint RegionTwo net1

Non-Local Router
  - Non-Local Router will be able to reside in more than one OpenStack cloud,
    and internally inter-connected with bridge network.
  - Bridge network used internally for non-local router is a special cross
    Neutron L2 network.
  - Local networks or cross Neutron L2 networks can be attached to local
    router or non-local routers if the network can be presented in the region
    where the router can reside.
  - During the router creation, if availability-zone-hint is not specified,
    or specified with availability zone name, or more than one region name,
    or more than one availability zone name, then the router will be created
    as non-local router.
  - For example, non-local router could be created as follows:

    .. code-block:: console

       neutron --os-region-name=CentralRegion router-create --availability-zone-hint RegionOne --availability-zone-hint RegionTwo R3

It's also important to understand that cross Neutron L2 network, local
router and non-local router can be created for different north-south/east-west
networking purpose.

North-South and East-West Networking
  - Instances in different OpenStack clouds can be attached to a cross
    Neutron L2 network directly, so that they can communicate with
    each other no matter in which OpenStack cloud.
  - If L3 networking across OpenStack clouds is preferred, local network
    attached to non-local router can be created for instances to attach.
  - Local router can be set gateway with external networks to support
    north-south traffic handled locally.
  - Non-local router can work only for cross Neutron east-west networking
    purpose if no external network is set to the router.
  - Non-local router can serve as the centralized north-south traffic gateway
    if external network is attached to the router, and support east-west
    traffic at the same time.
