======================================
Cross pod L2 networking in Tricircle
======================================

Background
==========
The Tricircle provides unified OpenStack API gateway and networking automation
functionality. Those main functionalities allow cloud operators to manage
multiple OpenStack instances which are running in one site or multiple sites
as a single OpenStack cloud.

Each bottom OpenStack instance which is managed by the Tricircle is also called
a pod.

The Tricircle has the following components:

* Nova API-GW
* Cinder API-GW
* Neutron API Server with Neutron Tricircle plugin
* Admin API
* XJob
* DB

Nova API-GW provides the functionality to trigger automatic networking creation
when new VMs are being provisioned. Neutron Tricircle plug-in is the
functionality to create cross OpenStack L2/L3 networking for new VMs. After the
binding of tenant-id and pod finished in the Tricircle, Cinder API-GW and Nova
API-GW will pass the cinder api or nova api request to appropriate bottom
OpenStack instance.

Please refer to the Tricircle design blueprint[1], especially from
'7. Stateless Architecture Proposal' for the detail description of each
components.


Problem Description
===================
When a user wants to create a network in Neutron API Server, the user can
specify the 'availability_zone_hints'(AZ or az will be used for short for
availability zone) during network creation[5], in the Tricircle, the
'az_hints' means which AZ the network should be spreaded into. The 'az_hints'
meaning in Tricircle is a little different from the 'az_hints' meaning in
Neutron[5]. If no 'az_hints' was specified during network creation, this created
network will be spread into any AZ. If there is a list of 'az_hints' during the
network creation, that means the network should be able to be spread into these
AZs which are suggested by a list of 'az_hints'.

When a user creates VM or Volume, there is also one parameter called
availability zone. The AZ parameter is used for Volume and VM co-location, so
that the Volume and VM will be created into same bottom OpenStack instance.

When a VM is being attached to a network, the Tricircle will check whether a
VM's AZ is inside in the network's AZs scope. If a VM is not in the network's
AZs scope, the VM creation will be rejected.

Currently, the Tricircle only supports one pod in one AZ. And only supports a
network associated with one AZ. That means currently a tenant's network will
be presented only in one bottom OpenStack instance, that also means all VMs
connected to the network will be located at one bottom OpenStack instance.
If there are more than one pod in one AZ, refer to the dynamic pod binding[6].

There are lots of use cases where a tenant needs a network being able to be
spread out into multiple bottom OpenStack instances in one AZ or multiple AZs.

* Capacity expansion: tenants add VMs more and more, the capacity of one
  OpenStack may not be enough, then a new OpenStack instance has to be added
  to the cloud. But the tenant still wants to add new VMs into same network.

* Cross OpenStack network service chaining. Service chaining is based on
  the port-pairs. Leveraging the cross pod L2 networking capability which
  is provided by the Tricircle, the chaining could also be done by across sites.
  For example, vRouter1 in pod1, but vRouter2 in pod2, these two VMs could be
  chained.

* Applications are often required to run in different availability zones to
  achieve high availability. Application needs to be designed as
  Active-Standby/Active-Active/N-Way to achieve high availability, and some
  components inside one application are designed to work as distributed
  cluster, this design typically leads to state replication or heart
  beat among application components (directly or via replicated database
  services, or via private designed message format). When this kind of
  applications are distributedly deployed into multiple OpenStack instances,
  cross OpenStack L2 networking is needed to support heart beat
  or state replication.

* When a tenant's VMs are provisioned in different OpenStack instances, there
  is E-W (East-West) traffic for these VMs, the E-W traffic should be only
  visible to the tenant, and isolation is needed. If the traffic goes through
  N-S (North-South) via tenant level VPN, overhead is too much, and the
  orchestration for multiple site to site VPN connection is also complicated.
  Therefore cross OpenStack L2 networking to bridge the tenant's routers in
  different OpenStack instances can provide more light weight isolation.

* In hybrid cloud, there is cross L2 networking requirement between the
  private OpenStack and the public OpenStack. Cross pod L2 networking will
  help the VMs migration in this case and it's not necessary to change the
  IP/MAC/Security Group configuration during VM migration.

The spec[5] is to explain how one AZ can support more than one pod, and how
to schedule a proper pod during VM or Volume creation.

And this spec is to deal with the cross OpenStack L2 networking automation in
the Tricircle.

The simplest way to spread out L2 networking to multiple OpenStack instances
is to use same VLAN. But there is a lot of limitations: (1) A number of VLAN
segment is limited, (2) the VLAN network itself is not good to spread out
multiple sites, although you can use some gateways to do the same thing.

