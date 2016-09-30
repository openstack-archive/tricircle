=====================
Installation with pip
=====================

At the command line::

    $ pip install tricircle

Or, if you have virtualenvwrapper installed::

    $ mkvirtualenv tricircle
    $ pip install tricircle


======================================
Single node installation with DevStack
======================================

Now the Tricircle can be played with DevStack.

- 1 Install DevStack. Please refer to
  http://docs.openstack.org/developer/devstack/
  on how to install DevStack into single VM or physcial machine
- 2 In DevStack folder, create a file local.conf, and copy the content of
  https://github.com/openstack/tricircle/blob/stable/newton/devstack/local.conf.sample
  to local.conf, change password in the file if needed.
- 3 Run DevStack. In DevStack folder, run::

    ./stack.sh

- 4 After DevStack successfully starts, we need to create environment
  variables for the user (admin user as example in this document). In DevStack
  folder, create a file admin-openrc, and copy the content of
  https://github.com/openstack/tricircle/blob/stable/newton/devstack/admin-openrc.sh
  to the admin-openrc, change the password in the file if needed. Then run the
  following command to set the environment variables::

      source admin-openrc

 'admin-openrc' is used to create environment variable as the following::

      export OS_PROJECT_DOMAIN_ID=default
      export OS_USER_DOMAIN_ID=default
      export OS_PROJECT_NAME=admin
      export OS_TENANT_NAME=admin
      export OS_USERNAME=admin
      export OS_PASSWORD=password #change password as you set in your own environment
      export OS_AUTH_URL=http://127.0.0.1:5000
      export OS_IDENTITY_API_VERSION=3
      export OS_IMAGE_API_VERSION=2
      export OS_REGION_NAME=RegionOne



- 5 Check if services have been correctly registered. Run "openstack endpoint list" and
  you should get output look like as following::

        +----------------------------------+-----------+--------------+----------------+
        | ID                               | Region    | Service Name | Service Type   |
        +----------------------------------+-----------+--------------+----------------+
        | 230059e8533e4d389e034fd68257034b | RegionOne | glance       | image          |
        | 25180a0a08cb41f69de52a7773452b28 | RegionOne | nova         | compute        |
        | bd1ed1d6f0cc42398688a77bcc3bda91 | Pod1      | neutron      | network        |
        | 673736f54ec147b79e97c395afe832f9 | RegionOne | ec2          | ec2            |
        | fd7f188e2ba04ebd856d582828cdc50c | RegionOne | neutron      | network        |
        | ffb56fd8b24a4a27bf6a707a7f78157f | RegionOne | keystone     | identity       |
        | 88da40693bfa43b9b02e1478b1fa0bc6 | Pod1      | nova         | compute        |
        | f35d64c2ddc44c16a4f9dfcd76e23d9f | RegionOne | nova_legacy  | compute_legacy |
        | 8759b2941fe7469e9651de3f6a123998 | RegionOne | tricircle    | Cascading      |
        +----------------------------------+-----------+--------------+----------------+

  "RegionOne" is the region you set in local.conf via REGION_NAME, whose default
  value is "RegionOne", we use it as the region for the Tricircle instance;
  "Pod1" is the region set via "POD_REGION_NAME", new configuration option
  introduced by the Tricircle, we use it as the bottom OpenStack instance.
- 6 Create pod instances for Tricircle and bottom OpenStack. The "token" can be
  obtained from the Keystone. We can use the command to get the "token" as follows::

   openstack token issue

  The commands to create pod instances for the Tricircle and bottom OpenStack::

   curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
       -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

   curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
       -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

  Pay attention to "pod_name" parameter we specify when creating pod. Pod name
  should exactly match the region name registered in Keystone since it is used
  by the Tricircle to route API request. In the above commands, we create pods
  named "RegionOne" and "Pod1" for the Tricircle instance and bottom OpenStack
  instance.

  The Tricircle API service will automatically create an aggregate when user
  creates a bottom pod, so command "nova aggregate-list" will show the following
  result::

    +----+----------+-------------------+
    | Id | Name     | Availability Zone |
    +----+----------+-------------------+
    | 1  | ag_Pod1  | az1               |
    +----+----------+-------------------+

