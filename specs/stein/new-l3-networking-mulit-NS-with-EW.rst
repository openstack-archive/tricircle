=================================================
A New Layer-3 Networking multi-NS-with-EW-enabled
=================================================

Problems
========
Based on spec for l3 networking [1], a l3 networking which enables multiple
NS traffic along with EW traffic is demonstrated. However, in the
aforementioned l3 networking model, the host route will be only valid after
DHCP lease time expired and renewed. It may take dhcp_lease_duration for VMs
in the subnet to update the host route, after a new pod with external
network is added to Tricircle. To solve the problem, this spec is written
to introduce a new l3 networking model.

Proposal
========
For the networking model in [1], a tenant network is attached to two
routers, one for NS traffic, the other for EW traffic. In the new networking
model, inspired by combined bridge network [2], we propose to attach the
tenant network to one router, and the router takes charge of routing NS
and EW traffic. The new networking mode is plotted in Fig. 1. ::

    +-----------------------+             +----------------------+
    |            ext-net1   |             |        ext-net2      |
    |      +---+---+        |             |            +--+---+  |
    |RegionOne |            |             | RegionTwo     |      |
    |      +---+---+        |             |          +----+--+   |
    |      |  R1   +------+ |             | +--------+  R2   |   |
    |      +-------+      | |             | |        +-------+   |
    |           net1      | |             | |      net2          |
    |     +------+---+-+  | |             | | +-+----+------+    |
    |            |   |    | |             | |   |    |           |
    |  +---------+-+ |    | |             | |   | +--+--------+  |
    |  | Instance1 | |    | |             | |   | | Instance2 |  |
    |  +-----------+ |    | |             | |   | +-----------+  |
    |           +----+--+ | |             | |  ++------+         |
    |           | R3(1) +-+-----------------+--+ R3(2) |         |
    |           +-------+   |  bridge net |    +-------+         |
    +-----------------------+             +----------------------+

    Figure 1 Multiple external networks with east-west networking

As shown in Fig. 1, R1 connects to external network (i.e., ext-net1) and
ext-net1 is the default gateway of R1. Meanwhile, net1 is attached to R3
and R3's default gateway is the bridge net. Further, interfaces of bridge
net are only attached to R1 and R2 which are regarded as local routers.

In such a scenario, all traffic (no matter NS or EW traffic) flows to R3.
For EW traffic, from net1 to net2, R3(1) will forwards packets to the
interface of net2 in R3(2) router namespace. For NS traffic, R3 forwards
packets to the interface of an available local router (i.e., R1 or R2)
which attached to the real external network. As a result, bridge net is
an internal net where NS and EW traffic is steered, rather than the real
external network of R3.

To create such a topology, we need to create a logical (non-local) router
R3 in the central Neutron. Tricircle central Neutron plugin then creates
R3(1) in RegionOne and R3(2) in RegionTwo, as well as the bridge network
to inter-connect R3(1) and R3(2). As such, the networking for EW traffic
is ready for tenants. To enable NS traffic, real external networks are
required to be attached to R3. When explicitly adding the gateway port
of each external network to R3, Tricircle automatically creates a local
router (e.g. R1) for external network and set the gateway to the local
router. Then to connect the local router (e.g. R1) and the non-local
router (R3), two interfaces of bridge-net are also created and attached
to respect router. The logical topology in central Neutron is plotted
in Fig. 2. ::

      ext-net1             ext-net2
    +---+---+            +---+---+
        |                    |
    +---+---+            +---+---+
    |  R1   |            |  R2   |
    +---+---+            +---+---+
        |                    |
    +---+--------------------+---+
    |         bridge-net         |
    +-------------+--------------+
                  |
                  |
    +-------------+--------------+
    |            R3              |
    +---+--------------------+---+
        | net1          net2 |
    +---+-----+-+      +---+-+---+
              |            |
    +---------+-+       +--+--------+
    | Instance1 |       | Instance2 |
    +-----------+       +-----------+

    Figure 2 Logical topology in central Neutron

To improve the logic of building l3 networking, we introduce routed network to
manage external networks in central Neutron. In central Neutron, one routed
network is created as a logical external network, and real external networks
are stored as segments of the external network. As such, the local routers
(e.g., R1 and R2 in Fig. 2) are transparent to users. As a result, when a real
external network is created, a local router is created and the external
network's gateway is set to the router. Moreover, a port of bridge-net is
created and added to the local router.

