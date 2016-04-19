# Tricircle

(The original PoC source code, please switch to
["poc"](https://github.com/openstack/tricircle/tree/poc) tag, or
["stable/fortest"](https://github.com/openstack/tricircle/tree/stable/fortest)
branch)

Tricircle is an OpenStack project that aims to deal with multiple OpenStack
deployment across multiple data centers. It provides users a single management
view by having only one Tricircle instance on behalf of all the involved
OpenStack instances.

Tricircle presents one big region to the end user in KeyStone. And each
OpenStack instance, which is called a pod, is a sub-region of Tricircle in
KeyStone, and not visible to end user directly.

Tricircle acts as OpenStack API gateway, can accept all OpenStack API calls
and forward the API calls to regarding OpenStack instance(pod), and deal with
cross pod networking automaticly.

The end user can see avaialbility zone (AZ in short) and use AZ to provision
VM, Volume, even Network through Tricircle.

Similar as AWS, one AZ can includes many pods, and a tenant's resources will
be bound to specific pods automaticly.

## Project Resources
License: Apache 2.0

- Design documentation: [Tricircle Design Blueprint](https://docs.google.com/document/d/18kZZ1snMOCD9IQvUKI5NVDzSASpw-QKj7l2zNqMEd3g/)
- Wiki: https://wiki.openstack.org/wiki/tricircle
- Documentation: http://docs.openstack.org/developer/tricircle
- Source: https://github.com/openstack/tricircle
- Bugs: http://bugs.launchpad.net/tricircle
- Blueprints: https://launchpad.net/tricircle

## Play with DevStack
Now stateless design can be played with DevStack.

- 1 Git clone DevStack of stable/mitaka branch.
```
git clone https://github.com/openstack-dev/devstack.git -b stable/mitaka
```
- 2 Git clone Tricircle of stable/mitaka branch, or just download
devstack/local.conf.sample.
```
git clone https://github.com/openstack/tricircle.git -b stable/mitaka
```
- 3 Copy devstack/local.conf.sample to DevStack folder and rename it to
local.conf, change password in the file if needed.
- 4 Run DevStack.
- 5 After DevStack successfully starts, check if services have been correctly
registered. Run "openstack endpoint list" and you should get similar output
as following:
```
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
```
"RegionOne" is the region you set in local.conf via REGION_NAME, whose default
value is "RegionOne", we use it as the region for top OpenStack(Tricircle);
"Pod1" is the region set via "POD_REGION_NAME", new configuration option
introduced by Tricircle, we use it as the bottom OpenStack.
- 6 Create pod instances for Tricircle and bottom OpenStack
```
curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'
```
Pay attention to "pod_name" parameter we specify when creating pod. Pod name
should exactly match the region name registered in Keystone since it is used
by Tricircle to route API request. In the above commands, we create pods named
"RegionOne" and "Pod1" for top OpenStack(Tricircle) and bottom OpenStack.
Tricircle API service will automatically create a aggregate when user creates
a bottom pod, so command "nova aggregate-list" will show the following result:
```
+----+----------+-------------------+
| Id | Name     | Availability Zone |
+----+----------+-------------------+
| 1  | ag_Pod1  | az1               |
+----+----------+-------------------+
```
- 7 Create necessary resources to boot a virtual machine.
```
nova flavor-create test 1 1024 10 1
neutron net-create net1
neutron subnet-create net1 10.0.0.0/24
glance image-list
```
Note that flavor mapping has not been implemented yet so the created flavor is
just a database record and actually flavor in bottom OpenStack with the same id
will be used.
- 8 Boot a virtual machine.
```
nova boot --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az1 vm1
```
- 9 Create, list, show and delete volume.
```
cinder --debug create --availability-zone=az1 1
cinder --debug list
cinder --debug show $volume_id
cinder --debug delete $volume_id
cinder --debug list
```
### Quick Verify

A sample of admin-openrc.sh and an installation verification script can be found
in devstack/ directory.

#### admin-openrc.sh

Create client environment variables for the admin user as the following:

```
export OS_PROJECT_DOMAIN_ID=default
export OS_USER_DOMAIN_ID=default
export OS_PROJECT_NAME=admin
export OS_TENANT_NAME=admin
export OS_USERNAME=admin
export OS_PASSWORD=password #change password as you set in your own environment
export OS_AUTH_URL=http://127.0.0.1:5000
export OS_IDENTITY_API_VERSION=3  #It's very important to set region name of top openstack,
                                  #because tricircle has different API urls.
export OS_IMAGE_API_VERSION=2
export OS_REGION_NAME=RegionOne

```
The command to use the admin-openrc.sh is:

```
source tricircle/devstack/admin-openrc.sh
```

#### verify_top_install.sh

This script is to quickly verify the installation of Tricircle in Top OpenStack
as the step 5-9 above and save the output to logs.
Before verifying the installation, you should modify the script to your own
environment.

- 1 The default post URL is 127.0.0.1, change it if needed,
- 2 The default create net1 is 10.0.0.0/24, change it if needed.

Then you do the following steps in Top OpenStack to verify:

```
cd tricircle/devstack/
./verify_top_install.sh 2>&1 | tee logs
```

## Cross-pod L3 networking with DevStack
Now stateless design supports cross-pod l3 networking.

### Introduction

To achieve cross-pod l3 networking, Tricircle utilizes a shared provider VLAN
network at first phase. We are considering later using DCI controller to create
a multi-segment VLAN network, VxLAN network for L3 networking purpose. When a
subnet is attached to a router in top pod, Tricircle not only creates corresponding
subnet and router in bottom pod, but also creates a VLAN type "bridge" network.
Both tenant network and "bridge" network are attached to bottom router. Each
tenant will have one allocated VLAN, which is shared by the tenant's "bridge"
networks across bottom pods. The CIDRs of "bridge" networks for one tenant are
also the same, so the router interfaces in "bridge" networks across different
bottom pods can communicate with each other via the provider VLAN network. By
adding an extra route as following:
```
destination: CIDR of tenant network in another bottom pod
nexthop: "bridge" network interface ip in another bottom pod
```
when a server sends a packet whose receiver is in another network and in
another bottom pod, the packet first goes to router namespace, then is
forwarded to the router namespace in another bottom pod according to the extra
route, at last the packet is sent to the target server. This configuration job
is triggered when user attaches a subnet to a router in top pod and finished
asynchronously.

Currently cross-pod L2 networking is not supported yet, so tenant networks
cannot cross pods, that is to say, one network in top pod can only locate in
one bottom pod, tenant network is bound to bottom pod. Otherwise we cannot
correctly configure extra route since for one destination CIDR, we have more
than one possible nexthop addresses.

> When cross-pod L2 networking is introduced, L2GW will be used to connect L2
> network in different pods. No extra route is required to connect L2 network.
> All L3 traffic will be forwarded to the local L2 network, then go to the
> server in another pod via the L2GW.

We use "availability_zone_hints" attribute for user to specify the bottom pod
he wants to create the bottom network. Currently we do not support attaching
a network to a router without setting "availability_zone_hints" attribute of
the network.

### Prerequisite

To play cross-pod L3 networking, two nodes are needed. One to run Tricircle
and one bottom pod, the other one to run another bottom pod. Both nodes have
two network interfaces, for management and provider VLAN network. For VLAN
network, the physical network infrastructure should support VLAN tagging. If
you would like to try north-south networking, too, you should prepare one more
network interface in the second node for external network. In this guide, the
external network is also vlan type, so the local.conf sample is based on vlan
type external network setup.

> DevStack supports multiple regions sharing the same Keystone, but one recent
> merged [patch](https://github.com/openstack-dev/devstack/commit/923be5f791c78fa9f21b2e217a6b61328c493a38#diff-4f76c30de6fd72bd49643dbcf1007a61)
> introduces a bug to DevStack so you may have problem deploying Tricircle if
> you use the newest DevStack code. One quick fix is:
```
> diff --git a/stack.sh b/stack.sh
> index c21ff77..0f8251e 100755
> --- a/stack.sh
> +++ b/stack.sh
> @@ -1024,7 +1024,7 @@ export OS_USER_DOMAIN_ID=default
>  export OS_PASSWORD=$ADMIN_PASSWORD
>  export OS_PROJECT_NAME=admin
>  export OS_PROJECT_DOMAIN_ID=default
> -export OS_REGION_NAME=$REGION_NAME
> +export OS_REGION_NAME=RegionOne
```
> RegionOne is the region name of top OpenStack(Tricircle).

### Setup

In node1,

- 1 Git clone DevStack of stable/mitaka branch.
```
git clone https://github.com/openstack-dev/devstack.git -b stable/mitaka
```
- 2 Git clone Tricircle of stable/mitaka branch, or just download
devstack/local.conf.node_1.sample.
```
git clone https://github.com/openstack/tricircle.git -b stable/mitaka
```
- 3 Copy devstack/local.conf.node_1.sample to DevStack folder and rename it to
local.conf, change password in the file if needed.
- 4 Change the following options according to your environment:
```
HOST_IP=10.250.201.24
    - change to your management interface ip.
Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000)
    - the format is (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
      you can change physical network name, but remember to adapt your change to the
      commands showed in this guide; also, change min vlan and max vlan to adapt the
      vlan range your physical network supports.
OVS_BRIDGE_MAPPINGS=bridge:br-bridge
    - the format is <physical network name>:<ovs bridge name>, you can change these names,
      but remember to adapt your change to the commands showed in this guide.
Q_USE_PROVIDERNET_FOR_PUBLIC=True
    - use this option if you would like to try L3 north-south networking.
```
Tricircle doesn't support security group currently so we use these two options
to disable security group functionality.
```
Q_USE_SECGROUP=False
LIBVIRT_FIREWALL_DRIVER=nova.virt.firewall.NoopFirewallDriver
```
- 5 Create OVS bridge and attach the VLAN network interface to it
```
sudo ovs-vsctl add-br br-bridge
sudo ovs-vsctl add-port br-bridge eth1
```
br-bridge is the OVS bridge name you configure on OVS_PHYSICAL_BRIDGE, eth1 is
the device name of your VLAN network interface
- 6 Run DevStack.
- 7 After DevStack successfully starts, begin to setup node2.

In node2,

- 1 Git clone DevStack of stable/mitaka branch.
```
git clone https://github.com/openstack-dev/devstack.git -b stable/mitaka
```
- 2 Git clone Tricircle of stable/mitaka branch, or just download
devstack/local.conf.node_2.sample.
```
git clone https://github.com/openstack/tricircle.git -b stable/mitaka
```
- 3 Copy devstack/local.conf.node_2.sample to DevStack folder and rename it to
local.conf, change password in the file if needed.
- 4 Change the following options according to your environment:
```
HOST_IP=10.250.201.25
    - change to your management interface ip.
KEYSTONE_SERVICE_HOST=10.250.201.24
    - change to management interface ip of node1.
KEYSTONE_AUTH_HOST=10.250.201.24
    - change to management interface ip of node1.
GLANCE_SERVICE_HOST=10.250.201.24
    - change to management interface ip of node1.
Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=(network_vlan_ranges=bridge:2001:3000,extern:3001:4000)
    - the format is (network_vlan_ranges=<physical network name>:<min vlan>:<max vlan>),
      you can change physical network name, but remember to adapt your change to the
      commands showed in this guide; also, change min vlan and max vlan to adapt the
      vlan range your physical network supports.
OVS_BRIDGE_MAPPINGS=bridge:br-bridge,extern:br-ext
    - the format is <physical network name>:<ovs bridge name>, you can change these names,
      but remember to adapt your change to the commands showed in this guide.
Q_USE_PROVIDERNET_FOR_PUBLIC=True
    - use this option if you would like to try L3 north-south networking.
```
In this guide, we define two physical networks in node2, one is "bridge" for
bridge network, the other one is "extern" for external network. If you do not
want to try L3 north-south networking, you can simply remove the "extern" part.
The external network type we use in the guide is vlan, if you want to use other
network type like flat, please refer to
[DevStack document](http://docs.openstack.org/developer/devstack/).

- 5 Create OVS bridge and attach the VLAN network interface to it
```
sudo ovs-vsctl add-br br-bridge
sudo ovs-vsctl add-port br-bridge eth1
```
br-bridge is the OVS bridge name you configure on OVS_PHYSICAL_BRIDGE, eth1 is
the device name of your VLAN network interface
- 6 Run DevStack.
- 7 After DevStack successfully starts, the setup is finished.

### How to play
All the following operations are performed in node1

- 1 Check if services have been correctly registered. Run "openstack endpoint
list" and you should get similar output as following:
```
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
```
"RegionOne" is the region you set in local.conf via REGION_NAME in node1, whose
default value is "RegionOne", we use it as the region for Tricircle; "Pod1" is
the region set via POD_REGION_NAME, new configuration option introduced by
Tricircle, we use it as the bottom OpenStack; "Pod2" is the region you set via
REGION_NAME in node2, we use it as another bottom OpenStack.
- 2 Create pod instances for Tricircle and bottom OpenStack
```
curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod2", "az_name": "az2"}}'
```
- 3 Create network with AZ scheduler hints specified
```
curl -X POST http://127.0.0.1:9696/v2.0/networks -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" \
    -d '{"network": {"name": "net1", "admin_state_up": true, "availability_zone_hints": ["az1"]}}'
curl -X POST http://127.0.0.1:9696/v2.0/networks -H "Content-Type: application/json" \
    -H "X-Auth-Token: $token" \
    -d '{"network": {"name": "net2", "admin_state_up": true, "availability_zone_hints": ["az2"]}}'
```
Here we create two networks separately bound to Pod1 and Pod2
- 4 Create necessary resources to boot virtual machines.
```
nova flavor-create test 1 1024 10 1
neutron subnet-create net1 10.0.1.0/24
neutron subnet-create net2 10.0.2.0/24
glance image-list
```
- 5 Boot virtual machines.
```
nova boot --flavor 1 --image $image_id --nic net-id=$net1_id --availability-zone az1 vm1
nova boot --flavor 1 --image $image_id --nic net-id=$net2_id --availability-zone az2 vm2
```
- 6 Create router and attach interface
```
neutron router-create router
neutron router-interface-add router $subnet1_id
neutron router-interface-add router $subnet2_id
```
- 7 Launch VNC console anc check connectivity
By now, two networks are connected by the router, the two virtual machines
should be able to communicate with each other, we can launch a VNC console to
check. Currently Tricircle doesn't support VNC proxy, we need to go to bottom
OpenStack to obtain a VNC console.
```
nova --os-region-name Pod1 get-vnc-console vm1 novnc
nova --os-region-name Pod2 get-vnc-console vm2 novnc
```
Login one virtual machine via VNC and you should find it can "ping" the other
virtual machine. Security group functionality is disabled in bottom OpenStack
so no need to configure security group rule.

### North-South Networking

Before running DevStack in node2, you need to create another ovs bridge for
external network and then attach port.
```
sudo ovs-vsctl add-br br-ext
sudo ovs-vsctl add-port br-ext eth2
```

Below listed the operations related to north-south networking:
- 1 Create external network
```
curl -X POST http://127.0.0.1:9696/v2.0/networks -H "Content-Type: application/json" \
     -H "X-Auth-Token: $token" \
     -d '{"network": {"name": "ext-net", "admin_state_up": true, "router:external": true, "provider:network_type": "vlan", "provider:physical_network": "extern", "availability_zone_hints": ["Pod2"]}}'
```
Pay attention that when creating external network, we still need to pass
"availability_zone_hints" parameter, but the value we pass is the name of pod,
not the name of availability zone.
> Currently external network needs to be created before attaching subnet to the
> router, because plugin needs to utilize external network information to setup
> bridge network when handling interface adding operation. This limitation will
> be removed later.

- 2 Create external subnet
```
neutron subnet-create --name ext-subnet --disable-dhcp ext-net 163.3.124.0/24
```
- 3 Set router external gateway
```
neutron router-gateway-set router ext-net
```
Now virtual machine in the subnet attached to the router should be able to
"ping" machines in the external network. In our test, we use hypervisor tool
to directly start a virtual machine in the external network to check the
network connectivity.
- 4 Create floating ip
```
neutron floatingip-create ext-net
```
- 5 Associate floating ip
```
neutron floatingip-list
neutron port-list
neutron floatingip-associate $floatingip_id $port_id
```
Now you should be able to access virtual machine with floating ip bound from
the external network.

### Quick verify

A sample of admin-openrc.sh and an installation verification script can be found
in devstack/ directory.

And a demo blog with virtualbox can be found in [this](http://shipengfei92.cn/play_tricircle_with_virtualbox).

#### verify_cross_pod_install.sh

This script is to quickly verify the installation of Tricircle in Cross Pod
OpenStack as the contents above and save the output to logs.
Before verifying the installation, some parameters should be modified to your own
environment.

- 1 The default URL is 127.0.0.1, change it if needed,
- 2 This script create a external network 10.50.11.0/26 according to the work environment,
change it if needed.
- 3 This script create 2 subnets 10.0.1.0/24 and 10.0.2.0/24, Change these if needed.
- 4 The default created floating-ip is attached to the VM with port 10.0.2.3 created by
the subnets, modify it according to your environment.

Then do the following steps in Node1 OpenStack to verify network functions:

```
cd tricircle/devstack/
./verify_cross_pod_install.sh 2>&1 | tee logs
```
