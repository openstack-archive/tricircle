===========================================
Cross Neutron VxLAN Networking in Tricircle
===========================================

Background
==========

Currently we only support VLAN as the cross-Neutron network type. For VLAN network
type, central plugin in Tricircle picks a physical network and allocates a VLAN
tag(or uses what users specify), then before the creation of local network,
local plugin queries this provider network information and creates the network
based on this information. Tricircle only guarantees that instance packets sent
out of hosts in different pods belonging to the same VLAN network will be tagged
with the same VLAN ID. Deployers need to carefully configure physical networks
and switch ports to make sure that packets can be transported correctly between
physical devices.

For more flexible deployment, VxLAN network type is a better choice. Compared
to 12-bit VLAN ID, 24-bit VxLAN ID can support more numbers of bridge networks
and cross-Neutron L2 networks. With MAC-in-UDP encapsulation of VxLAN network,
hosts in different pods only need to be IP routable to transport instance
packets.

Proposal
========

There are some challenges to support cross-Neutron VxLAN network.

1. How to keep VxLAN ID identical for the same VxLAN network across Neutron servers

2. How to synchronize tunnel endpoint information between pods

3. How to trigger L2 agents to build tunnels based on this information

4. How to support different back-ends, like ODL, L2 gateway

The first challenge can be solved as VLAN network does, we allocate VxLAN ID in
central plugin and local plugin will use the same VxLAN ID to create local
network. For the second challenge, we introduce a new table called
"shadow_agents" in Tricircle database, so central plugin can save the tunnel
endpoint information collected from one local Neutron server in this table
and use it to populate the information to other local Neutron servers when
needed. Here is the schema of the table:

.. csv-table:: Shadow Agent Table
  :header: Field, Type, Nullable, Key, Default

  id, string, no, primary, null
  pod_id, string, no, , null
  host, string, no, unique, null
  type, string, no, unique, null
  tunnel_ip, string, no, , null

**How to collect tunnel endpoint information**

When the host where a port will be located is determined, local Neutron server
will receive a port-update request containing host ID in the body. During the
process of this request, local plugin can query agent information that contains
tunnel endpoint information from local Neutron database with host ID and port
VIF type; then send tunnel endpoint information to central Neutron server by
issuing a port-update request with this information in the binding profile.

**How to populate tunnel endpoint information**

When the tunnel endpoint information in one pod is needed to be populated to
other pods, XJob will issue port-create requests to corresponding local Neutron
servers with tunnel endpoint information queried from Tricircle database in the
bodies. After receiving such request, local Neutron server will save tunnel
endpoint information by calling real core plugin's "create_or_update_agent"
method. This method comes from neutron.db.agent_db.AgentDbMixin class. Plugins
that support "agent" extension will have this method. Actually there's no such
agent daemon running in the target local Neutron server, but we insert a record
for it in the database so the local Neutron server will assume there exists an
agent. That's why we call it shadow agent.

The proposed solution for the third challenge is based on the shadow agent and
L2 population mechanism. In the original Neutron process, if the port status
is updated to active, L2 population mechanism driver does two things. First,
driver checks if the updated port is the first port in the target agent. If so,
driver collects tunnel endpoint information of other ports in the same network,
then sends the information to the target agent via RPC. Second, driver sends
the tunnel endpoint information of the updated port to other agents where ports
in the same network are located, also via RPC. L2 agents will build the tunnels
based on the information they received. To trigger the above processes to build
tunnels across Neutron servers, we further introduce shadow port.

Let's say we have two instance ports, port1 is located in host1 in pod1 and
port2 is located in host2 in pod2. To make L2 agent running in host1 build a
tunnel to host2, we create a port with the same properties of port2 in pod1.
As discussed above, local Neutron server will create shadow agent during the
process of port-create request, so local Neutron server in pod1 won't complain
that host2 doesn't exist. To trigger L2 population process, we then update the
port status to active, so L2 agent in host1 will receive tunnel endpoint
information of port2 and build the tunnel. Port status is a read-only property
so we can't directly update it via ReSTful API. Instead, we issue a port-update
request with a special key in the binding profile. After local Neutron server
receives such request, it pops the special key from the binding profile and
updates the port status to active. XJob daemon will take the job to create and
update shadow ports.

