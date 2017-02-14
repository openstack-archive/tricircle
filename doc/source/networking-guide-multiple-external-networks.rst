=====================================================
North South Networking via Multiple External Networks
=====================================================

The following figure illustrates one typical networking mode, instances have
two interfaces, one interface is connected to net3 for heartbeat or
data replication, the other interface is connected to net1 or net2 to provide
service. There is different external network in different region to support
service redundancy in case of region level failure.

.. code-block:: console

                +-----------------+       +-----------------+
                |  RegionOne      |       |  RegionTwo      |
                |                 |       |                 |
                |     ext_net1    |       |     ext_net2    |
                |   +-----+-----+ |       |   +-----+-----+ |
                |         |       |       |         |       |
                |         |       |       |         |       |
                |      +--+--+    |       |      +--+--+    |
                |      |     |    |       |      |     |    |
                |      | R1  |    |       |      | R2  |    |
                |      |     |    |       |      |     |    |
                |      +--+--+    |       |      +--+--+    |
                |         |       |       |         |       |
                |         |       |       |         |       |
                |     +---+-+-+   |       |     +---+-+-+   |
                |     net1  |     |       |     net2  |     |
                |           |     |       |           |     |
                |  +--------+--+  |       |  +--------+--+  |
                |  | Instance1 |  |       |  | Instance2 |  |
                |  +-----------+  |       |  +-----------+  |
                |         |       |       |         |       |
                |         |       | net3  |         |       |
                |  +------+-------------------------+----+  |
                |                 |       |                 |
                +-----------------+       +-----------------+

How to create this network topology
===================================

Create external network ext-net1, which will be located in RegionOne.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --router:external --availability-zone-hint RegionOne ext-net1

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionOne                            |
    | id                        | 9b3d04be-0c00-40ed-88ff-088da6fcd8bd |
    | name                      | ext-net1                             |
    | project_id                | 532890c765604609a8d2ef6fc8e5f6ef     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 170                                  |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 532890c765604609a8d2ef6fc8e5f6ef     |
    +---------------------------+--------------------------------------+

Create subnet in ext-net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet1 --disable-dhcp ext-net1 163.3.124.0/24
    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "163.3.124.2", "end": "163.3.124.254"} |
    | cidr              | 163.3.124.0/24                                   |
    | created_at        | 2017-01-12T07:03:45Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | False                                            |
    | gateway_ip        | 163.3.124.1                                      |
    | host_routes       |                                                  |
    | id                | a2eecc16-deb8-42a6-a41b-5058847ed20a             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | ext-subnet1                                      |
    | network_id        | 9b3d04be-0c00-40ed-88ff-088da6fcd8bd             |
    | project_id        | 532890c765604609a8d2ef6fc8e5f6ef                 |
    | revision_number   | 2                                                |
    | subnetpool_id     |                                                  |
    | tenant_id         | 532890c765604609a8d2ef6fc8e5f6ef                 |
    | updated_at        | 2017-01-12T07:03:45Z                             |
    +-------------------+--------------------------------------------------+

Create router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create R1
    +-----------------------+--------------------------------------+
    | Field                 | Value                                |
    +-----------------------+--------------------------------------+
    | admin_state_up        | True                                 |
    | created_at            | 2017-01-12T07:04:13Z                 |
    | description           |                                      |
    | external_gateway_info |                                      |
    | id                    | 063de74b-d962-4fc2-96d9-87e2cb35c082 |
    | name                  | R1                                   |
    | project_id            | 532890c765604609a8d2ef6fc8e5f6ef     |
    | revision_number       | 1                                    |
    | status                | ACTIVE                               |
    | tenant_id             | 532890c765604609a8d2ef6fc8e5f6ef     |
    | updated_at            | 2017-01-12T07:04:13Z                 |
    +-----------------------+--------------------------------------+

