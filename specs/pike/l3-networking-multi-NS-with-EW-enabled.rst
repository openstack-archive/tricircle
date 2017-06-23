===========================================
Layer-3 Networking multi-NS-with-EW-enabled
===========================================

Problems
========

There are already several scenarios fulfilled in Tricircle for north-
south networking.

Scenario "North South Networking via Multiple External Networks"[1] meets
the demand for multiple external networks, but local network can not
reach other local networks which are not in the same OpenStack cloud.

Scenario "North South Networking via Single External Network"[2] can meet
local networks east-west networking requirement, but the north-south traffic
needs to go to single gateway.

In multi-region cloud deployment, a requirement is that each OpenStack cloud
provides external network, north-south traffic is expected to be handled
locally for shortest path, and/or use multiple external networks to ensure
application north-south traffic redundancy, at the same time east-west
networking of tenant's networks between OpenStack cloud is also needed.

Proposal
========

To address the above problems, the key limitation is the pattern for router
gateway, one router in Neutron can only be attached to one external network.
As what's described in the spec of combined bridge network[3], only external
network is suitable for working as bridge network due to DVR challenge.

North-south traffic via the external network in the same region is conflict
with external network as bridge network.

The proposal is to introduce a new networking mode for this scenario::


    +-----------------------+             +----------------------+
    |       ext-net1        |             |           ext-net2   |
    |      +---+---+        |             |            +--+---+  |
    |RegionOne |            |             | RegionTwo     |      |
    |      +---+---+        |             |          +----+--+   |
    |      |  R1   |        |             |          |  R2   |   |
    |      +--+----+        |             |          +--+----+   |
    |         | net1        |             |        net2 |        |
    |     +---+--+---+-+    |             |   ++-----+--+---+    |
    |            |   |      |             |    |     |           |
    |  +---------+-+ |      |             |    |  +--+--------+  |
    |  | Instance1 | |      |             |    |  | Instance2 |  |
    |  +-----------+ |      |             |    |  +-----------+  |
    |           +----+--+   | bridge-net  |  +-+-----+           |
    |           | R3(1) +--------------------+ R3(2) |           |
    |           +-------+   |             |  +-------+           |
    +-----------------------+             +----------------------+
     Figure.1 Multiple external networks with east-west networking

R1 is the router to connect the external network ext-net1 directly
in RegionOne. Net1's default gateway is R1, so all north-south traffic
will be forwarded by R1 by default. In short, north-south traffic of net2
will be processed by R2 in RegionTwo. R1 and R2 are local routers which
is supposed to be presented in only one region. Region name should be
specified in availability-zone-hint during router creation in central
Neutron, for example::

   openstack --os-region-name=CentralRegion router create --availability-zone-hint=RegionOne R1
   openstack --os-region-name=CentralRegion router create --availability-zone-hint=RegionTwo R2

   openstack --os-region-name=CentralRegion router add subnet R1 <net1's subnet>
   openstack --os-region-name=CentralRegion router add subnet R2 <net2's subnet>

In order to process the east-west traffic from net1 to net2, R3(1) and R3(2)
will be introduced, R3(1) and R3(2) will be inter-connected by bridge-net.
Bridge-net could be VLAN or VxLAN cross Neutron L2 network, and it's the
"external network" for both R3(1) and R3(2), please note here the bridge-net
is not real external network, just the concept of Neutron network. R3(1) and
R3(2) will only forward the east-west traffic across Neutron for local
networks, so it's not necessary to work as DVR, centralized router is good
enough.

In central Neutron, we only need to create a virtual logical router R3,
and R3 router is called as east-west gateway, to handle the east-west
traffic for local networks in different region, and it's non-local router.
Tricircle central Neutron plugin will help to create R3(1) in RegionOne and
R3(2) in RegionTwo, and use the bridge network to inter-connect R3(1) and
R3(2). The logical topology in central Neutron looks like follows::

         ext-net1             ext-net2
        +-------+              +--+---+
            |                     |
        +---+---+            +----+--+
        |  R1   |            |  R2   |
        +--+----+            +--+----+
           | net1          net2 |
       +---+--+---++  ++-----+--+---+
              |   |    |     |
    +---------+-+ |    |  +--+--------+
    | Instance1 | |    |  | Instance2 |
    +-----------+ |    |  +-----------+
                +-+----+--+
                |   R3    |
                +---------+

    Figure.2 Logical topology in central Neutron

