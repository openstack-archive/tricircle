===============================================================
Multiple North-South gateways with East-West Networking enabled
===============================================================

The following figure illustrates another typical networking mode.
In multi-region cloud deployment, a requirement is that each OpenStack
cloud provides external network, north-south traffic is expected to be
handled locally for shortest path, and/or use multiple external networks
to ensure application north-south traffic redundancy, at the same time
east-west networking of tenant's networks among OpenStack clouds is also
needed.

.. code-block:: console

    +-------------------------------+             +------------------------------+
    | RegionOne    ext-net1         |             | RegionTwo   ext-net2         |
    |             +-------+         |             |              +--+---+        |
    |                 |             |             |                 |            |
    |             +---+-------+     |             | +---------------+--+         |
    |             |    R1     |     |             | |      R2          |         |
    |             +--+--+-----+     |             | +-------+-----+----+         |
    |     net1       |  |           |             |         |     | net3         |
    |   +-+-------+--++ |           |             |         |   +-++----+----+   |
    |     |       |     | net2      |             |  net4   |      |    |        |
    | +---+-----+ |  ++-+---+--+    |             | +-+-----+---++ | +--+------+ |
    | |Instance1| |   |     |       |             |   |         |  | |Instance3| |
    | +---------+ |   | +---+-----+ |             | +-+-------+ |  | +---------+ |
    |             |   | |Instance2| |             | |Instance4| |  |             |
    |             |   | +---------+ |             | +---------+ |  |             |
    |        +----+---+--------+    | bridge-net  |  +----------+--+-----+       |
    |        |      R3(1)      +---------------------+        R3(2)      |       |
    |        +-----------------+    |             |  +-------------------+       |
    +-------------------------------+             +------------------------------+

The logical topology to be composed in Tricircle is as follows. R3(1), R3(2)
and bridge-net will be one logical router R3, and R3 is only for cross
Neutron east-west traffic. North-south traffic of net1, net2 will go
through R1, north-south traffic of net3, net4 will go through R2.

.. code-block:: console

                  ext-net1                                     ext-net2
                 +-------+                                      +--+---+
                     |                                             |
                 +---+----------+                  +---------------+--+
                 | R1(RegionOne)|                  |  R2(RegionTwo)   |
                 +--+--+--------+                  +-------+-----+----+
    net1(RegionOne) |  |                                   |     | net3(RegionTwo)
       +-+-------+--++ |                            net4   |   +-++----+----+
         |       |     | net2(RegionOne)       (RegionTwo) |      |    |
     +---+-----+ |  ++-+---+--+                    +-+-----+---++ | +--+------+
     |Instance1| |   |     |                         |         |  | |Instance3|
     +---------+ |   | +---+-----+                 +-+-------+ |  | +---------+
                 |   | |Instance2|                 |Instance4| |  |
                 |   | +---------+                 +---------+ |  |
            +----+---+-----------------------------------------+--+-----+
            |                 R3(RegionOne,RegionTwo)                   |
            +-----------------------------------------------------------+


How to create this network topology
===================================

Create external network ext-net1, which will be located in RegionOne.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type flat --provider:physical_network extern --router:external --availability-zone-hint RegionOne ext-net1

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionOne                            |
    | id                        | ff7375f3-5bc6-4349-b097-72e42a90648a |
    | name                      | ext-net1                             |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | flat                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  |                                      |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a79642b4c1674be1b306d8c436d07793     |
    +---------------------------+--------------------------------------+

Create subnet in ext-net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet1 --disable-dhcp ext-net1 163.3.3.0/24
    +-------------------+----------------------------------------------+
    | Field             | Value                                        |
    +-------------------+----------------------------------------------+
    | allocation_pools  | {"start": "163.3.3.2", "end": "163.3.3.254"} |
    | cidr              | 163.3.3.0/24                                 |
    | created_at        | 2017-04-19T06:04:07Z                         |
    | description       |                                              |
    | dns_nameservers   |                                              |
    | enable_dhcp       | False                                        |
    | gateway_ip        | 163.3.3.1                                    |
    | host_routes       |                                              |
    | id                | 3d0cfacc-ce90-4924-94b9-a95d567568b9         |
    | ip_version        | 4                                            |
    | ipv6_address_mode |                                              |
    | ipv6_ra_mode      |                                              |
    | name              | ext-subnet1                                  |
    | network_id        | ff7375f3-5bc6-4349-b097-72e42a90648a         |
    | project_id        | a79642b4c1674be1b306d8c436d07793             |
    | revision_number   | 2                                            |
    | subnetpool_id     |                                              |
    | tags              |                                              |
    | tenant_id         | a79642b4c1674be1b306d8c436d07793             |
    | updated_at        | 2017-04-19T06:04:07Z                         |
    +-------------------+----------------------------------------------+

Create router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create --availability-zone-hint RegionOne R1
    +-------------------------+--------------------------------------+
    | Field                   | Value                                |
    +-------------------------+--------------------------------------+
    | admin_state_up          | True                                 |
    | availability_zone_hints | RegionOne                            |
    | availability_zones      |                                      |
    | created_at              | 2017-04-19T06:04:37Z                 |
    | description             |                                      |
    | distributed             | False                                |
    | external_gateway_info   |                                      |
    | id                      | a665d383-bb0b-478a-b4c7-d0b316a01806 |
    | name                    | R1                                   |
    | project_id              | a79642b4c1674be1b306d8c436d07793     |
    | revision_number         | 4                                    |
    | status                  | ACTIVE                               |
    | tags                    |                                      |
    | tenant_id               | a79642b4c1674be1b306d8c436d07793     |
    | updated_at              | 2017-04-19T06:04:37Z                 |
    +-------------------------+--------------------------------------+