So flexible tenant level L2 networking across multiple OpenStack instances in
one site or in multiple sites is needed.

Proposed Change
===============

Cross pod L2 networking can be divided into three categories,
``Shared VLAN``, ``Shared VxLAN`` and ``Mixed VLAN/VxLAN``.

* Shared VLAN

  Network in each bottom OpenStack is VLAN type and has the same VLAN ID.
  If we want shared VLAN L2 networking to work in multi-site scenario, i.e.,
  Multiple OpenStack instances in multiple sites, physical gateway needs to
  be manually configured to make one VLAN networking be extended to other
  sites.

  *Manual setup physical gateway is out of the scope of this spec*

* Shared VxLAN

  Network in each bottom OpenStack instance is VxLAN type and has the same
  VxLAN ID.

  Leverage L2GW[2][3] to implement this type of L2 networking.

* Mixed VLAN/VxLAN

  Network in each bottom OpenStack instance may have different types and/or
  have different segment IDs.

  Leverage L2GW[2][3] to implement this type of L2 networking.

There is another network type called “Local Network”. For “Local Network”,
the network will be only presented in one bottom OpenStack instance. And the
network won't be presented in different bottom OpenStack instances. If a VM
in another pod tries to attach to the “Local Network”, it should be failed.
This use case is quite useful for the scenario in which cross pod L2
networking is not required, and one AZ will not include more than bottom
OpenStack instance.

Cross pod L2 networking will be able to be established dynamically during
tenant's VM is being provisioned.

There is assumption here that only one type of L2 networking will work in one
cloud deployment.


A Cross Pod L2 Networking Creation
------------------------------------

A cross pod L2 networking creation will be able to be done with the az_hint
attribute of the network. If az_hint includes one AZ or more AZs, the network
will be presented only in this AZ or these AZs, if no AZ in az_hint, it means
that the network can be extended to any bottom OpenStack.

There is a special use case for external network creation. For external
network creation, you need to specify the pod_id but not AZ in the az_hint
so that the external network will be only created in one specified pod per AZ.

 *Support of External network in multiple OpenStack instances in one AZ
 is out of scope of this spec.*

Pluggable L2 networking framework is proposed to deal with three types of
L2 cross pod networking, and it should be compatible with the
``Local Network``.

1. Type Driver under Tricircle Plugin in Neutron API server

* Type driver to distinguish different type of cross pod L2 networking. So
  the Tricircle plugin need to load type driver according to the configuration.
  The Tricircle can reuse the type driver of ML2 with update.

* Type driver to allocate VLAN segment id for shared VLAN L2 networking.

* Type driver to allocate VxLAN segment id for shared VxLAN L2 networking.

* Type driver for mixed VLAN/VxLAN to allocate VxLAN segment id for the
  network connecting L2GWs[2][3].

* Type driver for Local Network only updating ``network_type`` for the
  network to the Tricircle Neutron DB.

When a network creation request is received in Neutron API Server in the
Tricircle, the type driver will be called based on the configured network
type.

2. Nova API-GW to trigger the bottom networking automation

Nova API-GW can be aware of when a new VM is provisioned if boot VM api request
is received, therefore Nova API-GW is responsible for the network creation in
the bottom OpenStack instances.

Nova API-GW needs to get the network type from Neutron API server in the
Tricircle, and deal with the networking automation based on the network type:

* Shared VLAN
  Nova API-GW creates network in bottom OpenStack instance in which the VM will
  run with the VLAN segment id, network name and type that are retrieved from
  the Neutron API server in the Tricircle.

* Shared VxLAN
  Nova API-GW creates network in bottom OpenStack instance in which the VM will
  run with the VxLAN segment id, network name and type which are retrieved from
  Tricricle Neutron API server. After the network in the bottom OpenStack
  instance is created successfully, Nova API-GW needs to make this network in the
  bottom OpenStack instance as one of the segments in the network in the Tricircle.

* Mixed VLAN/VxLAN
  Nova API-GW creates network in different bottom OpenStack instance in which the
  VM will run with the VLAN or VxLAN segment id respectively, network name and type
  which are retrieved from Tricricle Neutron API server. After the network in the
  bottom OpenStack instances is created successfully, Nova API-GW needs to update
  network in the Tricircle with the segmentation information of bottom netwoks.

3. L2GW driver under Tricircle Plugin in Neutron API server

Tricircle plugin needs to support multi-segment network extension[4].

