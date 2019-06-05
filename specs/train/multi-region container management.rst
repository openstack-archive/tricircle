=============================================
Container Management in Multi-Region Scenario
=============================================

Background
==========

Currently, multi-region container management is not supported in the Tricircle.
This spec is to describe how container management will be implemented
in the Tricircle multi-region scenario. Now openstack provides many components
for container services such as zun,kuyr,kuryr-libnetwork. Zun is a component that
provides container management service in openstack, it provides a unified OpenStack API
for launching and managing containers, supporting docker container technology.
Kuryr is an component that interfaces a container network to a neutron network.
Kuryr-libnetwork is a kuryr plugin running under the libnetwork framework and provides
network services for containers. Zun integrates with keystone, neutron,
and glance to implement container management. Keystone provides identity authentication
for containers, neutron provides network for containers, and glance provides images for containers.
These openstack services work together to accomplish the multi-region container management.

Overall Implementation
======================

The Tricircle is designed in a Central_Neutron-Local_Neutron fashion, where all the local neutrons are
managed by the central neutron. As a result, in order to adapt the Central_Neutron-Local_Neutron design and
the container network requirements and image requirements, we plan to deploy zun, kuryr,kuryr-libnetwork and
raw docker engine as follows. ::

 +--------------------------------------------------+                     +--------------------------------------------------+
 |                                                  |    Central Region   |                                                  |
 |        +--------+                             +--×---------------------×--+                             +--------+        |
 |  +-----| Glance |                User   <---- |          Keystone         | ---->   User                | Glance |-----+  |
 |  |     +--------+              x------x       +---------------------------+       x------x              +--------+     |  |
 |  |                                |           |       Central Neutron     |           |                                |  |
 |  |  +---------------+             |           +--×----^-----------^----×--+           |             +---------------+  |  |
 |  |  |   Zun  API    |<------------+              |    |           |    |              +------------>|   Zun  API    |  |  |
 |  |  +---------------+        +---------------+   |    |           |    |   +---------------+        +---------------+  |  |
 |  |  |               |        |               |   |    |           |    |   |               |        |               |  |  |
 |  +--+  Zun Compute  +--------+ Docker Engine |   |    |           |    |   | Docker Engine +--------+  Zun Compute  +--+  |
 |     |               |        |               |   |    |           |    |   |               |        |               |     |
 |     +-------+-------+        +-------+-------+   |    |           |    |   +-------+-------+        +-------+-------+     |
 |             |                        |           |    |           |    |           |                        |             |
 |             |                        |           |    |           |    |           |                        |             |
 |     +-------+-------+        +-------+-------+   |    |           |    |   +-------+-------+        +-------+-------+     |
 |     |               |        |               |   |    |           |    |   |               |        |               |     |
 |     | Local Neutron +--------+     Kuryr     |   |    |           |    |   |     Kuryr     <--------> Local Neutron |     |
 |     |               |        |  libnetwork   |   |    |           |    |   |  libnetwork   |        |               |     |
 |     +-------+-------+        +---------------+   |    |           |    |   +---------------+        +-------+-------+     |
 |             |                                    |    |           |    |                                    |             |
 |             +------------------------------------×----+           +----×------------------------------------+             |
 |                                                  |                     |                                                  |
 +--------------------------------------------------+                     +--------------------------------------------------+
                      Region One                                                               Region Two

                                Fig. 1 The multi-region container management architecture.

