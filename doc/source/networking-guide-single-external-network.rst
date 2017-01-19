==================================================
North South Networking via Single External Network
==================================================

The following figure illustrates one typical networking mode, the north
south networking traffic for the tenant will be centralized through
single external network. Only one virtual router is needed even if
the tenant's network are located in multiple OpenStack regions.

.. code-block:: console

    +-----------------+       +-----------------+        +-----------------+       +-----------------+
    |   RegionOne     |       |   RegionTwo     |        |   RegionOne     |       |   RegionTwo     |
    |                 |       |                 |        |                 |       |                 |
    |                 |       |      ext-net1   |        |                 |       |      ext-net1   |
    |                 |       |   +-------+---+ |        |                 |       |   +-------+---+ |
    |                bridge net           |     |        |                bridge net           |     |
    |        -+-------+-------+---+-+     |     |        |        -+-------+-------+-+-+-+     |     |
    |         |       |       |   |    +--+--+  |        |         |       |       | | |    +--+--+  |
    |      +--+--+    |       |   +----+  R1 |  |        |      +--+--+    |       | | +----+  R1 |  |
    |      |  R1 |    |       |        +-----+  |  --->  |      |  R1 |    |       | |      +-----+  |
    |      +--+--+    |       |                 |        |      +--+--+    |       | |               |
    |         |       |       |                 |        |         |       |       | |   +-----+     |
    |         |       |       |                 |        |         |       |       | +---+  R1 |     |
    |         |       |       |                 |        |         |       |       |     +--+--+     |
    |         |       |       |                 |        |         |       |       |        |        |
    |         | net1  |       |                 |        |         | net1  |       |   net2 |        |
    |     +---+--+-+  |       |                 |        |     +---+--+-+  |       |   +-+--+---+    |
    |            |    |       |                 |        |            |    |       |     |           |
    |            |    |       |                 |        |            |    |       |     |           |
    |  +---------+-+  |       |                 |        |  +---------+-+  |       |  +--+--------+  |
    |  | Instance1 |  |       |                 |        |  | Instance1 |  |       |  | Instance2 |  |
    |  +-----------+  |       |                 |        |  +-----------+  |       |  +-----------+  |
    +-----------------+       +-----------------+        +-----------------+       +-----------------+

How to create this network topology
===================================

The first step is to create the left topology, then enhance the topology to
the right one. Different order to create this topology is also possible,
for example, create router and tenant network first, then boot instance,
set the router gateway, and associate floating IP as the last step.

Create external network ext-net1, which will be located in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --router:external --availability-zone-hint RegionTwo ext-net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionTwo                            |
    | id                        | 494a1d2f-9a0f-4d0d-a5e9-f926fce912ac |
    | name                      | ext-net1                             |
    | project_id                | 640e791e767e49939d5c600fdb3f8431     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 170                                  |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 640e791e767e49939d5c600fdb3f8431     |
    +---------------------------+--------------------------------------+

Create subnet in ext-net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet1 --disable-dhcp ext-net1 163.3.124.0/24
    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "163.3.124.2", "end": "163.3.124.254"} |
    | cidr              | 163.3.124.0/24                                   |
    | created_at        | 2017-01-14T02:11:48Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | False                                            |
    | gateway_ip        | 163.3.124.1                                      |
    | host_routes       |                                                  |
    | id                | 5485feab-f843-4ffe-abd5-6afe5319ad82             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | ext-subnet1                                      |
    | network_id        | 494a1d2f-9a0f-4d0d-a5e9-f926fce912ac             |
    | project_id        | 640e791e767e49939d5c600fdb3f8431                 |
    | revision_number   | 2                                                |
    | subnetpool_id     |                                                  |
    | tenant_id         | 640e791e767e49939d5c600fdb3f8431                 |
    | updated_at        | 2017-01-14T02:11:48Z                             |
    +-------------------+--------------------------------------------------+

