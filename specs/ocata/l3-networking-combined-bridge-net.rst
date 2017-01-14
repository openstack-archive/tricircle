==============================================
Layer-3 Networking and Combined Bridge Network
==============================================

Background
==========

To achieve cross-OpenStack layer-3 networking, we utilize a bridge network to
connect networks in each OpenStack cloud, as shown below:

East-West networking::

  +-----------------------+                +-----------------------+
  | OpenStack1            |                | OpenStack2            |
  |                       |                |                       |
  | +------+  +---------+ | +------------+ | +---------+  +------+ |
  | | net1 |  |      ip1| | | bridge net | | |ip2      |  | net2 | |
  | |      +--+    R    +---+            +---+    R    +--+      | |
  | |      |  |         | | |            | | |         |  |      | |
  | +------+  +---------+ | +------------+ | +---------+  +------+ |
  +-----------------------+                +-----------------------+

  Fig 1

North-South networking::

  +---------------------+                  +-------------------------------+
  | OpenStack1          |                  | OpenStack2                    |
  |                     |                  |                               |
  | +------+  +-------+ | +--------------+ | +-------+  +----------------+ |
  | | net1 |  |    ip1| | |  bridge net  | | |    ip2|  |  external net  | |
  | |      +--+  R1   +---+              +---+  R2   +--+                | |
  | |      |  |       | | | 100.0.1.0/24 | | |       |  | 163.3.124.0/24 | |
  | +------+  +-------+ | +--------------+ | +-------+  +----------------+ |
  +---------------------+                  +-------------------------------+

  Fig 2

To support east-west networking, we configure extra routes in routers in each
OpenStack cloud::

  In OpenStack1, destination: net2, nexthop: ip2
  In OpenStack2, destination: net1, nexthop: ip1

To support north-south networking, we set bridge network as the external
network in OpenStack1 and as the internal network in OpenStack2. For instance
in net1 to access the external network, the packets are SNATed twice, first
SNATed to ip1, then SNATed to ip2. For floating ip binding, ip in net1 is first
bound to ip(like 100.0.1.5) in bridge network(bridge network is attached to R1
as external network), then the ip(100.0.1.5) in bridge network is bound to ip
(like 163.3.124.8)in the real external network (bridge network is attached to
R2 as internal network).

Problems
========

The idea of introducing a bridge network is good, but there are some problems
in the current usage of the bridge network.

Redundant Bridge Network
------------------------

We use two bridge networks to achieve layer-3 networking for each tenant. If
VLAN is used as the bridge network type, limited by the range of VLAN tag, only
2048 pairs of bridge networks can be created. The number of tenants supported
is far from enough.

Redundant SNAT
--------------

In the current implementation, packets are SNATed two times for outbound
traffic and are DNATed two times for inbound traffic. The drawback is that
packets of outbound traffic consume extra operations. Also, we need to maintain
extra floating ip pool for inbound traffic.

DVR support
-----------

Bridge network is attached to the router as an internal network for east-west
networking and north-south networking when the real external network and the
router are not located in the same OpenStack cloud. It's fine when the bridge
network is VLAN type, since packets directly go out of the host and are
exchanged by switches. But if we would like to support VxLAN as the bridge
network type later, attaching bridge network as an internal network in the
DVR scenario will cause some troubles. How DVR connects the internal networks
is that packets are routed locally in each host, and if the destination is not
in the local host, the packets are sent to the destination host via a VxLAN
tunnel. Here comes the problem, if bridge network is attached as an internal
network, the router interfaces will exist in all the hosts where the router
namespaces are created, so we need to maintain lots of VTEPs and VxLAN tunnels
for bridge network in the Tricircle. Ports in bridge network are located in
different OpenStack clouds so local Neutron server is not aware of ports in
other OpenStack clouds and will not setup VxLAN tunnel for us.

Proposal
========

