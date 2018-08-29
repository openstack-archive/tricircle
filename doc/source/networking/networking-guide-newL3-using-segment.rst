================================================================
How to use the new layer-3 networking model for multi-NS-with-EW
================================================================

The following figure illustrates the new layer-3 networking model for multi-NS-with-EW::

    ext-net1             ext-net2

    +---+---+            +---+---+
        |                    |
    +---+---+            +---+---+
    |  R1   |            |  R2   |
    +---+---+            +---+---+
        |                    |
    +---+--------------------+---+
    |         bridge-net         |
    +-------------+--------------+
                  |
                  |
    +-------------+--------------+
    |            R3              |
    +---+--------------------+---+
        | net1          net2 |
    +---+-----+-+      +---+-+---+
              |            |
    +---------+-+       +--+--------+
    | Instance1 |       | Instance2 |
    +-----------+       +-----------+

    Figure 1 Logical topology in central Neutron

As shown in Fig. 1, each external network(i.e., ext-net1, ext-net2) will connect to a Router(i.e., R1, R2).
These routers will take charge of routing NS traffic and connect with the logical(non-local) router through
bridge network. This is the networking model in the spec [1]_, a routed network is using to manage the
external networks in central Neutron.

When we create a logical router(i.e., R3) in central Neutron, Tricircle will create local router in each region.
Then attach the network(i.e, net1, net2) to central router(i.e, R3), this router will take charge of all
traffic (no matter NS or EW traffic).