Tricircle central Neutron plugin will use logical router R3 to create R3(1)
in RegionOne, and R3(2) in RegionTwo.

Please note that R3(1) is not the default gateway of net1, and R3(2) is not
the default gateway of net2 too. So the user has to create a port and use
this port as the router interface explicitly between router and local
network.

In central Neutron, the topology could be created like this::

    openstack --os-region-name=CentralRegion port create --network=net1 net1-R3-interface
    openstack --os-region-name=CentralRegion router add port R3 <net1-R3-interface's id>

    openstack --os-region-name=CentralRegion port create --network=net2 net2-R3-interface
    openstack --os-region-name=CentralRegion router add port R3 <net2-R3-interface's id>

Tricircle central Neutron plugin will automatically configure R3(1), R3(2) and
bridge-network as follows:

For net1, host route should be added::

    destination=net2's cidr, nexthop=<net1-R3-interface's IP>

For net2, host route should be added::

    destination=net1's cidr, nexthop=<net2-R3-interface's IP>

In R3(1), extra route will be configured::

    destination=net2's cidr, nexthop=R3(2)'s interface in bridge-net

In R3(2), extra route will be configured::

    destination=net1's cidr, nexthop=R3(1)'s interface in bridge-net

R3(1) and R3(2) will set the external gateway to bridge-net::

    router-gateway-set R3(1) bridge-net
    router-gateway-set R3(2) bridge-net

Now, north-south traffic of Instance1 and Instance2 work like follows::

    Instance1 -> net1 -> R1 -> ext-net1
    Instance2 -> net2 -> R2 -> ext-net2

Only one hop for north-south traffic.

East-west traffic between Instance1 and Instance2 work like follows::

    Instance1 <-> net1 <-> R3(1) <-> bridge-net <-> R3(2) <-> net2 <-> Instance2

Two hops for cross Neutron east-west traffic.

The topology will be more complex if there are cross Neutron L2 networks
except local networks::

    +-----------------------+             +----------------------+
    |       ext-net1        |             |           ext-net2   |
    |      +-------+        |             |            +--+---+  |
    |RegionOne |            |             | RegionTwo     |      |
    |      +---+----------+ |             | +-------------+--+   |
    |      |    R1        | |             | |      R2        |   |
    |      +--+--+---+--+-+ |             | ++-+----+---+----+   |
    |    net1 |  |   |  |   |             |  | |    |   | net2   |
    |     ++--++ |   |  |   |             |  | |    | +-+---+    |
    |      | net3|   |  |   |             |  | |    |net4|       |
    |      |  ++---+ |  |   |             |  | |  ++---+ |       |
    |      |   |     |  |   |  net5       |  | |   |     |       |
    |      |   |   +++-------------------------+-++|     |       |
    |      |   |    |   |   |  net6       |  |   | |     |       |
    |      |   |    |++-+--------------------+++ | |     |       |
    |      |   |    | |     |             |   |  | |     |       |
    |      |   |    | |     |             |   |  | |     |       |
    |      |   |    | |     |             |   |  | |     |       |
    |      |   |    | |     |             |   |  | |     |       |
    | +----+---+----+-+-+   | bridge-net  |  ++--+-+-----+-----+ |
    | |      R3(1)      +--------------------+      R3(2)      | |
    | +-----------------+   |             |  +-----------------+ |
    +-----------------------+             +----------------------+

    Figure.3 Multi-NS and cross Neutron L2 networks