To address the above problems, we propose to combine the bridge networks for
east-west and north-south networking. Bridge network is always attached to
routers as an external network. In the DVR scenario, different from router
interfaces, router gateway will only exist in the SNAT namespace in a specific
host, which reduces the number of VTEPs and VxLAN tunnels the Tricircle needs
to handle. By setting "enable_snat" option to "False" when attaching the router
gateway, packets will not be SNATed when go through the router gateway, so
packets are only SNATed and DNATed one time in the real external gateway.
However, since one router can only be attached to one external network, in the
OpenStack cloud where the real external network is located, we need to add one
more router to connect the bridge network with the real external network. The
network topology is shown below::

  +-------------------------+                  +-------------------------+
  |OpenStack1               |                  |OpenStack2               |
  |  +------+   +--------+  |  +------------+  |  +--------+   +------+  |
  |  |      |   |     IP1|  |  |            |  |  |IP2     |   |      |  |
  |  | net1 +---+   R1   XXXXXXX bridge net XXXXXXX   R2   +---+ net2 |  |
  |  |      |   |        |  |  |            |  |  |        |   |      |  |
  |  +------+   +--------+  |  +---X----+---+  |  +--------+   +------+  |
  |                         |      X    |      |                         |
  +-------------------------+      X    |      +-------------------------+
                                   X    |
                                   X    |
  +--------------------------------X----|-----------------------------------+
  |OpenStack3                      X    |                                   |
  |                                X    |                                   |
  |  +------+    +--------+        X    |   +--------+    +--------------+  |
  |  |      |    |     IP3|        X    |   |IP4     |    |              |  |
  |  | net3 +----+   R3   XXXXXXXXXX    +---+   R4   XXXXXX external net |  |
  |  |      |    |        |                 |        |    |              |  |
  |  +------+    +--------+                 +--------+    +--------------+  |
  |                                                                         |
  +-------------------------------------------------------------------------+

  router interface: -----
  router gateway: XXXXX
  IPn: router gateway ip or router interface ip

  Fig 3

Extra routes and gateway ip are configured to build the connection::

  routes of R1: net2 via IP2
                net3 via IP3
  external gateway ip of R1: IP4
      (IP2 and IP3 are from bridge net, so routes will only be created in
       SNAT namespace)

  routes of R2: net1 via IP1
                net3 via IP3
  external gateway ip of R2: IP4
      (IP1 and IP3 are from bridge net, so routes will only be created in
       SNAT namespace)

  routes of R3: net1 via IP1
                net2 via IP2
  external gateway ip of R3: IP4
      (IP1 and IP2 are from bridge net, so routes will only be created in
       SNAT namespace)

  routes of R4: net1 via IP1
                net2 via IP2
                net3 via IP3
  external gateway ip of R1: real-external-gateway-ip
  disable DVR mode

An alternative solution which can reduce the extra router is that for the
router that locates in the same OpenStack cloud with the real external network,
we attach the bridge network as an internal network, so the real external
network can be attached to the same router. Here is the topology::

  +-------------------------+                  +-------------------------+
  |OpenStack1               |                  |OpenStack2               |
  |  +------+   +--------+  |  +------------+  |  +--------+   +------+  |
  |  |      |   |     IP1|  |  |            |  |  |IP2     |   |      |  |
  |  | net1 +---+   R1   XXXXXXX bridge net XXXXXXX   R2   +---+ net2 |  |
  |  |      |   |        |  |  |            |  |  |        |   |      |  |
  |  +------+   +--------+  |  +-----+------+  |  +--------+   +------+  |
  |                         |        |         |                         |
  +-------------------------+        |         +-------------------------+
                                     |
                                     |
              +----------------------|---------------------------------+
              |OpenStack3            |                                 |
              |                      |                                 |
              |      +------+    +---+----+      +--------------+      |
              |      |      |    |  IP3   |      |              |      |
              |      | net3 +----+   R3   XXXXXXXX external net |      |
              |      |      |    |        |      |              |      |
              |      +------+    +--------+      +--------------+      |
              |                                                        |
              +--------------------------------------------------------+

  router interface: -----
  router gateway: XXXXX
  IPn: router gateway ip or router interface ip

  Fig 4

