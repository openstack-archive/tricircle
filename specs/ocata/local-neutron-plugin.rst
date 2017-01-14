==============================
Tricircle Local Neutron Plugin
==============================

Background
==========

One of the key value we would like to achieve via the Tricircle project is to
provide networking automation functionality across several OpenStack instances.
Each OpenStack instance runs its own Nova and Neutron services but shares the
same Keystone service or uses federated Keystone, which is a multi-region
deployment mode. With networking automation, virtual machines or bare metals
booted in different OpenStack instances can inter-communicate via layer2 or
layer3 network.

Considering the cross OpenStack layer2 network case, if Neutron service in each
OpenStack instance allocates ip address independently, the same ip address
could be assigned to virtual machines in different OpenStack instances, thus ip
address conflict could occur. One straightforward solution to this problem is
to divide the ip allocation pool into several parts and each OpenStack instance
has one. The drawback is that since virtual machines are not distributed evenly
in each OpenStack instance, we may see some OpenStack instances uses up ip
addresses while other OpenStack instances still have ip addresses not
allocated. What's worse, dividing the ip allocation pool makes it impossible
for us to process virtual machine migration from one OpenStack instance to
another.

Thanks to Neutron's flexible plugin framework, by writing a new plugin and
configuring Neutron server to use it, developers can define what Neutron server
should do after receiving a network resources operation request. So for the
ip address conflict issue discussed above, we decide to run one central Neutron
server with the Tricircle central Neutron plugin(abbr: "central plugin") to
manage ip allocation pool centrally.

Besides central plugin, we need a bridge to connect central and local Neutron
servers since each OpenStack instance has its own local Nova and Neutron server
but these two services are not aware of the central Neutron server. This bridge
should validate requested network data via the central Neutron server, then
create necessary network resources in the target OpenStack instance with the
data retrieved from the central Neutron server.

Local Plugin
============

For connecting central and local Neutron servers, Neutron plugin is again a
good place for us to build the bridge. We can write our own plugin, the
Tricircle local Neutron plugin(abbr: "local plugin") to trigger the cross
OpenStack networking automation in local Neutron server. During virtual machine
booting, local Nova server will interact with local Neutron server to query
network or create port, which will trigger local plugin to retrieve data from
central Neutron server and create necessary network resources according to the
data. To support different core plugins, we will introduce a new option
"real_core_plugin" in the "tricircle" configuration group. During
initialization, local plugin will load the plugin specified by
"real_core_plugin". Local plugin only adds logic to interact with central
Neutron server, but invokes the real core plugin to finish the CRUD operations
of local network resources. The following graph shows the relation between user
and Nova and Neutron servers: ::

                   +------+
                   | user |
                   +-+--+-+
                     |  |
         +-----------+  +----------------------+
         |  boot vm         create and query   |
         |                  network resource   |
         v                                     |
    +----+-------+                             |
    | local Nova |     xxxxxxxxxxxxxxx         |
    +----+-------+   xxx             xxx       |
         |          xx                 xx      |
         +---+    xxx      +--------+   xxx    |
             |    x        |        |     x    |
             |    x        |        |     x    |
             v    V        |        v     x    v
    +--------+---------+   |   +----+----------+----+
    | local Neutron    |   |   | central Neutron    |
    | +--------------+ |   |   | +----------------+ |
    | | local plugin | |   |   | | central plugin | |
    | +--------------+ |   |   | +----------------+ |
    +------------------+   |   +--------------------+
             |             |
             +-------------+

Next using virtual machine booting procedure to elaborate how local plugin
works. To begin with, user creates network and subnet via central Neutron
server. Then this user passes the network id as the requested network
information to local Nova server to boot a virtual machine. During parameter
validation, local Nova server queries local Neutron server to ensure the
passed-in network id is valid, which is a "network-get" request. In the
"network-get" handle function, local plugin first checks if local Neutron
already has a network with that id. If not, local plugin retrieves network and
also subnet information from central Neutron server then creates network and
subnet based on this information. User may pass an invalid network id by
mistake, in this case, local plugin will receive a 404 response from central
Neutron server, it just returns a 404 response to local Nova server.

