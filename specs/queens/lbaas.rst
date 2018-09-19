==========================================
Distributed LBaaS in Multi-Region Scenario
==========================================

Background
==========

Currently, LBaaS (Load-Balancing-as-a-Service) is not supported in the
Tricircle. This spec is to describe how LBaaS will be implemented in
the Tricircle. LBaaS is an advanced service of Neutron, which allows for
proprietary and open-source load balancing technologies to drive the actual
load balancing of requests. Based on the networking guide of Ocata release,
LBaaS can be configured with an agent or Octavia. Given that the OpenStack
community try to take Octavia as the reference implementation of LBaaS, we
only enable LBaaS based on Octavia in the Tricircle.

Different from existing LBaaS implementation, Octavia accomplishes its
delivery of load balancing services by managing a fleet of virtual machines,
containers, or bare metal servers, collectively known as amphorae, which it
spins up on demand. This spec file is dedicated to how to implement LBaaS
in multiple regions with the Tricircle.

Overall Implementation
======================

The Tricircle is designed in a central-local fashion, where all the local
neutrons are managed by the central neutron. As a result, in order to adapt
the central-local design and the amphorae mechanism of
Octavia, we plan to deploy LBaaS as follows. ::

                +---------------------------+
                |                           |
                |      Central Neutron      |
                |                           |
                +---------------------------+
                       Central Region

  +----------------------------+    +-----------------------------+
  |     +----------------+     |    |     +----------------+      |
  |     |  LBaaS Octavia |     |    |     |  LBaaS Octavia |      |
  |     +----------------+     |    |     +----------------+      |
  | +------+ +---------------+ |    | +-------+ +---------------+ |
  | | Nova | | Local Neutron | |    | | Nova  | | Local Neutron | |
  | +------+ +---------------+ |    | +-------+ +---------------+ |
  +----------------------------+    +-----------------------------+
            Region One                          Region Two

As demonstrated in the figure above, for each region where a local neutron
is installed, admins can optionally choose to configure and install Octavia.
Typically, Octavia leverages nova installed in its region to spin up amphorae.
By employing load balancing softwares (e.g. haproxy) installed in the
amphorae and Virtual Router Redundancy Protocol (VRRP), a load balancer which
consists of a VIP and an amphora, can balance load across members with
high availability. However, under the central-local scenario, we plan to let
Octavia employ the central neutron in Central Region to manage networking
resources, while still employ services in its region to manage amphora.
Hence, the workflow of networking resource management in Tricircle can be
described as follows.

Tenant-->local neutron API-->neutron-LBaaS--->local Octavia--->central neutron

Specifically, when a tenant attempts to create a load balancer, he/she needs to
send a request to the local neutron-lbaas service. The service plugin of
neutron-lbaas then prepares for creating the load balancer, including
creating port via local plugin, inserting the info of the port into the
database, and so on. Next the service plugin triggers the creating function
of the corresponding driver of Octavia, i.e.,
Octavia.network.drivers.neutron.AllowedAddressPairsDriver to create the
amphora. During the creation, Octavia employs the central neutron to
complete a series of operations, for instance, allocating VIP, plugging
in VIP, updating databases. Given that the main features of managing
networking resource are implemented, we hence need to adapt the mechanism
of Octavia and neutron-lbaas by improving the functionalities of the local
and central plugins.

Considering the Tricircle is dedicated to enabling networking automation
across Neutrons, the implementation can be divided as two parts,
i.e., LBaaS members in one OpenStack instance, and LBaaS members in
multiple OpenStack instances.

LBaaS members in single region
==============================

For LBaaS in one region, after installing octavia, cloud tenants should
build a management network and two security groups for amphorae manually
in the central neutron. Next, tenants need to create an interface for health
management. Then, tenants need to configure the newly created networking
resources for octavia and let octavia employ central neutron to create
resources. Finally, tenants can create load balancers, listeners, pools,
and members in the local neutron. In this case, all the members of a
loadbalancer are in one region, regardless of whether the members reside
in the same subnet or not.

LBaaS members in multiple regions
=================================

1. members in the same subnet yet locating in different regions
---------------------------------------------------------------
As shown below. ::

  +-------------------------------+  +-----------------------+
  | +---------------------------+ |  |                       |
  | |    Amphora                | |  |                       |
  | |                           | |  |                       |
  | |  +-------+  +---------+   | |  |                       |
  | +--+ mgmt  +--+ subnet1 +---+ |  |                       |
  |    +-------+  +---------+     |  |                       |
  |                               |  |                       |
  | +--------------------------+  |  | +-------------------+ |
  | | +---------+  +---------+ |  |  | |    +---------+    | |
  | | | member1 |  | member2 | |  |  | |    | member3 |    | |
  | | +---------+  +---------+ |  |  | |    +---------+    | |
  | +--------------------------+  |  | +-------------------+ |
  |       network1(subnet1)       |  |   network1(subnet1)   |
  +-------------------------------+  +-----------------------+
             Region One                     Region Two
  Fig. 1. The scenario of balancing load across instances of one subnet which
  reside in different regions.

As shown in Fig. 1, suppose that a load balancer is created in Region one,
and hence a listener, a pool, and two members in subnet1. When adding an
instance in Region Two to the pool as a member, the local neutron creates
the network in Region Two. Members that locate in different regions yet
reside in the same subnet form a shared VLAN/VxLAN network. As a result,
the Tricircle supports adding members that locates in different regions to
a pool.

2. members residing in different subnets and regions
----------------------------------------------------
As shown below. ::

  +---------------------------------------+  +-----------------------+
  | +-----------------------------------+ |  |                       |
  | |            Amphora                | |  |                       |
  | |                                   | |  |                       |
  | | +---------+  +------+ +---------+ | |  |                       |
  | +-+ subnet2 +--+ mgmt +-+ subnet1 +-+ |  |                       |
  |   +---------+  +------+ +---------+   |  |                       |
  |                                       |  |                       |
  | +----------------------------------+  |  | +-------------------+ |
  | |                                  |  |  | |                   | |
  | |   +---------+      +---------+   |  |  | |    +---------+    | |
  | |   | member1 |      | member2 |   |  |  | |    | member3 |    | |
  | |   +---------+      +---------+   |  |  | |    +---------+    | |
  | |                                  |  |  | |                   | |
  | +----------------------------------+  |  | +-------------------+ |
  |           network1(subnet1)           |  |    network2(subnet2)  |
  +---------------------------------------+  +-----------------------+
                 Region One                         Region Two
  Fig. 2. The scenario of balancing load across instances of different subnets
  which reside in different regions as well.

As show in Fig. 2, supposing that a load balancer is created in region one, as
well as a listener, a pool, and two members in subnet1. When adding an instance
of subnet2 located in region two, the local neutron-lbaas queries the central
neutron whether subnet2 exist or not. If subnet2 exists, the local
neutron-lbaas employ octavia to plug a port of subnet2 to the amphora. This
triggers cross-region vxlan networking process, then the amphora can reach
the members. As a result, the LBaaS in multiple regions works.

Please note that LBaaS in multiple regions should not be applied to the local
network case. When adding a member in a local network which resides in other
regions, neutron-lbaas use 'get_subnet' will fail and returns "network not
located in current region"

Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

Configuration guide needs to be updated to introduce the configuration of
Octavia, local neutron, and central neutron.

References
==========

None
