=======================
The Tricircle Admin API
=======================
This Admin API documentation describes the ways of interacting with the
Tricircle service via HTTP protocol using Representational State Transfer(ReST).

API Versions
============
In order to bring new features to users over time, versioning is supported
by the Tricircle. The latest version of the Tricircle is v1.0.

The Version APIs work the same as other APIs as they still require
authentication.

+------------------+----------------+-----+-----------------------------------------------+
|**GET**           |/               |     |List All Major versions                        |
|                  |                |     |                                               |
|**GET**           |/{api_version}  |     |Show Details of Specific API Version           |
+------------------+----------------+-----+-----------------------------------------------+

Service URLs
============
All API calls through the rest of this document require authentication with
the OpenStack Identity service. They also require a base service url that can
be got from the OpenStack Tricircle endpoint. This will be the root url that
every call below will be added to build a full path.

For instance, if the Tricircle service url is http://127.0.0.1/tricircle/v1.0
then the full API call for /pods is http://127.0.0.1/tricircle/v1.0/pods.

As such, for the rest of this document we will leave out the root url where
GET /pods really means GET {tricircle_service_url}/pods.

Pod
===
A pod represents a region in Keystone. When operating a pod, the Tricircle
decides the correct endpoints to send request based on the region of the pod.
Considering the architecture of the Tricircle, we have two kinds of pods: pod
for central Neutron and pod for local Neutron.


+------------------+---------+-----------------------------------+------------------------+
|**GET**           |/pods    |                                   |Retrieve Pod List       |
+------------------+---------+-----------------------------------+------------------------+

This fetches all the pods, including pod for central Neutron and pod(s) for
local Neutron.

Normal Response Code: 200

**Response**

Pods contains a list of pod instances whose attributes are described in the
following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+
|region_name|body   | string        |region_name is specified by user but must match the  |
|           |       |               |region name registered in Keystone.                  |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this is a pod for    |
|           |       |               |central Neutron. If az_name is not empty, it means   |
|           |       |               |the pod will belong to this availability zone.       |
|           |       |               |Multiple pods with the same az_name means that these |
|           |       |               |pods are under the same availability zone.           |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name used in the pod for local |
|           |       |               |Neutron when creating network, router objects. It    |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request forwarded to the pod for|
|           |       |               |local Neutron. If the pod_az_name is different from  |
|           |       |               |az_name, then the az parameter will be replaced with |
|           |       |               |the pod_az_name when the request is forwarded to     |
|           |       |               |relevant pod for local Neutron.                      |
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located.                                          |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /pods.

::

    {
        "pods": [
           {
                "dc_name": "",
                "pod_az_name": "",
                "pod_id": "1a51bee7-10f0-47e8-bb4a-70f51394069c",
                "az_name": "",
                "region_name": "RegionOne"
            },
            {
                "dc_name": "",
                "pod_az_name": "",
                "pod_id": "22cca6ad-b791-4805-af14-923c5224fcd2",
                "az_name": "az2",
                "region_name": "Pod2"
            },
            {
                "dc_name": "",
                "pod_az_name": "",
                "pod_id": "3c22e5d4-5fed-45ed-a1e9-d532668cedc2",
                "az_name": "az1",
                "region_name": "Pod1"
            }
        ]
    }

+------------------+-------------------+-----------------------+-------------------------------+
|**GET**           |/pods/{pod_id}     |                       |Retrieve a Single Pod          |
+------------------+-------------------+-----------------------+-------------------------------+

This fetches a pod for central Neutron or a pod for local Neutron.

Normal Response Code: 200

**Request**

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |path   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

Here are two kinds of pods, including pod for central Neutron and pod for local
Neutron. az_name is one of its attributes. A pod with empty az_name is for
central Neutron, otherwise a pod with az_name specified is for local Neutron.
All of its attributes are described in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+
|region_name|body   | string        |region_name is specified by user but must match the  |
|           |       |               |region name registered in Keystone.                  |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this is a pod for    |
|           |       |               |central Neutron. If az_name is not empty, it means   |
|           |       |               |the pod will belong to this availability zone.       |
|           |       |               |Multiple pods with the same az_name means that these |
|           |       |               |pods are under the same availability zone.           |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name used in the pod for local |
|           |       |               |Neutron when creating network, router objects. It    |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request forwarded to the pod for|
|           |       |               |local Neutron. If the pod_az_name is different from  |
|           |       |               |az_name, then the az parameter will be replaced with |
|           |       |               |the pod_az_name when the request is forwarded to     |
|           |       |               |relevant pod for local Neutron.                      |
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located.                                          |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /pods/{pod_id}.

