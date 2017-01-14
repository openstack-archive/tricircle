================
Local Networking
================

The following figure illustrates one networking mode without cross
Neutron networking requirement, only networking inside one region is needed.

.. code-block:: console

                +-----------------+       +-----------------+
                |   RegionOne     |       |   RegionTwo     |
                |                 |       |                 |
                |     ext-net1    |       |     ext-net2    |
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
                |     +---+-+-+   |       |     +---++--+   |
                |     net1  |     |       |     net2 |      |
                |           |     |       |          |      |
                |   +-------+---+ |       |  +-------+----+ |
                |   | instance1 | |       |  | instance2  | |
                |   +-----------+ |       |  +------------+ |
                +-----------------+       +-----------------+

How to create this network topology
===================================

Create external network ext-net1, which will be located in RegionOne.
Need to specify region name as the value of availability-zone-hint.
If availability-zone-hint is not provided, then the external network
will be created in a default region.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create --provider:network_type vlan --provider:physical_network extern --router:external --availability-zone-hint RegionOne ext-net1

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   | RegionOne                            |
    | id                        | a3a23b20-b0c1-461a-bc00-3db04ce212ca |
    | name                      | ext-net1                             |
    | project_id                | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 170                                  |
    | router:external           | True                                 |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | c0e194dfadd44fc1983fd6dd7c8ed384     |
    +---------------------------+--------------------------------------+

For external network, the network will be created in the region specified in
availability-zone-hint too.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-list
    +--------------------------------------+----------+---------+
    | id                                   | name     | subnets |
    +--------------------------------------+----------+---------+
    | a3a23b20-b0c1-461a-bc00-3db04ce212ca | ext-net1 |         |
    +--------------------------------------+----------+---------+

    $ neutron --os-region-name=RegionOne net-list
    +--------------------------------------+--------------------------------------+---------+
    | id                                   | name                                 | subnets |
    +--------------------------------------+--------------------------------------+---------+
    | a3a23b20-b0c1-461a-bc00-3db04ce212ca | a3a23b20-b0c1-461a-bc00-3db04ce212ca |         |
    +--------------------------------------+--------------------------------------+---------+

Create subnet in ext-net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name ext-subnet1 --disable-dhcp ext-net1 163.3.124.0/24
    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "163.3.124.2", "end": "163.3.124.254"} |
    | cidr              | 163.3.124.0/24                                   |
    | created_at        | 2017-01-10T04:49:16Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | False                                            |
    | gateway_ip        | 163.3.124.1                                      |
    | host_routes       |                                                  |
    | id                | 055ec17a-5b64-4cff-878c-c898427aabe3             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | ext-subnet1                                      |
    | network_id        | a3a23b20-b0c1-461a-bc00-3db04ce212ca             |
    | project_id        | c0e194dfadd44fc1983fd6dd7c8ed384                 |
    | revision_number   | 2                                                |
    | subnetpool_id     |                                                  |
    | tenant_id         | c0e194dfadd44fc1983fd6dd7c8ed384                 |
    | updated_at        | 2017-01-10T04:49:16Z                             |
    +-------------------+--------------------------------------------------+