After the network id validation passes, local Nova server continues to schedule
a host so compute manager running in that host will do the left works. Compute
manager creates a port in the requested network via local Neutron server, which
is a "port-create" request. In the "port-create" handle function, local plugin
sends the same request to central Neutron server to create a port, and uses
the returned port information to create a local port. With local plugin, we
ensure all ip addresses are allocated by central Neutron server.

At the end of the network setup of the virtual machine, compute manager issues
a "port-update" request to local Neutron server to associate the host with the
port. In the "port-update" handle function, local plugin recognizes that this
request is sent from local Nova server by the request body that the request
body contains host information, so it sends a "port-update" request to central
Neutron server with region name in the request body. In Keystone, we register
services inside one OpenStack instance as one unique region, so we can use
region name to identify one OpenStack instance. After receiving the request,
central Neutron server is informed that one virtual machine port is correctly
setup in one OpenStack instance, so it starts the cross OpenStack networking
automation process, like security group rule population, tunnel setup for
layer2 communication and route setup for layer3 communication, which are done
by making Neutron API call to each local Neutron server.


Implementation
==============

Implementation details of the local plugin is discussed in this section.

Resource Id
-----------

Local plugin always retrieves data of networks resources from central Neutron
server and use these data to create network resources in local Neutron server.
During the creation of these network resources, we need to guarantee resource
ids in central and local server the same. Consider the scenario that user
creates a port via central Neutron server then use this port to boot a virtual
machine. After local Nova server receives the request, it will use the port id
to create a tap device for the virtual machine. If port ids in central and
local Neutron servers are different, OVS agent can't correctly recognize the
tap device and configure it. As a result, virtual machine fails to connect to
the network. Fortunately, database access module in Neutron allow us to specify
id before creating the resource record, so in local plugin, we just specify id
the same as central resource's to create local resource.

Network Type Adaption
---------------------

Two network types are supported currently in central plugin, which are local
and vlan type. Before creating network based on information retrieved
from central Neutron server, local plugin needs to adapt network type. For
local type, local plugin creates the network without specifying the network
type, so the default tenant network type is used. For vlan type, local plugin
keeps the network type, segmentation id and physical network parameter.

We plan to support another two network types later. They are shared_vxlan and
mixed network type. For shared_vxlan type, local plugin changes the network
type parameter from "shared_vxlan" to "vxlan", but keeps the segmentation id
parameter(vxlan type doesn't need physical network parameter). For mixed type,
like local type, local plugin uses the default tenant network type to create
the network, but it needs to do one more thing, that is to save the segment
information in central Neutron server. Neutron has a extension which allows one
network to carry multiple segments information[1], so segment information of
each local network can all be saved in the central network.

Dhcp Port Handle
----------------

After local subnet creation, local Neutron server will schedule one dhcp agent
for that subnet, and dhcp agent will automatically create a dhcp port. The ip
address of this dhcp port is not allocated by central Neutron server, so we may
encounter ip address conflict. We need to address this problem to ensure all ip
addresses are allocated by central Neutron server.

Here is the approach. After central Neutron server receives subnet creation
subnet, central plugin not only creates the requested subnet, but also create a
port to pre-allocate an ip address for the dhcp port. So during creation of
local subnet, local plugin will query central Neutron server to retrieve the
data of the pre-created port and use its ip address to create a local dhcp
port. The "device_id" of the dhcp port is set to "reserved_dhcp_port" so after
one dhcp agent is scheduled, it will use this port other than create a new one.

Gateway Port Handle
-------------------

If cross OpenStack layer2 networking is enabled in one network, we need to
allocate one gateway ip for that network in each OpenStack instance. The reason
is that we want layer3 routing to be finished locally in each OpenStack
instance. If all the OpenStack instances have the same gateway ip, packets sent
to the gateway may reach the remote one, so the path is not the best and not
predictable.

How we address this problem in local plugin is that before creating local
subnet, local plugin sends request to central Neutron server to create an
"gateway port", then uses the ip of this port as the gateway ip of the local
subnet. Name of the gateway port includes the region name of the OpenStack
instance and the id of the subnet so each OpenStack instance can have its own
gateway port and gateway ip for one specific subnet.

Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

Installation guide needs to be updated to introduce the configuration of
central and local plugin.

References
==========
[1] https://blueprints.launchpad.net/neutron/+spec/ml2-multi-segment-api
