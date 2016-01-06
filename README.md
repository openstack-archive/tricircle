# Tricircle

(Attention Please, Stateless Design Proposal is being worked on the
["experiment"](https://github.com/openstack/tricircle/tree/experiment) branch).

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
- 2 Git clone Tricircle, or just download devstack/local.conf.sample
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