The routed network is created as follows: ::

    openstack --os-region-name=CentralRegion network create --share --provider-physical-network extern --provider-network-type vlan --provider-segment 3005 ext-net
    openstack --os-region-name=CentralRegion network segment create --physical-network extern  --network-type vlan --segment 3005 --network ext-net ext-sm-net1
    openstack --os-region-name=CentralRegion network segment create --physical-network extern  --network-type vlan --segment 3005 --network ext-net ext-sm-net2
    openstack --os-region-name=CentralRegion subnet create --network ext-net --network-segment ext-net1 --ip-version 4 --subnet-range 203.0.113.0/24 net1-subnet-v4
    openstack --os-region-name=CentralRegion subnet create --network ext-net --network-segment ext-net1 --ip-version 4 --subnet-range 203.0.114.0/24 net2--subnet-v4

The logical topology exposed to users is plotted in Fig. 3. ::

                 ext-net (routed network)
               +---+---+
                   |
                   |
    +--------------+-------------+
    |            R3              |
    +---+--------------------+---+
        | net1          net2 |
    +---+-----+-+      +---+-+---+
              |            |
    +---------+-+       +--+--------+
    | Instance1 |       | Instance2 |
    +-----------+       +-----------+

    Figure 3 Logical topology exposed to users in central Neutron

For R3, net1 and net2 should be attached to R3: ::

    openstack --os-region-name=CentralRegion router add subnet R3 <net1's subnet>
    openstack --os-region-name=CentralRegion router add subnet R3 <net2's subnet>

The gateway of the ext-net, i.e., the routed network, is set to R3: ::

    openstack --os-region-name=CentralRegion router set <ext-net> R3

However, a routed network does not have a gateway. Consequently, the command
above fails for trying adding the gateway of a routed network to the router,
i.e., R3. To ensure the command works, we plan to create a gateway port for
the routed network before setting the gateway to a router. Actually, the port
is a blank port which does not have an IP, because a routed network is a
software entity of multiple segments (i.e., subnets). To make sure the
gateways of real external networks can be retrieved, we manage the IPs of
gateways in "tags" field of the gateway port.

This command creates a port of bridget-net and add it to R3, which is plotted in
Fig. 2.

Tricircle central Neutron plugin will automatically configure R3(1), R3(2)
and bridge-network as follows:

For net1 and net2, no host route is needed, so in such an l3 networking
model, users are no longer required to wait for DHCP renew to update
host route. All traffic is forwarded to R3 by default.

In R3(1), extra route will be configured: ::

    destination=net2's cidr, nexthop=R3(2)'s interface in bridge-net
    destination=ext-net1's cidr, nexthop=R1's interface in bridge-net

In R3(2), extra route will be configured: ::

    destination=net1's cidr, nexthop=R3(1)'s interface in bridge-net
    destination=ext-net2's cidr, nexthop=R2's interface in bridge-net

R3(1) and R3(2) will set the external gateway to bridge-net: ::

    router-gateway-set R3(1) bridge-net
    router-gateway-set R3(2) bridge-net

Now, north-south traffic of Instance1 and Instance2 work as follows: ::

    Instance1 -> net1 -> R3(1) -> R1 -> ext-net1
    Instance2 -> net2 -> R3(2) -> R2 -> ext-net2

Two hops for north-south traffic.

East-west traffic between Instance1 and Instance2 work as follows: ::

    Instance1 <-> net1 <-> R3(1) <-> bridge-net <-> R3(2) <-> net2 <-> Instance2

Two hops for cross Neutron east-west traffic.

The topology with cross Neutron L2 networks except local networks is
illustrated in Fig. 4. ::

    +-----------------------+            +-----------------------+
    |    ext-net1           |            |          ext-net2     |
    |      +---+---+        |            |             +--+---+  |
    |RegionOne |            |            |  RegionTwo     |      |
    |      +---+------+     |            |     +----------+--+   |
    |      |    R1    +---+ |            | +---+   R2        |   |
    |      +----------+   | |            | |   +-------------+   |
    |    net1             | |            | |              net2   |
    |     ++---+          | |            | |          +-----+    |
    |      | net3         | |            | |         net4|       |
    |      |  ++---+      | |            | |      +--+-+ |       |
    |      |   |          | |  net5      | |         |   |       |
    |      |   | +-+-----------------------------+-+ |   |       |
    |      |   |   |      | |  net6      | |     |   |   |       |
    |      |   |   | ++-----------------------++ |   |   |       |
    |      |   |   |  |   | |            | |  |  |   |   |       |
    |      |   |   |  |   | |            | |  |  |   |   |       |
    |      |   |   |  |   | |            | |  |  |   |   |       |
    |      |   |   |  |   | |            | |  |  |   |   |       |
    | +----+---+---+--+-+ | | bridge-net | | ++--+---+---+-----+ |
    | |      R3(1)      +-+----------------+-+      R3(2)      | |
    | +-----------------+   |            |   +-----------------+ |
    +-----------------------+            +-----------------------+

    Figure 4 Multi-NS and cross Neutron L2 networks

