=======================
The Tricircle Admin API
=======================
This Admin API describes the ways of interacting with the Tricircle service
via HTTP protocol using Representational State Transfer(ReST).

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

For instance, if the Tricircle service url is http://127.0.0.1:19999/v1.0 then
the full API call for /pods is http://127.0.0.1:19999/v1.0/pods.

As such, for the rest of this document we will leave out the root url where
GET /pods really means GET {tricircle_service_url}/pods.

Pod
===
A pod represents a region in Keystone. When operating a pod, the Tricircle
decides the correct endpoints to send request based on the region of the pod.
Considering the 2-layers architecture of the Tricircle, we also have two kinds
of pods: top pod and bottom pod.


+------------------+---------+-----------------------------------+------------------------+
|**GET**           |/pods    |                                   |Retrieve Pod List       |
+------------------+---------+-----------------------------------+------------------------+

This fetches all the pods including top pod and bottom pod(s).

Normal Response Code: 200

**Response**

Pods contains a list of pod instance whose attributes are described in the
following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_name   |body   | string        |pod_name is specified by user but must match the     |
|           |       |               |region name registered in Keystone. When creating a  |
|           |       |               |bottom pod, the Tricircle automatically creates a    |
|           |       |               |host aggregation and assigns the new availability    |
|           |       |               |zone id to it.                                       |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this pod is a top    |
|           |       |               |region, no host aggregation will be generated. If    |
|           |       |               |az_name is not empty, it means the pod will belong   |
|           |       |               |to this availability zone. Multiple pods with the    |
|           |       |               |same az_name means that these pods are under the same|
|           |       |               |availability zone.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name in the bottom pod, it     |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request to the bottom pod. If   |
|           |       |               |the pod_az_name is different from az_name, then the  |
|           |       |               |az parameter will be replaced with the pod_az_name   |
|           |       |               |when the request is forwarded to relevant bottom pod.|
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located at.                                       |
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
                "pod_name": "RegionOne"
            },
            {
                "dc_name": "",
                "pod_az_name": "",
                "pod_id": "22cca6ad-b791-4805-af14-923c5224fcd2",
                "az_name": "az2",
                "pod_name": "Pod2"
            },
            {
                "dc_name": "",
                "pod_az_name": "",
                "pod_id": "3c22e5d4-5fed-45ed-a1e9-d532668cedc2",
                "az_name": "az1",
                "pod_name": "Pod1"
            }
        ]
    }

+------------------+-------------------+-----------------------+-------------------------------+
|**GET**           |/pods/{pod_id}     |                       |Retrieve a Single Pod          |
+------------------+-------------------+-----------------------+-------------------------------+

This fetches a single pod such as a top pod or a bottom pod.

Normal Response Code: 200

**Request**

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |path   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

Here are two kinds of pods, including top pod and bottom pod. az_name is one
of its attributes. If the az_name is empty, it means a top pod otherwise it
means a bottom pod. All of its attributes are described in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_name   |body   | string        |pod_name is specified by user but must match the     |
|           |       |               |region name registered in Keystone. When creating a  |
|           |       |               |bottom pod, the Tricircle automatically creates a    |
|           |       |               |host aggregation and assigns the new availability    |
|           |       |               |zone id to it.                                       |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this pod is a top    |
|           |       |               |region, no host aggregation will be generated. If    |
|           |       |               |az_name is not empty, it means the pod will belong   |
|           |       |               |to this availability zone. Multiple pods with the    |
|           |       |               |same az_name means that these pods are under the same|
|           |       |               |availability zone.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name in the bottom pod, it     |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request to the bottom pod. If   |
|           |       |               |the pod_az_name is different from az_name, then the  |
|           |       |               |az parameter will be replaced with the pod_az_name   |
|           |       |               |when the request is forwarded to relevant bottom pod.|
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located at.                                       |
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
            "pod_name": "Pod1"
        }
    }

+---------------+-------+------------------------------------+--------------------+
|**POST**       |/pods  |                                    |Create a Pod        |
+---------------+-------+------------------------------------+--------------------+

This creates a pod such as a top pod or a bottom pod.

Normal Response Code: 200

**Request**

Some essential attributes of the pod instance are required and described
in the following table.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_name   |body   | string        |pod_name is specified by user but must match the     |
|           |       |               |region name registered in Keystone. When creating a  |
|           |       |               |bottom pod, the Tricircle automatically creates a    |
|           |       |               |host aggregation and assigns the new availability    |
|           |       |               |zone id to it.                                       |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this pod is a top    |
|           |       |               |region, no host aggregation will be generated. If    |
|           |       |               |az_name is not empty, it means the pod will belong   |
|           |       |               |to this availability zone. Multiple pods with the    |
|           |       |               |same az_name means that these pods are under the same|
|           |       |               |availability zone.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name in the bottom pod, it     |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request to the bottom pod. If   |
|           |       |               |the pod_az_name is different from az_name, then the  |
|           |       |               |az parameter will be replaced with the pod_az_name   |
|           |       |               |when the request is forwarded to relevant bottom pod.|
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located at.                                       |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

