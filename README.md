# Tricircle

(Attention Please, Stateless Design Proposal is being worked on the
["experiment"](https://github.com/openstack/tricircle/tree/experiment) branch).

(The original PoC source code, please switch to
["poc"](https://github.com/openstack/tricircle/tree/poc) tag, or
["stable/fortest"](https://github.com/openstack/tricircle/tree/stable/fortest)
branch)

Tricircle is a OpenStack project that aims to deal with OpenStack deployment
across multiple sites. It provides users a single management view by having
only one OpenStack instance on behalf of all the involved ones. It essentially
serves as a communication bus between the central OpenStack instance and the
other OpenStack instances that are called upon.

## Project Resources
- Project status, bugs, and blueprints are tracked on
[Launchpad](https://launchpad.net/tricircle)
- Additional resources are linked from the project
[Wiki](https://wiki.openstack.org/wiki/Tricircle) page

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
value is "RegionOne", we use it as the top OpenStack; "Pod1" is the region set
via "POD_REGION_NAME", new configuration option introduced by Tricircle,
we use it as the bottom OpenStack.
- 6 Create site instances for both top and bottom OpenStack
```
curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "RegionOne"}}'

curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" -H "X-Auth-Token: $token" -d '{"pod": {"pod_name":  "Pod1", "az_name": "az1"}}'

```
Pay attention to "name" parameter we specify when creating site. Site name
should exactly match the region name registered in Keystone since it is used
by Tricircle to route API request. In the above commands, we create sites named
"RegionOne" and "Pod1" for top OpenStack and bottom OpenStack. Tricircle API
service will automatically create a aggregate when user creates a bottom site,
so command "nova aggregate-list" will show the following result:
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
```
Note that flavor mapping has not been implemented yet so the created flavor is
just a database record and actually flavor in bottom OpenStack with the same id
will be used.
- 8 Boot a virtual machine.
```
nova boot --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az1 vm1
```