- 7 Create necessary resources to boot a virtual machine::

     nova flavor-create test 1 1024 10 1
     neutron net-create net1
     neutron subnet-create net1 10.0.0.0/24
     neutron net-list
     glance image-list

  Note that flavor mapping has not been implemented yet so the created flavor
  is just record saved in database as metadata. Actual flavor is saved in
  bottom OpenStack instance.
- 8 Boot a virtual machine::

     nova boot --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az1 vm1

- 9 Create, list, show and delete volume::

      cinder --debug create --availability-zone=az1 1
      cinder --debug list
      cinder --debug show $volume_id
      cinder --debug delete $volume_id
      cinder --debug list

- 10 Attach the volume to a server::

      cinder create --availability-zone=az1 1
      cinder list
      nova list
      nova volume-attach $vm_id $volume_id
      cinder volume show $volume_id


Verification with script
^^^^^^^^^^^^^^^^^^^^^^^^
A sample of admin-openrc.sh and an installation verification script can be found
in devstack/ in the Tricircle root folder. 'admin-openrc.sh' is used to create
environment variables for the admin user as the following::

  export OS_PROJECT_DOMAIN_ID=default
  export OS_USER_DOMAIN_ID=default
  export OS_PROJECT_NAME=admin
  export OS_TENANT_NAME=admin
  export OS_USERNAME=admin
  export OS_PASSWORD=password #change password as you set in your own environment
  export OS_AUTH_URL=http://127.0.0.1:5000
  export OS_IDENTITY_API_VERSION=3
  export OS_IMAGE_API_VERSION=2
  export OS_REGION_NAME=RegionOne

The command to use the admin-openrc.sh is::

  source tricircle/devstack/admin-openrc.sh

'verify_top_install.sh' script is to quickly verify the installation of
the Tricircle in Top OpenStack as the step 5-9 above and save the output
to logs.

Before verifying the installation, you should modify the script based on your
own environment.

- 1 The default post URL is 127.0.0.1, change it if needed.
- 2 The default create net1's networ address is 10.0.0.0/24, change it if
  needed.

Then you do the following steps to verify::

  cd tricircle/devstack/
  ./verify_top_install.sh 2>&1 | tee logs

=========================================================
Two nodes installation with DevStack (Local network type)
=========================================================

Introduction
^^^^^^^^^^^^

Now the Tricircle supports cross-pod l3 networking, all cross OpenStack L3
networking in this part means L3 networking for local network type. For
"local network", the network will be only presented in one bottom pod. If
a VM in one pod tries to attach to a local network in another pod, it should
be failed. So cross-pod L2 networking is not supported in local network.

To achieve cross-pod l3 networking, the Tricircle utilizes a shared provider
VLAN network at first phase. We are considering later using VxLAN network or
multi-segment VLAN network for L3 networking purpose. When a subnet is attached
to a router in top pod, the Tricircle not only creates corresponding subnet and
router in bottom pod, but also creates a VLAN type "bridge" network. Both tenant
network and "bridge" network are attached to bottom router. Each tenant will
have one allocated VLAN, which is shared by the tenant's "bridge" networks
across bottom pods. The CIDRs of "bridge" networks for one tenant are also the
same, so the router interfaces in "bridge" networks across different bottom pods
can communicate with each other via the provider VLAN network. By adding an
extra route as following::

  destination: CIDR of tenant network in another bottom pod
  nexthop: "bridge" network interface ip in another bottom pod

when a server sends a packet whose receiver is in another network and in
another bottom pod, the packet first goes to router namespace, then is
forwarded to the router namespace in another bottom pod according to the extra
route, at last the packet is sent to the target server. This configuration job
is triggered when user attaches a subnet to a router in top pod and finished
asynchronously.

This part of installation guide focuses on cross-pod l3 networking for local
network.

Prerequisite
^^^^^^^^^^^^