The logical topology in central Neutron for Figure.3 looks like as follows::

       ext-net1                                  ext-net2
      +-------+                                   +--+---+
          |                                          |
      +---+----------+                 +-------------+--+
      |    R1        |                 |      R2        |
      +--+--+---+--+-+                 ++-+----+---+----+
    net1 |  |   |  |                    | |    |   | net2
     ++--++ |   |  |                    | |    | +-+---+
      | net3|   |  |                    | |    |net4|
      |  ++---+ |  |                    | |  ++---+ |
      |   |     |  |      net5          | |   |     |
      |   |     +------+------------------+   |     |
      |   |        |   |  net6          |     |     |
      |   |        +-------------+------+     |     |
      |   |            |         |            |     |
      |   |            |         |            |     |
      |   |            |         |            |     |
      |   |            |         |            |     |
    +-+---+------------+---------+------------+-----+-+
    |                    R3                           |
    +-------------------------------------------------+
  Figure.4 Logical topology in central Neutron with cross Neutron L2 network

East-west traffic inside one region will be processed locally through default
gateway. For example, in RegionOne, R1 has router interfaces in net1, net3,
net5, net6, the east-west traffic between these networks will work as follows::

    net1 <-> R1 <-> net3
    net1 <-> R1 <-> net5
    net1 <-> R1 <-> net6
    net3 <-> R1 <-> net5
    net3 <-> R1 <-> net6
    net5 <-> R1 <-> net6

There is nothing special for east-west traffic between local networks
in different OpenStack regions.

Net5 and net6 are cross Neutron L2 networks, instances could be attached
to network from different regions, and instances are reachable in a remote
region via the cross Neutron L2 network itself. There is no need to add host
route for cross Neutron L2 network, for it's routable in the same region for
other local networks or cross Neutron L2 networks, default route is enough
for east-west traffic.

It's needed to address how one cross Neutron L2 network will be
attached different local router: different gateway IP address will be used.
For example, in central Neutron, net5's default gateway IP is 192.168.0.1
in R1, the user needs to create a gateway port explicitly for local router R2
and net5, for example 192.168.0.2, then net5 will be attached to R2 using this
gateway port 192.168.0.2. Tricircle central Neutron plugin will make this
port's IP 192.168.0.2 as the default gateway IP for net5 in RegionTwo.

Besides of gateway ports creation for local router R2, it's also needed to
create a gateway port for R3 and net5, which is used for east-west traffic.
Because R3 will be spread into RegionOne and RegionTwo, so net5 will have
different gateway ports in RegionOne and RegionTwo. Tricircle central Neutron
plugin needs to reserve the gateway ports in central Neutron, and create these
gateway ports in RegionOne and RegionTwo for net5 on R3. Because R3 is the
east-west gateway router for net5, so these gateway ports are not the default
gateway port. Then host route in net5 should be updated for local networks
which are not in the same region:

For net5 in RegionOne, host route should be added::

    destination=net2's cidr, nexthop=<net5-R3-RegionOne-interface's IP>
    destination=net4's cidr, nexthop=<net5-R3-RegionOne-interface's IP>

For net5 in RegionTwo, host route should be added::

    destination=net1's cidr, nexthop=<net5-R3-RegionTwo-interface's id>
    destination=net3's cidr, nexthop=<net5-R3-RegionTwo-interface's IP>

Similar operation for net6 in RegionOne and RegionTwo.

If R1 and R2 are centralized routers, cross Neutron L2 network will
work, but if R1 and R2 are DVRs, then DVR MAC issue mentioned in the
spec "l3-networking-combined-bridge-net" should be fixed[2].

