=================================
Dynamic Pod Binding in Tricircle
=================================

Background
===========

Most public cloud infrastructure is built with Availability Zones (AZs).
Each AZ is consisted of one or more discrete data centers, each with high
bandwidth and low latency network connection, separate power and facilities.
These AZs offer cloud tenants the ability to operate production
applications and databases deployed into multiple AZs are more highly
available, fault tolerant and scalable than a single data center.

In production clouds, each AZ is built by modularized OpenStack, and each
OpenStack is one pod. Moreover, one AZ can include multiple pods. Among the
pods, they are classified into different categories. For example, servers
in one pod are only for general purposes, and the other pods may be built
for heavy load CAD modeling with GPU. So pods in one AZ could be divided
into different groups. Different pod groups for different purposes, and
the VM's cost and performance are also different.

The concept "pod" is created for the Tricircle to facilitate managing
OpenStack instances among AZs, which therefore is transparent to cloud
tenants. The Tricircle maintains and manages a pod binding table which
records the mapping relationship between a cloud tenant and pods. When the
cloud tenant creates a VM or a volume, the Tricircle tries to assign a pod
based on the pod binding table.

Motivation
===========

In resource allocation scenario, when a tenant creates a VM in one pod and a
new volume in a another pod respectively. If the tenant attempt to attach the
volume to the VM, the operation will fail. In other words, the volume should
be in the same pod where the VM is, otherwise the volume and VM would not be
able to finish the attachment. Hence, the Tricircle needs to ensure the pod
binding so as to guarantee that VM and volume are created in one pod.

In capacity expansion scenario, when resources in one pod are exhausted,
then a new pod with the same type should be added into the AZ. Therefore,
new resources of this type should be provisioned in the new added pod, which
requires dynamical change of pod binding. The pod binding could be done
dynamically by the Tricircle, or by admin through admin api for maintenance
purpose. For example, for maintenance(upgrade, repairement) window, all
new provision requests should be forwarded to the running one, but not
the one under maintenance.

Solution: dynamic pod binding
==============================

It's quite headache for capacity expansion inside one pod, you have to
estimate, calculate, monitor, simulate, test, and do online grey expansion
for controller nodes and network nodes whenever you add new machines to the
pod. It's quite big challenge as more and more resources added to one pod,
and at last you will reach limitation of one OpenStack. If this pod's
resources exhausted or reach the limit for new resources provisioning, the
Tricircle needs to bind tenant to a new pod instead of expanding the current
pod unlimitedly. The Tricircle needs to select a proper pod and stay binding
for a duration, in this duration VM and volume will be created for one tenant
in the same pod.

For example, suppose we have two groups of pods, and each group has 3 pods,
i.e.,

GroupA(Pod1, Pod2, Pod3) for general purpose VM,

GroupB(Pod4, Pod5, Pod6) for CAD modeling.

Tenant1 is bound to Pod1, Pod4 during the first phase for several months.
In the first phase, we can just add weight in Pod, for example, Pod1, weight 1,
Pod2, weight2, this could be done by adding one new field in pod table, or no
field at all, just link them by the order created in the Tricircle. In this
case, we use the pod creation time as the weight.

If the tenant wants to allocate VM/volume for general VM, Pod1 should be
selected. It can be implemented with flavor or volume type metadata. For
general VM/Volume, there is no special tag in flavor or volume type metadata.

If the tenant wants to allocate VM/volume for CAD modeling VM, Pod4 should be
selected. For CAD modeling VM/Volume, a special tag "resource: CAD Modeling"
in flavor or volume type metadata determines the binding.

When it is detected that there is no more resources in Pod1, Pod4. Based on
the resource_affinity_tag, the Tricircle queries the pod table for available
pods which provision a specific type of resources. The field resource_affinity
is a key-value pair. The pods will be selected when there are matched
key-value in flavor extra-spec or volume extra-spec. A tenant will be bound
to one pod in one group of pods with same resource_affinity_tag. In this case,
the Tricircle obtains Pod2 and Pod3 for general purpose, as well as Pod5 an
Pod6 for CAD purpose. The Tricircle needs to change the binding, for example,
tenant1 needs to be bound to Pod2, Pod5.

Implementation
===============

Measurement
-------------

To get the information of resource utilization of pods, the Tricircle needs to
conduct some measurements on pods. The statistic task should be done in
bottom pod.

For resources usages, current cells provide interface to retrieve usage for
cells [1]. OpenStack provides details of capacity of a cell, including disk
and ram via api of showing cell capacities [1].