For Shared VxLAN or Mixed VLAN/VxLAN L2 network type, L2GW driver will utilize the
multi-segment network extension in Neutron API server to build the L2 network in the
Tricircle. Each network in the bottom OpenStack instance will be a segment for the
whole cross pod L2 networking in the Tricircle.

After the network in the bottom OpenStack instance was created successfully, Nova
API-GW will call Neutron server API to update the network in the Tricircle with a
new segment from the network in the bottom OpenStack instance.

If the network in the bottom OpenStack instance was removed successfully, Nova
API-GW will call Neutron server api to remove the segment in the bottom OpenStack
instance from network in the Tricircle.

When L2GW driver under Tricircle plugin in Neutron API server receives the
segment update request, L2GW driver will start async job to orchestrate L2GW API
for L2 networking automation[2][3].


Data model impact
-----------------

In database, we are considering setting physical_network in top OpenStack instance
as ``bottom_physical_network#bottom_pod_id`` to distinguish segmentation information
in different bottom OpenStack instance.

REST API impact
---------------

None

Security impact
---------------

None

Notifications impact
--------------------

None

Other end user impact
---------------------

None

Performance Impact
------------------

None

Other deployer impact
---------------------

None

Developer impact
----------------

None


Implementation
==============

**Local Network Implementation**

For Local Network, L2GW is not required. In this scenario, no cross pod L2/L3
networking is required.

A user creates network ``Net1`` with single AZ1 in az_hint, the Tricircle plugin
checks the configuration, if ``tenant_network_type`` equals ``local_network``,
it will invoke Local Network type driver. Local Network driver under the
Tricircle plugin will update ``network_type`` in database.

For exmaple, a user creates VM1 in AZ1 which has only one pod ``POD1``, and
connects it to network ``Net1``. ``Nova API-GW`` will send network creation
request to ``POD1`` and the VM will be booted in AZ1 (There should be only one
pod in AZ1).

If a user wants to create VM2 in AZ2 or ``POD2`` in AZ1, and connect it to
network ``Net1`` in the Tricircle, it would be failed. Because the ``Net1`` is
local_network type network and it is limited to present in ``POD1`` in AZ1 only.

**Shared VLAN Implementation**

For Shared VLAN, L2GW is not required. This is the most simplest cross pod
L2 networking for limited scenario. For example, with a small number of
networks, all VLANs are extended through physical gateway to support cross
site VLAN networking, or all pods under same core switch with same visible
VLAN ranges that supported by the core switch are connected by the core
switch.

when a user creates network called ``Net1``, the Tricircle plugin checks the
configuration. If ``tenant_network_type`` equals ``shared_vlan``, the
Tricircle will invoke Shared VLAN type driver. Shared VLAN driver will
create ``segment``, and assign ``network_type`` with VLAN, update
``segment`` and ``network_type`` and ``physical_network`` with DB

A user creates VM1 in AZ1, and connects it to network Net1. If VM1 will be
booted in ``POD1``, ``Nova API-GW`` needs to get the network information and
send network creation message to ``POD1``. Network creation message includes
``network_type`` and ``segment`` and ``physical_network``.

Then the user creates VM2 in AZ2, and connects it to network Net1. If VM will
be booted in ``POD2``, ``Nova API-GW`` needs to get the network information and
send create network message to ``POD2``. Create network message includes
``network_type`` and ``segment`` and ``physical_network``.

**Shared VxLAN Implementation**

A user creates network ``Net1``, the Tricircle plugin checks the configuration, if
``tenant_network_type`` equals ``shared_vxlan``, it will invoke shared VxLAN
driver. Shared VxLAN driver will allocate ``segment``, and assign
``network_type`` with VxLAN, and update network with ``segment`` and
``network_type`` with DB

A user creates VM1 in AZ1, and connects it to network ``Net1``. If VM1 will be
booted in ``POD1``, ``Nova API-GW`` needs to get the network information and send
create network message to ``POD1``, create network message includes
``network_type`` and ``segment``.

``Nova API-GW`` should update ``Net1`` in Tricircle with the segment information
got by ``POD1``.

Then the user creates VM2 in AZ2, and connects it to network ``Net1``. If VM2 will
be booted in ``POD2``,  ``Nova API-GW`` needs to get the network information and
send network creation massage to ``POD2``, network creation message includes
``network_type`` and ``segment``.

``Nova API-GW`` should update ``Net1`` in the Tricircle with the segment information
get by ``POD2``.