::

    {
        "pod": {
            "dc_name": "",
            "pod_az_name": "",
            "pod_id": "3c22e5d4-5fed-45ed-a1e9-d532668cedc2",
            "az_name": "az1",
            "region_name": "Pod1"
        }
    }

+---------------+-------+------------------------------------+--------------------+
|**POST**       |/pods  |                                    |Create a Pod        |
+---------------+-------+------------------------------------+--------------------+

This creates a pod for central Neutron or a pod for local Neutron.

Normal Response Code: 200

**Request**

Some essential attributes of the pod instance are required and described
in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|region_name|body   | string        |region_name is specified by user but must match the  |
|           |       |               |region name registered in Keystone.                  |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this is a pod for    |
|           |       |               |central Neutron. If az_name is not empty, it means   |
|           |       |               |the pod will belong to this availability zone.       |
|           |       |               |Multiple pods with the same az_name means that these |
|           |       |               |pods are under the same availability zone.           |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name used in the pod for local |
|           |       |               |Neutron when creating network, router objects. It    |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request forwarded to the pod for|
|           |       |               |local Neutron. If the pod_az_name is different from  |
|           |       |               |az_name, then the az parameter will be replaced with |
|           |       |               |the pod_az_name when the request is forwarded to     |
|           |       |               |relevant pod for local Neutron.                      |
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located.                                          |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

An id is assigned to a pod instance when it's created. All of its attributes
are listed below.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is automatically generated when creating a pod|
+-----------+-------+---------------+-----------------------------------------------------+
|region_name|body   | string        |region_name is specified by user but must match the  |
|           |       |               |region name registered in Keystone.                  |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this is a pod for    |
|           |       |               |central Neutron. If az_name is not empty, it means   |
|           |       |               |the pod will belong to this availability zone.       |
|           |       |               |Multiple pods with the same az_name means that these |
|           |       |               |pods are under the same availability zone.           |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name used in the pod for local |
|           |       |               |Neutron when creating network, router objects. It    |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request forwarded to the pod for|
|           |       |               |local Neutron. If the pod_az_name is different from  |
|           |       |               |az_name, then the az parameter will be replaced with |
|           |       |               |the pod_az_name when the request is forwarded to     |
|           |       |               |relevant pod for local Neutron.                      |
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located.                                          |
+-----------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for POST /pods.

::

    {
        "pod": {
            "region_name": "Pod3",
            "az_name": "az1",
            "pod_az_name": "az1",
            "dc_name": "data center 1"
        }
    }

**Response Example**

This is an example of response information for POST /pods.

::

    {
        "pod": {
            "dc_name": "data center 1",
            "pod_az_name": "az1",
            "pod_id": "e02e03b8-a94f-4eb1-991e-a8a271cc2313",
            "az_name": "az1",
            "region_name": "Pod3"
        }
    }


+------------------+-----------------+------------------------+-------------------------+
|**DELETE**        |/pods/{pod_id}   |                        |Delete a Pod             |
+------------------+-----------------+------------------------+-------------------------+

This deletes a pod for central Neutron or a pod for local Neutron from
availability-zone.

Normal Response Code: 200

**Request**

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |path   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

There is no response. But we can list all the pods to verify whether the
specific pod has been deleted or not.

Resource Routing
================
The Tricircle is responsible for resource(for example, network, subnet, port,
router, etc) creation both in local Neutron and central Neutron.

In order to dispatch resource operation request to the proper local Neutron,
we need a resource routing table, which maps a resource from the central
Neutron to local Neutron where it's located.