An id is assigned to a pod instance when it's created. All of its attributes
are listed below.

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|pod_id     |body   | string        |pod_id is automatically generated when creating a pod|
+-----------+-------+---------------+-----------------------------------------------------+
|pod_name   |body   | string        |pod_name is specified by user but must match the     |
|           |       |               |region name registered in Keystone. When creating a  |
|           |       |               |bottom pod, the Tricircle automatically creates a    |
|           |       |               |host aggregation and assigns the new availability    |
|           |       |               |zone id to it.                                       |
+-----------+-------+---------------+-----------------------------------------------------+
|az_name    |body   | string        |When az_name is empty, it means this pod is a top    |
|           |       |               |region, no host aggregation will be generated. If    |
|           |       |               |az_name is not empty, it means the pod will belong   |
|           |       |               |to this availability zone. Multiple pods with the    |
|           |       |               |same az_name means that these pods are under the same|
|           |       |               |availability zone.                                   |
+-----------+-------+---------------+-----------------------------------------------------+
|pod_az_name|body   | string        |pod_az_name is the az name in the bottom pod, it     |
|           |       |               |could be empty. If it's empty, then no az parameter  |
|           |       |               |will be added to the request to the bottom pod. If   |
|           |       |               |the pod_az_name is different from az_name, then the  |
|           |       |               |az parameter will be replaced with the pod_az_name   |
|           |       |               |when the request is forwarded to relevant bottom pod.|
+-----------+-------+---------------+-----------------------------------------------------+
|dc_name    |body   | string        |dc_name is the name of the data center where the pod |
|           |       |               |is located at.                                       |
+-----------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for POST /pods.

::

    {
        "pod": {
            "pod_name": "Pod3",
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
            "pod_name": "Pod3"
        }
    }


+------------------+-----------------+------------------------+-------------------------+
|**DELETE**        |/pods/{pod_id}   |                        |Delete a Pod             |
+------------------+-----------------+------------------------+-------------------------+

This deletes a pod such as a top pod or a bottom pod from availability-zone.

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

Pod Binding
===========
A pod binding represents a mapping relationship between tenant and pod. Pods
are classified into different categories. A tenant will be bound to different
pod groups for different purposes.

+------------------+------------+---------------------+-------------------------------------+
|**GET**           |/bindings   |                     |Retrieve Pod Binding List            |
+------------------+------------+---------------------+-------------------------------------+

This fetches all the pod bindings.

Normal Response Code: 200

**Response**

Pod bindings contain one or more binding instances whose attributes
are listed in the following table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|tenant_id    |body   | string        |tenant_id is automatically generated when adding a   |
|             |       |               |uuid of a project object in KeyStone. "Tenant" is an |
|             |       |               |old term for a project in Keystone. Starting in API  |
|             |       |               |version 3, "project" is the preferred term.          |
|             |       |               |Accordingly, project_id is used instead of tenant_id.|
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-------------+-------+---------------+-----------------------------------------------------+
|id           |body   | string        |id is a uuid attribute of the pod binding. It is     |
|             |       |               |automatically generated when new binding relation    |
|             |       |               |happens between tenant and pod.                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | date          |created time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | date          |updated time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /bindings.

::

    {
        "pod_bindings": [
            {
                "updated_at": null,
                "tenant_id": "1782b3310f144836aa73c1ac5117d8da",
                "created_at": "2016-06-03 07:37:50",
                "id": "6ba7510c-baeb-44ad-8815-c4d229b52e46",
                "pod_id": "22cca6ad-b791-4805-af14-923c5224fcd2"
            },
            {
                "updated_at": null,
                "tenant_id": "1782b3310f144836aa73c1ac5117d8da",
                "created_at": "2016-06-03 07:37:06",
                "id": "f0a54f30-6208-499d-b087-0ac64f6f2756",
                "pod_id": "3c22e5d4-5fed-45ed-a1e9-d532668cedc2"
            }
       ]
    }


+------------------+---------------+-------------+---------------------------------------+
|**GET**           |/bindings/{id} |             |Retrieve a Single Pod Binding          |
+------------------+---------------+-------------+---------------------------------------+

This fetches a single pod binding.

Normal Response Code: 200

**Request**

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|id           |path   | string        |id is a uuid attribute of the pod binding. It is     |
|             |       |               |automatically generated when new binding relation    |
|             |       |               |happens between tenant and pod.                      |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

