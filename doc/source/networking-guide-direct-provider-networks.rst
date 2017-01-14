===================================================
North South Networking via Direct Provider Networks
===================================================

The following figure illustrates one typical networking mode, instances have
two interfaces, one interface is connected to net1 for heartbeat or
data replication, the other interface is connected to phy_net1 or phy_net2 to
provide service. There is different physical network in different region to
support service redundancy in case of region level failure.

.. code-block:: console

                +-----------------+       +-----------------+
                |RegionOne        |       |RegionTwo        |
                |                 |       |                 |
                |   phy_net1      |       |   phy_net2      |
                |  +--+---------+ |       |  +--+---------+ |
                |     |           |       |     |           |
                |     |           |       |     |           |
                |  +--+--------+  |       |  +--+--------+  |
                |  |           |  |       |  |           |  |
                |  | Instance1 |  |       |  | Instance2 |  |
                |  +------+----+  |       |  +------+----+  |
                |         |       |       |         |       |
                |         |       |       |         |       |
                |   net1  |       |       |         |       |
                |  +------+-------------------------+---+   |
                |                 |       |                 |
                +-----------------+       +-----------------+

How to create this network topology
===================================

Create provider network phy_net1, which will be located in az1, including
RegionOne.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --availability-zone-hint az1 phy_net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az1                                  |
    | id                        | b7832cbb-d399-4d5d-bcfd-d1b804506a1a |
    | name                      | phy_net1                             |
    | project_id                | ce444c8be6da447bb412db7d30cd7023     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 170                                  |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | ce444c8be6da447bb412db7d30cd7023     |
    +---------------------------+--------------------------------------+

Create subnet in phy_net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create phy_net1 202.96.1.0/24
    +-------------------+------------------------------------------------+
    | Field             | Value                                          |
    +-------------------+------------------------------------------------+
    | allocation_pools  | {"start": "202.96.1.2", "end": "202.96.1.254"} |
    | cidr              | 202.96.1.0/24                                  |
    | created_at        | 2017-01-11T08:43:48Z                           |
    | description       |                                                |
    | dns_nameservers   |                                                |
    | enable_dhcp       | True                                           |
    | gateway_ip        | 202.96.1.1                                     |
    | host_routes       |                                                |
    | id                | 4941c48e-5602-40fc-a117-e84833b85ed3           |
    | ip_version        | 4                                              |
    | ipv6_address_mode |                                                |
    | ipv6_ra_mode      |                                                |
    | name              |                                                |
    | network_id        | b7832cbb-d399-4d5d-bcfd-d1b804506a1a           |
    | project_id        | ce444c8be6da447bb412db7d30cd7023               |
    | revision_number   | 2                                              |
    | subnetpool_id     |                                                |
    | tenant_id         | ce444c8be6da447bb412db7d30cd7023               |
    | updated_at        | 2017-01-11T08:43:48Z                           |
    +-------------------+------------------------------------------------+

Create provider network phy_net2, which will be located in az2, including
RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --availability-zone-hint az2 phy_net2
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az2                                  |
    | id                        | 731293af-e68f-4677-b433-f46afd6431f3 |
    | name                      | phy_net2                             |
    | project_id                | ce444c8be6da447bb412db7d30cd7023     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 168                                  |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | ce444c8be6da447bb412db7d30cd7023     |
    +---------------------------+--------------------------------------+

Create subnet in phy_net2.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create phy_net2 202.96.2.0/24
    +-------------------+------------------------------------------------+
    | Field             | Value                                          |
    +-------------------+------------------------------------------------+
    | allocation_pools  | {"start": "202.96.2.2", "end": "202.96.2.254"} |
    | cidr              | 202.96.2.0/24                                  |
    | created_at        | 2017-01-11T08:47:07Z                           |
    | description       |                                                |
    | dns_nameservers   |                                                |
    | enable_dhcp       | True                                           |
    | gateway_ip        | 202.96.2.1                                     |
    | host_routes       |                                                |
    | id                | f5fb4f11-4bc1-4911-bcca-b0eaccc6eaf9           |
    | ip_version        | 4                                              |
    | ipv6_address_mode |                                                |
    | ipv6_ra_mode      |                                                |
    | name              |                                                |
    | network_id        | 731293af-e68f-4677-b433-f46afd6431f3           |
    | project_id        | ce444c8be6da447bb412db7d30cd7023               |
    | revision_number   | 2                                              |
    | subnetpool_id     |                                                |
    | tenant_id         | ce444c8be6da447bb412db7d30cd7023               |
    | updated_at        | 2017-01-11T08:47:08Z                           |
    +-------------------+------------------------------------------------+

Create net1 which will work as the L2 network across RegionOne and RegionTwo.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network bridge --availability-zone-hint az1 --availability-zone-hint az2 net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | az1                                  |
    |                           | az2                                  |
    | id                        | 1897a446-bf6a-4bce-9374-6a3825ee5051 |
    | name                      | net1                                 |
    | project_id                | ce444c8be6da447bb412db7d30cd7023     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | bridge                               |
    | provider:segmentation_id  | 132                                  |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | ce444c8be6da447bb412db7d30cd7023     |
    +---------------------------+--------------------------------------+