The Tricircle plugin detects that the network includes more than one segment
network, calls L2GW driver to start async job for cross pod networking for
``Net1``. The L2GW driver will create L2GW1 in ``POD1`` and L2GW2 in ``POD2``. In
``POD1``, L2GW1 will connect the local ``Net1`` and create L2GW remote connection
to L2GW2, then populate the information of MAC/IP which resides in L2GW1. In
``POD2``, L2GW2 will connect the local ``Net1`` and create L2GW remote connection
to L2GW1, then populate remote MAC/IP information which resides in ``POD1`` in L2GW2.

L2GW driver in the Tricircle will also detect the new port creation/deletion API
request. If port (MAC/IP) created or deleted in ``POD1`` or ``POD2``, it needs to
refresh the L2GW2 MAC/IP information.

Whether to populate the information of port (MAC/IP) should be configurable according
to L2GW capability. And only populate MAC/IP information for the ports that are not
resides in the same pod.

**Mixed VLAN/VxLAN**

To achieve cross pod L2 networking, L2GW will be used to connect L2 network in
different pods, using L2GW should work for Shared VxLAN and Mixed VLAN/VxLAN
scenario.

When L2GW connected with local network in the same OpenStack instance, no
matter it's VLAN or VxLAN or GRE, the L2GW should be able to connect the
local network, and because L2GW is extension of Neutron, only network
UUID should be enough for L2GW to connect the local network.

When admin user creates network in Tricircle, he/she specifies the network
type as one of the network type as discussed above. In the phase of creating
network in Tricircle, only one record is saved in the database, no network
will be created in bottom OpenStack.

After the network in the bottom created successfully, need to retrieve the
network information like segment id, network name and network type, and make
this network in the bottom pod as one of the segments in the network in
Tricircle.

In the Tricircle, network could be created by tenant or admin. For tenant, no way
to specify the network type and segment id, then default network type will
be used instead. When user uses the network to boot a VM, ``Nova API-GW``
checks the network type. For Mixed VLAN/VxLAN network, ``Nova API-GW`` first
creates network in bottom OpenStack without specifying network type and segment
ID, then updates the top network with bottom network segmentation information
returned by bottom OpenStack.

A user creates network ``Net1``, plugin checks the configuration, if
``tenant_network_type`` equals ``mixed_vlan_vxlan``, it will invoke mixed VLAN
and VxLAN driver. The driver needs to do nothing since segment is allocated
in bottom.

A user creates VM1 in AZ1, and connects it to the network ``Net1``, the VM is
booted in bottom ``POD1``, and ``Nova API-GW`` creates network in ``POD1`` and
queries the network detail segmentation information (using admin role), and
gets network type, segment id, then updates this new segment to the ``Net1``
in Tricircle ``Neutron API Server``.

Then the user creates another VM2, and with AZ info AZ2, then the VM should be
able to be booted in bottom ``POD2`` which is located in AZ2. And when VM2 should
be able to be booted in AZ2, ``Nova API-GW`` also creates a network in ``POD2``,
and queries the network information including segment and network type,
updates this new segment to the ``Net1`` in Tricircle ``Neutron API Server``.

The Tricircle plugin detects that the ``Net1`` includes more than one network
segments, calls L2GW driver to start async job for cross pod networking for
``Net1``. The L2GW driver will create L2GW1 in ``POD1`` and L2GW2 in ``POD2``. In
``POD1``, L2GW1 will connect the local ``Net1`` and create L2GW remote connection
to L2GW2, then populate information of MAC/IP which resides in ``POD2`` in L2GW1.
In ``POD2``, L2GW2 will connect the local ``Net1`` and create L2GW remote connection
to L2GW1, then populate remote MAC/IP information which resides in ``POD1`` in L2GW2.

L2GW driver in Tricircle will also detect the new port creation/deletion api
calling, if port (MAC/IP) created or deleted in ``POD1``, then needs to refresh
the L2GW2 MAC/IP information. If port (MAC/IP) created or deleted in ``POD2``,
then needs to refresh the L2GW1 MAC/IP information,

Whether to populate MAC/IP information should be configurable according to
L2GW capability. And only populate MAC/IP information for the ports that are
not resides in the same pod.

**L3 bridge network**

Current implementation without cross pod L2 networking.

* A special bridge network is created and connected to the routers in
  different bottom OpenStack instances. We configure the extra routes of the routers
  to route the packets from one OpenStack to another. In current
  implementation, we create this special bridge network in each bottom
  OpenStack with the same ``VLAN ID``, so we have an L2 network to connect
  the routers.