Create router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create R1
    +-----------------------+--------------------------------------+
    | Field                 | Value                                |
    +-----------------------+--------------------------------------+
    | admin_state_up        | True                                 |
    | created_at            | 2017-01-14T02:12:15Z                 |
    | description           |                                      |
    | external_gateway_info |                                      |
    | id                    | 4c4c164d-2cfa-4d2b-ba81-3711f44a6962 |
    | name                  | R1                                   |
    | project_id            | 640e791e767e49939d5c600fdb3f8431     |
    | revision_number       | 1                                    |
    | status                | ACTIVE                               |
    | tenant_id             | 640e791e767e49939d5c600fdb3f8431     |
    | updated_at            | 2017-01-14T02:12:15Z                 |
    +-----------------------+--------------------------------------+

Set the router gateway to ext-net1 for R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-gateway-set R1 ext-net1
    Set gateway for router R1

Create local network net1 which will reside in RegionOne. You can use az1 or
RegionOne as the value of availability-zone-hint.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --availability-zone-hint RegionOne net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionOne                            |
    | id                        | dde37c9b-7fe6-4ca9-be1a-0abb9ba1eddf |
    | name                      | net1                                 |
    | project_id                | 640e791e767e49939d5c600fdb3f8431     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 640e791e767e49939d5c600fdb3f8431     |
    +---------------------------+--------------------------------------+

Create subnet in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.1.2", "end": "10.0.1.254"} |
    | cidr              | 10.0.1.0/24                                |
    | created_at        | 2017-01-14T02:14:09Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.1.1                                   |
    | host_routes       |                                            |
    | id                | 409f3b9e-3b14-4147-9443-51930eb9a882       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | dde37c9b-7fe6-4ca9-be1a-0abb9ba1eddf       |
    | project_id        | 640e791e767e49939d5c600fdb3f8431           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | 640e791e767e49939d5c600fdb3f8431           |
    | updated_at        | 2017-01-14T02:14:09Z                       |
    +-------------------+--------------------------------------------+

Add this subnet to router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-interface-add R1 409f3b9e-3b14-4147-9443-51930eb9a882
    Added interface 92eaf94d-e345-489a-bc91-3d3645d27f8b to router R1.

List the available images in RegionOne.

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 570b5674-4d7d-4c17-9e8a-1caed6194ff1 | cirros-0.3.4-x86_64-uec         |
    | 548cf82c-4353-407e-9aa2-3feac027c297 | cirros-0.3.4-x86_64-uec-kernel  |
    | 1d40fb9f-1669-4b4d-82b8-4c3b9cde0c03 | cirros-0.3.4-x86_64-uec-ramdisk |
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

    $ nova --os-region-name=RegionOne boot --flavor 1 --image 570b5674-4d7d-4c17-9e8a-1caed6194ff1 --nic net-id=dde37c9b-7fe6-4ca9-be1a-0abb9ba1eddf instance1
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance1                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | 548cf82c-4353-407e-9aa2-3feac027c297                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | 1d40fb9f-1669-4b4d-82b8-4c3b9cde0c03                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-n0k0u15s                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | N9A9iArByrdt                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-14T02:17:05Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | e7206415-e497-4110-b644-a64272625cef                           |
    | image                                | cirros-0.3.4-x86_64-uec (570b5674-4d7d-4c17-9e8a-1caed6194ff1) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance1                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | 640e791e767e49939d5c600fdb3f8431                               |
    | updated                              | 2017-01-14T02:17:05Z                                           |
    | user_id                              | 8e84fae0a5b74464b3300a4576d090a4                               |
    +--------------------------------------+----------------------------------------------------------------+

Make sure the instance1 is active in RegionOne.

.. code-block:: console

    $ nova --os-region-name=RegionOne list
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks      |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | e7206415-e497-4110-b644-a64272625cef | instance1 | ACTIVE | -          | Running     | net1=10.0.1.5 |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+

Create a floating IP for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-create ext-net1
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-01-14T02:19:24Z                 |
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 163.3.124.7                          |
    | floating_network_id | 494a1d2f-9a0f-4d0d-a5e9-f926fce912ac |
    | id                  | 04c18e73-675b-4273-a73a-afaf1e4f9811 |
    | port_id             |                                      |
    | project_id          | 640e791e767e49939d5c600fdb3f8431     |
    | revision_number     | 1                                    |
    | router_id           |                                      |
    | status              | DOWN                                 |
    | tenant_id           | 640e791e767e49939d5c600fdb3f8431     |
    | updated_at          | 2017-01-14T02:19:24Z                 |
    +---------------------+--------------------------------------+