If OpenStack is not running with cells mode, we can ask Nova to provide
an interface to show the usage detail in AZ. Moreover, an API for usage
query at host level is provided for admins [3], through which we can obtain
details of a host, including cpu, memory, disk, and so on.

Cinder also provides interface to retrieve the backend pool usage,
including updated time, total capacity, free capacity and so on [2].

The Tricircle needs to have one task to collect the usage in the bottom on
daily base, to evaluate whether the threshold is reached or not. A threshold
or headroom could be configured for each pod, but not to reach 100% exhaustion
of resources.

On top there should be no heavy process. So getting the sum info from the
bottom can be done in the Tricircle. After collecting the details, the
Tricircle can judge whether a pod reaches its limit.

Tricircle
----------

The Tricircle needs a framework to support different binding policy (filter).

Each pod is one OpenStack instance, including controller nodes and compute
nodes. E.g.,

::

                         +->  controller(s) - pod1 <--> compute nodes <---+
                                                                          |
   The tricircle         +->  controller(s) - pod2 <--> compute nodes <---+ resource migration, if necessary
  (resource controller)                       ....                        |
                         +->  controller(s) - pod{N} <--> compute nodes <-+


The Tricircle selects a pod to decide where the requests should be forwarded
to which controller. Then the controllers in the selected pod will do its own
scheduling.

One simplest binding filter is as follows. Line up all available pods in a
list and always select the first one. When all the resources in the first pod
has been allocated, remove it from the list. This is quite like how production
cloud is built: at first, only a few pods are in the list, and then add more
and more pods if there is not enough resources in current cloud. For example,

List1 for general pool: Pod1 <- Pod2 <- Pod3
List2 for CAD modeling pool: Pod4 <- Pod5 <- Pod6

If Pod1's resource exhausted, Pod1 is removed from List1. The List1 is changed
to: Pod2 <- Pod3.
If Pod4's resource exhausted, Pod4 is removed from List2. The List2 is changed
to: Pod5 <- Pod6

If the tenant wants to allocate resources for general VM, the Tricircle
selects Pod2. If the tenant wants to allocate resources for CAD modeling VM,
the Tricircle selects Pod5.

Filtering
-------------

For the strategy of selecting pods, we need a series of filters. Before
implementing dynamic pod binding, the binding criteria are hard coded to
select the first pod in the AZ. Hence, we need to design a series of filter
algorithms. Firstly, we plan to design an ALLPodsFilter which does no
filtering and passes all the available pods. Secondly, we plan to design an
AvailabilityZoneFilter which passes the pods matching the specified available
zone. Thirdly, we plan to design a ResourceAffiniyFilter which passes the pods
matching the specified resource type. Based on the resource_affinity_tag,
the Tricircle can be aware of which type of resource the tenant wants to
provision. In the future, we can add more filters, which requires adding more
information in the pod table.

Weighting
-------------

After filtering all the pods, the Tricircle obtains the available pods for a
tenant. The Tricircle needs to select the most suitable pod for the tenant.
Hence, we need to define a weight function to calculate the corresponding
weight of each pod. Based on the weights, the Tricircle selects the pod which
has the maximum weight value. When calculating the weight of a pod, we need
to design a series of weigher. We first take the pod creation time into
consideration when designing the weight function. The second one is the idle
capacity, to select a pod which has the most idle capacity. Other metrics
will be added in the future, e.g., cost.

Data Model Impact
==================

Firstly, we need to add a column “resource_affinity_tag” to the pod table,
which is used to store the key-value pair, to match flavor extra-spec and
volume extra-spec.

Secondly, in the pod binding table, we need to add fields of start binding
time and end binding time, so the history of the binding relationship could
be stored.

Thirdly, we need a table to store the usage of each pod for Cinder/Nova.
We plan to use JSON object to store the usage information. Hence, even if
the usage structure is changed, we don't need to update the table. And if
the usage value is null, that means the usage has not been initialized yet.
As just mentioned above, the usage could be refreshed in daily basis. If it's
not initialized yet, it means there is still lots of resources available,
which could be scheduled just like this pod has not reach usage threshold.

Dependencies
=============

None


Testing
========

None


Documentation Impact
=====================

None


Reference
==========

[1] http://developer.openstack.org/api-ref-compute-v2.1.html#showCellCapacities

[2] http://developer.openstack.org/api-ref-blockstorage-v2.html#os-vol-pool-v2

[3] http://developer.openstack.org/api-ref-compute-v2.1.html#showinfo