Pod binding represents a mapping relationship between tenant and pod. All
of its attributes are described in the following table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|tenant_id    |body   | string        |tenant_id is automatically generated when adding a   |
|             |       |               |uuid of a project object in KeyStone. "Tenant" is an |
|             |       |               |old term for a project in Keystone. Starting in API  |
|             |       |               |version 3, "project" is the preferred term.          |
|             |       |               |Accordingly, project_id is used instead of tenant_id.|
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-------------+-------+---------------+-----------------------------------------------------+
|id           |body   | string        |id is a uuid attribute of the pod binding. It is     |
|             |       |               |automatically generated when new binding relation    |
|             |       |               |happens between tenant and pod.                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | date          |created time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | date          |updated time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+

**Response Example**

This is an example of response information for GET /bindings/{id}.

::

    {
        "pod_binding": {
            "updated_at": null,
            "tenant_id": "1782b3310f144836aa73c1ac5117d8da",
            "created_at": "2016-06-03 07:37:06",
            "id": "f0a54f30-6208-499d-b087-0ac64f6f2756",
            "pod_id": "3c22e5d4-5fed-45ed-a1e9-d532668cedc2"
        }
    }


+---------------+-----------+--------------------+------------------------------------------+
|**POST**       |/bindings  |                    |Create a Pod Binding                      |
+---------------+-----------+--------------------+------------------------------------------+

This creates a pod binding.

Normal Response Code: 200

**Request**

Some essential attributes of the pod binding instance are required and
described in the following table.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|tenant_id    |body   | string        |tenant_id is automatically generated when adding a   |
|             |       |               |uuid of a project object in KeyStone. "Tenant" is an |
|             |       |               |old term for a project in Keystone. Starting in API  |
|             |       |               |version 3, "project" is the preferred term.          |
|             |       |               |Accordingly, project_id is used instead of tenant_id.|
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-------------+-------+---------------+-----------------------------------------------------+

**Response**

An id is assigned to a pod binding instance when it is created, and some other
attribute values are given meanwhile. All of its fields are listed below.

+-------------+-------+---------------+-----------------------------------------------------+
|Name         |In     |   Type        |    Description                                      |
+=============+=======+===============+=====================================================+
|tenant_id    |body   | string        |tenant_id is automatically generated when adding a   |
|             |       |               |uuid of a project object in KeyStone. "Tenant" is an |
|             |       |               |old term for a project in Keystone. Starting in API  |
|             |       |               |version 3, "project" is the preferred term.          |
|             |       |               |Accordingly, project_id is used instead of tenant_id.|
+-------------+-------+---------------+-----------------------------------------------------+
|pod_id       |body   | string        |pod_id is a uuid attribute of the pod object.        |
+-------------+-------+---------------+-----------------------------------------------------+
|id           |body   | string        |id is a uuid attribute of the pod binding. It is     |
|             |       |               |automatically generated when new binding relation    |
|             |       |               |happens between tenant and pod.                      |
+-------------+-------+---------------+-----------------------------------------------------+
|created_at   |body   | date          |created time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+
|updated_at   |body   | date          |updated time of the pod binding.                     |
+-------------+-------+---------------+-----------------------------------------------------+

**Request Example**

This is an example of request information for POST /bindings.

::

    {
        "pod_binding": {
            "tenant_id": "1782b3310f144836aa73c1ac5117d8da",
            "pod_id": "e02e03b8-a94f-4eb1-991e-a8a271cc2313"
        }
    }

**Response Example**

This is an example of response information for POST /bindings.

::

    {
        "pod_binding": {
            "updated_at": null,
            "tenant_id": "1782b3310f144836aa73c1ac5117d8da",
            "created_at": "2016-08-18 14:06:33",
            "id": "b17ac347-c898-4cea-a09d-7b0a6ec34f56",
            "pod_id": "e02e03b8-a94f-4eb1-991e-a8a271cc2313"
        }
    }

+---------------+----------------+---------------+------------------------------------------+
|**DELETE**     |/bindings/{id}  |               |Delete a Pod Binding                      |
+---------------+----------------+---------------+------------------------------------------+

This deletes a pod binding.

Normal Response Code: 200

**Request**

+-----------+-------+---------------+-----------------------------------------------------+
|Name       |In     |   Type        |    Description                                      |
+===========+=======+===============+=====================================================+
|id         |path   | string        |id is a uuid attribute of the pod binding. It is     |
|           |       |               |automatically generated when new binding relation    |
|           |       |               |happens between tenant and pod.                      |
+-----------+-------+---------------+-----------------------------------------------------+

**Response**

There is no response. But we can list all the pod bindings to verify
whether the specific pod binding has been deleted or not.