List the port in net1 for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion port-list
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | id                                 | name                               | mac_address       | fixed_ips                            |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | 37e9cfe5-d410-4625-963d-           |                                    | fa:16:3e:14:47:a8 | {"subnet_id": "409f3b9e-             |
    | b7ea4347d72e                       |                                    |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.5"}            |
    | 92eaf94d-e345-489a-                |                                    | fa:16:3e:63:a9:08 | {"subnet_id": "409f3b9e-             |
    | bc91-3d3645d27f8b                  |                                    |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.1"}            |
    | d3ca5e74-470e-4953-a280-309b5e8e11 | dhcp_port_409f3b9e-                | fa:16:3e:7e:72:98 | {"subnet_id": "409f3b9e-             |
    | 46                                 | 3b14-4147-9443-51930eb9a882        |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.2"}            |
    | b4eef6a0-70e6-4a42-b0c5-f8f49cee25 | interface_RegionOne_409f3b9e-      | fa:16:3e:00:e1:5b | {"subnet_id": "409f3b9e-             |
    | c0                                 | 3b14-4147-9443-51930eb9a882        |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.7"}            |
    | 65b52fe3-f765-4124-a97f-           | bridge_port_640e791e767e49939d5c60 | fa:16:3e:df:7b:97 | {"subnet_id": "d637f4e5-4b9a-4237    |
    | f73a76e820e6                       | 0fdb3f8431_daa08da0-c60e-          |                   | -b3bc-ccfba45a5c37", "ip_address":   |
    |                                    | 42c8-bc30-1ed887111ecb             |                   | "100.0.0.7"}                         |
    | e0755307-a498-473e-                |                                    | fa:16:3e:1c:70:b9 | {"subnet_id": "5485feab-f843-4ffe-   |
    | 99e5-30cbede36b8e                  |                                    |                   | abd5-6afe5319ad82", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.7"}                       |
    | 2404eb83-f2f4-4a36-b377-dbc8befee1 |                                    | fa:16:3e:25:80:e6 | {"subnet_id": "5485feab-f843-4ffe-   |
    | 93                                 |                                    |                   | abd5-6afe5319ad82", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.9"}                       |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+

Associate the floating IP to instance1's IP in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-associate 04c18e73-675b-4273-a73a-afaf1e4f9811 37e9cfe5-d410-4625-963d-b7ea4347d72e
    Associated floating IP 04c18e73-675b-4273-a73a-afaf1e4f9811

Create network topology in RegionTwo.

Create net2 in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --availability-zone-hint RegionTwo net2
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionTwo                            |
    | id                        | cfe622f9-1851-4033-a4ba-6718659a147c |
    | name                      | net2                                 |
    | project_id                | 640e791e767e49939d5c600fdb3f8431     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 640e791e767e49939d5c600fdb3f8431     |
    +---------------------------+--------------------------------------+

Create subnet in net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net2 10.0.2.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.2.2", "end": "10.0.2.254"} |
    | cidr              | 10.0.2.0/24                                |
    | created_at        | 2017-01-14T02:36:03Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.2.1                                   |
    | host_routes       |                                            |
    | id                | 4e3376f8-0bda-450d-b4fb-9eb77c4ef919       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | cfe622f9-1851-4033-a4ba-6718659a147c       |
    | project_id        | 640e791e767e49939d5c600fdb3f8431           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | 640e791e767e49939d5c600fdb3f8431           |
    | updated_at        | 2017-01-14T02:36:03Z                       |
    +-------------------+--------------------------------------------+

Add router interface for the subnet to R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-interface-add R1 4e3376f8-0bda-450d-b4fb-9eb77c4ef919
    Added interface d4b0e6d9-8bfb-4cd6-8824-92731c0226da to router R1.

List available images in RegionTwo.

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 392aa24f-a1a8-4897-bced-70301e1c7e3b | cirros-0.3.4-x86_64-uec         |
    | 41ac5372-764a-4e31-8c3a-66cdc5a6529e | cirros-0.3.4-x86_64-uec-kernel  |
    | 55523513-719d-4949-b697-db98ab3e938e | cirros-0.3.4-x86_64-uec-ramdisk |
    +--------------------------------------+---------------------------------+

List available flavors in RegionTwo.

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

Boot instance2, and connect the instance2 to net2.

.. code-block:: console

    $ nova --os-region-name=RegionTwo boot --flavor 1 --image 392aa24f-a1a8-4897-bced-70301e1c7e3b --nic net-id=cfe622f9-1851-4033-a4ba-6718659a147c instance2
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance2                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | 41ac5372-764a-4e31-8c3a-66cdc5a6529e                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | 55523513-719d-4949-b697-db98ab3e938e                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-3v42ltzp                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | o62QufgY2JAF                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-14T02:39:42Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | e489ab4e-957d-4537-9870-fff87406aac5                           |
    | image                                | cirros-0.3.4-x86_64-uec (392aa24f-a1a8-4897-bced-70301e1c7e3b) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance2                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | 640e791e767e49939d5c600fdb3f8431                               |
    | updated                              | 2017-01-14T02:39:42Z                                           |
    | user_id                              | 8e84fae0a5b74464b3300a4576d090a4                               |
    +--------------------------------------+----------------------------------------------------------------+

Check to see if instance2 is active.

.. code-block:: console

    $ nova --os-region-name=RegionTwo list
    +--------------------------------------+-----------+--------+------------+-------------+----------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks       |
    +--------------------------------------+-----------+--------+------------+-------------+----------------+
    | e489ab4e-957d-4537-9870-fff87406aac5 | instance2 | ACTIVE | -          | Running     | net2=10.0.2.10 |
    +--------------------------------------+-----------+--------+------------+-------------+----------------+

You can ping instance2 from instance1, or vice versa now.

Create floating IP for instance2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-create ext-net1
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-01-14T02:40:55Z                 |
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 163.3.124.13                         |
    | floating_network_id | 494a1d2f-9a0f-4d0d-a5e9-f926fce912ac |
    | id                  | f917dede-6e0d-4c5a-8d02-7d5774d094ba |
    | port_id             |                                      |
    | project_id          | 640e791e767e49939d5c600fdb3f8431     |
    | revision_number     | 1                                    |
    | router_id           |                                      |
    | status              | DOWN                                 |
    | tenant_id           | 640e791e767e49939d5c600fdb3f8431     |
    | updated_at          | 2017-01-14T02:40:55Z                 |
    +---------------------+--------------------------------------+

List port of instance2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion port-list
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | id                                 | name                               | mac_address       | fixed_ips                            |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | 37e9cfe5-d410-4625-963d-           |                                    | fa:16:3e:14:47:a8 | {"subnet_id": "409f3b9e-             |
    | b7ea4347d72e                       |                                    |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.5"}            |
    | ed9bdc02-0f0d-4763-a993-e0972c6563 |                                    | fa:16:3e:c1:10:a3 | {"subnet_id": "4e3376f8-0bda-450d-   |
    | fa                                 |                                    |                   | b4fb-9eb77c4ef919", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.10"}                         |
    | 92eaf94d-e345-489a-                |                                    | fa:16:3e:63:a9:08 | {"subnet_id": "409f3b9e-             |
    | bc91-3d3645d27f8b                  |                                    |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.1"}            |
    | f98ceee7-777b-4cff-                | interface_RegionTwo_409f3b9e-      | fa:16:3e:aa:cf:e2 | {"subnet_id": "409f3b9e-             |
    | b5b9-c27b4277bb7f                  | 3b14-4147-9443-51930eb9a882        |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.12"}           |
    | d3ca5e74-470e-4953-a280-309b5e8e11 | dhcp_port_409f3b9e-                | fa:16:3e:7e:72:98 | {"subnet_id": "409f3b9e-             |
    | 46                                 | 3b14-4147-9443-51930eb9a882        |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.2"}            |
    | b4eef6a0-70e6-4a42-b0c5-f8f49cee25 | interface_RegionOne_409f3b9e-      | fa:16:3e:00:e1:5b | {"subnet_id": "409f3b9e-             |
    | c0                                 | 3b14-4147-9443-51930eb9a882        |                   | 3b14-4147-9443-51930eb9a882",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.7"}            |
    | d4b0e6d9-8bfb-                     |                                    | fa:16:3e:f9:5f:4e | {"subnet_id": "4e3376f8-0bda-450d-   |
    | 4cd6-8824-92731c0226da             |                                    |                   | b4fb-9eb77c4ef919", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.1"}                          |
    | e54f0a40-837f-                     | interface_RegionTwo_4e3376f8-0bda- | fa:16:3e:fa:84:da | {"subnet_id": "4e3376f8-0bda-450d-   |
    | 48e7-9397-55170300d06e             | 450d-b4fb-9eb77c4ef919             |                   | b4fb-9eb77c4ef919", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.11"}                         |
    | d458644d-a401-4d98-bec3-9468fdd56d | dhcp_port_4e3376f8-0bda-450d-b4fb- | fa:16:3e:b2:a6:03 | {"subnet_id": "4e3376f8-0bda-450d-   |
    | 1c                                 | 9eb77c4ef919                       |                   | b4fb-9eb77c4ef919", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.2"}                          |
    | 65b52fe3-f765-4124-a97f-           | bridge_port_640e791e767e49939d5c60 | fa:16:3e:df:7b:97 | {"subnet_id": "d637f4e5-4b9a-4237    |
    | f73a76e820e6                       | 0fdb3f8431_daa08da0-c60e-          |                   | -b3bc-ccfba45a5c37", "ip_address":   |
    |                                    | 42c8-bc30-1ed887111ecb             |                   | "100.0.0.7"}                         |
    | cee45aac-                          | bridge_port_640e791e767e49939d5c60 | fa:16:3e:d0:50:0d | {"subnet_id": "d637f4e5-4b9a-4237    |
    | fd07-4a2f-8008-02757875d1fe        | 0fdb3f8431_b072000e-3cd1-4a1a-     |                   | -b3bc-ccfba45a5c37", "ip_address":   |
    |                                    | aa60-9ffbca119b1a                  |                   | "100.0.0.8"}                         |
    | dd4707cc-fe2d-429c-8c2f-           |                                    | fa:16:3e:9e:85:62 | {"subnet_id": "5485feab-f843-4ffe-   |
    | 084b525e1789                       |                                    |                   | abd5-6afe5319ad82", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.13"}                      |
    | e0755307-a498-473e-                |                                    | fa:16:3e:1c:70:b9 | {"subnet_id": "5485feab-f843-4ffe-   |
    | 99e5-30cbede36b8e                  |                                    |                   | abd5-6afe5319ad82", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.7"}                       |
    | 2404eb83-f2f4-4a36-b377-dbc8befee1 |                                    | fa:16:3e:25:80:e6 | {"subnet_id": "5485feab-f843-4ffe-   |
    | 93                                 |                                    |                   | abd5-6afe5319ad82", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.9"}                       |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+

Associate the floating IP to the instance2's IP address in net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-associate f917dede-6e0d-4c5a-8d02-7d5774d094ba ed9bdc02-0f0d-4763-a993-e0972c6563fa
    Associated floating IP f917dede-6e0d-4c5a-8d02-7d5774d094ba

Make sure the floating IP association works.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | 04c18e73-675b-4273-a73a-afaf1e4f9811 | 10.0.1.5         | 163.3.124.7         | 37e9cfe5-d410-4625-963d-b7ea4347d72e |
    | f917dede-6e0d-4c5a-8d02-7d5774d094ba | 10.0.2.10        | 163.3.124.13        | ed9bdc02-0f0d-4763-a993-e0972c6563fa |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

    $ neutron --os-region-name=RegionTwo floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | 3a220f53-fdfe-44e3-847a-b00464135416 | 10.0.1.5         | 163.3.124.7         | 37e9cfe5-d410-4625-963d-b7ea4347d72e |
    | fe15192f-04cb-48c8-8a90-7a7c016f40ae | 10.0.2.10        | 163.3.124.13        | ed9bdc02-0f0d-4763-a993-e0972c6563fa |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