The logical topology in central Neutron for Figure. 4 is plotted in Fig. 5. ::

     ext-net1                           ext-net2
    +---+---+                          +--+---+
        |                                 |
     +--+-----------+                 +---+------------+
     |    R1        |                 |      R2        |
     +----------+---+                 +----+-----------+
                |                          |
     +----------+--------------------------+-----------+
     |                   bridge-net                    |
     +-----------------------+-------------------------+
                             |
     +-----------------------+-------------------------+
     |                    R3                           |
     +--+----+------+-----------------+---------+----+-+
        |    |      |                 |         |    |
        |    |      |                 |         |    |
        |    |      |                 |         |    |
        |    |    +-+--------------------+      |    |
        |    |     net5               |         |    |
        |    |         +--------------+------+  |    |
        |    |            net6                  |    |
        |  +-+---+                          +---+-+  |
        |   net3                             net2    |
      +-+---+                                    +---+-+
       net1                                       net4

    Figure 5 Logical topology in central Neutron with cross Neutron L2 network

By adding networks to R3, EW traffic is routed by R3.

For net5 in RegionOne, extra route in R3(1) should be added: ::

    destination=net1's cidr, nexthop=<net5-R3-RegionOne-interface's IP>
    destination=net3's cidr, nexthop=<net5-R3-RegionOne-interface's IP>

For net5 in RegionTwo, extra route in R3(2) should be added: ::

    destination=net1's cidr, nexthop=<net5-R3-RegionTwo-interface's id>
    destination=net3's cidr, nexthop=<net5-R3-RegionTwo-interface's IP>

The east-west traffic between these networks will work as follows::

    net1 <-> R3 <-> net3
    net1 <-> R3 <-> net5
    net1 <-> R3 <-> net6
    net3 <-> R3 <-> net5
    net3 <-> R3 <-> net6
    net5 <-> R3 <-> net6

For NS traffic, the route to external network is already configured,
so NS traffic is routed to R1 or R2.

Implementation
==============

Part 0: add an option in local.conf to enable the new l3 networking model

Add an option "ENABLE_HOST_ROUTE_INDEPENDENT_L3_NETWORKING", whose value
is TRUE or FALSE, to indicate whether users expect to adopt such new l3
networking model.

Part 1: enable external network creation with transparent (local) router

This part mainly ensures a real external network is created along with a
local router, and set the gateway of the external network to the router.
As shown in Fig. 2, when ext-net1 is created, R1 is created, too. And the
gateway of ext-net1 is set to R1. Moreover, the local router, e.g. R1, is
transparent to users. In other words, users only create external network,
while tricircle complete the creation of the local router. As a result,
users are unaware of the local routers.

Part 2: enable routed network and gateway setting process

This part enables routed network in the central neutron. Meanwhile, this
part also needs to complete the process of setting gateway of the routed
network to the distributed router, e.g. R3 in Fig. 2. Here since the routed
network is a software entity of multiple real external networks, the gateway
ip of the routed network is set as NULL. And the gateway ips of real external
networks is planned to stored in tag field of the routed network. So this
part mainly deal with the blank gateway ip of the routed network when setting
gateway to the router.

Part 3: modify floating ip creation

In the existing l3 networking, external network and tenant network is
connected by a router, so implementing floating ip only needs NAT once.
However, in the new l3 networking model, as shown in Fig. 2, external network
and tenant network connect two routers, respectively. And the two routers
are connected by bridge network. So implementing floating ip needs to be NATed
twice. This part mainly deal with such an issue.

Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

1. Add a new guide for North South Networking via Multiple External Networks
   with east-west enabled.
2. Release notes.

Reference
=========

.. [1] https://github.com/openstack/tricircle/blob/master/specs/pike/l3-networking-multi-NS-with-EW-enabled.rst
.. [2] https://github.com/openstack/tricircle/blob/master/specs/ocata/l3-networking-combined-bridge-net.rst