Create subnet in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.1.2", "end": "10.0.1.254"} |
    | cidr              | 10.0.1.0/24                                |
    | created_at        | 2017-01-11T08:49:53Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.1.1                                   |
    | host_routes       |                                            |
    | id                | 6a6c63b4-7f41-4a8f-9393-55cd79380e5a       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | 1897a446-bf6a-4bce-9374-6a3825ee5051       |
    | project_id        | ce444c8be6da447bb412db7d30cd7023           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | ce444c8be6da447bb412db7d30cd7023           |
    | updated_at        | 2017-01-11T08:49:53Z                       |
    +-------------------+--------------------------------------------+

List available images in RegionOne.

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 924a5078-efe5-4abf-85e8-992b7e5f6ac3 | cirros-0.3.4-x86_64-uec         |
    | d3e8349d-d58d-4d17-b0ab-951c095fbbc4 | cirros-0.3.4-x86_64-uec-kernel  |
    | c4cd7482-a145-4f26-9f41-a9ac17b9492c | cirros-0.3.4-x86_64-uec-ramdisk |
    +--------------------------------------+---------------------------------+

List available flavors in RegionOne.

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

Boot instance1 in RegionOne, and connect this instance to net1 and phy_net1.

.. code-block:: console

    $ nova --os-region-name=RegionOne boot --flavor 1 --image 924a5078-efe5-4abf-85e8-992b7e5f6ac3 --nic net-id=1897a446-bf6a-4bce-9374-6a3825ee5051 --nic net-id=b7832cbb-d399-4d5d-bcfd-d1b804506a1a instance1
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance1                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | d3e8349d-d58d-4d17-b0ab-951c095fbbc4                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | c4cd7482-a145-4f26-9f41-a9ac17b9492c                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-eeu5hjq7                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | ZB3Ve3nPS66g                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-11T10:49:32Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 5fd0f616-1077-46df-bebd-b8b53d09663c                           |
    | image                                | cirros-0.3.4-x86_64-uec (924a5078-efe5-4abf-85e8-992b7e5f6ac3) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance1                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | ce444c8be6da447bb412db7d30cd7023                               |
    | updated                              | 2017-01-11T10:49:33Z                                           |
    | user_id                              | 66d7b31664a840939f7d3f2de5e717a9                               |
    +--------------------------------------+----------------------------------------------------------------+

List available images in RegionTwo.

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 1da4303c-96bf-4714-a4dc-cbd5709eda29 | cirros-0.3.4-x86_64-uec         |
    | fb35d578-a984-4807-8234-f0d0ca393e89 | cirros-0.3.4-x86_64-uec-kernel  |
    | a615d6df-be63-4d5a-9a05-5cf7e23a438a | cirros-0.3.4-x86_64-uec-ramdisk |
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

Boot instance1 in RegionOne, and connect this instance to net1 and phy_net2.

.. code-block:: console

    $ nova --os-region-name=RegionTwo boot --flavor 1 --image 1da4303c-96bf-4714-a4dc-cbd5709eda29 --nic net-id=1897a446-bf6a-4bce-9374-6a3825ee5051 --nic net-id=731293af-e68f-4677-b433-f46afd6431f3 instance2
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance2                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | fb35d578-a984-4807-8234-f0d0ca393e89                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | a615d6df-be63-4d5a-9a05-5cf7e23a438a                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-m0duhg40                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | M5FodqwcsTiJ                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-11T12:55:35Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 010a0a24-0453-4e73-ae8d-21c7275a9df5                           |
    | image                                | cirros-0.3.4-x86_64-uec (1da4303c-96bf-4714-a4dc-cbd5709eda29) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance2                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | ce444c8be6da447bb412db7d30cd7023                               |
    | updated                              | 2017-01-11T12:55:35Z                                           |
    | user_id                              | 66d7b31664a840939f7d3f2de5e717a9                               |
    +--------------------------------------+----------------------------------------------------------------+

Make sure the instance1 is active in RegionOne.

.. code-block:: console

    $ nova --os-region-name=RegionOne list
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks                            |
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------------+
    | 5fd0f616-1077-46df-bebd-b8b53d09663c | instance1 | ACTIVE | -          | Running     | net1=10.0.1.4; phy_net1=202.96.1.13 |
    +--------------------------------------+-----------+--------+------------+-------------+-------------------------------------+

Make sure the instance2 is active in RegionTwo.

.. code-block:: console

    $ nova --os-region-name=RegionTwo list
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks                           |
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------------+
    | 010a0a24-0453-4e73-ae8d-21c7275a9df5 | instance2 | ACTIVE | -          | Running     | phy_net2=202.96.2.5; net1=10.0.1.5 |
    +--------------------------------------+-----------+--------+------------+-------------+------------------------------------+

Now you can ping instance2's IP address 10.0.1.5 from instance1, or ping
instance1's IP address 10.0.1.4 from instance2.

Note: Not all images will bring up the second nic, so you can ssh into
instance1 or instance2, use ifconfig -a to check whether all NICs are created,
and bring up all NICs if necessary.
