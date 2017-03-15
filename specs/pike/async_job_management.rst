=========================================
Tricircle Asynchronous Job Management API
=========================================

Background
==========
In the Tricircle, XJob provides OpenStack multi-region functionality. It
receives and processes jobs from the Admin API or Tricircle Central
Neutron Plugin and handles them in an asynchronous way. For example, when
booting an instance in the first time for the project, router, security
group rule, FIP and other resources may have not already been created in
the local Neutron(s), these resources could be created asynchronously to
accelerate response for the initial instance booting request, different
from network, subnet and security group resources that must be created
before an instance booting. Central Neutron could send such creation jobs
to local Neutron(s) through XJob and then local Neutron(s) handle them
with their own speed.

Implementation
==============
XJob server may strike occasionally so tenants and cloud administrators
need to know the job status and delete or redo the failed job if necessary.
Asynchronous job management APIs provide such functionality and they are
listed as following:

* Create a job

  Create a job to synchronize resource if necessary.

  Create Job Request::

        POST /v1.0/jobs
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

        Response:
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

        Normal Response Code: 202


* Get a job

  Retrieve a job from the Tricircle database.

  The detailed information of the job will be shown. Otherwise
  it will return "Resource not found" exception.

  List Request::

        GET /v1.0/jobs/3f4ecf30-0213-4f1f-9cb0-0233bcedb767

        Response:
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

        Normal Response Code: 200

* Get all jobs

  Retrieve all of the jobs from the Tricircle database.

  List Request::

        GET /v1.0/jobs/detail

        Response:
        {
           "jobs":
               [
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

        Normal Response Code: 200

* Get all jobs with filter(s)

  Retrieve job(s) from the Tricircle database. We can filter them by
  project ID, job type and job status. If no filter is provided,
  GET /v1.0/jobs will return all jobs.

  The response contains a list of jobs. Using filters, a subset of jobs
  will be returned.

  List Request::

        GET /v1.0/jobs?project_id=d01246bc5792477d9062a76332b7514a

        Response:
        {
           "jobs":
               [
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

        Normal Response Code: 200


* Get all jobs' schemas

  Retrieve all jobs' schemas. User may want to know what the resources
  are needed for a specific job.

  List Request::

        GET /v1.0/jobs/schemas

        return all jobs' schemas.
        Response:
        {
           "schemas":
               [
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

        Normal Response Code: 200


* Delete a job

  Delete a failed or duplicated job from the Tricircle database.
  A pair of curly braces will be returned if succeeds, otherwise an
  exception will be thrown. What's more, we can list all jobs to verify
  whether it is deleted successfully or not.

  Delete Job Request::

        DELETE /v1.0/jobs/{id}

        Response:
        This operation does not return a response body.

        Normal Response Code: 200


* Redo a job

  Redo a halted job brought by the XJob server corruption or network failures.
  The job handler will redo a failed job with time interval, but this Admin
  API will redo a job immediately. Nothing will be returned for this request,
  but we can monitor its status through the execution state.

  Redo Job Request::

        PUT /v1.0/jobs/{id}

        Response:
        This operation does not return a response body.

        Normal Response Code: 200


Data Model Impact
=================

In order to manage the jobs for each tenant, we need to filter them by
project ID. So project ID is going to be added to the AsyncJob model and
AsyncJobLog model.

Dependencies
============

None

Documentation Impact
====================

- Add documentation for asynchronous job management API
- Add release note for asynchronous job management API

References
==========

None