The limitation of this solution is that R3 needs to be set as non-DVR mode.
As is discussed above, for network attached to DVR mode router, the router
interfaces of this network will be created in all the hosts where the router
namespaces are created. Since these interfaces all have the same IP and MAC,
packets sent between instances(could be virtual machine, container or bare
metal) can't be directly wrapped in the VxLAN packets, otherwise packets sent
from different hosts will have the same MAC. How Neutron solve this problem is
to introduce DVR MACs which are allocated by Neutron server and assigned to
each host hosting DVR mode router. Before wrapping the packets in the VxLAN
packets, the source MAC of the packets are replaced by the DVR MAC of the host.
If R3 is DVR mode, source MAC of packets sent from net3 to bridge network will
be changed, but after the packets reach R1 or R2, R1 and R2 don't recognize the
DVR MAC, so the packets are dropped.

The same, extra routes and gateway ip are configured to build the connection::

  routes of R1: net2 via IP2
                net3 via IP3
  external gateway ip of R1: IP3
      (IP2 and IP3 are from bridge net, so routes will only be created in
       SNAT namespace)

  routes of R2: net1 via IP1
                net3 via IP3
  external gateway ip of R1: IP3
      (IP1 and IP3 are from bridge net, so routes will only be created in
       SNAT namespace)

  routes of R3: net1 via IP1
                net2 via IP2
  external gateway ip of R3: real-external-gateway-ip
      (non-DVR mode, routes will all be created in the router namespace)

The real external network can be deployed in one dedicated OpenStack cloud. In
that case, there is no need to run services like Nova and Cinder in that cloud.
Instance and volume will not be provisioned in that cloud. Only Neutron service
is required. Then the above two topologies transform to the same one::

  +-------------------------+                  +-------------------------+
  |OpenStack1               |                  |OpenStack2               |
  |  +------+   +--------+  |  +------------+  |  +--------+   +------+  |
  |  |      |   |     IP1|  |  |            |  |  |IP2     |   |      |  |
  |  | net1 +---+   R1   XXXXXXX bridge net XXXXXXX   R2   +---+ net2 |  |
  |  |      |   |        |  |  |            |  |  |        |   |      |  |
  |  +------+   +--------+  |  +-----+------+  |  +--------+   +------+  |
  |                         |        |         |                         |
  +-------------------------+        |         +-------------------------+
                                     |
                                     |
                         +-----------|-----------------------------------+
                         |OpenStack3 |                                   |
                         |           |                                   |
                         |           |   +--------+    +--------------+  |
                         |           |   |IP3     |    |              |  |
                         |           +---+   R3   XXXXXX external net |  |
                         |               |        |    |              |  |
                         |               +--------+    +--------------+  |
                         |                                               |
                         +-----------------------------------------------+

  Fig 5

The motivation of putting the real external network in a dedicated OpenStack
cloud is to simplify the real external network management, and also to separate
the real external network and the internal networking area, for better security
control.

Discussion
==========

The implementation of DVR does bring some restrictions to our cross-OpenStack
layer-2 and layer-3 networking, resulting in the limitation of the above two
proposals. In the first proposal, if the real external network is deployed with
internal networks in the same OpenStack cloud, one extra router is needed in
that cloud. Also, since one of the router is DVR mode and the other is non-DVR
mode, we need to deploy at least two l3 agents, one is dvr-snat mode and the
other is legacy mode. The limitation of the second proposal is that the router
is non-DVR mode, so east-west and north-south traffic are all go through the
router namespace in the network node.

Also, cross-OpenStack layer-2 networking can not work with DVR because of
source MAC replacement. Considering the following topology::

  +----------------------------------------------+       +-------------------------------+
  |OpenStack1                                    |       |OpenStack2                     |
  |  +-----------+   +--------+   +-----------+  |       |  +--------+   +------------+  |
  |  |           |   |        |   |           |  |       |  |        |   |            |  |
  |  | net1      +---+   R1   +---+ net2      |  |       |  |   R2   +---+ net2       |  |
  |  | Instance1 |   |        |   | Instance2 |  |       |  |        |   | Instance3  |  |
  |  +-----------+   +--------+   +-----------+  |       |  +--------+   +------------+  |
  |                                              |       |                               |
  +----------------------------------------------+       +-------------------------------+

  Fig 6

