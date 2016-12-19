=====================================
Tricircle Table Clean After Splitting
=====================================

Background
==========
Originally the Tricircle provided unified OpenStack API gateway and networking
automation functionality. But now the Tricircle narrows its scope to networking
automation across Neutron servers, the functionality of OpenStack API gateway
is developed in another project called Trio2o[1].

Problem Description
===================
After this splitting, many tables would no longer be used, including quota,
volume, aggregate and pod binding, etc. The data models, tables and APIs of
them should be removed. As for the rest of the tables that are still in use
in the Tricircle, they should be renamed for better understanding.

Apart from the table cleaning work and table renaming work, a new feature
will be developed to remove the dependency on old table. During the period
of external network creation, it will take 'availability_zone_hints' (AZ or
az will be used for short for availability zone) as a parameter. Previously
az_hints was searched in the pod binding table by az_name and tenant_id, now
the pod binding table is deprecated and new search strategy is needed to fix
the problem[2]. A function named find_pod_by_az will be developed to find the
az_hints by az_name in the pod table. Given the az_name, if it is not empty,
we first match it with region_name in the pod table. When a pod with the same
region_name is found, it will be returned back. The search procedure is
complete. If no pod is found with the same region_name, then we try to match
it with az_name in the pod table. If multiple pods are found, then we will
raise an exception. If only one pod is found, this pod will be returned back.
An exception will be raised if no pod is matched at the end of the previous
search procedure. However, if the az_name is empty, we will return None, a new
configuration item "default_region_for_external_network" will be used.

Proposed Change
===============

All tables that need to be changed can be divided into two categories,
``Table to be removed``, ``Table to be renamed``.

Table to be removed:

- quality_of_service_specs

- quota_classes

- quota_usages

- quotas

- reservations

- volume_type_extra_specs

- volume_type_projects

- volume_types

- aggregates

- aggregate_metadata

- instance_types

- instance_type_projects

- instance_type_extra_specs

- key_pairs

- pod_binding

Table to be renamed:

- cascaded_pod_service_configuration(new name: cached_endpoints)

- cascaded_pods(new name: pods)

- cascaded_pods_resource_routing(new name: resource_routings)

- job(new name: async_jobs)

The deprecated tables will be removed from the repository directly, and other
tables containing old meanings will be renamed for better understanding.

After the deletion of pod binding table, a new feature will be developed to
lookup the az in the pod table rather than the pod binding table.

Data Model Impact
=================

In database, many tables are removed, other tables are renamed for better
understanding.

Documentation Impact
====================

After the pod binding table is removed, the explanation of the pod binding
API in the doc/source/api_v1.rst will be removed as well.

Dependencies
============

None

References
==========
[1] https://github.com/openstack/trio2o

[2] https://review.openstack.org/#/c/412325/
