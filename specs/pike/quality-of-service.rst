=============================
Tricircle Quality of Service
=============================

Background
==========

QoS is defined as the ability to guarantee certain network requirements
like bandwidth, latency, jitter and reliability in order to satisfy a
Service Level Agreement (SLA) between an application provider and end
tenants. In the Tricircle, each OpenStack instance runs its own Nova and
Neutron services but shares the same Keystone service or uses federated
KeyStones, which is a multi-region deployment mode. With networking automation,
networks or ports created in different OpenStack cloud should be able to be
associated with QoS policies.

Proposal
========

As networking automation across Neutron could be done through the Tricircle,
the QoS automation should be able to work based on tenant's need too. When
tenant wants to apply QoS to the network or port from the central Neutron, QoS
can't be created in the local Neutron server in the bottom pod directly, since
it's still unclear whether the network will be presented in this pod or not.

In order to achieve QoS automation operations, QoS can't be created in the
local Neutron server directly until there are some existing networks/ports
in bottom pod. The Tricircle central Neutron plugin(abbr: "central plugin")
will operate QoS information in the local Neutron server, QoS service isn't
like network/port that needs to be created during VM booting, in order to
speed up the local VMs booting and reduce the delay that caused by
synchronization between central Neutron and local Neutron, Tricircle central
plugin should use an asynchronous method to associate QoS with the local
network/port, or remove QoS association in each local Neutron if needed.

Implementation
==============

Case 1, QoS policy creation
----------------------------

In this case, we only create QoS in the central Neutron.

Case 2, QoS policy association without local network/port in place
-----------------------------------------------------------

QoS has been created in the central Neutron but local network/port has not
yet been created.

In this case, we just need to update network/port with QoS policy id in the
central Neutron.

Case 3, QoS policy association with local network/port in place
---------------------------------------------------------------

After QoS has been created in the central Neutron and local network/port
also has been created, associate QoS with network/port in the central Neutron.

In this case, network/port has been created in the local Neutron. After
network/port is updated with the QoS policy id in the central Neutron, we also
need to do some similar association in the local Neutron. Central Neutron uses
"create_qos_policy" job to create the local QoS policy firstly, then update the
network/port QoS association asynchronously in the local Neutron through the
network/port routing information and add the QoS routing information in routing
table. XJob will interact with local Neutron to update the QoS policy id for
network/port in local Neutron.

Case 4, provision VM with QoS policy associated central port/network
--------------------------------------------------------------

QoS has been associated to central port/network first, local network/port
is created later in VM provision.

In this case, QoS has been associated to the central network/port and at this
point local network/port does not exist. Since QoS has not been created in
the local Neutron but central Neutron has finished the association, local
neutron needs to trigger central Neutron to finish the local network/port
QoS association when VMs booting in the local. When VM booting in the bottom
pod, local Neutron sends update port request with port information to central
Neutron and if QoS id field exists in the network/port, the central Neutron
will be triggered to use XJob to create an QoS policy creation job in the
local Neutron (it also speeds up VM booting) and add the QoS routing
information in routing table.

Case 5, QoS policy updating
----------------------------

In this case, if local network/port isn't associated with QoS, we only update
QoS in the central Neutron.

If QoS policy has been associated with local network/port in place, after
central Neutron updates QoS, central Neutron will use XJob to create a QoS
asynchronous updating job through the network/port routing information.
XJob will asynchronously update QoS in the local Neutron.

Case 6, QoS policy disassociation
-----------------------------------

For QoS policy disassociation, just need to change the parameters of
"QoS_policy_id" to None when update network/port in the central Neutron and
we can disassociate network/port.

In this case, if network/port in local Neutron isn't associated with QoS, we
only disassociate network/port in the central Neutron.

If QoS policy has been associated with network/port in local Neutron, after
central Neutron disassociates network, central Neutron will use XJob to
create a network update job to disassociate the network with the QoS policy;
for port, central Neutron will synchronously update the port to disassociate
it with the QoS policy in the local Neutron.

Case 7, QoS policy deletion
----------------------------

QoS policy can only be deleted if there is no any association in central
Neutron. In this case, if local network/port isn't associated with QoS, we
only delete QoS in the central Neutron.