net2 supports cross-OpenStack layer-2 networking, so instances in net2 can be
created in both OpenStack clouds. If the router net1 and net2 connected to is
DVR mode, when Instance1 ping Instance2, the packets are routed locally and
exchanged via a VxLAN tunnel. Source MAC replacement is correctly handled
inside OpenStack1. But when Instance1 tries to ping Instance3, OpenStack2 does
not recognize the DVR MAC from OpenStack1, thus connection fails. Therefore,
only local type network can be attached to a DVR mode router.

Cross-OpenStack layer-2 networking and DVR may co-exist after we address the
DVR MAC recognition problem(we will issue a discussion about this problem in
the Neutron community) or introduce l2 gateway. Actually this bridge network
approach is just one of the implementation, we are considering in the near
future to provide a mechanism to let SDN controller to plug in, which DVR and
bridge network may be not needed.

Having the above limitation, can our proposal support the major user scenarios?
Considering whether the tenant network and router are local or across OpenStack
clouds, we divide the user scenarios into four categories. For the scenario of
cross-OpenStack router, we use the proposal shown in Fig 3 in our discussion.

Local Network and Local Router
------------------------------

Topology::

  +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |
  | ext net1        |       | ext net2        |
  |   +-----+-----+ |       |   +-----+-----+ |
  |         |       |       |         |       |
  |         |       |       |         |       |
  |      +--+--+    |       |      +--+--+    |
  |      |     |    |       |      |     |    |
  |      | R1  |    |       |      | R2  |    |
  |      |     |    |       |      |     |    |
  |      +--+--+    |       |      +--+--+    |
  |         |       |       |         |       |
  |         |       |       |         |       |
  |     +---+---+   |       |     +---+---+   |
  |     net1        |       |     net2        |
  |                 |       |                 |
  +-----------------+       +-----------------+

  Fig 7

Each OpenStack cloud has its own external network, instance in each local
network accesses the external network via the local router. If east-west
networking is not required, this scenario has no requirement on cross-OpenStack
layer-2 and layer-3 networking functionality. Both central Neutron server and
local Neutron server can process network resource management request. While if
east-west networking is needed, we have two choices to extend the above
topology::

                                                  *
  +-----------------+       +-----------------+   *   +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |   *   |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |   *   |                 |       |                 |
  | ext net1        |       | ext net2        |   *   | ext net1        |       | ext net2        |
  |   +-----+-----+ |       |   +-----+-----+ |   *   |   +-----+-----+ |       |   +-----+-----+ |
  |         |       |       |         |       |   *   |         |       |       |         |       |
  |         |       |       |         |       |   *   |         |       |       |         |       |
  |      +--+--+    |       |      +--+--+    |   *   |      +--+--+    |       |      +--+--+    |
  |      |     |    |       |      |     |    |   *   |      |     |    |       |      |     |    |
  |      | R1  |    |       |      | R2  |    |   *   |      | R1  +--+ |       |  +---+ R2  |    |
  |      |     |    |       |      |     |    |   *   |      |     |  | |       |  |   |     |    |
  |      +--+--+    |       |      +--+--+    |   *   |      +--+--+  | |       |  |   +--+--+    |
  |         |       |       |         |       |   *   |         |     | |       |  |      |       |
  |         |       |       |         |       |   *   |         |     | |       |  |      |       |
  |     +---+-+-+   |       |     +---+-+-+   |   *   |     +---+---+ | |       |  |  +---+---+   |
  |     net1  |     |       |     net2  |     |   *   |     net1      | |       |  |  net2        |
  |           |     |       |           |     |   *   |               | |       |  |              |
  |  +--------+--+  |       |  +--------+--+  |   *   |               | | net3  |  |              |
  |  | Instance1 |  |       |  | Instance2 |  |   *   |  +------------+------------+-----------+  |
  |  +-----------+  |       |  +-----------+  |   *   |                 |       |                 |
  |         |       |       |         |       |   *   +-----------------+       +-----------------+
  |         |       | net3  |         |       |   *
  |  +------+-------------------------+----+  |   *   Fig 8.2
  |                 |       |                 |   *
  +-----------------+       +-----------------+   *
                                                  *
  Fig 8.1

