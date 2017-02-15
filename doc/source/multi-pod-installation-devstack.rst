====================================
Multi-pod Installation with DevStack
====================================

Introduction
^^^^^^^^^^^^

In the single pod installation guide, we discuss how to deploy the Tricircle in
one single pod with DevStack. Besides the Tricircle API and the central Neutron
server, only one pod(one pod means one OpenStack instance) is running. Network
is created with the default network type: local. Local type network will be only
presented in one pod. If a local type network is already hosting virtual machines
in one pod, you can not use it to boot virtual machine in another pod. That is
to say, local type network doesn't support cross-pod l2 networking.

With multi-pod installation of the Tricircle, you can try out cross-pod l2
networking and cross-pod l3 networking features.

As the first step to support cross-pod l2 networking, we have added VLAN
network type to the Tricircle. When a VLAN type network created via the
central Neutron server is used to boot virtual machines in different pods, local
Neutron server in each pod will create a VLAN type network with the same VLAN
ID and physical network as the central network, so each pod should be configured
with the same VLAN allocation pool and physical network. Then virtual machines
in different pods can communicate with each other in the same physical network
with the same VLAN tag.

Cross-pod l3 networking is supported in two ways in the Tricircle. If two
networks connected to the router are of local type, we utilize a shared provider
VLAN network to achieve cross-pod l3 networking. Later we may also use VxLAN
network or multi-segment VLAN network. When a subnet is attached to a router via
the central Neutron server, the Tricircle not only creates corresponding subnet
and router in the pod, but also creates a VLAN type "bridge" network. Both
tenant network and "bridge" network are attached to the router. Each tenant will
have one allocated VLAN, which is shared by the tenant's "bridge" networks
across pods. The CIDRs of "bridge" networks for one tenant are also the same, so
the router interfaces in "bridge" networks across different pods can communicate
with each other via the provider VLAN network. By adding an extra route as
following::

  destination: CIDR of tenant network in another pod
  nexthop: "bridge" network interface ip in another pod

When a virtual machine sends a packet whose receiver is in another network and
in another pod, the packet first goes to router, then is forwarded to the router
in another pod according to the extra route, at last the packet is sent to the
target virtual machine. This route configuration job is triggered when user
attaches a subnet to a router via the central Neutron server and the job is
finished asynchronously.

If one of the network connected to the router is not local type, meaning that
cross-pod l2 networking is supported in this network(like VLAN type), and
the l2 network can be stretched into current pod, packets sent to the virtual
machine in this network will not pass through the "bridge" network. Instead,
packets first go to router, then are directly forwarded to the target virtual
machine via the l2 network. A l2 network's presence scope is determined by the
network's availability zone hint. If the l2 network is not able to be stretched
into the current pod, the packets will still pass through the "bridge network".
For example, let's say we have two pods, pod1 and pod2, and two availability
zones, az1 and az2. Pod1 belongs to az1 and pod2 belongs to az2. If the
availability zone hint of one VLAN type network is set to az1, this
network can not be stretched to pod2. So packets sent from pod2 to virtual
machines in this network still need to pass through the "bridge network".

Prerequisite
^^^^^^^^^^^^

In this guide we take two nodes deployment as an example. One node to run the
Tricircle API, the central Neutron server and one pod, the other one node to run
another pod. Both nodes have two network interfaces, for management network and
provider VLAN network. For VLAN network, the physical network infrastructure
should support VLAN tagging. If you would like to try north-south networking,
too, you should prepare one more network interface in the second node for the
external network. In this guide, the external network is also VLAN type, so the
local.conf sample is based on VLAN type external network setup. For the resource
requirements to setup each node, please refer to
`All-In-One Single Machine <http://docs.openstack.org/developer/devstack/guides/single-machine.html>`_
for installing DevStack in bare metal server and
`All-In-One Single VM <http://docs.openstack.org/developer/devstack/guides/single-vm.html>`_
for installing DevStack in virtual machine.


Setup
^^^^^

In pod1 in node1 for Tricircle service, central Neutron and OpenStack
RegionOne,

- 1 Install DevStack. Please refer to
  `DevStack document <http://docs.openstack.org/developer/devstack/>`_
  on how to install DevStack into single VM or bare metal server.

- 2 In DevStack folder, create a file local.conf, and copy the content of
  `local.conf node1 sample <https://github.com/openstack/tricircle/blob/master/devstack/local.conf.node_1.sample>`_
  to local.conf, change password in the file if needed.

- 3 Change the following options according to your environment

  - change HOST_IP to your management interface ip::

      HOST_IP=10.250.201.24

  - the format of Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS is
    (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
    you can change physical network name, but remember to adapt your change
    to the commands showed in this guide; also, change min VLAN and max vlan
    to adapt the VLAN range your physical network supports. You need to
    additionally specify the physical network "extern" to ensure the
    central neutron can create "extern" physical network which located in
    other pods::

      Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000,extern:3001:4000)

  - the format of OVS_BRIDGE_MAPPINGS is <physical network name>:<ovs bridge name>,
    you can change these names, but remember to adapt your change to the
    commands showed in this guide. You do not need specify the bridge mapping
    for "extern", because this physical network is located in other pods::

      OVS_BRIDGE_MAPPINGS=bridge:br-vlan

  - set TRICIRCLE_START_SERVICES to True to install the Tricircle service and
    central Neutron in node1::

      TRICIRCLE_START_SERVICES=True

