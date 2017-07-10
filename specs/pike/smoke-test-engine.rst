=================
Smoke Test Engine
=================

Problems
========
Currently we are running a simple smoke test in the CI job. Several resources
are created to build a simple topology, then we query to check whether the
resources are also created in local Neutron servers as expected. The problems
exist are:

- 1 Bash scripts are used to invoke client to send API request while python
  scripts are used to check the result. Mix use of bash and python makes us
  hard to write new tests.
- 2 Resources are not cleaned at the end of the test so we can't proceed other
  tests in the same environment.

Proposal
========
Using bash scripts to do both API request and result validation is tricky and
hard to read, working with python is a better choice. We have several python
libraries that can help us to send API request: openstackclient, neutronclient
and openstacksdk. The main goal of the first two libraries is providing command
line interface(CLI), so they don't expose methods for us to send API request,
but we can still use them by calling internal functions that are used by their
CLI instance. The drawback of using internal functions is that those internal
functions are undocumented and are possible to be changed or removed someday.
Compare to openstackclient and neutronclient, openstacksdk is a library that
aims for application building and is well-documented. Actually openstackclient
uses openstacksdk for some of its commands' implementation. The limitation of
openstacksdk is that some service extensions like trunk and service function
chaining have not been supported yet, but it's easy to extend by our own.

Before starting to write python code to prepare, validate and finally clean
resources for each test scenario, let's hold on and move one step forward. Heat
uses template to define resources and networking topologies that need to be
created, we can also use YAML file to describe our test tasks.

Schema
------

A task can be defined as a dict that has the following basic fields:

.. csv-table::
   :header: Field, Type, Description, Required or not
   :widths: 10, 10, 40, 10

   task_id, string, user specified task ID, required
   region, string, keystone region to send API, required
   type, string, resource type, required
   depend, list, task IDs the current task depends on, optional
   params, dict, "parameters to run the task, usage differs in different task types", optional

Currently four type of tasks are defined. The usage of "params" field for each
type of task is listed below:

.. csv-table::
   :header: Task type, Usage of "params" field
   :widths: 10, 50

   create, used as the post body of the create request
   query, used as the query filter
   action, used as the put body of the action request
   validate, used as the filter to query resources that need to be validated

Task doesn't have "task type" field, but it can have an extra dict type field
to include extra needed information for that task. This extra field differs in
different task types. "Create" task doesn't have an extra field.

.. list-table::
   :widths: 15, 10, 10, 40, 10
   :header-rows: 1

   * - Extra field
     - Sub field
     - Type
     - Description
     - Required or not
   * - query(for query task)
     - get_one
     - bool
     - whether to return an element or a list
     - required
   * - action(for action task)
     - target
     - string
     - target resource ID
     - required
   * -
     - method
     - string
     - action method, "update" and "delete" are also included
     - required
   * -
     - retries
     - int
     - times to retry the current task
     - optional
   * - validate(for validate task)
     - predicate
     - string
     - value should be "any" or "all", "any" means that for each condition,
       there exists an resource satisfying that condition; "all" means that
       every condition is satisfied by all the resources
     - required
   * -
     - condition
     - list
     - each condition is a dict, key of the dict is the field of the resource,
       value of the dict is the expected value of the resource field
     - required
   * -
     - retries
     - int
     - times to retry the current task
     - optional

Several related tasks can be grouped to form a task set. A task set is a dict
with the following fields:

.. csv-table::
   :header: Field, Type, Description, Required or not
   :widths: 10, 10, 40, 10

   task_set_id, string, user specified task set ID, required
   depend, list, task set IDs the current task set depends on, optional
   tasks, list, task dicts of the task set, required

So the YAML file contains a list of task sets.

Result and Reference
--------------------

"Create" and "query" type tasks will return results, which can be used in the
definition of other tasks that depend on them. Use ``task_id@resource_field``
to refer to "resource_field" of the resource returned by "task_id". If the task
relied on belongs to other task set, use ``task_set_id@task_id@resource_field``
to specify the task set ID. The reference can be used in the "params", "action
target" and "validate condition" field. If reference is used, task_id needs to
be in the list of task's "depend" field, and task_set_id needs to be in the
list of task set's "depend" field. For the "query" type task which is depended
on, "get_one" field needs to be true.

Example
-------

Give an example to show how to use the above schema to define tasks::

  - task_set_id: preparation
    tasks:
      - task_id: image1
        region: region1
        type: image
        query:
          get_one: true
      - task_id: net1
        region: central
        type: network
        params:
          name: net1
      - task_id: subnet1
        region: central
        type: subnet
        depend: [net1]
        params:
          name: subnet1
          ip_version: 4
          cidr: 10.0.1.0/24
          network_id: net1@id
      - task_id: vm1
        region: region1
        type: server
        depend:
          - net1
          - subnet1
          - image1
        params:
          flavor_id: 1
          image_id: image1@id
          name: vm1
          networks:
            - uuid: net1@id
  - task_set_id: wait-for-job
    tasks:
      - task_id: check-job
        region: central
        type: job
        validate:
          predicate: all
          retries: 10
          condition:
            - status: SUCCESS
  - task_set_id: check
    depend: [preparation]
    tasks:
      - task_id: check-servers1
        region: region1
        type: server
        validate:
          predicate: any
          condition:
            - status: ACTIVE
              name: vm1

The above YAML content define three task sets. "Preparation" task set create
network, subnet and server, then "wait-for-job" task set waits for asynchronous
jobs to finish, finally "check" task set check whether the server is active.

Implementation
==============

A task engine needs to be implemented to parse the YAML file, analyse the task
and task set dependency and then run the tasks. A runner based on openstacksdk
will also be implemented.

Dependencies
============

None