In the left topology, two instances are connected by a shared VxLAN network,
only local network is attached to local router, so it can be either legacy or
DVR mode. In the right topology, two local routers are connected by a shared
VxLAN network, so they can only be legacy mode.

Cross-OpenStack Network and Local Router
----------------------------------------

Topology::

  +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |
  | ext net1        |       | ext net2        |
  |   +-----+-----+ |       |   +-----+-----+ |
  |         |       |       |         |       |
  |         |       |       |         |       |
  |      +--+--+    |       |      +--+--+    |
  |      |     |    |       |      |     |    |
  |      | R1  |    |       |      | R2  |    |
  |      |     |    |       |      |     |    |
  |      +--+--+    |       |      +--+--+    |
  |         |       |       |         |       |
  |   net1  |       |       |         |       |
  |  +--+---+---------------------+---+---+   |
  |     |           |       |     |           |
  |     |           |       |     |           |
  |  +--+--------+  |       |  +--+--------+  |
  |  | Instance1 |  |       |  | Instance2 |  |
  |  +-----------+  |       |  +-----------+  |
  |                 |       |                 |
  +-----------------+       +-----------------+

  Fig 9

From the Neutron API point of view, attaching a network to different routers
that each has its own external gateway is allowed but packets can only get out
via one of the external network because there is only one gateway ip in one
subnet. But in the Tricircle, we allocate one gateway ip for network in each
OpenStack cloud, so instances can access specific external network via specific
gateway according to which OpenStack cloud they are located.

We can see this topology as a simplification of the topology shown in Fig 8.1
that it doesn't require an extra network interface for instances. And if no
other networks are attached to R1 and R2 except net1, R1 and R2 can be DVR
mode.

In the NFV scenario, usually instance itself acts as a router, so there's no
need to create a Neutron router and we directly attach the instance to the
provider network and access the real external network via the provider network.
In that case, when creating Neutron network, "router:external" label should be
set to "False". See Fig 10::

  +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |
  | provider net1   |       | provider net2   |
  |  +--+---------+ |       |  +--+---------+ |
  |     |           |       |     |           |
  |     |           |       |     |           |
  |  +--+--------+  |       |  +--+--------+  |
  |  | VNF       |  |       |  | VNF       |  |
  |  | Instance1 |  |       |  | Instance2 |  |
  |  +------+----+  |       |  +------+----+  |
  |         |       |       |         |       |
  |         |       |       |         |       |
  |   net1  |       |       |         |       |
  |  +------+-------------------------+---+   |
  |                 |       |                 |
  +-----------------+       +-----------------+

  Fig 10

Local Network and Cross-OpenStack Router
----------------------------------------

Topology::

  +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |
  |                 |       | ext net         |
  |                 |       |   +-------+---+ |
  |   bridge net    |       |           |     |
  |   +-----+-----------------+-+-+     |     |
  |         |       |       | | |    +--+--+  |
  |         |       |       | | |    |     |  |
  |      +--+--+    |       | | +----+  R  |  |
  |      |     |    |       | |      |     |  |
  |      |  R  |    |       | |      +-----+  |
  |      |     |    |       | |               |
  |      +--+--+    |       | |   +-----+     |
  |         |       |       | |   |     |     |
  |         |       |       | +---+  R  |     |
  |     +---+---+   |       |     |     |     |
  |     net1        |       |     +--+--+     |
  |                 |       |        |        |
  |                 |       |        |        |
  |                 |       |    +---+---+    |
  |                 |       |    net2         |
  |                 |       |                 |
  +-----------------+       +-----------------+

  Fig 11