Set the router gateway to ext-net1 for R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-gateway-set R1 ext-net1
    Set gateway for router R1

    $ neutron --os-region-name=CentralRegion router-show R1
    +-----------------------+------------------------------------------------------------------------------------------------------------+
    | Field                 | Value                                                                                                      |
    +-----------------------+------------------------------------------------------------------------------------------------------------+
    | admin_state_up        | True                                                                                                       |
    | created_at            | 2017-01-12T07:04:13Z                                                                                       |
    | description           |                                                                                                            |
    | external_gateway_info | {"network_id": "9b3d04be-0c00-40ed-88ff-088da6fcd8bd", "external_fixed_ips": [{"subnet_id":                |
    |                       | "a2eecc16-deb8-42a6-a41b-5058847ed20a", "ip_address": "163.3.124.5"}]}                                     |
    | id                    | 063de74b-d962-4fc2-96d9-87e2cb35c082                                                                       |
    | name                  | R1                                                                                                         |
    | project_id            | 532890c765604609a8d2ef6fc8e5f6ef                                                                           |
    | revision_number       | 3                                                                                                          |
    | status                | ACTIVE                                                                                                     |
    | tenant_id             | 532890c765604609a8d2ef6fc8e5f6ef                                                                           |
    | updated_at            | 2017-01-12T07:04:36Z                                                                                       |
    +-----------------------+------------------------------------------------------------------------------------------------------------+

Create local network net1 which will reside in RegionOne. You can use az1 or
RegionOne as the value of availability-zone-hint.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --availability-zone-hint az1 net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az1                                  |
    | id                        | de4fda27-e4f7-4448-80f6-79ee5ea2478b |
    | name                      | net1                                 |
    | project_id                | 532890c765604609a8d2ef6fc8e5f6ef     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 532890c765604609a8d2ef6fc8e5f6ef     |
    +---------------------------+--------------------------------------+

Create a subnet in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.1.2", "end": "10.0.1.254"} |
    | cidr              | 10.0.1.0/24                                |
    | created_at        | 2017-01-12T07:05:57Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.1.1                                   |
    | host_routes       |                                            |
    | id                | 2c8f446f-ba02-4140-a793-913033aa3580       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | de4fda27-e4f7-4448-80f6-79ee5ea2478b       |
    | project_id        | 532890c765604609a8d2ef6fc8e5f6ef           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | 532890c765604609a8d2ef6fc8e5f6ef           |
    | updated_at        | 2017-01-12T07:05:57Z                       |
    +-------------------+--------------------------------------------+

Add this subnet to router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-interface-add R1 2c8f446f-ba02-4140-a793-913033aa3580
    Added interface d48a8e87-61a0-494b-bc06-54f7a008ea78 to router R1.

Create net3 which will work as the L2 network across RegionOne and RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network bridge --availability-zone-hint az1 --availability-zone-hint az2 net3

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az1                                  |
    |                           | az2                                  |
    | id                        | 68d04c60-469d-495d-bb23-0d36d56235bd |
    | name                      | net3                                 |
    | project_id                | 532890c765604609a8d2ef6fc8e5f6ef     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | bridge                               |
    | provider:segmentation_id  | 138                                  |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 532890c765604609a8d2ef6fc8e5f6ef     |
    +---------------------------+--------------------------------------+


Create a subnet in net3.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net3 10.0.3.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.3.2", "end": "10.0.3.254"} |
    | cidr              | 10.0.3.0/24                                |
    | created_at        | 2017-01-12T07:07:42Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.3.1                                   |
    | host_routes       |                                            |
    | id                | 5ab92c3c-b799-451c-b5d5-b72274fb0fcc       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | 68d04c60-469d-495d-bb23-0d36d56235bd       |
    | project_id        | 532890c765604609a8d2ef6fc8e5f6ef           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | 532890c765604609a8d2ef6fc8e5f6ef           |
    | updated_at        | 2017-01-12T07:07:42Z                       |
    +-------------------+--------------------------------------------+