Here is the flow of shadow agent and shadow port process::

  +-------+       +---------+                                                          +---------+
  |       |       |         |     +---------+                                          |         |
  | Local |       | Local   |     |         |      +----------+       +------+         | Local   |
  | Nova  |       | Neutron |     | Central |      |          |       |      |         | Neutron |
  | Pod1  |       | Pod1    |     | Neutron |      | Database |       | XJob |         | Pod2    |
  |       |       |         |     |         |      |          |       |      |         |         |
  +---+---+       +---- ----+     +----+----+      +----+-----+       +--+---+         +----+----+
      |               |                |                |                |                  |
      | update port1  |                |                |                |                  |
      | [host id]     |                |                |                |                  |
      +--------------->                |                |                |                  |
      |               | update port1   |                |                |                  |
      |               | [agent info]   |                |                |                  |
      |               +---------------->                |                |                  |
      |               |                | save shadow    |                |                  |
      |               |                | agent info     |                |                  |
      |               |                +---------------->                |                  |
      |               |                |                |                |                  |
      |               |                | trigger shadow |                |                  |
      |               |                | port setup job |                |                  |
      |               |                | for pod1       |                |                  |
      |               |                +--------------------------------->                  |
      |               |                |                |                | query ports in   |
      |               |                |                |                | the same network |
      |               |                |                |                +------------------>
      |               |                |                |                |                  |
      |               |                |                |                |     return port2 |
      |               |                |                |                <------------------+
      |               |                |                |   query shadow |                  |
      |               |                |                |     agent info |                  |
      |               |                |                |      for port2 |                  |
      |               |                |                <----------------+                  |
      |               |                |                |                |                  |
      |               |                |                |  create shadow |                  |
      |               |                |                | port for port2 |                  |
      |               <--------------------------------------------------+                  |
      |               |                |                |                |                  |
      |               | create shadow  |                |                |                  |
      |               | agent and port |                |                |                  |
      |               +-----+          |                |                |                  |
      |               |     |          |                |                |                  |
      |               |     |          |                |                |                  |
      |               <-----+          |                |                |                  |
      |               |                |                |  update shadow |                  |
      |               |                |                | port to active |                  |
      |               <--------------------------------------------------+                  |
      |               |                |                |                |                  |
      |               | L2 population  |                |                | trigger shadow   |
      |               +-----+          |                |                | port setup job   |
      |               |     |          |                |                | for pod2         |
      |               |     |          |                |                +-----+            |
      |               <-----+          |                |                |     |            |
      |               |                |                |                |     |            |
      |               |                |                |                <-----+            |
      |               |                |                |                |                  |
      |               |                |                |                |                  |
      +               +                +                +                +                  +

Bridge network can support VxLAN network in the same way, we just create shadow
ports for router interface and router gateway. In the above graph, local Nova
server updates port with host ID to trigger the whole process. L3 agent will
update interface port and gateway port with host ID, so similar process will
be triggered to create shadow ports for router interface and router gateway.

Currently Neutron team is working on push notification [1]_, Neutron server
will send resource data to agents; agents cache this data and use it to do the
real job like configuring openvswitch, updating iptables, configuring dnsmasq,
etc. Agents don't need to retrieve resource data from Neutron server via RPC
any more. Based on push notification, if tunnel endpoint information is stored
in port object later, and this information supports updating via ReSTful API,
we can simplify the solution for challenge 3 and 4. We just need to create
shadow port containing tunnel endpoint information. This information will be
pushed to agents and agents use it to create necessary tunnels and flows.

**How to support different back-ends besides ML2+OVS implementation**

We consider two typical back-ends that can support cross-Neutron VxLAN networking,
L2 gateway and SDN controller like ODL. For L2 gateway, we consider only
supporting static tunnel endpoint information for L2 gateway at the first step.
Shadow agent and shadow port process is almost the same with the ML2+OVS
implementation. The difference is that, for L2 gateway, the tunnel IP of the
shadow agent is set to the tunnel endpoint of the L2 gateway. So after L2
population, L2 agents will create tunnels to the tunnel endpoint of the L2
gateway. For SDN controller, we assume that SDN controller has the ability to
manage tunnel endpoint information across Neutron servers, so Tricircle only helps to
allocate VxLAN ID and keep the VxLAN ID identical across Neutron servers for one network.
Shadow agent and shadow port process will not be used in this case. However, if
different SDN controllers are used in different pods, it will be hard for each
SDN controller to connect hosts managed by other SDN controllers since each SDN
controller has its own mechanism. This problem is discussed in this page [2]_.
One possible solution under Tricircle is as what L2 gateway does. We create
shadow ports that contain L2 gateway tunnel endpoint information so SDN
controller can build tunnels in its own way. We then configure L2 gateway in
each pod to forward the packets between L2 gateways. L2 gateways discussed here
are mostly hardware based, and can be controlled by SDN controller. SDN
controller will use ML2 mechanism driver to receive the L2 network context and
further control L2 gateways for the network.

To distinguish different back-ends, we will add a new configuration option
cross_pod_vxlan_mode whose valid values are "p2p", "l2gw" and "noop". Mode
"p2p" works for the ML2+OVS scenario, in this mode, shadow ports and shadow
agents containing host tunnel endpoint information are created; mode "l2gw"
works for the L2 gateway scenario, in this mode, shadow ports and shadow agents
containing L2 gateway tunnel endpoint information are created. For the SDN
controller scenario, as discussed above, if SDN controller can manage tunnel
endpoint information by itself, we only need to use "noop" mode, meaning that
neither shadow ports nor shadow agents will be created; or if SDN controller
can manage hardware L2 gateway, we can use "l2gw" mode.

Data Model Impact
=================

New table "shadow_agents" is added.

Dependencies
============

None

Documentation Impact
====================

- Update configuration guide to introduce options for VxLAN network
- Update networking guide to discuss new scenarios with VxLAN network
- Add release note about cross-Neutron VxLAN networking support

References
==========

.. [1] https://blueprints.launchpad.net/neutron/+spec/push-notifications
.. [2] http://etherealmind.com/help-wanted-stitching-a-federated-sdn-on-openstack-with-evpn/