Since the router is cross-OpenStack type, the Tricircle automatically creates
bridge network to connect router instances inside the two OpenStack clouds and
connect the router instance to the real external network. Networks attached to
the router are local type, so the router can be either legacy or DVR mode.

Cross-OpenStack Network and Cross-OpenStack Router
--------------------------------------------------

Topology::

                                                 *
  +-----------------+       +-----------------+  *  +-----------------+       +-----------------+
  |OpenStack1       |       |OpenStack2       |  *  |OpenStack1       |       |OpenStack2       |
  |                 |       |                 |  *  |                 |       |                 |
  |                 |       | ext net         |  *  |                 |       | ext net         |
  |                 |       |   +-------+---+ |  *  |                 |       |   +-------+---+ |
  |   bridge net    |       |           |     |  *  |   bridge net    |       |           |     |
  |   +-----+-----------------+-+-+     |     |  *  |   +-----+-----------------+-+-+     |     |
  |         |       |       | | |    +--+--+  |  *  |         |       |       | | |    +--+--+  |
  |         |       |       | | |    |     |  |  *  |         |       |       | | |    |     |  |
  |         |       |       | | +----+  R  |  |  *  |         |       |       | | +----+  R  |  |
  |         |       |       | |      |     |  |  *  |         |       |       | |      |     |  |
  |      +--+--+    |       | |      +-----+  |  *  |      +--+--+    |       | |      +-----+  |
  |      |     |    |       | |               |  *  |      |     |    |       | |               |
  |      |  R  |    |       | |   +-----+     |  *  |   +--+  R  |    |       | |   +-----+     |
  |      |     |    |       | |   |     |     |  *  |   |  |     |    |       | |   |     |     |
  |      +--+--+    |       | +---+  R  |     |  *  |   |  +--+--+    |       | +---+  R  +--+  |
  |         |       |       |     |     |     |  *  |   |     |       |       |     |     |  |  |
  |         |       |       |     +--+--+     |  *  |   |     |       |       |     +--+--+  |  |
  |         |       |       |        |        |  *  |   |     |       |       |        |     |  |
  |         |       |       |        |        |  *  |   |     |       |       |        |     |  |
  |     +---+------------------------+---+    |  *  |   | +---+------------------------+---+ |  |
  |     net1        |       |                 |  *  |   | net1        |       |              |  |
  |                 |       |                 |  *  |   |             |       |              |  |
  +-----------------+       +-----------------+  *  |   |             |       |              |  |
                                                 *  | +-+------------------------------------++ |
  Fig 12.1                                       *  | net2            |       |                 |
                                                 *  |                 |       |                 |
                                                 *  +-----------------+       +-----------------+
                                                 *
                                                    Fig 12.2

In Fig 12.1, the router can only be legacy mode since net1 attached to the
router is shared VxLAN type. Actually in this case the bridge network is not
needed for east-west networking. Let's see Fig 12.2, both net1 and net2 are
shared VxLAN type and are attached to the router(also this router can only be
legacy mode), so packets between net1 and net2 are routed in the router of the
local OpenStack cloud and then sent to the target. Extra routes will be cleared
so no packets will go through the bridge network. This is the current
implementation of the Tricircle to support VLAN network.

Recommended Layer-3 Networking Mode
-----------------------------------

Let's make a summary of the above discussion. Assume that DVR mode is a must,
the recommended layer-3 topology for each scenario is listed below.

+----------------------------+---------------------+------------------+
| north-south networking via | isolated east-west  | Fig 7            |
| multiple external networks | networking          |                  |
|                            +---------------------+------------------+
|                            | connected east-west | Fig 8.1 or Fig 9 |
|                            | networking          |                  |
+----------------------------+---------------------+------------------+
| north-south networking via                       | Fig 11           |
| single external network                          |                  |
+----------------------------+---------------------+------------------+
| north-south networking via                       | Fig 10           |
| direct provider network                          |                  |
+--------------------------------------------------+------------------+

Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

Guide of multi-node DevStack installation needs to be updated to introduce
the new bridge network solution.