Difference between L2 networking for tenant's VM and for L3 bridging network.

* The creation of bridge network is triggered during attaching router
  interface and adding router external gateway.

* The L2 network for VM is triggered by ``Nova API-GW`` when a VM is to be
  created in one pod, and finds that there is no network, then the network
  will be created before the VM is booted, network or port parameter is
  required to boot VM. The IP/Mac for VM is allocated in the ``Tricircle``,
  top layer to avoid IP/mac collision if they are allocated separately in
  bottom pods.

After cross pod L2 networking is introduced, the L3 bridge network should
be updated too.

L3 bridge network N-S (North-South):

* For each tenant, one cross pod N-S bridge network should be created for router
  N-S inter-connection. Just replace the current shared VLAN N-S bridge network
  to corresponding Shared VxLAN or Mixed VLAN/VxLAN.

L3 bridge network E-W (East-West):

* When attaching router interface happened, for Shared VLAN, it will keep
  current process to establish E-W bridge network. For Shared VxLAN and Mixed
  VLAN/VxLAN, if a L2 network is able to expand to the current pod, then just
  expand the L2 network to the pod, all E-W traffic will go out from local L2
  network, then no bridge network is needed.

* For example, (Net1, Router1) in ``Pod1``,  (Net2, Router1) in ``Pod2``, if
  ``Net1`` is a cross pod L2 network, and can be expanded to Pod2, then will just
  expand ``Net1`` to Pod2. After the ``Net1`` expansion ( just like cross pod L2 networking
  to spread one network in multiple pods ), it’ll look like (Net1, Router1)
  in ``Pod1``, (Net1, Net2, Router1) in ``Pod2``, In ``Pod2``, no VM in ``Net1``, only for
  E-W traffic. Now the E-W traffic will look like this:

from Net2 to Net1:

Net2 in Pod2 -> Router1 in Pod2 -> Net1 in Pod2 -> L2GW in Pod2 ---> L2GW in
Pod1 -> Net1 in Pod1.

Note: The traffic for ``Net1`` in ``Pod2`` to ``Net1`` in ``Pod1`` can bypass the L2GW in
``Pod2``, that means outbound traffic can bypass the local L2GW if the remote VTEP of
L2GW is known to the local compute node and the packet from the local compute
node with VxLAN encapsulation cloud be routed to remote L2GW directly. It's up
to the L2GW implementation. With the inbound traffic through L2GW, the inbound
traffic to the VM will not be impacted by the VM migration from one host to
another.

If ``Net2`` is a cross pod L2 network, and can be expanded to ``Pod1`` too, then will
just expand ``Net2`` to ``Pod1``. After the ``Net2`` expansion(just like cross pod L2
networking to spread one network in multiple pods ), it’ll look like (Net2,
Net1, Router1) in ``Pod1``,  (Net1, Net2, Router1) in ``Pod2``, In ``Pod1``, no VM in
Net2, only for E-W traffic. Now the E-W traffic will look like this:
from ``Net1`` to ``Net2``:

Net1 in Pod1 -> Router1 in Pod1 -> Net2 in Pod1 -> L2GW in Pod1 ---> L2GW in
Pod2 -> Net2 in Pod2.

To limit the complexity, one network’s az_hint can only be specified when
creating, and no update is allowed, if az_hint need to be updated, you have
to delete the network and create again.

If the network can’t be expanded, then E-W bridge network is needed. For
example, Net1(AZ1, AZ2,AZ3), Router1; Net2(AZ4, AZ5, AZ6), Router1.
Then a cross pod L2 bridge network has to be established:

Net1(AZ1, AZ2, AZ3), Router1 --> E-W bridge network ---> Router1,
Net2(AZ4, AZ5, AZ6).

Assignee(s)
------------

Primary assignee:


Other contributors:


Work Items
------------

Dependencies
============

None


Testing
=======

None


Documentation Impact
====================

None


References
==========
[1] https://docs.google.com/document/d/18kZZ1snMOCD9IQvUKI5NVDzSASpw-QKj7l2zNqMEd3g/

[2] https://review.openstack.org/#/c/270786/

[3] https://github.com/openstack/networking-l2gw/blob/master/specs/kilo/l2-gateway-api.rst

[4] http://developer.openstack.org/api-ref-networking-v2-ext.html#networks-multi-provider-ext

[5] http://docs.openstack.org/mitaka/networking-guide/adv-config-availability-zone.html

[6] https://review.openstack.org/#/c/306224/