In order to make the topology not too complex, this use case will not be
supported: a cross Neutron L2 network is not able to be stretched into
the region where there are local networks. This use case is not useful
and will make the east-west traffic even more complex::

    +-----------------------+             +----------+     +-----------------+
    |       ext-net1        |             | ext-net2 |     |      ext-net4   |
    |      +-------+        |             | +------+ |     |       +--+---+  |
    |RegionOne |            |             | RegionTwo|     |  Region4 |      |
    |      +---+----------+ |             | +------+ |     |  +-------+--+   |
    |      |    R1        | |             | | R2   | |     |  |  R4      |   |
    |      +--+--+---+--+-+ |             | ++-+---+ |     |  +-+---+----+   |
    |    net1 |  |   |  |   |             |  | |     |     |    |   | net2   |
    |     ++--++ |   |  |   |             |  | |     |     |    | +-+---+    |
    |      | net3|   |  |   |             |  | |     |     |    |net4|       |
    |      |  ++---+ |  |   |             |  | |     |     |  ++---+ |       |
    |      |   |     |  |   |  net5       |  | |     |     |   |     |       |
    |      |   |   +-+-------------------------+-+   |     |   |     |       |
    |      |   |        |   |  net6       |  |       |     |   |     |       |
    |      |   |      +-+--------------------+       |     |   |     |       |
    |      |   |            |             |          |     |   |     |       |
    |      |   |            |             |          |     |   |     |       |
    |      |   |            |             |          |     |   |     |       |
    |      |   |            |             |          |     |   |     |       |
    | +----+---+--------+   |             |  +-----+ |     | +-+-----+-----+ |
    | |      R3(1)      |   |             |  |R3(2)| |     | |   R3(3)     | |
    | +-----------+-----+   |             |  +-+---+ |     | +-----+-------+ |
    |             |         |             |    |     |     |       |         |
    +-----------------------+             +----------+     +-----------------+
                  |          bridge-net        |                   |
                  +----------------------------+-------------------+

    Figure.5 Cross Neutron L2 network not able to be stretched into some region


Implementation
--------------

Local router: It's a router which is created with region name specified in the
availability zone hint, this will be present only in the specific region.

East-west gateway router: It's a router which will be spread into multiple
regions and this will handle the east-west traffic to attached local networks.

The following description of implementation is not pseudo code, it's the
logical judgemenet for different conditions combination.

Adding router interface to east-west gateway router::

    if IP of the router interface is the subnet default gateway IP
        # north-south traffic and east-west traffic will
        # go through this router
        # router is the default router gateway, it's the
        # single north-south external network mode
        if the network is cross Neutron L2 network
            reserve gateway port in different region
            add router interface in each region using reserved gateway port IP
            make sure the gateway port IP is the default route
        else # local network
            add router interface using the default gateway port or the port
            specified in request
    else # not the default gateway IP in this subnet
        if the network is cross Neutron L2 network
            reserve gateway port in different region
            add router interface in each region using reserved gateway port IP
            update host route in each connected local network in each region,
            next hop is the reserved gateway port IP
        else # local network
            create router in the region as needed
            add router interface using the port specified in request
            if there are more than one interfaces on this router
                update host route in each connected local network in each
                region, next hop is port IP on this router.

    Configure extra route to the router in each region for EW traffic

Adding router interface to local router for cross Neutron L2 network will
make the local router as the default gateway router in this region::

    # default north-south traffic will go through this router
    add router interface using the default gateway port or the port
    specified in request
    make sure this local router in the region is the default gateway

If external network is attached to east-west gateway router, and network's
default gateway is the east-west gateway router, then the router will be
upgraded to north-south networking via single external network mode.

Constraints:
    Network can only be attached to one local router in one region.

    If a network has already been attached to a east-west gateway router,
    and the east-west gateway router is the default gateway of this network,
    then the network can't be attached to another local router.

.. note:: Host route update in a subnet will function only in next
   dhcp request. It may take dhcp_lease_duration for VMs in the subnet
   to update the host route. It's better to compose the networking
   topology before attached VMs to the netwrok. dhcp_lease_duration is
   configured by the cloud operator. If tenant wants to make the host
   route work immediately, can send dhcp request directly in VMs.


Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

1. Add new guide for North South Networking via Multiple External Networks
   with east-west enabled.
2. Release notes.

Reference
=========

.. [1] North South Networking via Multiple External Networks: https://docs.openstack.org/developer/tricircle/networking-guide-multiple-external-networks.html
.. [2] l3-networking-combined-bridge-net: https://github.com/openstack/tricircle/blob/master/specs/ocata/l3-networking-combined-bridge-net.rst
.. [3] North South Networking via Single External Network: https://docs.openstack.org/developer/tricircle/networking-guide-single-external-network.html
