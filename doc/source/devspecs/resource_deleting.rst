========================================
Reliable resource deleting in Tricircle
========================================

Background
==========
During the deletion of resources which are mapped to several local Neutron(s),
it may bring some conflict operations. For example, deleting a network in
central neutron which is also resided in several local Neutron(s). The reason
is that network-get request will trigger local neutron to query central
neutron and create the network, and we delete local networks before deleting
central network. When a network-get request comes to a local neutron server
after the local network is completely deleted in that region and at this time
the network in central neutron still exists (assuming it takes certain time to
delete all local networks), local neutron will still retrieve the network from
central neutron and the deleted local network will be recreated. This issue
also applies to the deletion cases of other resource types.

Proposed Solution
=================
Recently, Tricircle adds a feature to distinguish the source of requests[1], so
we can distinguish the deletion request from 'Central Neutron' or
'Local Neutron'. In order to avoid the conflict mentioned above, we introduce a
new table called "deleting_resource" in Tricircle database, so central plugin
can save the resource deletion information and set the information when it
receives a deletion request. Here is the schema of the table:

.. csv-table:: Resource deleting table
  :header: Field, Type, Nullable, pk/fk/uk, Description

  resource_id, string, False, uk, resource id in central Neutron
  resource_type, string, False, uk, resource_type denotes one of the available resource types
  deleted_at, timestamp, False, n/a, deletion timestamp

**How to delete the resource without conflict operation**

Let's take network deletion as an example.

At the beginning of network-delete handle, central neutron server sets the
information of deleted network into the "deleting_resource" table.

At this point, if get-request from local neutron servers comes, central
neutron server will check the "deleting_resource" table whether the
associated resource has been recorded and return 404 to local neutron server
if the associated resources is being deleting.

At this point, if deletion request is from central Neutron, central neutron
server will check the "deleting_resource" table whether the associated
resource has been recorded and it will return 204 to user if associated
resource is being deleting.

For the get-request of user, central neutron server will query the related
network information in "deleting_resource" table and will return the deleting
resource to user if the network information which the user queries exists in
the table. When user re-deleting the network after something wrong happens,
central neutron will return 204 to user.

At the end of network-delete handle that all the mapped local networks have
been deleted, central neutron server will remove the deleting resource record
and remove this network.

In addition, there is a timestamp in table that cloud administrator is able to
delete a resource which is in deleting status over long time (too long to
delete, or in abnormal status).

[1] https://review.opendev.org/#/c/518421/