When user issues a resource update, query or delete request, central Neutron
will capture this request and extract resource id from the request, then
dispatch the request to target local Neutron on the basis of the routing table.


+------------------+-------------+--------------------+---------------------------------+
|**GET**           |/routings    |                    |Retrieve All Resource Routings   |
+------------------+-------------+--------------------+---------------------------------+

This fetches all the resource routing entries by default, but we can
apply filter(s) on the returned values to only show the specific routing
entries. Accordingly the filtering condition(s) will be added to the tail of
the service url separated by question mark. For example, the default service
url is GET /routings, when filtering is applied, the service url becomes
GET /routings?attribute=attribute_value. One or multiple conditions are
supported.

Normal Response Code: 200

**Response**

The resource routing set contains a list of resource routing entries whose
attributes are described in the following table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |body   | biginteger    |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | timestamp     |created time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | timestamp     |updated time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /routings. By default, all
the resource routing entries will be returned.

::

    {
        "routings": [
           {
                "updated_at": "2016-09-25 03:16:31"",
                "created_at": "2016-09-25 03:16:30",
                "top_id": "4487087e-34c7-40d8-8553-3a4206d0591b",
                "id": 2,
                "bottom_id": "834ef10b-a96f-460c-b448-b39b9f3e6b52",
                "project_id": "d937fe2ad1064a37968885a58808f7a3",
                "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
                "resource_type": "security_group"
            },
            {
                "updated_at": "2016-09-25 03:16:33",
                "created_at": "2016-09-25 03:16:32",
                "top_id": "a4d786fd-0511-4fac-be45-8b9ee447324b",
                "id": 3,
                "bottom_id": "7a05748c-5d1a-485e-bd5c-e52bc39b5414",
                "project_id": "d937fe2ad1064a37968885a58808f7a3",
                "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
                "resource_type": "network"
            }
        ]
    }

This is an example of response information for GET /routings?id=2. When a
filter is applied to the list request, only the specific routing entry is
retrieved.

::

    {
        "routings": [
           {
                "updated_at": "2016-09-25 03:16:31"",
                "created_at": "2016-09-25 03:16:30",
                "top_id": "4487087e-34c7-40d8-8553-3a4206d0591b",
                "id": 2,
                "bottom_id": "834ef10b-a96f-460c-b448-b39b9f3e6b52",
                "project_id": "d937fe2ad1064a37968885a58808f7a3",
                "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
                "resource_type": "security_group"
            }
        ]
    }

+------------------+---------------+---------------+-------------------------------------+
|**GET**           |/routings/{id} |               |Retrieve a Single Resource Routing   |
+------------------+---------------+---------------+-------------------------------------+

This fetches a single resource routing entry.

Normal Response Code: 200

**Request**

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |path   | biginteger    |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

A kind of resource in central Neutron, when it is created by the Tricircle, is
mapped to the same resource in local Neutron. Resource routing records this
mapping relationship. All of its attributes are described in the following
table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |body   | biginteger    |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | timestamp     |created time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | timestamp     |updated time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /routings/{id}.

::

    {
        "routing": {
            "updated_at": null,
            "created_at": "2016-10-25 13:10:26",
            "top_id": "09fd7cc9-d169-4b5a-88e8-436ecf4d0bfe",
            "id": 43,
            "bottom_id": "dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ef",
            "project_id": "d937fe2ad1064a37968885a58808f7a3",
            "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
            "resource_type": "subnet"
        }
    }

+------------------+---------------+-----------------+-----------------------------------+
|**POST**          |/routings      |                 |Create a Resource Routing          |
+------------------+---------------+-----------------+-----------------------------------+

This creates a resource routing. For a kind of resource created in central
Neutron, it is mapped to the same resource in local Neutron.

Normal Response Code: 200

**Request**

Some essential fields of the resource routing entry are required and described
in the following table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

An id is assigned to the resource routing when it's created. All routing
entry's attributes are listed below.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |body   | biginteger    |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | timestamp     |created time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | timestamp     |updated time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for POST /routings.

::

    {
        "routing": {
            "top_id": "09fd7cc9-d169-4b5a-88e8-436ecf4d0bfg",
            "bottom_id": "dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ek",
            "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
            "project_id": "d937fe2ad1064a37968885a58808f7a3",
            "resource_type": "subnet"
        }
    }

