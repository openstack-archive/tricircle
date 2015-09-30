================
Tricircle API v1
================
This API describes the ways of interacting with Tricircle(Cascade) service via
HTTP protocol using Representational State Transfer(ReST).

Application Root [/]
====================
Application Root provides links to all possible API methods for Tricircle. URLs
for other resources described below are relative to Application Root.

API v1 Root [/v1/]
==================
All API v1 URLs are relative to API v1 root.

Site [/sites/{site_id}]
=======================
A site represents a region in Keystone. When operating a site, Tricircle
decides the correct endpoints to send request based on the region of the site.
Considering the 2-layers architecture of Tricircle, we also have 2 kinds of
sites: top site and bottom site. A site has the following attributes:

- site_id
- site_name
- az_id

**site_id** is automatically generated when creating a site. **site_name** is
specified by user but **MUST** match the region name registered in Keystone.
When creating a bottom site, Tricircle automatically creates a host aggregate
and assigns the new availability zone id to **az_id**. Top site doesn't need a
host aggregate so **az_id** is left empty.

URL Parameters
--------------
- site_id: Site id

Models
------
::

    {
        "site_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
        "site_name": "Site1",
        "az_id": "az_Site1"
    }

Retrieve Site List [GET]
------------------------
- URL: /sites
- Status: 200
- Returns: List of Sites

Response
::

    {
        "sites": [
            {
                "site_id": "f91ca3a5-d5c6-45d6-be4c-763f5a2c4aa3",
                "site_name": "RegionOne",
                "az_id": ""
            },
            {
                "site_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
                "site_name": "Site1",
                "az_id": "az_Site1"
            }
        ]
    }

Retrieve a Single Site [GET]
----------------------------
- URL: /sites/site_id
- Status: 200
- Returns: Site

Response
::

    {
        "site": {
            "site_id": "302e02a6-523c-4a92-a8d1-4939b31a788c",
            "site_name": "Site1",
            "az_id": "az_Site1"
        }
    }

Create a Site [POST]
--------------------
- URL: /sites
- Status: 201
- Returns: Created Site

Request (application/json)

.. csv-table::
    :header: "Parameter", "Type", "Description"

    name, string, name of the Site
    top, bool, "indicate whether it's a top Site, optional, default false"

::

    {
        "name": "RegionOne"
        "top": true
    }

Response
::

    {
        "site": {
            "site_id": "f91ca3a5-d5c6-45d6-be4c-763f5a2c4aa3",
            "site_name": "RegionOne",
            "az_id": ""
        }
    }