Set the router gateway to ext-net1 for R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-gateway-set R1 ext-net1
    Set gateway for router R1

    $ neutron --os-region-name=CentralRegion router-show R1
    +-------------------------+----------------------------------------------------------------------------------------------------------+
    | Field                   | Value                                                                                                    |
    +-------------------------+----------------------------------------------------------------------------------------------------------+
    | admin_state_up          | True                                                                                                     |
    | availability_zone_hints | RegionOne                                                                                                |
    | availability_zones      |                                                                                                          |
    | created_at              | 2017-04-19T06:04:37Z                                                                                     |
    | description             |                                                                                                          |
    | distributed             | False                                                                                                    |
    | external_gateway_info   | {"network_id": "ff7375f3-5bc6-4349-b097-72e42a90648a", "external_fixed_ips": [{"subnet_id": "3d0cfacc-   |
    |                         | ce90-4924-94b9-a95d567568b9", "ip_address": "163.3.3.7"}]}                                               |
    | id                      | a665d383-bb0b-478a-b4c7-d0b316a01806                                                                     |
    | name                    | R1                                                                                                       |
    | project_id              | a79642b4c1674be1b306d8c436d07793                                                                         |
    | revision_number         | 6                                                                                                        |
    | status                  | ACTIVE                                                                                                   |
    | tags                    |                                                                                                          |
    | tenant_id               | a79642b4c1674be1b306d8c436d07793                                                                         |
    | updated_at              | 2017-04-19T06:05:11Z                                                                                     |
    +-------------------------+----------------------------------------------------------------------------------------------------------+

Create local network net1 which will reside in RegionOne. You can use
RegionOne as the value of availability-zone-hint to create a local network.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --availability-zone-hint RegionOne net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionOne                            |
    | id                        | bbc5527d-25a5-4ea1-9ef6-47e7dca9029b |
    | name                      | net1                                 |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a79642b4c1674be1b306d8c436d07793     |
    +---------------------------+--------------------------------------+

Create a subnet in net1.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion subnet create --network=net1 --subnet-range 10.0.1.0/24 subnet-net1
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | allocation_pools  | 10.0.1.2-10.0.1.254                  |
    | cidr              | 10.0.1.0/24                          |
    | created_at        | 2017-04-19T06:16:32Z                 |
    | description       |                                      |
    | dns_nameservers   |                                      |
    | enable_dhcp       | True                                 |
    | gateway_ip        | 10.0.1.1                             |
    | host_routes       |                                      |
    | id                | b501197b-53c8-44a6-8e4a-ee36260da239 |
    | ip_version        | 4                                    |
    | ipv6_address_mode | None                                 |
    | ipv6_ra_mode      | None                                 |
    | name              | subnet-net1                          |
    | network_id        | bbc5527d-25a5-4ea1-9ef6-47e7dca9029b |
    | project_id        | a79642b4c1674be1b306d8c436d07793     |
    | revision_number   | 2                                    |
    | segment_id        | None                                 |
    | service_types     | None                                 |
    | subnetpool_id     | None                                 |
    | updated_at        | 2017-04-19T06:16:32Z                 |
    +-------------------+--------------------------------------+

Add this subnet to router R1.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion router add subnet R1 subnet-net1

Create local network net2 which will reside in RegionOne. You can use
RegionOne as the value of availability-zone-hint to create a local network.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion network create --availability-zone-hint=RegionOne net2
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | UP                                   |
    | availability_zone_hints   | RegionOne                            |
    | availability_zones        | None                                 |
    | created_at                | None                                 |
    | description               | None                                 |
    | dns_domain                | None                                 |
    | id                        | 3779cfd5-790c-43a7-9231-ed473789dc93 |
    | ipv4_address_scope        | None                                 |
    | ipv6_address_scope        | None                                 |
    | is_default                | None                                 |
    | mtu                       | None                                 |
    | name                      | net2                                 |
    | port_security_enabled     | False                                |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | local                                |
    | provider:physical_network | None                                 |
    | provider:segmentation_id  | None                                 |
    | qos_policy_id             | None                                 |
    | revision_number           | None                                 |
    | router:external           | Internal                             |
    | segments                  | None                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | updated_at                | None                                 |
    +---------------------------+--------------------------------------+

Create a subnet in net2.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion subnet create --network=net2 --subnet-range 10.0.2.0/24 subnet-net2
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | allocation_pools  | 10.0.2.2-10.0.2.254                  |
    | cidr              | 10.0.2.0/24                          |
    | created_at        | 2017-04-19T06:28:19Z                 |
    | description       |                                      |
    | dns_nameservers   |                                      |
    | enable_dhcp       | True                                 |
    | gateway_ip        | 10.0.2.1                             |
    | host_routes       |                                      |
    | id                | d0222001-e80f-49c3-9f0a-7f3688843e66 |
    | ip_version        | 4                                    |
    | ipv6_address_mode | None                                 |
    | ipv6_ra_mode      | None                                 |
    | name              | subnet-net2                          |
    | network_id        | 3779cfd5-790c-43a7-9231-ed473789dc93 |
    | project_id        | a79642b4c1674be1b306d8c436d07793     |
    | revision_number   | 2                                    |
    | segment_id        | None                                 |
    | service_types     | None                                 |
    | subnetpool_id     | None                                 |
    | updated_at        | 2017-04-19T06:28:19Z                 |
    +-------------------+--------------------------------------+

Add this subnet to router R1.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion router add subnet R1 subnet-net2

Create external network ext-net2, which will be located in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type flat --provider:physical_network extern --router:external --availability-zone-hint RegionTwo ext-net2

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionTwo                            |
    | id                        | 6f0f139d-6857-45f5-925d-419b5f896c2a |
    | name                      | ext-net2                             |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | flat                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  |                                      |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a79642b4c1674be1b306d8c436d07793     |
    +---------------------------+--------------------------------------+

Create subnet in ext-net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet2 --disable-dhcp ext-net2 163.3.5.0/24
    +-------------------+----------------------------------------------+
    | Field             | Value                                        |
    +-------------------+----------------------------------------------+
    | allocation_pools  | {"start": "163.3.5.2", "end": "163.3.5.254"} |
    | cidr              | 163.3.5.0/24                                 |
    | created_at        | 2017-04-19T07:00:01Z                         |
    | description       |                                              |
    | dns_nameservers   |                                              |
    | enable_dhcp       | False                                        |
    | gateway_ip        | 163.3.5.1                                    |
    | host_routes       |                                              |
    | id                | 7680acd4-db7c-44f0-bf7d-6f76e2de5778         |
    | ip_version        | 4                                            |
    | ipv6_address_mode |                                              |
    | ipv6_ra_mode      |                                              |
    | name              | ext-subnet2                                  |
    | network_id        | 6f0f139d-6857-45f5-925d-419b5f896c2a         |
    | project_id        | a79642b4c1674be1b306d8c436d07793             |
    | revision_number   | 2                                            |
    | subnetpool_id     |                                              |
    | tags              |                                              |
    | tenant_id         | a79642b4c1674be1b306d8c436d07793             |
    | updated_at        | 2017-04-19T07:00:01Z                         |
    +-------------------+----------------------------------------------+

Create router R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create --availability-zone-hint RegionTwo R2
    +-------------------------+--------------------------------------+
    | Field                   | Value                                |
    +-------------------------+--------------------------------------+
    | admin_state_up          | True                                 |
    | availability_zone_hints | RegionTwo                            |
    | availability_zones      |                                      |
    | created_at              | 2017-04-19T07:00:31Z                 |
    | description             |                                      |
    | distributed             | False                                |
    | external_gateway_info   |                                      |
    | id                      | 643cc4ec-cdd5-4b14-bcc6-328b86035d50 |
    | name                    | R2                                   |
    | project_id              | a79642b4c1674be1b306d8c436d07793     |
    | revision_number         | 4                                    |
    | status                  | ACTIVE                               |
    | tags                    |                                      |
    | tenant_id               | a79642b4c1674be1b306d8c436d07793     |
    | updated_at              | 2017-04-19T07:00:31Z                 |
    +-------------------------+--------------------------------------+

Set the router gateway to ext-net2 for R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-gateway-set R2 ext-net2
    Set gateway for router R2

    $ neutron --os-region-name=CentralRegion router-show R2
    +-------------------------+----------------------------------------------------------------------------------------------------------+
    | Field                   | Value                                                                                                    |
    +-------------------------+----------------------------------------------------------------------------------------------------------+
    | admin_state_up          | True                                                                                                     |
    | availability_zone_hints | RegionTwo                                                                                                |
    | availability_zones      |                                                                                                          |
    | created_at              | 2017-04-19T07:00:31Z                                                                                     |
    | description             |                                                                                                          |
    | distributed             | False                                                                                                    |
    | external_gateway_info   | {"network_id": "6f0f139d-6857-45f5-925d-419b5f896c2a", "external_fixed_ips": [{"subnet_id": "7680acd4    |
    |                         | -db7c-44f0-bf7d-6f76e2de5778", "ip_address": "163.3.5.10"}]}                                             |
    | id                      | 643cc4ec-cdd5-4b14-bcc6-328b86035d50                                                                     |
    | name                    | R2                                                                                                       |
    | project_id              | a79642b4c1674be1b306d8c436d07793                                                                         |
    | revision_number         | 6                                                                                                        |
    | status                  | ACTIVE                                                                                                   |
    | tags                    |                                                                                                          |
    | tenant_id               | a79642b4c1674be1b306d8c436d07793                                                                         |
    | updated_at              | 2017-04-19T07:00:54Z                                                                                     |
    +-------------------------+----------------------------------------------------------------------------------------------------------+

Create local network net3 which will reside in RegionTwo. You can use
RegionTwo as the value of availability-zone-hint to create a local network.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion network create --availability-zone-hint=RegionTwo net3
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | UP                                   |
    | availability_zone_hints   | RegionTwo                            |
    | availability_zones        | None                                 |
    | created_at                | None                                 |
    | description               | None                                 |
    | dns_domain                | None                                 |
    | id                        | a914edd9-629e-41bd-98ef-ec52736aeaa2 |
    | ipv4_address_scope        | None                                 |
    | ipv6_address_scope        | None                                 |
    | is_default                | None                                 |
    | mtu                       | None                                 |
    | name                      | net3                                 |
    | port_security_enabled     | False                                |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | local                                |
    | provider:physical_network | None                                 |
    | provider:segmentation_id  | None                                 |
    | qos_policy_id             | None                                 |
    | revision_number           | None                                 |
    | router:external           | Internal                             |
    | segments                  | None                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | updated_at                | None                                 |
    +---------------------------+--------------------------------------+

Create a subnet in net3.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion subnet create --network=net3 --subnet-range 10.0.3.0/24 subnet-net3
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | allocation_pools  | 10.0.3.2-10.0.3.254                  |
    | cidr              | 10.0.3.0/24                          |
    | created_at        | 2017-04-19T07:15:46Z                 |
    | description       |                                      |
    | dns_nameservers   |                                      |
    | enable_dhcp       | True                                 |
    | gateway_ip        | 10.0.3.1                             |
    | host_routes       |                                      |
    | id                | a2582af0-ab39-43e7-8b23-f2911804633b |
    | ip_version        | 4                                    |
    | ipv6_address_mode | None                                 |
    | ipv6_ra_mode      | None                                 |
    | name              | subnet-net3                          |
    | network_id        | a914edd9-629e-41bd-98ef-ec52736aeaa2 |
    | project_id        | a79642b4c1674be1b306d8c436d07793     |
    | revision_number   | 2                                    |
    | segment_id        | None                                 |
    | service_types     | None                                 |
    | subnetpool_id     | None                                 |
    | updated_at        | 2017-04-19T07:15:46Z                 |
    +-------------------+--------------------------------------+

Add this subnet to router R2.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion router add subnet R2 subnet-net3


Create local network net4 which will reside in RegionTwo. You can use
RegionTwo as the value of availability-zone-hint to create a local network.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion network create --availability-zone-hint=RegionTwo net4
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | UP                                   |
    | availability_zone_hints   | RegionTwo                            |
    | availability_zones        | None                                 |
    | created_at                | None                                 |
    | description               | None                                 |
    | dns_domain                | None                                 |
    | id                        | 60c2e42a-3875-4d11-9850-59148aee24c2 |
    | ipv4_address_scope        | None                                 |
    | ipv6_address_scope        | None                                 |
    | is_default                | None                                 |
    | mtu                       | None                                 |
    | name                      | net4                                 |
    | port_security_enabled     | False                                |
    | project_id                | a79642b4c1674be1b306d8c436d07793     |
    | provider:network_type     | local                                |
    | provider:physical_network | None                                 |
    | provider:segmentation_id  | None                                 |
    | qos_policy_id             | None                                 |
    | revision_number           | None                                 |
    | router:external           | Internal                             |
    | segments                  | None                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | updated_at                | None                                 |
    +---------------------------+--------------------------------------+

Create a subnet in net4.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion subnet create --network=net4 --subnet-range 10.0.4.0/24 subnet-net4
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | allocation_pools  | 10.0.4.2-10.0.4.254                  |
    | cidr              | 10.0.4.0/24                          |
    | created_at        | 2017-04-19T07:19:25Z                 |
    | description       |                                      |
    | dns_nameservers   |                                      |
    | enable_dhcp       | True                                 |
    | gateway_ip        | 10.0.4.1                             |
    | host_routes       |                                      |
    | id                | 5a76080f-efe5-4890-855e-56bd9068c6cf |
    | ip_version        | 4                                    |
    | ipv6_address_mode | None                                 |
    | ipv6_ra_mode      | None                                 |
    | name              | subnet-net4                          |
    | network_id        | 60c2e42a-3875-4d11-9850-59148aee24c2 |
    | project_id        | a79642b4c1674be1b306d8c436d07793     |
    | revision_number   | 2                                    |
    | segment_id        | None                                 |
    | service_types     | None                                 |
    | subnetpool_id     | None                                 |
    | updated_at        | 2017-04-19T07:19:25Z                 |
    +-------------------+--------------------------------------+

Add this subnet to router R2.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion router add subnet R2 subnet-net4

Create router R3 in RegionOne and RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create --availability-zone-hint RegionOne --availability-zone-hint RegionTwo R3
    +-------------------------+--------------------------------------+
    | Field                   | Value                                |
    +-------------------------+--------------------------------------+
    | admin_state_up          | True                                 |
    | availability_zone_hints | RegionOne                            |
    |                         | RegionTwo                            |
    | availability_zones      |                                      |
    | created_at              | 2017-04-19T07:21:37Z                 |
    | description             |                                      |
    | distributed             | False                                |
    | external_gateway_info   |                                      |
    | id                      | 01fb7cf9-7b24-486f-8170-0282ebe2fc06 |
    | name                    | R3                                   |
    | project_id              | a79642b4c1674be1b306d8c436d07793     |
    | revision_number         | 4                                    |
    | status                  | ACTIVE                               |
    | tags                    |                                      |
    | tenant_id               | a79642b4c1674be1b306d8c436d07793     |
    | updated_at              | 2017-04-19T07:21:37Z                 |
    +-------------------------+--------------------------------------+

Create port in net1 and attach net1 to R3 using this port.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion port create --network=net1 net1-R3-interface
    +-----------------------+-------------------------------------------------------------------------+
    | Field                 | Value                                                                   |
    +-----------------------+-------------------------------------------------------------------------+
    | admin_state_up        | UP                                                                      |
    | allowed_address_pairs | None                                                                    |
    | binding_host_id       | None                                                                    |
    | binding_profile       | None                                                                    |
    | binding_vif_details   | None                                                                    |
    | binding_vif_type      | None                                                                    |
    | binding_vnic_type     | None                                                                    |
    | created_at            | 2017-04-19T07:22:40Z                                                    |
    | description           |                                                                         |
    | device_id             |                                                                         |
    | device_owner          |                                                                         |
    | dns_assignment        | None                                                                    |
    | dns_name              | None                                                                    |
    | extra_dhcp_opts       |                                                                         |
    | fixed_ips             | ip_address='10.0.1.8', subnet_id='b501197b-53c8-44a6-8e4a-ee36260da239' |
    | id                    | 53b28b73-9aaf-4432-9c11-24243a92c931                                    |
    | ip_address            | None                                                                    |
    | mac_address           | fa:16:3e:1e:c7:fe                                                       |
    | name                  | net1-R3-interface                                                       |
    | network_id            | bbc5527d-25a5-4ea1-9ef6-47e7dca9029b                                    |
    | option_name           | None                                                                    |
    | option_value          | None                                                                    |
    | port_security_enabled | False                                                                   |
    | project_id            | a79642b4c1674be1b306d8c436d07793                                        |
    | qos_policy_id         | None                                                                    |
    | revision_number       | 3                                                                       |
    | security_groups       | dee6ea7c-eec5-426a-9385-c40d00565a3a                                    |
    | status                | ACTIVE                                                                  |
    | subnet_id             | None                                                                    |
    | updated_at            | 2017-04-19T07:22:40Z                                                    |
    +-----------------------+-------------------------------------------------------------------------+

    $ openstack --os-region-name=CentralRegion router add port R3 net1-R3-interface

Create port in net2 and attach net2 to R3 using this port.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion port create --network=net2 net2-R3-interface
    +-----------------------+-------------------------------------------------------------------------+
    | Field                 | Value                                                                   |
    +-----------------------+-------------------------------------------------------------------------+
    | admin_state_up        | UP                                                                      |
    | allowed_address_pairs | None                                                                    |
    | binding_host_id       | None                                                                    |
    | binding_profile       | None                                                                    |
    | binding_vif_details   | None                                                                    |
    | binding_vif_type      | None                                                                    |
    | binding_vnic_type     | None                                                                    |
    | created_at            | 2017-04-19T07:24:07Z                                                    |
    | description           |                                                                         |
    | device_id             |                                                                         |
    | device_owner          |                                                                         |
    | dns_assignment        | None                                                                    |
    | dns_name              | None                                                                    |
    | extra_dhcp_opts       |                                                                         |
    | fixed_ips             | ip_address='10.0.2.5', subnet_id='d0222001-e80f-49c3-9f0a-7f3688843e66' |
    | id                    | a0d7a00b-db0b-48e8-9ec4-62a7aa15de98                                    |
    | ip_address            | None                                                                    |
    | mac_address           | fa:16:3e:1c:e4:10                                                       |
    | name                  | net2-R3-interface                                                       |
    | network_id            | 3779cfd5-790c-43a7-9231-ed473789dc93                                    |
    | option_name           | None                                                                    |
    | option_value          | None                                                                    |
    | port_security_enabled | False                                                                   |
    | project_id            | a79642b4c1674be1b306d8c436d07793                                        |
    | qos_policy_id         | None                                                                    |
    | revision_number       | 3                                                                       |
    | security_groups       | dee6ea7c-eec5-426a-9385-c40d00565a3a                                    |
    | status                | ACTIVE                                                                  |
    | subnet_id             | None                                                                    |
    | updated_at            | 2017-04-19T07:24:07Z                                                    |
    +-----------------------+-------------------------------------------------------------------------+

    $ openstack --os-region-name=CentralRegion router add port R3 net2-R3-interface

Create port in net3 and attach net3 to R3 using this port.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion port create --network=net3 net3-R3-interface
    +-----------------------+--------------------------------------------------------------------------+
    | Field                 | Value                                                                    |
    +-----------------------+--------------------------------------------------------------------------+
    | admin_state_up        | UP                                                                       |
    | allowed_address_pairs | None                                                                     |
    | binding_host_id       | None                                                                     |
    | binding_profile       | None                                                                     |
    | binding_vif_details   | None                                                                     |
    | binding_vif_type      | None                                                                     |
    | binding_vnic_type     | None                                                                     |
    | created_at            | 2017-04-19T07:25:21Z                                                     |
    | description           |                                                                          |
    | device_id             |                                                                          |
    | device_owner          |                                                                          |
    | dns_assignment        | None                                                                     |
    | dns_name              | None                                                                     |
    | extra_dhcp_opts       |                                                                          |
    | fixed_ips             | ip_address='10.0.3.11', subnet_id='a2582af0-ab39-43e7-8b23-f2911804633b' |
    | id                    | 95a73056-e75c-46cf-911e-a979bc46f2c4                                     |
    | ip_address            | None                                                                     |
    | mac_address           | fa:16:3e:0d:a3:be                                                        |
    | name                  | net3-R3-interface                                                        |
    | network_id            | a914edd9-629e-41bd-98ef-ec52736aeaa2                                     |
    | option_name           | None                                                                     |
    | option_value          | None                                                                     |
    | port_security_enabled | False                                                                    |
    | project_id            | a79642b4c1674be1b306d8c436d07793                                         |
    | qos_policy_id         | None                                                                     |
    | revision_number       | 3                                                                        |
    | security_groups       | dee6ea7c-eec5-426a-9385-c40d00565a3a                                     |
    | status                | ACTIVE                                                                   |
    | subnet_id             | None                                                                     |
    | updated_at            | 2017-04-19T07:25:21Z                                                     |
    +-----------------------+--------------------------------------------------------------------------+

    $ openstack --os-region-name=CentralRegion router add port R3 net3-R3-interface

Create port in net4 and attach net4 to R3 using this port.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion port create --network=net4 net4-R3-interface
    +-----------------------+-------------------------------------------------------------------------+
    | Field                 | Value                                                                   |
    +-----------------------+-------------------------------------------------------------------------+
    | admin_state_up        | UP                                                                      |
    | allowed_address_pairs | None                                                                    |
    | binding_host_id       | None                                                                    |
    | binding_profile       | None                                                                    |
    | binding_vif_details   | None                                                                    |
    | binding_vif_type      | None                                                                    |
    | binding_vnic_type     | None                                                                    |
    | created_at            | 2017-04-19T07:26:18Z                                                    |
    | description           |                                                                         |
    | device_id             |                                                                         |
    | device_owner          |                                                                         |
    | dns_assignment        | None                                                                    |
    | dns_name              | None                                                                    |
    | extra_dhcp_opts       |                                                                         |
    | fixed_ips             | ip_address='10.0.4.4', subnet_id='5a76080f-efe5-4890-855e-56bd9068c6cf' |
    | id                    | 2d29593b-ad4a-4904-9053-9dbdddfcfc05                                    |
    | ip_address            | None                                                                    |
    | mac_address           | fa:16:3e:df:4c:d0                                                       |
    | name                  | net4-R3-interface                                                       |
    | network_id            | 60c2e42a-3875-4d11-9850-59148aee24c2                                    |
    | option_name           | None                                                                    |
    | option_value          | None                                                                    |
    | port_security_enabled | False                                                                   |
    | project_id            | a79642b4c1674be1b306d8c436d07793                                        |
    | qos_policy_id         | None                                                                    |
    | revision_number       | 3                                                                       |
    | security_groups       | dee6ea7c-eec5-426a-9385-c40d00565a3a                                    |
    | status                | ACTIVE                                                                  |
    | subnet_id             | None                                                                    |
    | updated_at            | 2017-04-19T07:26:18Z                                                    |
    +-----------------------+-------------------------------------------------------------------------+

    $ openstack --os-region-name=CentralRegion router add port R3 net4-R3-interface

Now the networking topology has been composed. Just boot instances in different network.

List the available images in RegionOne.

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list

    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 1f87a3d9-9de1-47c9-bae3-9d1c02ec6ea1 | cirros-0.3.4-x86_64-uec         |
    | be37ca60-aaa1-4b6f-854e-1610be8fc32a | cirros-0.3.4-x86_64-uec-kernel  |
    | ea820854-2655-4aff-b6b3-8ca234bb8c85 | cirros-0.3.4-x86_64-uec-ramdisk |
    +--------------------------------------+---------------------------------+

List the available flavors in RegionOne.

.. code-block:: console

    $ nova --os-region-name=RegionOne flavor-list
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | ID | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | 1  | m1.tiny   | 512       | 1    | 0         |      | 1     | 1.0         | True      |
    | 2  | m1.small  | 2048      | 20   | 0         |      | 1     | 1.0         | True      |
    | 3  | m1.medium | 4096      | 40   | 0         |      | 2     | 1.0         | True      |
    | 4  | m1.large  | 8192      | 80   | 0         |      | 4     | 1.0         | True      |
    | 5  | m1.xlarge | 16384     | 160  | 0         |      | 8     | 1.0         | True      |
    | c1 | cirros256 | 256       | 0    | 0         |      | 1     | 1.0         | True      |
    | d1 | ds512M    | 512       | 5    | 0         |      | 1     | 1.0         | True      |
    | d2 | ds1G      | 1024      | 10   | 0         |      | 1     | 1.0         | True      |
    | d3 | ds2G      | 2048      | 10   | 0         |      | 2     | 1.0         | True      |
    | d4 | ds4G      | 4096      | 20   | 0         |      | 4     | 1.0         | True      |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+

Boot instance1 in RegionOne, and connect this instance to net1.

.. code-block:: console

    $ regionone_image_id=$(openstack --os-region-name=RegionOne image list | awk 'NR==4 {print $2}')
    $ net1_id=$(openstack --os-region-name=CentralRegion network show net1 -f value -c id)
    $ nova --os-region-name=RegionOne boot --flavor 1 --image $regionone_image_id --nic net-id=$net1_id instance1
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance1                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | be37ca60-aaa1-4b6f-854e-1610be8fc32a                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | ea820854-2655-4aff-b6b3-8ca234bb8c85                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-2dutlvrz                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | u9D7s45DxcaP                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-04-19T07:43:27Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 94d25a05-81e7-4c71-bcf5-5953a225574a                           |
    | image                                | cirros-0.3.4-x86_64-uec (1f87a3d9-9de1-47c9-bae3-9d1c02ec6ea1) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance1                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | a79642b4c1674be1b306d8c436d07793                               |
    | updated                              | 2017-04-19T07:43:27Z                                           |
    | user_id                              | 76ae1ba819994f37a0ca2563641421da                               |
    +--------------------------------------+----------------------------------------------------------------+

Boot instance2 in RegionOne, and connect this instance to net2.

.. code-block:: console

    $ regionone_image_id=$(openstack --os-region-name=RegionOne image list | awk 'NR==4 {print $2}')
    $ net2_id=$(openstack --os-region-name=CentralRegion network show net2 -f value -c id)
    $ nova --os-region-name=RegionOne boot --flavor 1 --image $regionone_image_id --nic net-id=$net2_id instance2
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance2                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | be37ca60-aaa1-4b6f-854e-1610be8fc32a                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | ea820854-2655-4aff-b6b3-8ca234bb8c85                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-n0qb1dot                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | YSB6w9Yb6dZb                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-04-19T07:45:36Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 2d53907a-8de9-4c8f-a330-28e5057e1ce5                           |
    | image                                | cirros-0.3.4-x86_64-uec (1f87a3d9-9de1-47c9-bae3-9d1c02ec6ea1) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance2                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | a79642b4c1674be1b306d8c436d07793                               |
    | updated                              | 2017-04-19T07:45:35Z                                           |
    | user_id                              | 76ae1ba819994f37a0ca2563641421da                               |
    +--------------------------------------+----------------------------------------------------------------+

List the available images in RegionTwo.

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list
    +--------------------------------------+--------------------------+
    | ID                                   | Name                     |
    +--------------------------------------+--------------------------+
    | f5100ea6-f4c9-4e79-b5fc-96a4b6c6dcd2 | cirros-0.3.5-x86_64-disk |
    +--------------------------------------+--------------------------+

List the available flavors in RegionTwo.

.. code-block:: console

    $ nova --os-region-name=RegionTwo flavor-list
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | ID | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | 1  | m1.tiny   | 512       | 1    | 0         |      | 1     | 1.0         | True      |
    | 2  | m1.small  | 2048      | 20   | 0         |      | 1     | 1.0         | True      |
    | 3  | m1.medium | 4096      | 40   | 0         |      | 2     | 1.0         | True      |
    | 4  | m1.large  | 8192      | 80   | 0         |      | 4     | 1.0         | True      |
    | 5  | m1.xlarge | 16384     | 160  | 0         |      | 8     | 1.0         | True      |
    | c1 | cirros256 | 256       | 0    | 0         |      | 1     | 1.0         | True      |
    | d1 | ds512M    | 512       | 5    | 0         |      | 1     | 1.0         | True      |
    | d2 | ds1G      | 1024      | 10   | 0         |      | 1     | 1.0         | True      |
    | d3 | ds2G      | 2048      | 10   | 0         |      | 2     | 1.0         | True      |
    | d4 | ds4G      | 4096      | 20   | 0         |      | 4     | 1.0         | True      |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+

Boot instance3 in RegionTwo, and connect this instance to net3.

.. code-block:: console

    $ regiontwo_image_id=$(openstack --os-region-name=RegionTwo image list | awk 'NR==4 {print $2}')
    $ net3_id=$(openstack --os-region-name=CentralRegion network show net3 -f value -c id)
    $ nova --os-region-name=RegionTwo boot --flavor 1 --image $regiontwo_image_id --nic net-id=$net3_id instance3
    +--------------------------------------+-----------------------------------------------------------------+
    | Property                             | Value                                                           |
    +--------------------------------------+-----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                          |
    | OS-EXT-AZ:availability_zone          |                                                                 |
    | OS-EXT-SRV-ATTR:host                 | -                                                               |
    | OS-EXT-SRV-ATTR:hostname             | instance3                                                       |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                               |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                 |
    | OS-EXT-SRV-ATTR:kernel_id            |                                                                 |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                               |
    | OS-EXT-SRV-ATTR:ramdisk_id           |                                                                 |
    | OS-EXT-SRV-ATTR:reservation_id       | r-3tokqjyn                                                      |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
    | OS-EXT-SRV-ATTR:user_data            | -                                                               |
    | OS-EXT-STS:power_state               | 0                                                               |
    | OS-EXT-STS:task_state                | scheduling                                                      |
    | OS-EXT-STS:vm_state                  | building                                                        |
    | OS-SRV-USG:launched_at               | -                                                               |
    | OS-SRV-USG:terminated_at             | -                                                               |
    | accessIPv4                           |                                                                 |
    | accessIPv6                           |                                                                 |
    | adminPass                            | 6WPPfJg2uyp4                                                    |
    | config_drive                         |                                                                 |
    | created                              | 2017-04-19T07:57:17Z                                            |
    | description                          | -                                                               |
    | flavor                               | m1.tiny (1)                                                     |
    | hostId                               |                                                                 |
    | host_status                          |                                                                 |
    | id                                   | d60a0fd6-15d7-4220-92e6-4a5b71e10f34                            |
    | image                                | cirros-0.3.5-x86_64-disk (f5100ea6-f4c9-4e79-b5fc-96a4b6c6dcd2) |
    | key_name                             | -                                                               |
    | locked                               | False                                                           |
    | metadata                             | {}                                                              |
    | name                                 | instance3                                                       |
    | os-extended-volumes:volumes_attached | []                                                              |
    | progress                             | 0                                                               |
    | security_groups                      | default                                                         |
    | status                               | BUILD                                                           |
    | tags                                 | []                                                              |
    | tenant_id                            | a79642b4c1674be1b306d8c436d07793                                |
    | updated                              | 2017-04-19T07:57:17Z                                            |
    | user_id                              | 76ae1ba819994f37a0ca2563641421da                                |
    +--------------------------------------+-----------------------------------------------------------------+

Boot instance4 in RegionTwo, and connect this instance to net4.

.. code-block:: console

    $ regiontwo_image_id=$(openstack --os-region-name=RegionTwo image list | awk 'NR==4 {print $2}')
    $ net4_id=$(openstack --os-region-name=CentralRegion network show net4 -f value -c id)
    $ nova --os-region-name=RegionTwo boot --flavor 1 --image $regiontwo_image_id --nic net-id=$net4_id instance4
    +--------------------------------------+-----------------------------------------------------------------+
    | Property                             | Value                                                           |
    +--------------------------------------+-----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                          |
    | OS-EXT-AZ:availability_zone          |                                                                 |
    | OS-EXT-SRV-ATTR:host                 | -                                                               |
    | OS-EXT-SRV-ATTR:hostname             | instance4                                                       |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                               |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                 |
    | OS-EXT-SRV-ATTR:kernel_id            |                                                                 |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                               |
    | OS-EXT-SRV-ATTR:ramdisk_id           |                                                                 |
    | OS-EXT-SRV-ATTR:reservation_id       | r-d0i6qz01                                                      |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
    | OS-EXT-SRV-ATTR:user_data            | -                                                               |
    | OS-EXT-STS:power_state               | 0                                                               |
    | OS-EXT-STS:task_state                | scheduling                                                      |
    | OS-EXT-STS:vm_state                  | building                                                        |
    | OS-SRV-USG:launched_at               | -                                                               |
    | OS-SRV-USG:terminated_at             | -                                                               |
    | accessIPv4                           |                                                                 |
    | accessIPv6                           |                                                                 |
    | adminPass                            | QzU8ttUdiTEk                                                    |
    | config_drive                         |                                                                 |
    | created                              | 2017-04-19T07:57:47Z                                            |
    | description                          | -                                                               |
    | flavor                               | m1.tiny (1)                                                     |
    | hostId                               |                                                                 |
    | host_status                          |                                                                 |
    | id                                   | 8746772e-889b-4132-9d6b-9fb44350f336                            |
    | image                                | cirros-0.3.5-x86_64-disk (f5100ea6-f4c9-4e79-b5fc-96a4b6c6dcd2) |
    | key_name                             | -                                                               |
    | locked                               | False                                                           |
    | metadata                             | {}                                                              |
    | name                                 | instance4                                                       |
    | os-extended-volumes:volumes_attached | []                                                              |
    | progress                             | 0                                                               |
    | security_groups                      | default                                                         |
    | status                               | BUILD                                                           |
    | tags                                 | []                                                              |
    | tenant_id                            | a79642b4c1674be1b306d8c436d07793                                |
    | updated                              | 2017-04-19T07:57:47Z                                            |
    | user_id                              | 76ae1ba819994f37a0ca2563641421da                                |
    +--------------------------------------+-----------------------------------------------------------------+

Check to see if all instances are booted successfully.

.. code-block:: console

    $ nova --os-region-name=RegionOne list
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks      |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | 94d25a05-81e7-4c71-bcf5-5953a225574a | instance1 | ACTIVE | -          | Running     | net1=10.0.1.7 |
    | 2d53907a-8de9-4c8f-a330-28e5057e1ce5 | instance2 | ACTIVE | -          | Running     | net2=10.0.2.9 |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+

    $ nova --os-region-name=RegionTwo list
    +--------------------------------------+-----------+--------+------------+-------------+----------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks       |
    +--------------------------------------+-----------+--------+------------+-------------+----------------+
    | d60a0fd6-15d7-4220-92e6-4a5b71e10f34 | instance3 | ACTIVE | -          | Running     | net3=10.0.3.6  |
    | 8746772e-889b-4132-9d6b-9fb44350f336 | instance4 | ACTIVE | -          | Running     | net4=10.0.4.14 |
    +--------------------------------------+-----------+--------+------------+-------------+----------------+

Check to see if the east-west routes were set correctly.

.. code-block:: console

    $ openstack --os-region-name=RegionOne subnet show subnet-net1
    +-------------------+-----------------------------------------------+
    | Field             | Value                                         |
    +-------------------+-----------------------------------------------+
    | allocation_pools  | 10.0.1.2-10.0.1.254                           |
    | cidr              | 10.0.1.0/24                                   |
    | created_at        | 2017-04-19T06:24:11Z                          |
    | description       |                                               |
    | dns_nameservers   |                                               |
    | enable_dhcp       | True                                          |
    | gateway_ip        | 10.0.1.1                                      |
    | host_routes       | destination='10.0.3.0/24', gateway='10.0.1.6' |
    |                   | destination='10.0.4.0/24', gateway='10.0.1.6' |
    | id                | b501197b-53c8-44a6-8e4a-ee36260da239          |
    | ip_version        | 4                                             |
    | ipv6_address_mode | None                                          |
    | ipv6_ra_mode      | None                                          |
    | name              | subnet-net1                                   |
    | network_id        | bbc5527d-25a5-4ea1-9ef6-47e7dca9029b          |
    | project_id        | a79642b4c1674be1b306d8c436d07793              |
    | revision_number   | 11                                            |
    | segment_id        | None                                          |
    | service_types     |                                               |
    | subnetpool_id     | None                                          |
    | updated_at        | 2017-04-19T07:58:25Z                          |
    +-------------------+-----------------------------------------------+

    $ openstack --os-region-name=RegionOne subnet show subnet-net2
    +-------------------+------------------------------------------------+
    | Field             | Value                                          |
    +-------------------+------------------------------------------------+
    | allocation_pools  | 10.0.2.2-10.0.2.254                            |
    | cidr              | 10.0.2.0/24                                    |
    | created_at        | 2017-04-19T06:29:50Z                           |
    | description       |                                                |
    | dns_nameservers   |                                                |
    | enable_dhcp       | True                                           |
    | gateway_ip        | 10.0.2.1                                       |
    | host_routes       | destination='10.0.3.0/24', gateway='10.0.2.12' |
    |                   | destination='10.0.4.0/24', gateway='10.0.2.12' |
    | id                | d0222001-e80f-49c3-9f0a-7f3688843e66           |
    | ip_version        | 4                                              |
    | ipv6_address_mode | None                                           |
    | ipv6_ra_mode      | None                                           |
    | name              | subnet-net2                                    |
    | network_id        | 3779cfd5-790c-43a7-9231-ed473789dc93           |
    | project_id        | a79642b4c1674be1b306d8c436d07793               |
    | revision_number   | 10                                             |
    | segment_id        | None                                           |
    | service_types     |                                                |
    | subnetpool_id     | None                                           |
    | updated_at        | 2017-04-19T07:58:28Z                           |
    +-------------------+------------------------------------------------+

    $ openstack --os-region-name=RegionTwo subnet show subnet-net3
    +-------------------+-----------------------------------------------+
    | Field             | Value                                         |
    +-------------------+-----------------------------------------------+
    | allocation_pools  | 10.0.3.2-10.0.3.254                           |
    | cidr              | 10.0.3.0/24                                   |
    | created_at        | 2017-04-19T07:17:46Z                          |
    | description       |                                               |
    | dns_nameservers   |                                               |
    | enable_dhcp       | True                                          |
    | gateway_ip        | 10.0.3.1                                      |
    | host_routes       | destination='10.0.1.0/24', gateway='10.0.3.4' |
    |                   | destination='10.0.2.0/24', gateway='10.0.3.4' |
    | id                | a2582af0-ab39-43e7-8b23-f2911804633b          |
    | ip_version        | 4                                             |
    | ipv6_address_mode | None                                          |
    | ipv6_ra_mode      | None                                          |
    | name              | subnet-net3                                   |
    | network_id        | a914edd9-629e-41bd-98ef-ec52736aeaa2          |
    | project_id        | a79642b4c1674be1b306d8c436d07793              |
    | revision_number   | 9                                             |
    | segment_id        | None                                          |
    | service_types     |                                               |
    | subnetpool_id     | None                                          |
    | updated_at        | 2017-04-19T07:58:30Z                          |
    +-------------------+-----------------------------------------------+

    $ openstack --os-region-name=RegionTwo subnet show subnet-net4
    +-------------------+------------------------------------------------+
    | Field             | Value                                          |
    +-------------------+------------------------------------------------+
    | allocation_pools  | 10.0.4.2-10.0.4.254                            |
    | cidr              | 10.0.4.0/24                                    |
    | created_at        | 2017-04-19T07:20:39Z                           |
    | description       |                                                |
    | dns_nameservers   |                                                |
    | enable_dhcp       | True                                           |
    | gateway_ip        | 10.0.4.1                                       |
    | host_routes       | destination='10.0.1.0/24', gateway='10.0.4.13' |
    |                   | destination='10.0.2.0/24', gateway='10.0.4.13' |
    | id                | 5a76080f-efe5-4890-855e-56bd9068c6cf           |
    | ip_version        | 4                                              |
    | ipv6_address_mode | None                                           |
    | ipv6_ra_mode      | None                                           |
    | name              | subnet-net4                                    |
    | network_id        | 60c2e42a-3875-4d11-9850-59148aee24c2           |
    | project_id        | a79642b4c1674be1b306d8c436d07793               |
    | revision_number   | 8                                              |
    | segment_id        | None                                           |
    | service_types     |                                                |
    | subnetpool_id     | None                                           |
    | updated_at        | 2017-04-19T07:58:32Z                           |
    +-------------------+------------------------------------------------+


Create a floating IP and associate it to instance1. The port id in local Neutron
is same as that in central Neutron, because there is no Nova in CentralRegion,
the command to get port id and store it in environment variable is issued to
RegionOne or RegionTwo. You can also get the port id manually if you issue
command to CentralRegion without --server being specified.

.. code-block:: console

    $ instance1_net1_port_id=$(openstack --os-region-name=RegionOne port list --network net1 --server instance1 -f value -c ID)
    $ openstack --os-region-name=CentralRegion floating ip create --port=$instance1_net1_port_id ext-net1
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-04-19T08:29:45Z                 |
    | description         |                                      |
    | fixed_ip_address    | 10.0.1.7                             |
    | floating_ip_address | 163.3.3.13                           |
    | floating_network_id | ff7375f3-5bc6-4349-b097-72e42a90648a |
    | id                  | 7af7503a-5b9b-441c-bf90-bdce47cf1e16 |
    | name                | None                                 |
    | port_id             | 588e9a9c-67f8-47b5-ab3b-8f5f93f00c15 |
    | project_id          | a79642b4c1674be1b306d8c436d07793     |
    | revision_number     | 1                                    |
    | router_id           | a665d383-bb0b-478a-b4c7-d0b316a01806 |
    | status              | DOWN                                 |
    | updated_at          | 2017-04-19T08:29:45Z                 |
    +---------------------+--------------------------------------+

    $ instance3_net3_port_id=$(openstack --os-region-name=RegionTwo port list --network net3 --server instance3 -f value -c ID)
    $ openstack --os-region-name=CentralRegion floating ip create --port=$instance3_net3_port_id ext-net2
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-04-19T08:32:09Z                 |
    | description         |                                      |
    | fixed_ip_address    | 10.0.3.6                             |
    | floating_ip_address | 163.3.5.4                            |
    | floating_network_id | 6f0f139d-6857-45f5-925d-419b5f896c2a |
    | id                  | f84c92eb-a724-4658-bae9-09e140f59705 |
    | name                | None                                 |
    | port_id             | 72d062e1-8a30-4c3e-a2f2-6414200c135a |
    | project_id          | a79642b4c1674be1b306d8c436d07793     |
    | revision_number     | 1                                    |
    | router_id           | 643cc4ec-cdd5-4b14-bcc6-328b86035d50 |
    | status              | DOWN                                 |
    | updated_at          | 2017-04-19T08:32:09Z                 |
    +---------------------+--------------------------------------+


Create a security group and add security group rule to allow ping, ssh to instance1 and instance3.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion security group create icmpssh
    $ openstack --os-region-name=CentralRegion security group rule create --protocol icmp icmpssh
    $ openstack --os-region-name=CentralRegion security group rule create --protocol tcp --dst-port 22:22 icmpssh
    $ neutron --os-region-name=CentralRegion port-update --security-group=icmpssh $instance1_net1_port_id
    $ neutron --os-region-name=CentralRegion port-update --security-group=icmpssh $instance3_net3_port_id

N-S and E-W networking can work now. Use network name space to do the test,
because instance1 and instance3 have been allowed with security
group rule for ssh and ping, instance1 and instance3 in different subnets
from different clouds can ping each other. And if you check the route in
each instance, the default N-S gateway is R1 or R2.

.. code-block:: console

    $ openstack --os-region-name=RegionOne subnet list
    +--------------------------------------+--------------------------------------+--------------------------------------+--------------+
    | ID                                   | Name                                 | Network                              | Subnet       |
    +--------------------------------------+--------------------------------------+--------------------------------------+--------------+
    | 3d0cfacc-ce90-4924-94b9-a95d567568b9 | 3d0cfacc-ce90-4924-94b9-a95d567568b9 | ff7375f3-5bc6-4349-b097-72e42a90648a | 163.3.3.0/24 |
    | b501197b-53c8-44a6-8e4a-ee36260da239 | subnet-net1                          | bbc5527d-25a5-4ea1-9ef6-47e7dca9029b | 10.0.1.0/24  |
    | d0222001-e80f-49c3-9f0a-7f3688843e66 | subnet-net2                          | 3779cfd5-790c-43a7-9231-ed473789dc93 | 10.0.2.0/24  |
    | d0dc980f-e21e-4d97-b397-6e9067ca3ee4 | d0dc980f-e21e-4d97-b397-6e9067ca3ee4 | 73633eb0-7771-410a-82c1-942f5c7a9726 | 100.0.0.0/24 |
    +--------------------------------------+--------------------------------------+--------------------------------------+--------------+

    $ ip netns
    qrouter-fb892c30-6368-4595-9194-fa8933bc65cc
    qdhcp-3779cfd5-790c-43a7-9231-ed473789dc93
    qdhcp-bbc5527d-25a5-4ea1-9ef6-47e7dca9029b
    qrouter-7f8aa44e-df15-4737-92be-58fde99e14c6

    $ sudo ip netns exec qdhcp-bbc5527d-25a5-4ea1-9ef6-47e7dca9029b ping 10.0.1.7

    $ sudo ip netns exec qdhcp-bbc5527d-25a5-4ea1-9ef6-47e7dca9029b ssh cirros@10.0.1.7

    In instance1:

    $ route
    Kernel IP routing table
    Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
    default         host-10-0-1-1.o 0.0.0.0         UG    0      0        0 eth0
    10.0.1.0        *               255.255.255.0   U     0      0        0 eth0
    10.0.3.0        host-10-0-1-6.o 255.255.255.0   UG    0      0        0 eth0
    10.0.4.0        host-10-0-1-6.o 255.255.255.0   UG    0      0        0 eth0
    169.254.169.254 host-10-0-1-1.o 255.255.255.255 UGH   0      0        0 eth0

    $ ping 10.0.3.6

    $ ssh cirros@10.0.3.6

    In instance3:

    $ ping 10.0.1.7