**Response Example**

This is an example of response information for POST /routings.

::

    {
        "routing": {
            "updated_at": null,
            "created_at": "2016-11-03 03:06:38",
            "top_id": "09fd7cc9-d169-4b5a-88e8-436ecf4d0bfg",
            "id": 45,
            "bottom_id": "dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ek",
            "project_id": "d937fe2ad1064a37968885a58808f7a3",
            "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
            "resource_type": "subnet"
        }
    }

+------------------+---------------+-----------------+-----------------------------------+
|**DELETE**        |/routings/{id} |                 |Delete a Resource Routing          |
+------------------+---------------+-----------------+-----------------------------------+

This deletes a resource routing entry. But deleting an existing routing entry
created by Tricircle itself may cause problem: Central Neutron may make wrong
judgement on whether the resource exists or not without this routing entry.
Moreover, related request can't be forwarded to the proper local Neutron
either.

Normal Response Code: 200

**Request**

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |path   |  biginteger   |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

There is no response. But we can list all the resource routing entries to
verify whether the specific routing entry has been deleted or not.

+------------------+---------------+-----------------+-----------------------------------+
|**PUT**           |/routings/{id} |                 |Update a Resource Routing          |
+------------------+---------------+-----------------+-----------------------------------+

This updates an existing resource routing entry. But updating an existing
routing entry created by Tricircle itself may cause problem: Central Neutron
may make wrong judgement on whether the resource exists or not without this
routing entry. Moreover, related request can't be forwarded to the proper local
Neutron either.

Normal Response Code: 200

**Request**

Some specific attributes of the resource routing entry can be updated, but they
are only limited to the fields in the following table, other fields can not be
updated manually.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

Some specific fields of the resource routing entry will be updated. All
attributes of routing entry are listed below.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |body   | biginteger    |id is the unique identification of the resource      |
|             |       |               |routing.                                             |
+-------------+-------+---------------+-----------------------------------------------------+
|top_id       |body   | string        |top_id denotes the resource id on central Neutron.   |
+-------------+-------+---------------+-----------------------------------------------------+
|bottom_id    |body   | string        |bottom_id denotes the resource id on local Neutron.  |
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is the uuid of one pod(i.e., one region).     |
+-------------+-------+---------------+-----------------------------------------------------+
|project_id   |body   | string        |project_id is the uuid of a project object in        |
|             |       |               |KeyStone. "Tenant" is an old term for a project in   |
|             |       |               |Keystone. Starting in API version 3, "project" is the|
|             |       |               |preferred term. They are identical in the context.   |
+-------------+-------+---------------+-----------------------------------------------------+
|resource_type|body   | string        |resource_type denotes one of the available resource  |
|             |       |               |types, including network, subnet, port, router and   |
|             |       |               |security_group.                                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | timestamp     |created time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | timestamp     |updated time of the resource routing.                |
+-------------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for PUT /routings/{id}.

::

    {
        "routing": {
            "resource_type": "router"
        }
    }

**Response Example**

This is an example of response information for PUT /routings/{id}. The change
of the field updated_at will be showed next time we retrieve this routing entry
from the database.

::

    {
        "routing": {
            "updated_at": null,
            "created_at": "2016-11-03 03:06:38",
            "top_id": "09fd7cc9-d169-4b5a-88e8-436ecf4d0bfg",
            "id": 45,
            "bottom_id": "dc80f9de-abb7-4ec6-ab7a-94f8fd1e20ek",
            "project_id": "d937fe2ad1064a37968885a58808f7a3",
            "pod_id": "444a8ce3-9fb6-4a0f-b948-6b9d31d6b202",
            "resource_type": "router"
        }
    }

Asynchronous Job
================
Tricircle XJob provides OpenStack multi-region functionality. It receives jobs
from the Admin API or Tricircle Central Neutron Plugin and handles them
asynchronously in Local Neutron(s).

