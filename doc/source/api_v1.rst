================
Tricircle API v1
================
This API describes the ways of interacting with Tricircle service via
HTTP protocol using Representational State Transfer(ReST).

Application Root [/]
====================
Application Root provides links to all possible API methods for Tricircle. URLs
for other resources described below are relative to Application Root.

API v1 Root [/v1/]
==================
All API v1 URLs are relative to API v1 root.

Pod [/pods/{pod_id}]
=======================
A pod represents a region in Keystone. When operating a pod, Tricircle
decides the correct endpoints to send request based on the region of the pod.
Considering the 2-layers architecture of Tricircle, we also have 2 kinds of
pods: top pod and bottom pod. A pod has the following attributes:

- pod_id
- pod_name
- pod_az_name
- dc_name
- az_name


**pod_id** is automatically generated when creating a site.

**pod_name** is specified by user but **MUST** match the region name
registered in Keystone. When creating a bottom pod, Tricircle automatically
creates a host aggregate and assigns the new availability zone id to

**az_name**. When **az_name** is empty, that means this pod is top region,
no host aggregate will be generated. If **az_name** is not empty, that means
this pod will belong to this availability zone. Multiple pods with same
**az_name** means that these pods are under same availability zone.

**pod_az_name** is the az name in the bottom pod, it could be empty, if empty,
then no az parameter will be added to the request to the bottom pod. If the
**pod_az_name** is different than **az_name**, then the az parameter will be
replaced to the **pod_az_name** when the request is forwarded to regarding
bottom pod.

**dc_name** is the name of the data center where the pod is located.

URL Parameters
--------------
- pod_id: Pod id

Models
------
::

    {
        "pod_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
        "pod_name": "pod1",
        "pod_az_name": "az1",
        "dc_name": "data center 1",
        "az_name": "az1"
    }

Retrieve Pod List [GET]
------------------------
- URL: /pods
- Status: 200
- Returns: List of Pods

Response
::

    {
        "pods": [
            {
                "pod_id": "f91ca3a5-d5c6-45d6-be4c-763f5a2c4aa3",
                "pod_name": "RegionOne",
            },
            {
                "pod_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
                "pod_name": "pod1",
                "pod_az_name": "az1",
                "dc_name": "data center 1",
                "az_name": "az1"
            }
        ]
    }

Retrieve a Single Pod [GET]
----------------------------
- URL: /pods/pod_id
- Status: 200
- Returns: Pod

Response
::

    {
        "pod": {
           "pod_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
           "pod_name": "pod1",
           "pod_az_name": "az1",
           "dc_name": "data center 1",
           "az_name": "az1"
        }
    }

Create a Pod [POST]
--------------------
- URL: /pods
- Status: 201
- Returns: Created Pod

Request (application/json)
::

    # for the pod represent the region where the Tricircle is running
    {
        "pod": {
           "pod_name": "RegionOne",
        }
    }

    # for the bottom pod which is managed by Tricircle
    {
        "pod": {
           "pod_name": "pod1",
           "pod_az_name": "az1",
           "dc_name": "data center 1",
           "az_name": "az1"
        }
    }

Response
::

    # for the pod represent the region where the Tricircle is running
    {
        "pod": {
           "pod_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
           "pod_name": "RegionOne",
           "pod_az_name": "",
           "dc_name": "",
           "az_name": ""
        }
    }

    # for the bottom pod which is managed by Tricircle
    {
        "pod": {
           "pod_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
           "pod_name": "pod1",
           "pod_az_name": "az1",
           "dc_name": "data center 1",
           "az_name": "az1"
        }
    }