To play cross-pod L3 networking, two nodes are needed. One to run Tricircle
and one bottom pod, the other one to run another bottom pod. Both nodes have
two network interfaces, for management and provider VLAN network. For VLAN
network, the physical network infrastructure should support VLAN tagging. If
you would like to try north-south networking, too, you should prepare one more
network interface in the second node for external network. In this guide, the
external network is also vlan type, so the local.conf sample is based on vlan
type external network setup.

Setup
^^^^^
In node1,

- 1 Git clone DevStack.
- 2 Git clone Tricircle, or just download devstack/local.conf.node_1.sample.
- 3 Copy devstack/local.conf.node_1.sample to DevStack folder and rename it to
  local.conf, change password in the file if needed.
- 4 Change the following options according to your environment::

    HOST_IP=10.250.201.24

  change to your management interface ip::

    Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000)

  the format is (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
  you can change physical network name, but remember to adapt your change
  to the commands showed in this guide; also, change min vlan and max vlan
  to adapt the vlan range your physical network supports::

   OVS_BRIDGE_MAPPINGS=bridge:br-bridge

  the format is <physical network name>:<ovs bridge name>, you can change
  these names, but remember to adapt your change to the commands showed in
  this guide::

    Q_USE_PROVIDERNET_FOR_PUBLIC=True

  use this option if you would like to try L3 north-south networking.


- 5 Create OVS bridge and attach the VLAN network interface to it::

      sudo ovs-vsctl add-br br-bridge
      sudo ovs-vsctl add-port br-bridge eth1

  br-bridge is the OVS bridge name you configure on OVS_PHYSICAL_BRIDGE, eth1 is
  the device name of your VLAN network interface
- 6 Run DevStack.
- 7 After DevStack successfully starts, begin to setup node2.

In node2,

- 1 Git clone DevStack.
- 2 Git clone Tricircle, or just download devstack/local.conf.node_2.sample.
- 3 Copy devstack/local.conf.node_2.sample to DevStack folder and rename it to
  local.conf, change password in the file if needed.
- 4 Change the following options according to your environment::

   HOST_IP=10.250.201.25

  change to your management interface ip::

    KEYSTONE_SERVICE_HOST=10.250.201.24

  change to management interface ip of node1::

    KEYSTONE_AUTH_HOST=10.250.201.24

  change to management interface ip of node1::

   GLANCE_SERVICE_HOST=10.250.201.24

  change to management interface ip of node1::

    Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000,extern:3001:4000)

  the format is (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
  you can change physical network name, but remember to adapt your change
  to the commands showed in this guide; also, change min vlan and max vlan
  to adapt the vlan range your physical network supports::

    OVS_BRIDGE_MAPPINGS=bridge:br-bridge,extern:br-ext

  the format is <physical network name>:<ovs bridge name>, you can change
  these names, but remember to adapt your change to the commands showed in
  this guide::

    Q_USE_PROVIDERNET_FOR_PUBLIC=True

  use this option if you would like to try L3 north-south networking.

  In this guide, we define two physical networks in node2, one is "bridge" for
  bridge network, the other one is "extern" for external network. If you do not
  want to try L3 north-south networking, you can simply remove the "extern" part.
  The external network type we use in the guide is vlan, if you want to use other
  network type like flat, please refer to
  [DevStack document](http://docs.openstack.org/developer/devstack/).

- 5 Create OVS bridge and attach the VLAN network interface to it::

    sudo ovs-vsctl add-br br-bridge
    sudo ovs-vsctl add-port br-bridge eth1

  br-bridge is the OVS bridge name you configure on OVS_PHYSICAL_BRIDGE, eth1 is
  the device name of your VLAN network interface
- 6 Run DevStack.
- 7 After DevStack successfully starts, the setup is finished.

How to play
^^^^^^^^^^^

All the following operations are performed in node1.

- 1 After the setup is finished, we also need to create environment variables for the
  admin user. In DevStack folder, create a file admin-openrc, and copy the content of
  https://github.com/openstack/tricircle/blob/stable/newton/devstack/admin-openrc.sh to the
  admin-openrc, change the password in the file if needed. Then run the following command
  to set the environment variables::

     source admin-openrc

- 2 Check if services have been correctly registered. Run "openstack endpoint
  list" and you should get similar output as following::

      +----------------------------------+-----------+--------------+----------------+
      | ID                               | Region    | Service Name | Service Type   |
      +----------------------------------+-----------+--------------+----------------+
      | 1fadbddef9074f81b986131569c3741e | RegionOne | tricircle    | Cascading      |
      | a5c5c37613244cbab96230d9051af1a5 | RegionOne | ec2          | ec2            |
      | 809a3f7282f94c8e86f051e15988e6f5 | Pod2      | neutron      | network        |
      | e6ad9acc51074f1290fc9d128d236bca | Pod1      | neutron      | network        |
      | aee8a185fa6944b6860415a438c42c32 | RegionOne | keystone     | identity       |
      | 280ebc45bf9842b4b4156eb5f8f9eaa4 | RegionOne | glance       | image          |
      | aa54df57d7b942a1a327ed0722dba96e | Pod2      | nova_legacy  | compute_legacy |
      | aa25ae2a3f5a4e4d8bc0cae2f5fbb603 | Pod2      | nova         | compute        |
      | 932550311ae84539987bfe9eb874dea3 | RegionOne | nova_legacy  | compute_legacy |
      | f89fbeffd7e446d0a552e2a6cf7be2ec | Pod1      | nova         | compute        |
      | e2e19c164060456f8a1e75f8d3331f47 | Pod2      | ec2          | ec2            |
      | de698ad5c6794edd91e69f0e57113e97 | RegionOne | nova         | compute        |
      | 8a4b2332d2a4460ca3f740875236a967 | Pod2      | keystone     | identity       |
      | b3ad80035f8742f29d12df67bdc2f70c | RegionOne | neutron      | network        |
      +----------------------------------+-----------+--------------+----------------+

  "RegionOne" is the region you set in local.conf via REGION_NAME in node1, whose
  default value is "RegionOne", we use it as the region for Tricircle; "Pod1" is
  the region set via POD_REGION_NAME, new configuration option introduced by
  Tricircle, we use it as the bottom OpenStack; "Pod2" is the region you set via
  REGION_NAME in node2, we use it as another bottom OpenStack. In node2, you also
  need to set KEYSTONE_REGION_NAME the same as REGION_NAME in node1, which is
  "RegionOne" in this example. So services in node2 can interact with Keystone
  service in RegionOne.
- 3 Create pod instances for Tricircle and bottom OpenStack, the "token" can be obtained
  from the Keystone::

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
        -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
        -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

    curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
        -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod2", "az_name": "az2"}}'

- 4 Create network with AZ scheduler hints specified::

    neutron net-create --availability-zone-hint az1 net1
    neutron net-create --availability-zone-hint az2 net2

  We use "availability_zone_hints" attribute for user to specify the bottom pod he wants
  to create the bottom network.

  Here we create two networks separately bound to Pod1 and Pod2.
- 5 Create necessary resources to boot virtual machines::

    nova flavor-create test 1 1024 10 1
    neutron subnet-create net1 10.0.1.0/24
    neutron subnet-create net2 10.0.2.0/24
    neutron net-list
    glance image-list

- 6 Boot virtual machines::

     nova boot --flavor 1 --image $image_id --nic net-id=$net1_id --availability-zone az1 vm1
     nova boot --flavor 1 --image $image_id --nic net-id=$net2_id --availability-zone az2 vm2

- 7 Create router and attach interface::

    neutron router-create router
    neutron router-interface-add router $subnet1_id
    neutron router-interface-add router $subnet2_id

- 8 Launch VNC console and check connectivity
  By now, two networks are connected by the router, the two virtual machines
  should be able to communicate with each other, we can launch a VNC console to
  check. Currently Tricircle doesn't support VNC proxy, we need to go to bottom
  OpenStack to obtain a VNC console::

     nova --os-region-name Pod1 get-vnc-console vm1 novnc
     nova --os-region-name Pod2 get-vnc-console vm2 novnc

  Login one virtual machine via VNC and you should find it can "ping" the other
  virtual machine. Default security group is applied so no need to configure
  security group rule.

North-South Networking
^^^^^^^^^^^^^^^^^^^^^^

Before running DevStack in node2, you need to create another ovs bridge for
external network and then attach port::

    sudo ovs-vsctl add-br br-ext
    sudo ovs-vsctl add-port br-ext eth2

Below listed the operations related to north-south networking.

- 1 Create external network::

      curl -X POST http://127.0.0.1:9696/v2.0/networks -H "Content-Type: application/json" \
          -H "X-Auth-Token: $token" \
          -d '{"network": {"name": "ext-net", "admin_state_up": true, "router:external": true,  "provider:network_type": "vlan", "provider:physical_network": "extern", "availability_zone_hints": ["Pod2"]}}'

  Pay attention that when creating external network, we still need to pass
  "availability_zone_hints" parameter, but the value we pass is the name of pod,
  not the name of availability zone.

 *Currently external network needs to be created before attaching subnet to the
 router, because plugin needs to utilize external network information to setup
 bridge network when handling interface adding operation. This limitation will
 be removed later.*

- 2 Create external subnet::

   neutron subnet-create --name ext-subnet --disable-dhcp ext-net 163.3.124.0/24

- 3 Set router external gateway::

   neutron router-gateway-set router ext-net

 Now virtual machine in the subnet attached to the router should be able to
 "ping" machines in the external network. In our test, we use hypervisor tool
 to directly start a virtual machine in the external network to check the
 network connectivity.

- 4 Create floating ip::

   neutron floatingip-create ext-net

- 5 Associate floating ip::

   neutron floatingip-list
   neutron port-list
   neutron floatingip-associate $floatingip_id $port_id

 Now you should be able to access virtual machine with floating ip bound from
 the external network.

Verification with script
^^^^^^^^^^^^^^^^^^^^^^^^

A sample of admin-openrc.sh and an installation verification script can be
found in devstack/ directory. And a demo blog with virtualbox can be found in
https://wiki.openstack.org/wiki/Play_tricircle_with_virtualbox

Script 'verify_cross_pod_install.sh' is to quickly verify the installation of
the Tricircle in Cross Pod OpenStack as the contents above and save the output
to logs.

Before verifying the installation, some parameters should be modified to your
own environment.

- 1 The default URL is 127.0.0.1, change it if needed,
- 2 This script create a external network 10.50.11.0/26 according to the work
  environment, change it if needed.
- 3 This script create 2 subnets 10.0.1.0/24 and 10.0.2.0/24, Change these if
  needed.
- 4 The default created floating-ip is attached to the VM with port 10.0.2.3
  created by the subnets, modify it according to your environment.

Then do the followings in Node1 OpenStack to verify network functions::

   cd tricircle/devstack/
   ./verify_cross_pod_install.sh 2>&1 | tee logs

===============================================================
Two nodes installation with DevStack (Shared VLAN network type)
===============================================================

As the first step to support cross-pod L2 networking, we have added shared VLAN
network type to the Tricircle. If you have already set up cross-pod L3 networking
in your environment, you can directly try out cross-pod L2 networking with shared
VLAN network since by default Neutron server uses the same physical network to
create shared VLAN network as the bridge network used in cross-pod L3 networking.

After you prepare two nodes and finish the creating about the pod instances for the
Tricircle and bottom OpenStack accoding to the above method. You can create network
in Shared VLAN network type(No AZ parameter in the following command means the network
will be able spanning into all AZs)::

    neutron net-create --provider:network_type shared_vlan net1
    neutron net-create --provider:network_type shared_vlan net2

After you create the network, you can continue deploying according to the above section.
After all steps are finished, VMs should be able to ping each other if they are attached
to the same network, no matter the VM is in which bottom OpenStack.