List the available images in RegionOne.

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 8747fd6a-72aa-4075-b936-a24bc48ed57b | cirros-0.3.4-x86_64-uec         |
    | 3a54e6fd-d215-437b-9d67-eac840c97f9c | cirros-0.3.4-x86_64-uec-kernel  |
    | 02b06834-2a9f-4dad-8d59-2a77963af8a5 | cirros-0.3.4-x86_64-uec-ramdisk |
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


Boot instance1 in RegionOne, and connect this instance to net1 and net3.

.. code-block:: console

    $ nova --os-region-name=RegionOne boot --flavor 1 --image 8747fd6a-72aa-4075-b936-a24bc48ed57b --nic net-id=68d04c60-469d-495d-bb23-0d36d56235bd --nic net-id=de4fda27-e4f7-4448-80f6-79ee5ea2478b instance1
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance1                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | 3a54e6fd-d215-437b-9d67-eac840c97f9c                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | 02b06834-2a9f-4dad-8d59-2a77963af8a5                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-9cnhvave                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | zDFR3x8pDDKi                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-12T07:09:53Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 3d53560e-4e04-43a0-b774-cfa3deecbca4                           |
    | image                                | cirros-0.3.4-x86_64-uec (8747fd6a-72aa-4075-b936-a24bc48ed57b) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance1                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | 532890c765604609a8d2ef6fc8e5f6ef                               |
    | updated                              | 2017-01-12T07:09:54Z                                           |
    | user_id                              | d2521e53aa8c4916b3a8e444f20cf1da                               |
    +--------------------------------------+----------------------------------------------------------------+

Make sure the instance1 is active in RegionOne.

.. code-block:: console

    $ nova --os-region-name=RegionOne list
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks                      |
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------+
    | 3d53560e-4e04-43a0-b774-cfa3deecbca4 | instance1 | ACTIVE | -          | Running     | net3=10.0.3.7; net1=10.0.1.13 |
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------+


Create a floating IP for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-create ext-net1
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-01-12T07:12:50Z                 |
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 163.3.124.6                          |
    | floating_network_id | 9b3d04be-0c00-40ed-88ff-088da6fcd8bd |
    | id                  | 645f9cd6-d8d4-427a-88fe-770240c96d09 |
    | port_id             |                                      |
    | project_id          | 532890c765604609a8d2ef6fc8e5f6ef     |
    | revision_number     | 1                                    |
    | router_id           |                                      |
    | status              | DOWN                                 |
    | tenant_id           | 532890c765604609a8d2ef6fc8e5f6ef     |
    | updated_at          | 2017-01-12T07:12:50Z                 |
    +---------------------+--------------------------------------+