As showned in the Fig. 1 above, in Tricircle, each region has already installed
a local neutron. In order to accomplish container management in Tricircle,
admins need to configure and install zun,docker,kuryr and kuryr-libnetwork.
Under the Central_Neutron-Local_Neutron scenario, we plan to let zun employ
the central neutron in Central Region to manage networking resources, meanwhile
still employ docker engine in its own region to manage docker container instance.
Then, use kuryr/kuryr-libnetwork to connect the container network to the neutron network.
Hence, the workflow of container creation in Tricircle can be described as follows. ::

 +-----------------------------------------------------------------------------------------------------------------------------------------------+
 |                                                  +---------------+    +---------------+    +-----------------+    +-------------------------+ |
 |             +----------+                     +-->| neutronClient | -->| Local Neutron | -->| Central Neutron | -->|Neutron network and port | |
 |    +------->| Keystone |                     |   +---------------+    +------^--------+    +--------+--------+    +-------------+-----------+ |
 |    |        +----------+                     |                               |                      |                           |             |
 |    |                                         |   +------------------+        +----------------------+         +-----------------+-----------+ |
 |    |                                         +-->| kuryr/libnetwork | --------------------------------------->|Connect container to network | |
 | +--+---+    +---------+    +-------------+   |   +------------------+                                         +-----------------+-----------+ |
 | | User | -->| Zun API | -->| Zun Compute | --+                                                                                  |             |
 | +------+    +---------+    +-------------+   |   +--------------+    +--------------+                                           |             |
 |                                              +-->| glanceClient | -->| docker image |                                     +=====+=====+       |
 |                                              |   +--------------+    +------+-------+                                     ‖ Container ‖       |
 |                                              |                              |                                             +=====+=====+       |
 |                                              |   +------------+    +--------V---------------+                                   |             |
 |                                              +-->| Docker API | -->| Create docker instance | ----------------------------------+             |
 |                                                  +------------+    +------------------------+                                                 |
 +-----------------------------------------------------------------------------------------------------------------------------------------------+
                                             Fig. 2 The multi-region container creation workflow.

Specifically, when a tenant attempts to create container, he/she needs to
send a request to Zun API. Then it will call zun compute driver to create
a container in four sub-steps. Firstly, call network_api(neutronClient) to
process neutron network(use Central_Neutron-Local_Neutron mechanism). Secondly,
call image_api(glanceClient) to provide docker image. Thirdly, call docker API
to create docker instance. Finally, use kuryr connect container to neutron network.
So far, a container can successfully created in Tricircle environment. Considering
the Tricircle is dedicated to enabling networking automation across Neutrons, so we
can implement the interconnection among multiple containers in multi-region scenario.
As shown below. ::

  +------------------------+   +-------------------+   +------------------------+
  |    net1                |   |                   |   |               net1     |
  | +---------+--------------------------+-------------------------+----------+ |
  |           |            |   |         |         |   |           |            |
  |           |            |   |         |         |   |           |            |
  |     +-----+------+     |   |         |         |   |     +-----+------+     |
  |     | Container1 |     |   |    +----+----+    |   |     | Container2 |     |
  |     +------------+     |   |    |         |    |   |     +------------+     |
  |                        |   |    |  Router |    |   |                        |
  |     +-----+------+     |   |    |         |    |   |     +-----+------+     |
  |     | Container3 |     |   |    +----+----+    |   |     | Container4 |     |
  |     +-----+------+     |   |         |         |   |     +-----+------+     |
  |           |            |   |         |         |   |           |            |
  |           |            |   |         |         |   |           |            |
  | +---------+--------------------------+-------------------------+----------+ |
  |    net2                |   |                   |   |               net2     |
  |                        |   |                   |   |                        |
  | +--------------------+ |   | +---------------+ |   | +--------------------+ |
  | |   Local  Neutron   | |   | |Central Neutron| |   | |   Local  Neutron   | |
  | +--------------------+ |   | +---------------+ |   | +--------------------+ |
  +------------------------+   +-------------------+   +------------------------+
         Region One               Central Region              Region Two

          Fig. 3 The container interconnection in multi-region scenario.

Although, combined with Tricircle, we can also implement the container deletion,
the container modification, the container lookup and so on in multi-region scenario.
That means we can implement container management in multi-region scenario.


Data Model Impact
-----------------

None

Dependencies
------------

None

Documentation Impact
--------------------

None

References
----------

None