However, XJob server may strike occasionally so the tenants or administrators
need to know the job status and delete or redo the failed job if necessary.
Asynchronous job management APIs provide such functionality and allow user
to perform CRUD operations on a job. For example, when there is a need to
synchronize resource between central Neutron and local Neutron, administrator
can create a job to process it.

Jobs are categorized into different groups according to their phases in
lifespan. Each job lives from birth till death. Right after a job is created,
its status is NEW. After picked up by the job handler its status becomes
RUNNING. Then if executed successfully, its status will be SUCCESS, otherwise
its status will be set to FAIL. But not all jobs go through the three phases.
For job whose status is NEW, if a newer job performing the same task comes,
then this newer job will be picked up by job handler, the status of the
relatively old job won't be changed until this job is cleaned from the job
queue. A NEW job may also expire if it waits for too long, then its status is
set to FAIL directly and skips the RUNNING phase. The expiration time span is
set by administrator. All failed jobs have the opportunity to run again in next
cycle of a periodical task.

After a job runs successfully it will be moved to job log table automatically,
the older versions of this job like new and failed jobs are removed from job
table at the same time.

There are two places to store jobs. All active jobs are stored in job table,
including NEW, RUNNING, FAIL jobs and a small bunch of SUCCESS jobs that
haven't been moved to job log table timely. But job log table only contains
SUCCESS jobs, they can be listed and shown like other jobs in job table,
but when performing delete or redo operation on them, an exception will
be raised.

+------------------+----------------+---------------------------+------------------------+
|**GET**           |/jobs           |                           |Retrieve Job List       |
+------------------+----------------+---------------------------+------------------------+

By default, this fetches all of the jobs including active jobs like NEW, FAIL
and RUNNING jobs as well as SUCCESS jobs from job log. We can filter them by
project ID, job type and job status to only get the specific kind of job
entries. Accordingly the filtering condition will be added to the tail
of the service url separated by question mark. For example, the default
service url is GET /jobs. Using a filter the service url becomes
GET /jobs?filter_name=value. One or multiple filtering conditions are
supported. Particularly, job status is case insensitive when filtering the
jobs, so both 'GET /jobs?status=NEW' and 'GET /jobs?status=new' will return
the same job set.

Normal Response Code: 200

**Response**

In normal case, a set of expected jobs will be returned. For invalid filtering
value, an empty set will be returned. For unsupported filter name, an error
will be raised.

The attributes of single job are described in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |body   | string        |id is a uuid attribute of the job.                   |
+-----------+-------+---------------+-----------------------------------------------------+
|project_id |body   | string        |project_id is the uuid of a project object in        |
|           |       |               |KeyStone. "Tenant" is an old term for a project in   |
|           |       |               |Keystone. Starting in API version 3, "project" is the|
|           |       |               |preferred term. They are identical in the context.   |
+-----------+-------+---------------+-----------------------------------------------------+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|status     |body   | string        |job status, including NEW, RUNNING, SUCCESS, FAIL.   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | object        |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+
|timestamp  |body   | timestamp     |create or update time of the job.                    |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /jobs. By default, all the
job entries will be retrieved.


::

    {
        "jobs": [
            {
                "id": "3f4ecf30-0213-4f1f-9cb0-0233bcedb767",
                "project_id": "d01246bc5792477d9062a76332b7514a",
                "type": "port_delete",
                "timestamp": "2017-03-03 11:05:36",
                "status": "NEW",
                "resource": {
                    "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                    "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
                }
            },
            {
                "id": "b01fe514-5211-4758-bbd1-9f32141a7ac2",
                "project_id": "d01246bc5792477d9062a76332b7514a",
                "type": "seg_rule_setup",
                "timestamp": "2017-03-01 17:14:44",
                "status": "FAIL",
                "resource": {
                    "project_id": "d01246bc5792477d9062a76332b7514a"
                }
            }
        ]
    }

This is an example of response information for GET /job?type=port_delete. Using
a filter only a part of job entries are retrieved.

::

    {
        "jobs": [
            {
                "id": "3f4ecf30-0213-4f1f-9cb0-0233bcedb767",
                "project_id": "d01246bc5792477d9062a76332b7514a",
                "type": "port_delete",
                "timestamp": "2017-03-03 11:05:36",
                "status": "NEW",
                "resource": {
                    "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                    "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
                }
            }
        ]
    }