Create router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-create R1
    +-----------------------+--------------------------------------+
    | Field                 | Value                                |
    +-----------------------+--------------------------------------+
    | admin_state_up        | True                                 |
    | created_at            | 2017-01-10T04:50:06Z                 |
    | description           |                                      |
    | external_gateway_info |                                      |
    | id                    | 7ce3282f-3864-4c55-84bf-fc5edc3293cb |
    | name                  | R1                                   |
    | project_id            | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | revision_number       | 1                                    |
    | status                | ACTIVE                               |
    | tenant_id             | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | updated_at            | 2017-01-10T04:50:06Z                 |
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
    | created_at            | 2017-01-10T04:50:06Z                                                                                       |
    | description           |                                                                                                            |
    | external_gateway_info | {"network_id": "a3a23b20-b0c1-461a-bc00-3db04ce212ca", "external_fixed_ips": [{"subnet_id": "055ec17a-5b64 |
    |                       | -4cff-878c-c898427aabe3", "ip_address": "163.3.124.5"}]}                                                   |
    | id                    | 7ce3282f-3864-4c55-84bf-fc5edc3293cb                                                                       |
    | name                  | R1                                                                                                         |
    | project_id            | c0e194dfadd44fc1983fd6dd7c8ed384                                                                           |
    | revision_number       | 3                                                                                                          |
    | status                | ACTIVE                                                                                                     |
    | tenant_id             | c0e194dfadd44fc1983fd6dd7c8ed384                                                                           |
    | updated_at            | 2017-01-10T04:51:19Z                                                                                       |
    +-----------------------+------------------------------------------------------------------------------------------------------------+

Create network net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create net1
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   |                                      |
    | id                        | beaf59eb-c597-4b69-bd41-8bf9fee2dc6a |
    | name                      | net1                                 |
    | project_id                | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | provider:network_type     | local                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  |                                      |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | c0e194dfadd44fc1983fd6dd7c8ed384     |
    +---------------------------+--------------------------------------+

Create a subnet in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.1.2", "end": "10.0.1.254"} |
    | cidr              | 10.0.1.0/24                                |
    | created_at        | 2017-01-10T04:54:29Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        | 10.0.1.1                                   |
    | host_routes       |                                            |
    | id                | ab812ed5-1a4c-4b12-859c-6c9b3df21642       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              |                                            |
    | network_id        | beaf59eb-c597-4b69-bd41-8bf9fee2dc6a       |
    | project_id        | c0e194dfadd44fc1983fd6dd7c8ed384           |
    | revision_number   | 2                                          |
    | subnetpool_id     |                                            |
    | tenant_id         | c0e194dfadd44fc1983fd6dd7c8ed384           |
    | updated_at        | 2017-01-10T04:54:29Z                       |
    +-------------------+--------------------------------------------+

Add this subnet to router R1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion router-interface-add R1 ab812ed5-1a4c-4b12-859c-6c9b3df21642
    Added interface 2b7eceaf-8333-49cd-a7fe-aa101d5c9598 to router R1.

List the available images in RegionOne.

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list
    +--------------------------------------+---------------------------------+
    | ID                                   | Name                            |
    +--------------------------------------+---------------------------------+
    | 2f73b93e-8b8a-4e07-8732-87f968852d82 | cirros-0.3.4-x86_64-uec         |
    | 4040ca54-2ebc-4ccd-8a0d-4284f4713ef1 | cirros-0.3.4-x86_64-uec-kernel  |
    | 7e86341f-2d6e-4a2a-b01a-e334fa904cf0 | cirros-0.3.4-x86_64-uec-ramdisk |
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

    $ nova --os-region-name=RegionOne boot --flavor 1 --image 2f73b93e-8b8a-4e07-8732-87f968852d82 --nic net-id=beaf59eb-c597-4b69-bd41-8bf9fee2dc6a instance1
    +--------------------------------------+----------------------------------------------------------------+
    | Property                             | Value                                                          |
    +--------------------------------------+----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                         |
    | OS-EXT-AZ:availability_zone          |                                                                |
    | OS-EXT-SRV-ATTR:host                 | -                                                              |
    | OS-EXT-SRV-ATTR:hostname             | instance1                                                      |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                              |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                |
    | OS-EXT-SRV-ATTR:kernel_id            | 4040ca54-2ebc-4ccd-8a0d-4284f4713ef1                           |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                              |
    | OS-EXT-SRV-ATTR:ramdisk_id           | 7e86341f-2d6e-4a2a-b01a-e334fa904cf0                           |
    | OS-EXT-SRV-ATTR:reservation_id       | r-5t409rww                                                     |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                              |
    | OS-EXT-SRV-ATTR:user_data            | -                                                              |
    | OS-EXT-STS:power_state               | 0                                                              |
    | OS-EXT-STS:task_state                | scheduling                                                     |
    | OS-EXT-STS:vm_state                  | building                                                       |
    | OS-SRV-USG:launched_at               | -                                                              |
    | OS-SRV-USG:terminated_at             | -                                                              |
    | accessIPv4                           |                                                                |
    | accessIPv6                           |                                                                |
    | adminPass                            | 23DipTvrpCvn                                                   |
    | config_drive                         |                                                                |
    | created                              | 2017-01-10T04:59:25Z                                           |
    | description                          | -                                                              |
    | flavor                               | m1.tiny (1)                                                    |
    | hostId                               |                                                                |
    | host_status                          |                                                                |
    | id                                   | 301546be-b675-49eb-b6c2-c5c986235ecb                           |
    | image                                | cirros-0.3.4-x86_64-uec (2f73b93e-8b8a-4e07-8732-87f968852d82) |
    | key_name                             | -                                                              |
    | locked                               | False                                                          |
    | metadata                             | {}                                                             |
    | name                                 | instance1                                                      |
    | os-extended-volumes:volumes_attached | []                                                             |
    | progress                             | 0                                                              |
    | security_groups                      | default                                                        |
    | status                               | BUILD                                                          |
    | tags                                 | []                                                             |
    | tenant_id                            | c0e194dfadd44fc1983fd6dd7c8ed384                               |
    | updated                              | 2017-01-10T04:59:26Z                                           |
    | user_id                              | a7b7420bd76c48c2bb5cb97c16bb165d                               |
    +--------------------------------------+----------------------------------------------------------------+

Make sure instance1 is active in RegionOne.

.. code-block:: console

    $ nova --os-region-name=RegionOne list
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | ID                                   | Name      | Status | Task State | Power State | Networks      |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+
    | 301546be-b675-49eb-b6c2-c5c986235ecb | instance1 | ACTIVE | -          | Running     | net1=10.0.1.4 |
    +--------------------------------------+-----------+--------+------------+-------------+---------------+

Verify regarding networking resource are provisioned in RegionOne.

.. code-block:: console

    $ neutron --os-region-name=RegionOne router-list
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+
    | id                                 | name                               | external_gateway_info              | distributed | ha    |
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+
    | d6cd0978-f3cc-4a0b-b45b-           | 7ce3282f-3864-4c55-84bf-           | {"network_id": "a3a23b20-b0c1      | False       | False |
    | a427ebc51382                       | fc5edc3293cb                       | -461a-bc00-3db04ce212ca",          |             |       |
    |                                    |                                    | "enable_snat": true,               |             |       |
    |                                    |                                    | "external_fixed_ips":              |             |       |
    |                                    |                                    | [{"subnet_id": "055ec17a-5b64      |             |       |
    |                                    |                                    | -4cff-878c-c898427aabe3",          |             |       |
    |                                    |                                    | "ip_address": "163.3.124.5"}]}     |             |       |
    +------------------------------------+------------------------------------+------------------------------------+-------------+-------+


Create a floating IP for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-create ext-net1
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | created_at          | 2017-01-10T05:17:48Z                 |
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 163.3.124.7                          |
    | floating_network_id | a3a23b20-b0c1-461a-bc00-3db04ce212ca |
    | id                  | 0c031c3f-93ba-49bf-9c98-03bf4b0c7b2b |
    | port_id             |                                      |
    | project_id          | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | revision_number     | 1                                    |
    | router_id           |                                      |
    | status              | DOWN                                 |
    | tenant_id           | c0e194dfadd44fc1983fd6dd7c8ed384     |
    | updated_at          | 2017-01-10T05:17:48Z                 |
    +---------------------+--------------------------------------+

List the port in net1 for instance1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion port-list
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | id                                 | name                               | mac_address       | fixed_ips                            |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+
    | 0b55c3b3-ae5f-4d03-899b-           |                                    | fa:16:3e:b5:1d:95 | {"subnet_id": "ab812ed5-1a4c-4b12    |
    | f056d967942e                       |                                    |                   | -859c-6c9b3df21642", "ip_address":   |
    |                                    |                                    |                   | "10.0.1.4"}                          |
    | 2b7eceaf-8333-49cd-a7fe-           |                                    | fa:16:3e:59:b3:ef | {"subnet_id": "ab812ed5-1a4c-4b12    |
    | aa101d5c9598                       |                                    |                   | -859c-6c9b3df21642", "ip_address":   |
    |                                    |                                    |                   | "10.0.1.1"}                          |
    | 572ad59f-                          | dhcp_port_ab812ed5-1a4c-4b12-859c- | fa:16:3e:56:7f:2b | {"subnet_id": "ab812ed5-1a4c-4b12    |
    | 5a15-4662-9fb8-f92a49389b28        | 6c9b3df21642                       |                   | -859c-6c9b3df21642", "ip_address":   |
    |                                    |                                    |                   | "10.0.1.2"}                          |
    | bf398883-c435-4cb2-8693-017a790825 | interface_RegionOne_ab812ed5-1a4c- | fa:16:3e:15:ef:1f | {"subnet_id": "ab812ed5-1a4c-4b12    |
    | 9e                                 | 4b12-859c-6c9b3df21642             |                   | -859c-6c9b3df21642", "ip_address":   |
    |                                    |                                    |                   | "10.0.1.7"}                          |
    | 452b8ebf-                          |                                    | fa:16:3e:1f:59:b2 | {"subnet_id": "055ec17a-5b64-4cff-   |
    | c9c6-4990-9048-644a3a6fde1a        |                                    |                   | 878c-c898427aabe3", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.5"}                       |
    | 8e77c6ab-2884-4779-91e2-c3a4975fdf |                                    | fa:16:3e:3c:88:7d | {"subnet_id": "055ec17a-5b64-4cff-   |
    | 50                                 |                                    |                   | 878c-c898427aabe3", "ip_address":    |
    |                                    |                                    |                   | "163.3.124.7"}                       |
    +------------------------------------+------------------------------------+-------------------+--------------------------------------+

Associate the floating IP to instance1's IP in net1.

.. code-block:: console

    $ neutron --os-region-name=CentralRegion floatingip-associate 0c031c3f-93ba-49bf-9c98-03bf4b0c7b2b 0b55c3b3-ae5f-4d03-899b-f056d967942e
    Associated floating IP 0c031c3f-93ba-49bf-9c98-03bf4b0c7b2b

Verify floating IP is associated in RegionOne too.

.. code-block:: console

    $ neutron --os-region-name=RegionOne floatingip-list
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | id                                   | fixed_ip_address | floating_ip_address | port_id                              |
    +--------------------------------------+------------------+---------------------+--------------------------------------+
    | b28baa80-d798-43e7-baff-e65873bd1ec2 | 10.0.1.4         | 163.3.124.7         | 0b55c3b3-ae5f-4d03-899b-f056d967942e |
    +--------------------------------------+------------------+---------------------+--------------------------------------+

You can create topology in RegionTwo like what has been done in RegionOne.