List the port in net1 for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion port-list
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | id                                 | name                               | mac_address       | fixed_ips                            |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | 185b5185-0254-486c-9d8b-           |                                    | fa:16:3e:da:ae:99 | {"subnet_id": "2c8f446f-             |
    | 198af4b4d40e                       |                                    |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.13"}           |
    | 248f9072-76d6-405a-                |                                    | fa:16:3e:dc:2f:b3 | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 8eb5-f0d3475c542d                  |                                    |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.7"}                          |
    | d48a8e87-61a0-494b-                |                                    | fa:16:3e:c6:8e:c5 | {"subnet_id": "2c8f446f-             |
    | bc06-54f7a008ea78                  |                                    |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.1"}            |
    | ce3a1530-20f4-4760-a451-81e5f939aa | dhcp_port_2c8f446f-                | fa:16:3e:e6:32:0f | {"subnet_id": "2c8f446f-             |
    | fc                                 | ba02-4140-a793-913033aa3580        |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.2"}            |
    | 7925a3cc-                          | interface_RegionOne_2c8f446f-      | fa:16:3e:c5:ad:6f | {"subnet_id": "2c8f446f-             |
    | 6c36-4bc3-a798-a6145fed442a        | ba02-4140-a793-913033aa3580        |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.3"}            |
    | 077c63b6-0184-4bf7-b3aa-           | dhcp_port_5ab92c3c-b799-451c-      | fa:16:3e:d2:a3:53 | {"subnet_id": "5ab92c3c-b799-451c-   |
    | b071de6f39be                       | b5d5-b72274fb0fcc                  |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.2"}                          |
    | c90be7bc-                          | interface_RegionOne_5ab92c3c-b799  | fa:16:3e:b6:e4:bc | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 31ea-4015-a432-2bef62e343d1        | -451c-b5d5-b72274fb0fcc            |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.9"}                          |
    | 3053fcb9-b6ad-4a9c-b89e-           | bridge_port_532890c765604609a8d2ef | fa:16:3e:fc:d0:fc | {"subnet_id": "53def0ac-59ef-        |
    | ffe6aff6523b                       | 6fc8e5f6ef_0c4faa42-5230-4adc-     |                   | 4c7b-b694-3375598954da",             |
    |                                    | bab5-10ee53ebf888                  |                   | "ip_address": "100.0.0.11"}          |
    | ce787983-a140-4c53-96d2-71f62e1545 |                                    | fa:16:3e:1a:62:7f | {"subnet_id": "a2eecc16-deb8-42a6    |
    | 3a                                 |                                    |                   | -a41b-5058847ed20a", "ip_address":   |
    |                                    |                                    |                   | "163.3.124.5"}                       |
    | 2d9fc640-1858-4c7e-b42c-           |                                    | fa:16:3e:00:7c:6e | {"subnet_id": "a2eecc16-deb8-42a6    |
    | d3ed3f338b8a                       |                                    |                   | -a41b-5058847ed20a", "ip_address":   |
    |                                    |                                    |                   | "163.3.124.6"}                       |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+

Associate the floating IP to instance1's IP in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-associate 645f9cd6-d8d4-427a-88fe-770240c96d09 185b5185-0254-486c-9d8b-198af4b4d40e
    Associated floating IP 645f9cd6-d8d4-427a-88fe-770240c96d09

Verify the floating IP was associated.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | 645f9cd6-d8d4-427a-88fe-770240c96d09 | 10.0.1.13        | 163.3.124.6         | 185b5185-0254-486c-9d8b-198af4b4d40e |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

You can also check that in RegionOne.

.. code-block:: console

    $ neutron --os-region-name=RegionOne floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | d59362fa-aea0-4e35-917e-8e586212c867 | 10.0.1.13        | 163.3.124.6         | 185b5185-0254-486c-9d8b-198af4b4d40e |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

    $ neutron --os-region-name=RegionOne router-list
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+
    | id                                 | name                               | external_gateway_info              | distributed | ha    |
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+
    | 0c4faa42-5230-4adc-                | 063de74b-d962-4fc2-96d9-87e2cb35c0 | {"network_id": "6932cd71-3cd4-4560 | False       | False |
    | bab5-10ee53ebf888                  | 82                                 | -88f3-2a112fff0cea",               |             |       |
    |                                    |                                    | "enable_snat": false,              |             |       |
    |                                    |                                    | "external_fixed_ips":              |             |       |
    |                                    |                                    | [{"subnet_id": "53def0ac-59ef-     |             |       |
    |                                    |                                    | 4c7b-b694-3375598954da",           |             |       |
    |                                    |                                    | "ip_address": "100.0.0.11"}]}      |             |       |
    | f99dcc0c-d94a-                     | ns_router_063de74b-d962-4fc2-96d9- | {"network_id": "9b3d04be-0c00      | False       | False |
    | 4b41-9236-2c0169f3ab7d             | 87e2cb35c082                       | -40ed-88ff-088da6fcd8bd",          |             |       |
    |                                    |                                    | "enable_snat": true,               |             |       |
    |                                    |                                    | "external_fixed_ips":              |             |       |
    |                                    |                                    | [{"subnet_id": "a2eecc16-deb8-42a6 |             |       |
    |                                    |                                    | -a41b-5058847ed20a", "ip_address": |             |       |
    |                                    |                                    | "163.3.124.5"}]}                   |             |       |
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+

Create network topology in RegionTwo.

Create external network ext-net2, which will be located in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --router:external --availability-zone-hint RegionTwo ext-net2
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionTwo                            |
    | id                        | ae806ecb-fa3e-4b3c-a582-caef3d8cd9b4 |
    | name                      | ext-net2                             |
    | project_id                | 532890c765604609a8d2ef6fc8e5f6ef     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 183                                  |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 532890c765604609a8d2ef6fc8e5f6ef     |
    +---------------------------+--------------------------------------+

Create subnet in ext-net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet2 --disable-dhcp ext-net2 163.3.125.0/24
    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "163.3.125.2", "end": "163.3.125.254"} |
    | cidr              | 163.3.125.0/24                                   |
    | created_at        | 2017-01-12T07:43:04Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | False                                            |
    | gateway_ip        | 163.3.125.1                                      |
    | host_routes       |                                                  |
    | id                | 9fb32423-95a8-4589-b69c-e2955234ae56             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | ext-subnet2                                      |
    | network_id        | ae806ecb-fa3e-4b3c-a582-caef3d8cd9b4             |
    | project_id        | 532890c765604609a8d2ef6fc8e5f6ef                 |
    | revision_number   | 2                                                |
    | subnetpool_id     |                                                  |
    | tenant_id         | 532890c765604609a8d2ef6fc8e5f6ef                 |
    | updated_at        | 2017-01-12T07:43:04Z                             |
    +-------------------+--------------------------------------------------+

Create router R2 which will work in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create R2
    +-----------------------+--------------------------------------+
    | Field                 | Value                                |
    +-----------------------+--------------------------------------+
    | admin_state_up        | True                                 |
    | created_at            | 2017-01-12T07:19:23Z                 |
    | description           |                                      |
    | external_gateway_info |                                      |
    | id                    | 8a8571db-e3ba-4b78-98ca-13d4dc1a4fb0 |
    | name                  | R2                                   |
    | project_id            | 532890c765604609a8d2ef6fc8e5f6ef     |
    | revision_number       | 1                                    |
    | status                | ACTIVE                               |
    | tenant_id             | 532890c765604609a8d2ef6fc8e5f6ef     |
    | updated_at            | 2017-01-12T07:19:23Z                 |
    +-----------------------+--------------------------------------+

Set the router gateway to ext-net2 for R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-gateway-set R2 ext-net2
    Set gateway for router R2

Check router R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-show R2
    +-----------------------+------------------------------------------------------------------------------------------------------------+
    | Field                 | Value                                                                                                      |
    +-----------------------+------------------------------------------------------------------------------------------------------------+
    | admin_state_up        | True                                                                                                       |
    | created_at            | 2017-01-12T07:19:23Z                                                                                       |
    | description           |                                                                                                            |
    | external_gateway_info | {"network_id": "ae806ecb-fa3e-4b3c-a582-caef3d8cd9b4", "external_fixed_ips": [{"subnet_id":                |
    |                       | "9fb32423-95a8-4589-b69c-e2955234ae56", "ip_address": "163.3.125.3"}]}                                     |
    | id                    | 8a8571db-e3ba-4b78-98ca-13d4dc1a4fb0                                                                       |
    | name                  | R2                                                                                                         |
    | project_id            | 532890c765604609a8d2ef6fc8e5f6ef                                                                           |
    | revision_number       | 7                                                                                                          |
    | status                | ACTIVE                                                                                                     |
    | tenant_id             | 532890c765604609a8d2ef6fc8e5f6ef                                                                           |
    | updated_at            | 2017-01-12T07:44:00Z                                                                                       |
    +-----------------------+------------------------------------------------------------------------------------------------------------+


Create net2 in az2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --availability-zone-hint az2 net2
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az2                                  |
    | id                        | 71b06c5d-2eb8-4ef4-a978-c5c98874811b |
    | name                      | net2                                 |
    | project_id                | 532890c765604609a8d2ef6fc8e5f6ef     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | 532890c765604609a8d2ef6fc8e5f6ef     |
    +---------------------------+--------------------------------------+

Create subnet in net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net2 10.0.2.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.2.2", "end": "10.0.2.254"} |
    | cidr              | 10.0.2.0/24                                |
    | created_at        | 2017-01-12T07:45:55Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.2.1                                   |
    | host_routes       |                                            |
    | id                | 356947cf-88e2-408b-ab49-7c0e79110a25       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | 71b06c5d-2eb8-4ef4-a978-c5c98874811b       |
    | project_id        | 532890c765604609a8d2ef6fc8e5f6ef           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | 532890c765604609a8d2ef6fc8e5f6ef           |
    | updated_at        | 2017-01-12T07:45:55Z                       |
    +-------------------+--------------------------------------------+

Add router interface for the subnet to R2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-interface-add R2 356947cf-88e2-408b-ab49-7c0e79110a25
    Added interface 805b16de-fbe9-4b54-b891-b39bc2f73a86 to router R2.

List available images in RegionTwo.

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 6fbad28b-d5f1-4924-a330-f9d5a6cf6c62 | cirros-0.3.4-x86_64-uec         |
    | cc912d30-5cbe-406d-89f2-8c09a73012c4 | cirros-0.3.4-x86_64-uec-kernel  |
    | 8660610d-d362-4f20-8f99-4d64c7c21284 | cirros-0.3.4-x86_64-uec-ramdisk |
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

Boot instance2, and connect the instance2 to net2 and net3.

.. code-block:: console

    $ nova --os-region-name=RegionTwo boot --flavor 1 --image 6fbad28b-d5f1-4924-a330-f9d5a6cf6c62 --nic net-id=68d04c60-469d-495d-bb23-0d36d56235bd --nic net-id=71b06c5d-2eb8-4ef4-a978-c5c98874811b instance2
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance2                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | cc912d30-5cbe-406d-89f2-8c09a73012c4                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | 8660610d-d362-4f20-8f99-4d64c7c21284                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-xylwc16h                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | Lmanqrz9GN77                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-13T01:41:19Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | dbcfef20-0794-4b5e-aa3f-d08dc6086eb6                           |
    | image                                | cirros-0.3.4-x86_64-uec (6fbad28b-d5f1-4924-a330-f9d5a6cf6c62) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance2                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | 532890c765604609a8d2ef6fc8e5f6ef                               |
    | updated                              | 2017-01-13T01:41:19Z                                           |
    | user_id                              | d2521e53aa8c4916b3a8e444f20cf1da                               |
    +--------------------------------------+----------------------------------------------------------------+

Check to see if instance2 is active.

.. code-block:: console

    $ nova --os-region-name=RegionTwo list
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks                     |
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------+
    | dbcfef20-0794-4b5e-aa3f-d08dc6086eb6 | instance2 | ACTIVE | -          | Running     | net3=10.0.3.4; net2=10.0.2.3 |
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------+

Create floating IP for instance2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-create ext-net2
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-01-13T01:45:10Z                 |
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 163.3.125.4                          |
    | floating_network_id | ae806ecb-fa3e-4b3c-a582-caef3d8cd9b4 |
    | id                  | e0dcbe62-0023-41a8-a099-a4c4b5285e03 |
    | port_id             |                                      |
    | project_id          | 532890c765604609a8d2ef6fc8e5f6ef     |
    | revision_number     | 1                                    |
    | router_id           |                                      |
    | status              | DOWN                                 |
    | tenant_id           | 532890c765604609a8d2ef6fc8e5f6ef     |
    | updated_at          | 2017-01-13T01:45:10Z                 |
    +---------------------+--------------------------------------+

List port of instance2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion port-list
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | id                                 | name                               | mac_address       | fixed_ips                            |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | 185b5185-0254-486c-9d8b-           |                                    | fa:16:3e:da:ae:99 | {"subnet_id": "2c8f446f-             |
    | 198af4b4d40e                       |                                    |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.13"}           |
    | 248f9072-76d6-405a-                |                                    | fa:16:3e:dc:2f:b3 | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 8eb5-f0d3475c542d                  |                                    |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.7"}                          |
    | 6b0fe2e0-a236-40db-bcbf-           |                                    | fa:16:3e:73:21:6c | {"subnet_id": "356947cf-88e2-408b-   |
    | 2f31f7124d83                       |                                    |                   | ab49-7c0e79110a25", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.3"}                          |
    | ab6dd6f4-b48a-4a3e-                |                                    | fa:16:3e:67:03:73 | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 9f43-90d0fccc181a                  |                                    |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.4"}                          |
    | 5c0e0e7a-0faf-                     |                                    | fa:16:3e:7b:11:c6 |                                      |
    | 44c4-a735-c8745faa9920             |                                    |                   |                                      |
    | d48a8e87-61a0-494b-                |                                    | fa:16:3e:c6:8e:c5 | {"subnet_id": "2c8f446f-             |
    | bc06-54f7a008ea78                  |                                    |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.1"}            |
    | ce3a1530-20f4-4760-a451-81e5f939aa | dhcp_port_2c8f446f-                | fa:16:3e:e6:32:0f | {"subnet_id": "2c8f446f-             |
    | fc                                 | ba02-4140-a793-913033aa3580        |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.2"}            |
    | 7925a3cc-                          | interface_RegionOne_2c8f446f-      | fa:16:3e:c5:ad:6f | {"subnet_id": "2c8f446f-             |
    | 6c36-4bc3-a798-a6145fed442a        | ba02-4140-a793-913033aa3580        |                   | ba02-4140-a793-913033aa3580",        |
    |                                    |                                    |                   | "ip_address": "10.0.1.3"}            |
    | 805b16de-                          |                                    | fa:16:3e:94:cd:82 | {"subnet_id": "356947cf-88e2-408b-   |
    | fbe9-4b54-b891-b39bc2f73a86        |                                    |                   | ab49-7c0e79110a25", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.1"}                          |
    | 30243711-d113-42b7-b712-81ca0d7454 | dhcp_port_356947cf-88e2-408b-      | fa:16:3e:83:3d:c8 | {"subnet_id": "356947cf-88e2-408b-   |
    | 6d                                 | ab49-7c0e79110a25                  |                   | ab49-7c0e79110a25", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.2"}                          |
    | 27fab5a2-0710-4742-a731-331f6c2150 | interface_RegionTwo_356947cf-88e2  | fa:16:3e:39:0a:f5 | {"subnet_id": "356947cf-88e2-408b-   |
    | fa                                 | -408b-ab49-7c0e79110a25            |                   | ab49-7c0e79110a25", "ip_address":    |
    |                                    |                                    |                   | "10.0.2.6"}                          |
    | a7d0bae1-51de-                     | interface_RegionTwo_5ab92c3c-b799  | fa:16:3e:d6:3f:ca | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 4b47-9f81-b012e511e4a7             | -451c-b5d5-b72274fb0fcc            |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.11"}                         |
    | 077c63b6-0184-4bf7-b3aa-           | dhcp_port_5ab92c3c-b799-451c-      | fa:16:3e:d2:a3:53 | {"subnet_id": "5ab92c3c-b799-451c-   |
    | b071de6f39be                       | b5d5-b72274fb0fcc                  |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.2"}                          |
    | c90be7bc-                          | interface_RegionOne_5ab92c3c-b799  | fa:16:3e:b6:e4:bc | {"subnet_id": "5ab92c3c-b799-451c-   |
    | 31ea-4015-a432-2bef62e343d1        | -451c-b5d5-b72274fb0fcc            |                   | b5d5-b72274fb0fcc", "ip_address":    |
    |                                    |                                    |                   | "10.0.3.9"}                          |
    | 3053fcb9-b6ad-4a9c-b89e-           | bridge_port_532890c765604609a8d2ef | fa:16:3e:fc:d0:fc | {"subnet_id": "53def0ac-59ef-        |
    | ffe6aff6523b                       | 6fc8e5f6ef_0c4faa42-5230-4adc-     |                   | 4c7b-b694-3375598954da",             |
    |                                    | bab5-10ee53ebf888                  |                   | "ip_address": "100.0.0.11"}          |
    | 5a10c53f-1f8f-43c1-a61c-           | bridge_port_532890c765604609a8d2ef | fa:16:3e:dc:f7:4a | {"subnet_id": "53def0ac-59ef-        |
    | 6cdbd052985e                       | 6fc8e5f6ef_cf71a43d-6df1-491d-     |                   | 4c7b-b694-3375598954da",             |
    |                                    | 894d-bd2e6620acfc                  |                   | "ip_address": "100.0.0.8"}           |
    | ce787983-a140-4c53-96d2-71f62e1545 |                                    | fa:16:3e:1a:62:7f | {"subnet_id": "a2eecc16-deb8-42a6    |
    | 3a                                 |                                    |                   | -a41b-5058847ed20a", "ip_address":   |
    |                                    |                                    |                   | "163.3.124.5"}                       |
    | 2d9fc640-1858-4c7e-b42c-           |                                    | fa:16:3e:00:7c:6e | {"subnet_id": "a2eecc16-deb8-42a6    |
    | d3ed3f338b8a                       |                                    |                   | -a41b-5058847ed20a", "ip_address":   |
    |                                    |                                    |                   | "163.3.124.6"}                       |
    | bfd53cea-6135-4515-ae63-f346125335 |                                    | fa:16:3e:ae:81:6f | {"subnet_id": "9fb32423-95a8-4589    |
    | 27                                 |                                    |                   | -b69c-e2955234ae56", "ip_address":   |
    |                                    |                                    |                   | "163.3.125.3"}                       |
    | 12495d5b-5346-48d0-8ed2-daea6ad42a |                                    | fa:16:3e:d4:83:cc | {"subnet_id": "9fb32423-95a8-4589    |
    | 3a                                 |                                    |                   | -b69c-e2955234ae56", "ip_address":   |
    |                                    |                                    |                   | "163.3.125.4"}                       |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+

Associate the floating IP to the instance2's IP address in net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-associate e0dcbe62-0023-41a8-a099-a4c4b5285e03 6b0fe2e0-a236-40db-bcbf-2f31f7124d83
    Associated floating IP e0dcbe62-0023-41a8-a099-a4c4b5285e03

Make sure the floating IP association works.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | 645f9cd6-d8d4-427a-88fe-770240c96d09 | 10.0.1.13        | 163.3.124.6         | 185b5185-0254-486c-9d8b-198af4b4d40e |
    | e0dcbe62-0023-41a8-a099-a4c4b5285e03 | 10.0.2.3         | 163.3.125.4         | 6b0fe2e0-a236-40db-bcbf-2f31f7124d83 |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

You can verify that in RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=RegionTwo floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | b8a6b83a-cc8f-4335-894c-ef71e7504ee1 | 10.0.2.3         | 163.3.125.4         | 6b0fe2e0-a236-40db-bcbf-2f31f7124d83 |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

Instance1 can ping instance2 through the IP address in the net3, and vice versa.

Note: Not all images will bring up the second nic, so you can ssh into
instance1 or instance2, use ifconfig -a to check whether all NICs are created,
and bring up all NICs if necessary.