+------------------+-------------------+-----------------------+-------------------------------+
|**GET**           |/jobs/detail       |                       |Retrieve Jobs with Filter(s)   |
+------------------+-------------------+-----------------------+-------------------------------+

Retrieve jobs from the Tricircle database. We can filter them by project ID,
job type and job status. It functions the same as service GET /jobs.

Normal Response Code: 200

**Response**

A list of jobs will be returned. The attributes of single job are described
in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |body   | string        |id is a uuid attribute of the job.                   |
+-----------+-------+---------------+-----------------------------------------------------+
|project_id |body   | string        |project_id is the uuid of a project object in        |
|           |       |               |KeyStone. "Tenant" is an old term for a project in   |
|           |       |               |Keystone. Starting in API version 3, "project" is the|
|           |       |               |preferred term. They are identical in the context.   |
+-----------+-------+---------------+-----------------------------------------------------+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|status     |body   | string        |job status, including NEW, RUNNING, SUCCESS, FAIL.   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | object        |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+
|timestamp  |body   | timestamp     |create or update time of the job.                    |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /jobs/detail.
::

    {
        "jobs": [
            {
                "id": "3f4ecf30-0213-4f1f-9cb0-0233bcedb767",
                "project_id": "d01246bc5792477d9062a76332b7514a",
                "type": "port_delete",
                "timestamp": "2017-03-03 11:05:36",
                "status": "NEW",
                "resource": {
                    "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                    "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
                }
            },
            {
                "id": "b01fe514-5211-4758-bbd1-9f32141a7ac2",
                "project_id": "d01246bc5792477d9062a76332b7514a",
                "type": "seg_rule_setup",
                "timestamp": "2017-03-01 17:14:44",
                "status": "FAIL",
                "resource": {
                    "project_id": "d01246bc5792477d9062a76332b7514a"
                }
            }
        ]
    }

+------------------+---------------+---------------+-------------------------------------+
|**GET**           |/jobs/{id}     |               |Retrieve a Single Job                |
+------------------+---------------+---------------+-------------------------------------+

This fetches a single job entry. This entry may be from job table or job log
table.

Normal Response Code: 200

**Request**

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |path   | string        |id is a uuid attribute of the job.                   |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

The attributes of the returned job are described in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |body   | string        |id is a uuid attribute of the job.                   |
+-----------+-------+---------------+-----------------------------------------------------+
|project_id |body   | string        |project_id is the uuid of a project object in        |
|           |       |               |KeyStone. "Tenant" is an old term for a project in   |
|           |       |               |Keystone. Starting in API version 3, "project" is the|
|           |       |               |preferred term. They are identical in the context.   |
+-----------+-------+---------------+-----------------------------------------------------+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|status     |body   | string        |job status, including NEW, RUNNING, SUCCESS, FAIL.   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | object        |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+
|timestamp  |body   | timestamp     |create or update time of the job.                    |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /job/{id}.

::

    {
        "job": {
            "id": "3f4ecf30-0213-4f1f-9cb0-0233bcedb767",
            "project_id": "d01246bc5792477d9062a76332b7514a",
            "type": "port_delete",
            "timestamp": "2017-03-03 11:05:36",
            "status": "NEW",
            "resource": {
                "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
            }
        }
    }

+------------------+----------------+---------------------------+------------------------+
|**GET**           |/jobs/schemas   |                           |Retrieve Jobs' Schemas  |
+------------------+----------------+---------------------------+------------------------+

Retrieve all jobs' schemas.


Normal Response Code: 200

**Response**

This returns a list of all jobs' schemas. The architecture of job schema
is described as following.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | array         |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /jobs/schemas.

