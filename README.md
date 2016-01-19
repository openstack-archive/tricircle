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

- 1 Git clone DevStack.
- 2 Git clone Tricircle, or just download devstack/local.conf.sample.
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
network, the physical network infrastructure should support VLAN tagging.

### Setup

In node1,

- 1 Git clone DevStack.
- 2 Git clone Tricircle, or just download devstack/local.conf.node_1.sample.
- 3 Copy devstack/local.conf.node_1.sample to DevStack folder and rename it to
local.conf, change password in the file if needed.
- 4 Change the following options according to your environment:
```
HOST_IP=10.250.201.24 - change to your management interface ip
TENANT_VLAN_RANGE=2001:3000 - change to VLAN range your physical network supports
PHYSICAL_NETWORK=bridge - change to whatever you like
OVS_PHYSICAL_BRIDGE=br-bridge - change to whatever you like
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

- 1 Git clone DevStack.
- 2 Git clone Tricircle, or just download devstack/local.conf.node_2.sample.
- 3 Copy devstack/local.conf.node_2.sample to DevStack folder and rename it to
local.conf, change password in the file if needed.
- 4 Change the following options according to your environment:
```
HOST_IP=10.250.201.25 - change to your management interface ip
KEYSTONE_SERVICE_HOST=10.250.201.24 - change to management interface ip of node1
KEYSTONE_AUTH_HOST=10.250.201.24 - change to management interface ip of node1
GLANCE_SERVICE_HOST=10.250.201.24 - change to management interface ip of node1
TENANT_VLAN_RANGE=2001:3000 - change to VLAN range your physical network supports
PHYSICAL_NETWORK=bridge - change to whatever you like
OVS_PHYSICAL_BRIDGE=br-bridge - change to whatever you like
```
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
    -H "X-Auth-Token: b5dc59ebfdb74dbfa2a6351682d10a6e" \
    -d '{"network": {"name": "net1", "admin_state_up": true, "availability_zone_hints": ["az1"]}}'
curl -X POST http://127.0.0.1:9696/v2.0/networks -H "Content-Type: application/json" \
    -H "X-Auth-Token: b5dc59ebfdb74dbfa2a6351682d10a6e" \
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