For EW traffic, from net1 to net2, R3(in net1's region) will forwards packets to the
interface of net2 in R3(in net2's region) router namespace. For NS traffic, R3 forwards
packets to the interface of an available local router (i.e., R1 or R2)
which attached to the real external network.

More details in the specs of A New Layer-3 Networking multi-NS-with-EW-enabled [1]

How to use segment for managing multiple networks in this network topology
==========================================================================

1. Enable the configuration of enable_l3_route_network in /tricircle/network/central_plugin.py

.. code-block:: console

    cfg.BoolOpt('enable_l3_route_network',
                default=True,
                help=_('Whether using new l3 networking model. When it is'
                       'set True, Tricircle will create a local router'
                       'automatically after creating an external network'))

2. Add segment plugin in /etc/neutron/neutron.conf.0

.. code-block:: console

    service_plugins = tricircle.network.segment_plugin.TricircleSegmentPlugin

Now we start to create segments and subnetworks.

.. code-block:: console

    stack@stack-atom:~/devstack$ openstack multiregion networking pod list
    stack@stack-atom:~/devstack$ openstack multiregion networking pod create --region-name CentralRegion
    +-------------+--------------------------------------+
    | Field       | Value                                |
    +-------------+--------------------------------------+
    | az_name     |                                      |
    | dc_name     |                                      |
    | pod_az_name |                                      |
    | pod_id      | f2f5757d-350f-4278-91a4-3baca12ebccc |
    | region_name | CentralRegion                        |
    +-------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack multiregion networking pod create --region-name RegionOne --availability-zone az1
    +-------------+--------------------------------------+
    | Field       | Value                                |
    +-------------+--------------------------------------+
    | az_name     | az1                                  |
    | dc_name     |                                      |
    | pod_az_name |                                      |
    | pod_id      | 7c34177a-a210-4edc-a5ca-b9615a7061b3 |
    | region_name | RegionOne                            |
    +-------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network create --share --provider-physical-network extern --provider-network-type vlan --provider-segment 3005 multisegment
    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | UP                                   |
    | availability_zone_hints   |                                      |
    | availability_zones        | None                                 |
    | created_at                | None                                 |
    | description               | None                                 |
    | dns_domain                | None                                 |
    | id                        | e848d653-e777-4715-9596-bd0427d9fd27 |
    | ipv4_address_scope        | None                                 |
    | ipv6_address_scope        | None                                 |
    | is_default                | None                                 |
    | is_vlan_transparent       | None                                 |
    | location                  | None                                 |
    | mtu                       | None                                 |
    | name                      | multisegment                         |
    | port_security_enabled     | False                                |
    | project_id                | 1f31124fadd247f18098a20a6da207ec     |
    | provider:network_type     | vlan                                 |
    | provider:physical_network | extern                               |
    | provider:segmentation_id  | 3005                                 |
    | qos_policy_id             | None                                 |
    | revision_number           | None                                 |
    | router:external           | Internal                             |
    | segments                  | None                                 |
    | shared                    | True                                 |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tags                      |                                      |
    | updated_at                | None                                 |
    +---------------------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network segment create --physical-network extern  --network-type vlan --segment 3005 --network multisegment newl3-RegionOne-sgmtnet01
    +------------------+--------------------------------------+
    | Field            | Value                                |
    +------------------+--------------------------------------+
    | description      |                                      |
    | id               | 802ccc73-1c99-455e-858a-1c19d77d1995 |
    | location         | None                                 |
    | name             | newl3-RegionOne-sgmtnet01            |
    | network_id       | e848d653-e777-4715-9596-bd0427d9fd27 |
    | network_type     | vlan                                 |
    | physical_network | extern                               |
    | segmentation_id  | 3005                                 |
    +------------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network list
    +--------------------------------------+---------------------------+---------+
    | ID                                   | Name                      | Subnets |
    +--------------------------------------+---------------------------+---------+
    | 5596d53f-d6ed-4ac5-9722-ad7e3e82e187 | newl3-RegionOne-sgmtnet01 |         |
    | e848d653-e777-4715-9596-bd0427d9fd27 | multisegment              |         |
    +--------------------------------------+---------------------------+---------+
    stack@stack-atom:~/devstack$  openstack --os-region-name=RegionOne network list
    +--------------------------------------+---------------------------+---------+
    | ID                                   | Name                      | Subnets |
    +--------------------------------------+---------------------------+---------+
    | 2b9f4e56-57be-4624-87b9-ab745ec321c0 | newl3-RegionOne-sgmtnet01 |         |
    +--------------------------------------+---------------------------+---------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion subnet create --network newl3-RegionOne-sgmtnet01  --subnet-range 10.0.0.0/24 newl3segment01-subnet-v4
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | allocation_pools  | 10.0.0.2-10.0.0.254                  |
    | cidr              | 10.0.0.0/24                          |
    | created_at        | 2018-11-28T09:22:39Z                 |
    | description       |                                      |
    | dns_nameservers   |                                      |
    | enable_dhcp       | True                                 |
    | gateway_ip        | 10.0.0.1                             |
    | host_routes       |                                      |
    | id                | f00f7eb0-a72a-4c25-8f71-46e3d872064a |
    | ip_version        | 4                                    |
    | ipv6_address_mode | None                                 |
    | ipv6_ra_mode      | None                                 |
    | location          | None                                 |
    | name              | newl3segment01-subnet-v4             |
    | network_id        | 5596d53f-d6ed-4ac5-9722-ad7e3e82e187 |
    | project_id        | 1f31124fadd247f18098a20a6da207ec     |
    | revision_number   | 0                                    |
    | segment_id        | None                                 |
    | service_types     | None                                 |
    | subnetpool_id     | None                                 |
    | tags              |                                      |
    | updated_at        | 2018-11-28T09:22:39Z                 |
    +-------------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network list
    +--------------------------------------+---------------------------+--------------------------------------+
    | ID                                   | Name                      | Subnets                              |
    +--------------------------------------+---------------------------+--------------------------------------+
    | 5596d53f-d6ed-4ac5-9722-ad7e3e82e187 | newl3-RegionOne-sgmtnet01 | f00f7eb0-a72a-4c25-8f71-46e3d872064a |
    | e848d653-e777-4715-9596-bd0427d9fd27 | multisegment              |                                      |
    +--------------------------------------+---------------------------+--------------------------------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion subnet list
    +--------------------------------------+--------------------------+--------------------------------------+-------------+
    | ID                                   | Name                     | Network                              | Subnet      |
    +--------------------------------------+--------------------------+--------------------------------------+-------------+
    | f00f7eb0-a72a-4c25-8f71-46e3d872064a | newl3segment01-subnet-v4 | 5596d53f-d6ed-4ac5-9722-ad7e3e82e187 | 10.0.0.0/24 |
    +--------------------------------------+--------------------------+--------------------------------------+-------------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=RegionOne network list
    +--------------------------------------+---------------------------+--------------------------------------+
    | ID                                   | Name                      | Subnets                              |
    +--------------------------------------+---------------------------+--------------------------------------+
    | 2b9f4e56-57be-4624-87b9-ab745ec321c0 | newl3-RegionOne-sgmtnet01 | f00f7eb0-a72a-4c25-8f71-46e3d872064a |
    +--------------------------------------+---------------------------+--------------------------------------+
    stack@stack-atom:~/devstack$  openstack --os-region-name=RegionOne subnet list
    +--------------------------------------+--------------------------------------+--------------------------------------+-------------+
    | ID                                   | Name                                 | Network                              | Subnet      |
    +--------------------------------------+--------------------------------------+--------------------------------------+-------------+
    | f00f7eb0-a72a-4c25-8f71-46e3d872064a | f00f7eb0-a72a-4c25-8f71-46e3d872064a | 2b9f4e56-57be-4624-87b9-ab745ec321c0 | 10.0.0.0/24 |
    +--------------------------------------+--------------------------------------+--------------------------------------+-------------+

This part is for how to delete segments and subnetworks.

.. code-block:: console

    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion subnet delete newl3segment01-subnet-v4
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion subnet list

    stack@stack-atom:~/devstack$ openstack --os-region-name=RegionOne subnet list

    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network delete newl3-RegionOne-sgmtnet01
    stack@stack-atom:~/devstack$ openstack --os-region-name=CentralRegion network list
    +--------------------------------------+--------------+---------+
    | ID                                   | Name         | Subnets |
    +--------------------------------------+--------------+---------+
    | e848d653-e777-4715-9596-bd0427d9fd27 | multisegment |         |
    +--------------------------------------+--------------+---------+
    stack@stack-atom:~/devstack$ openstack --os-region-name=RegionOne network list

    stack@stack-atom:~/devstack$


Reference
=========

.. [1] https://github.com/openstack/tricircle/blob/master/specs/stein/new-l3-networking-mulit-NS-with-EW.rst