If there is QoS policy routing info, after central Neutron deletes QoS,
central Neutron will use XJob to create a QoS asynchronous deletion job
through the network/port routing information. XJob will asynchronously
delete QoS in the local Neutron.

Case 8, QoS rule creation
--------------------------

In this case, if local network/port isn't associated with QoS, we only create
QoS rule in the central Neutron.

If QoS policy has been associated with local network/port in place, after central
Neutron creates QoS rules, central Neutron will use XJob to create a QoS rules
syncing job through the network/port routing information, then asynchronously
creates QoS rules in the local Neutron.

Case 9, QoS rule updating
--------------------------

In this case, if local network/port isn't associated with QoS, we only update
QoS rule in the central Neutron. If QoS policy has been associated with local
network/port in place, after central Neutron updates QoS rule, central Neutron
will trigger XJob to create a QoS rules syncing job in the local Neutron
through the network/port routing information. XJob will asynchronously update
QoS rule in the local Neutron.

Case 10, QoS rule deletion
----------------------------

In this case, if local network/port isn't associated with QoS, we only delete
QoS rule in the central Neutron.

If QoS policy has been associated with local network/port in place, after
central Neutron deletes QoS rule, central Neutron will use XJob to create a QoS
rules syncing job through the network/port routing information. XJob will
asynchronously delete QoS rule in the local Neutron.

QoS XJob jobs list
-------------------

- **1: create_qos_policy(self, ctxt, policy_id, pod_id, res_type, res_id=None)**

Asynchronously creating QoS policy for the corresponding pod which id equals
"pod_id", specify network or port in through the parameter res_type and
res_id. If res_type is RT_NETWORK, then res_id is network's uuid, if res_type
is RT_PORT, then res_id is port's uuid

**Triggering condition:**

When associating network/port in the central Neutron, if this network/port
exists in the local Neutron, triggering this asynchronous job to complete
the local association.

When central plugin processing a port update request sent by local plugin
and finding the port is associated with QoS.

If pod_id is POD_NOT_SPECIFIED then the async job will process all related
pods, so the create_qos_policy(self, ctxt, policy_id, pod_id) job will deal
with not only single pod's QoS association.

If the res_type is RT_NETWORK/RT_PORT, after creating the qos policy on pod,
the async job will bind the qos policy that just created to the network/port
specified by the parameter of res_id.

- **2: update_qos_policy(self, ctxt, policy_id, pod_id)**

Asynchronously updating QoS policy for the corresponding pod which id equals
"pod_id".

**Triggering condition:**

When updating QoS policy in the central Neutron, if it also exists in the
local Neutron, triggering this asynchronous job to complete the local QoS
updating.

If pod_id is POD_NOT_SPECIFIED then the async job will process all related
pods, so the update_qos_policy(self,ctxt,policy_id,pod_id) job will deal with
not only single pod's QoS association.

- **3: delete_qos_policy(self, ctxt, policy_id, pod_id)**

Asynchronously deleting QoS policy for the corresponding pod which id equals
"pod_id".

**Triggering condition:**

When deleting QoS policy in the central Neutron, if this QoS policy exists in
the local Neutron, triggering this asynchronous job to complete the local QoS
deletion.
(Warning: the deleted QoS policy must be disassociated first.)

If pod_id is POD_NOT_SPECIFIED then the async job will process all related
pods, so the delete_qos_policy(self,ctxt,policy_id,pod_id) job will deal with
not only single pod's QoS association.

- **4: sync_qos_policy_rules(self, ctxt, policy_id)**

Asynchronous operation for rules of one QoS policy for specified project.
There are two trigger conditions. The one is that central Neutron
creates/updates/deletes QoS rules after QoS policy has been associated with
local network/port. The other is that central plugin processes a port update request
sent by local plugin and finds the port is associated with QoS policy.

If the rule both exists in the central Neutron and local Neutron, but with
inconsistent content, just asynchronously updating this QoS rule in the local
Neutron.

If the rule exits in the central Neutron, but it does not exist in the local
Neutron, just asynchronously creating this QoS rule in the local Neutron.

If the rule exits in the local Neutron, but it does not exist in the central
Neutron, just asynchronously deleting this QoS rule in the local Neutron.


Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

Release notes