- 4 Create OVS bridge and attach the VLAN network interface to it ::

    sudo ovs-vsctl add-br br-vlan
    sudo ovs-vsctl add-port br-vlan eth1

  br-vlan is the OVS bridge name you configure on OVS_PHYSICAL_BRIDGE, eth1 is
  the device name of your VLAN network interface

- 5 Run DevStack. In DevStack folder, run ::

    ./stack.sh

- 6 After DevStack successfully starts, begin to setup node2.

In pod2 in node2 for OpenStack RegionTwo,

- 1 Install DevStack. Please refer to
  `DevStack document <http://docs.openstack.org/developer/devstack/>`_
  on how to install DevStack into single VM or bare metal server.

- 2 In DevStack folder, create a file local.conf, and copy the content of
  `local.conf node2 sample <https://github.com/openstack/tricircle/blob/master/devstack/local.conf.node_2.sample>`_
  to local.conf, change password in the file if needed.

- 3 Change the following options according to your environment

  - change HOST_IP to your management interface ip::

      HOST_IP=10.250.201.25

  - change KEYSTONE_SERVICE_HOST to management interface ip of node1::

      KEYSTONE_SERVICE_HOST=10.250.201.24

  - change KEYSTONE_AUTH_HOST to management interface ip of node1::

      KEYSTONE_AUTH_HOST=10.250.201.24

  - the format of Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS is
    (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
    you can change physical network name, but remember to adapt your change
    to the commands showed in this guide; also, change min vlan and max vlan
    to adapt the vlan range your physical network supports::

      Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000,extern:3001:4000)

  - the format of OVS_BRIDGE_MAPPINGS is <physical network name>:<ovs bridge name>,
    you can change these names, but remember to adapt your change to the commands
    showed in this guide::

      OVS_BRIDGE_MAPPINGS=bridge:br-vlan,extern:br-ext

  - set TRICIRCLE_START_SERVICES to False(it's True by default) so Tricircle
    services and central Neutron will not be started in node2::

      TRICIRCLE_START_SERVICES=False

  In this guide, we define two physical networks in node2, one is "bridge" for
  bridge network, the other one is "extern" for external network. If you do not
  want to try l3 north-south networking, you can simply remove the "extern"
  part. The external network type we use in the guide is VLAN, if you want to
  use other network type like flat, please refer to
  `DevStack document <http://docs.openstack.org/developer/devstack/>`_.

- 4 Create OVS bridge and attach the VLAN network interface to it ::

    sudo ovs-vsctl add-br br-vlan
    sudo ovs-vsctl add-port br-vlan eth1
    sudo ovs-vsctl add-br br-ext
    sudo ovs-vsctl add-port br-ext eth2

  br-vlan and br-ext are the OVS bridge names you configure on
  OVS_PHYSICAL_BRIDGE, eth1 and eth2 are the device names of your VLAN network
  interfaces, for the "bridge" network and the external network.

- 5 Run DevStack. In DevStack folder, run ::

    ./stack.sh

- 6 After DevStack successfully starts, the setup is finished.

.. note:: In the newest version of codes, we may fail to boot an instance in
   node2. The reason is that Apache configuration file of Nova placement API
   doesn't grant access right to the placement API bin folder. You can use
   "screen -r" to check placement API is working well or not. If placement API
   is in stuck status, manually update "/etc/apache2/sites-enabled/placement-api.conf"
   placement API configuration file in node2 to add the following section::

       <Directory /usr/local/bin>
           Require all granted
       </Directory>

   After update, restart Apache service first, and then placement API.

How to play
^^^^^^^^^^^

- 1 After DevStack successfully starts, we need to create environment variables
  for the user (admin user as example in this guide). In DevStack folder ::

    source openrc admin admin

- 2 Unset the region name environment variable, so that the command can be
  issued to specified region in following commands as needed ::

    unset OS_REGION_NAME

- 3 Check if services have been correctly registered. Run ::

    openstack --os-region-name=RegionOne endpoint list

  you should get output looks like as following ::

    +----------------------------------+---------------+--------------+----------------+
    | ID                               | Region        | Service Name | Service Type   |
    +----------------------------------+---------------+--------------+----------------+
    | 4adaab1426d94959be46314b4bd277c2 | RegionOne     | glance       | image          |
    | 5314a11d168042ed85a1f32d40030b31 | RegionTwo     | nova_legacy  | compute_legacy |
    | ea43c53a8ab7493dacc4db079525c9b1 | RegionOne     | keystone     | identity       |
    | a1f263473edf4749853150178be1328d | RegionOne     | neutron      | network        |
    | ebea16ec07d94ed2b5356fb0a2a3223d | RegionTwo     | neutron      | network        |
    | 8d374672c09845f297755117ec868e11 | CentralRegion | tricircle    | Tricircle      |
    | e62e543bb9cf45f593641b2d00d72700 | RegionOne     | nova_legacy  | compute_legacy |
    | 540bdedfc449403b9befef3c2bfe3510 | RegionOne     | nova         | compute        |
    | d533429712954b29b9f37debb4f07605 | RegionTwo     | glance       | image          |
    | c8bdae9506cd443995ee3c89e811fb45 | CentralRegion | neutron      | network        |
    | 991d304dfcc14ccf8de4f00271fbfa22 | RegionTwo     | nova         | compute        |
    +----------------------------------+---------------+--------------+----------------+

  "CentralRegion" is the region you set in local.conf via CENTRAL_REGION_NAME,
  whose default value is "CentralRegion", we use it as the region for the
  Tricircle API and central Neutron server. "RegionOne" and "RegionTwo" are the
  normal OpenStack regions which includes Nova, Neutron and Glance. Shared
  Keystone service is registered in "RegionOne".

- 4 Get token for the later commands. Run ::

    openstack --os-region-name=RegionOne token issue

- 5 Create pod instances for the Tricircle to manage the mapping between
  availability zones and OpenStack instances, "$token" is obtained in step 4 ::

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
      -H "X-Auth-Token: $token" -d '{"pod": {"region_name":  "CentralRegion"}}'

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
      -H "X-Auth-Token: $token" -d '{"pod": {"region_name":  "RegionOne", "az_name": "az1"}}'

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
      -H "X-Auth-Token: $token" -d '{"pod": {"region_name":  "RegionTwo", "az_name": "az2"}}'

  Pay attention to "region_name" parameter we specify when creating pod. Pod name
  should exactly match the region name registered in Keystone. In the above
  commands, we create pods named "CentralRegion", "RegionOne" and "RegionTwo".

- 6 Create necessary resources in central Neutron server ::

    neutron --os-region-name=CentralRegion net-create net1
    neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    neutron --os-region-name=CentralRegion net-create net2
    neutron --os-region-name=CentralRegion subnet-create net2 10.0.2.0/24

  Please note that the net1 and net2 ID will be used in later step to boot VM.

- 7 Get image ID and flavor ID which will be used in VM booting ::

    glance --os-region-name=RegionOne image-list
    nova --os-region-name=RegionOne flavor-list
    glance --os-region-name=RegionTwo image-list
    nova --os-region-name=RegionTwo flavor-list

- 8 Boot virtual machines ::

    nova --os-region-name=RegionOne boot --flavor 1 --image $image1_id --nic net-id=$net1_id vm1
    nova --os-region-name=RegionTwo boot --flavor 1 --image $image2_id --nic net-id=$net2_id vm2

- 9 Verify the VMs are connected to the networks ::

    neutron --os-region-name=CentralRegion port-list
    neutron --os-region-name=RegionOne port-list
    nova --os-region-name=RegionOne list
    neutron --os-region-name=RegionTwo port-list
    nova --os-region-name=RegionTwo list

  The ip address of each VM could be found in local Neutron server and central
  Neutron server. The port has same uuid in local Neutron server and central
  Neutron Server.

- 10 Create external network and subnet ::

    curl -X POST http://127.0.0.1:20001/v2.0/networks -H "Content-Type: application/json" \
      -H "X-Auth-Token: $token" \
      -d '{"network": {"name": "ext-net", "admin_state_up": true, "router:external": true,  "provider:network_type": "vlan", "provider:physical_network": "extern", "availability_zone_hints": ["RegionTwo"]}}'
    neutron --os-region-name=CentralRegion subnet-create --name ext-subnet --disable-dhcp ext-net 163.3.124.0/24

  Pay attention that when creating external network, we need to pass
  "availability_zone_hints" parameter, which is the name of the pod that will
  host external network.

  *Currently external network needs to be created before attaching subnet to the
  router, because plugin needs to utilize external network information to setup
  bridge network when handling interface adding operation. This limitation will
  be removed later.*

- 11 Create router and attach subnets in central Neutron server ::

    neutron --os-region-name=CentralRegion router-create router
    neutron --os-region-name=CentralRegion router-interface-add router $subnet1_id
    neutron --os-region-name=CentralRegion router-interface-add router $subnet2_id

- 12 Set router external gateway in central Neutron server ::

    neutron --os-region-name=CentralRegion router-gateway-set router ext-net

  Now virtual machine in the subnet attached to the router should be able to
  ping machines in the external network. In our test, we use hypervisor tool
  to directly start a virtual machine in the external network to check the
  network connectivity.

- 13 Launch VNC console and test connection ::

    nova --os-region-name=RegionOne get-vnc-console vm1 novnc
    nova --os-region-name=RegionTwo get-vnc-console vm2 novnc

  You should be able to ping vm1 from vm2 and vice versa.

- 14 Create floating ip in central Neutron server ::

   neutron --os-region-name=CentralRegion floatingip-create ext-net

- 15 Associate floating ip ::

   neutron --os-region-name=CentralRegion floatingip-list
   neutron --os-region-name=CentralRegion port-list
   neutron --os-region-name=CentralRegion floatingip-associate $floatingip_id $port_id

  Now you should be able to access virtual machine with floating ip bound from
  the external network.