::

    {
        "schemas": [
            {
                "type": "configure_route",
                "resource": ["router_id"]
            },
            {
                "type": "router_setup",
                "resource": ["pod_id", "router_id", "network_id"]
            },
            {
                "type": "port_delete",
                "resource": ["pod_id", "port_id"]
            },
            {
                "type": "seg_rule_setup",
                "resource": ["project_id"]
            },
            {
                "type": "update_network",
                "resource": ["pod_id", "network_id"]
            },
            {
                "type": "subnet_update",
                "resource": ["pod_id", "subnet_id"]
            },
            {
                "type": "shadow_port_setup",
                "resource": [pod_id", "network_id"]
            }
        ]
    }

+---------------+-------+------------------------------------+--------------------+
|**POST**       |/job   |                                    |Create a Job        |
+---------------+-------+------------------------------------+--------------------+

This creates a new job. If target job already exists in the job table and its
status is NEW, then this newer job will be picked up by job handler.

Normal Response Code: 202

**Request**

Some essential attributes of the job are required and they are described
in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|project_id |body   | string        |project_id is the uuid of a project object in        |
|           |       |               |KeyStone. "Tenant" is an old term for a project in   |
|           |       |               |Keystone. Starting in API version 3, "project" is the|
|           |       |               |preferred term. They are identical in the context.   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | object        |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

This returns a newly created job. Its attributes are described in the following
table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |body   | string        |id is a uuid attribute of the job.                   |
+-----------+-------+---------------+-----------------------------------------------------+
|project_id |body   | string        |project_id is the uuid of a project object in        |
|           |       |               |KeyStone. "Tenant" is an old term for a project in   |
|           |       |               |Keystone. Starting in API version 3, "project" is the|
|           |       |               |preferred term. They are identical in the context.   |
+-----------+-------+---------------+-----------------------------------------------------+
|type       |body   | string        |the type of a job.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|status     |body   | string        |job status, including NEW, RUNNING, SUCCESS, FAIL.   |
+-----------+-------+---------------+-----------------------------------------------------+
|resource   |body   | object        |all kinds of resources that are needed to run the    |
|           |       |               |job. It may also contain other necessary parameters  |
|           |       |               |such as pod_id and project_id that are not Neutron   |
|           |       |               |resources.                                           |
+-----------+-------+---------------+-----------------------------------------------------+
|timestamp  |body   | timestamp     |create time of the job.                              |
+-----------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for POST /jobs.

::

    {
        "job": {
            "type": "port_delete",
            "project_id": "d01246bc5792477d9062a76332b7514a",
            "resource": {
                "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
            }
        }
    }

**Response Example**

This is an example of response information for POST /jobs.

::

    {
        "job": {
            "id": "3f4ecf30-0213-4f1f-9cb0-0233bcedb767",
            "project_id": "d01246bc5792477d9062a76332b7514a",
            "type": "port_delete",
            "timestamp": "2017-03-03 11:05:36",
            "status": "NEW",
            "resource": {
                "pod_id": "0eb59465-5132-4f57-af01-a9e306158b86",
                "port_id": "8498b903-9e18-4265-8d62-3c12e0ce4314"
            }
        }
    }

+------------------+-----------------+------------------------+-------------------------+
|**DELETE**        |/jobs/{id}       |                        |Delete a Job             |
+------------------+-----------------+------------------------+-------------------------+

Delete a failed or duplicated job from the job table. If a user tries to delete
a job from job log table, an error will be raised.

Normal Response Code: 200

**Request**

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |path   | string        |id is a uuid attribute of the job.                   |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

A pair of curly braces will be returned if succeeds, otherwise an exception
will be thrown. We can list jobs to verify whether it has been deleted
successfully or not.

+------------------+---------------+-----------------+-----------------------------------+
|**PUT**           |/jobs/{id}     |                 |Redo a Job                         |
+------------------+---------------+-----------------+-----------------------------------+

Redo a halted job brought by the XJob server corruption or network failures.
The job handler will redo a failed job with time interval, but this Admin API
will redo a job immediately. If a user tries to redo a job in job log table,
an error will be raised.


Normal Response Code: 200

**Request**

Only job id is needed. We use PUT method to redo a job. Regularly PUT method
requires a request body, but considering the job redo operation doesn't
need more information other than job id, we will issue this request without
request body.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |path   | string        |id is a uuid attribute of the job.                   |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

Nothing will be returned for this request, but we can monitor its status
through the execution state.

