==================================
Work with Nova cell v2(experiment)
==================================

.. note:: Multi-cell support of Nova cell v2 is under development. DevStack
   doesn't support multi-cell deployment currently, so the steps discussed in
   this document may seem not that elegant. We will keep updating this document
   according to the progress of multi-cell development by Nova team.

Setup
^^^^^

- 1 Follow "Multi-pod Installation with DevStack" document to prepare your
  local.conf for both nodes, and set TRICIRCLE_DEPLOY_WITH_CELL to True for
  both nodes. Start DevStack in node1, then node2.

.. note:: After running DevStack in both nodes, a multi-cell environment will
  be prepared: there is one CentralRegion, where Nova API and central Neutron
  will be registered. Nova has two cells, node1 belongs to cell1, node2 belongs
  to cell2, and each cell will be configured to use a dedicated local Neutron.
  For cell1, it's RegionOne Neutron in node1; for cell2, it's RegionTwo Neutron
  in node2(you can set the region name in local.conf to make the name more
  friendly). End user can access CentralRegion endpoint of Nova and Neutron to
  experience the integration of Nova cell v2 and Tricircle.

- 2 Stop the following services in node2::

    systemctl stop devstack@n-sch.service
    systemctl stop devstack@n-super-cond.service
    systemctl stop devstack@n-api.service

  if the service of devstack@n-api-meta.service exists, stop it::

    systemctl stop devstack@n-api-meta.service

.. note:: Actually for cell v2, only one Nova API is required. We enable n-api
   in node2 because we need DevStack to help us create the necessary cell
   database. If n-api is disabled, neither API database nor cell database will
   be created.

- 3 In node2, run the following command::

    mysql -u$user -p$password -Dnova_cell1 -e 'select host, mapped from compute_nodes'

  you can see that this command returns you one row showing the host of node2
  is already mapped::

    +-----------+--------+
    | host      | mapped |
    +-----------+--------+
    | zhiyuan-2 |      1 |
    +-----------+--------+

  This host is registered to Nova API in node2, which is already stopped by us,
  We need to update this row to set "mapped" to 0::

    mysql -u$user -p$password -Dnova_cell1 -e 'update compute_nodes set mapped = 0 where host = "zhiyuan-2"'

  then we can register this host again in step4.

- 4 In node1, run the following commands to register the new cell::

    nova-manage cell_v2 create_cell --name cell2 \
      --transport-url rabbit://$rabbit_user:$rabbit_passwd@$node2_ip:5672/nova_cell1 \
      --database_connection mysql+pymysql://$db_user:$db_passwd@$node2_ip/nova_cell1?charset=utf8

    nova-manage cell_v2 discover_hosts

  then you can see the new cell and host are added in the database::

    mysql -u$user -p$password -Dnova_api -e 'select cell_id, host from host_mappings'

    +---------+-----------+
    | cell_id | host      |
    +---------+-----------+
    |       2 | zhiyuan-1 |
    |       3 | zhiyuan-2 |
    +---------+-----------+

    mysql -u$user -p$password -Dnova_api -e 'select id, name from cell_mappings'

    +----+-------+
    | id | name  |
    +----+-------+
    |  1 | cell0 |
    |  2 | cell1 |
    |  3 | cell2 |
    +----+-------+

- 5 In node1, run the following commands::

    systemctl restart devstack@n-sch.service

- 6 In node1, check if compute services in both hosts are registered::

    openstack --os-region-name CentralRegion compute service list

    +----+------------------+-----------+----------+---------+-------+----------------------------+
    | ID | Binary           | Host      | Zone     | Status  | State | Updated At                 |
    +----+------------------+-----------+----------+---------+-------+----------------------------+
    |  5 | nova-scheduler   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:56:02.000000 |
    |  6 | nova-conductor   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:56:09.000000 |
    |  8 | nova-consoleauth | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:56:01.000000 |
    |  1 | nova-conductor   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:56:07.000000 |
    |  3 | nova-compute     | zhiyuan-1 | nova     | enabled | up    | 2017-09-20T06:56:10.000000 |
    |  1 | nova-conductor   | zhiyuan-2 | internal | enabled | up    | 2017-09-20T06:56:07.000000 |
    |  3 | nova-compute     | zhiyuan-2 | nova     | enabled | up    | 2017-09-20T06:56:09.000000 |
    +----+------------------+-----------+----------+---------+-------+----------------------------+

    zhiyuan-1 has two nova-conductor services, because one of them is a super
    conductor service.

- 7 Create two aggregates and put the two hosts in each aggregate::

    nova --os-region-name CentralRegion aggregate-create ag1 az1
    nova --os-region-name CentralRegion aggregate-create ag2 az2
    nova --os-region-name CentralRegion aggregate-add-host ag1 zhiyuan-1
    nova --os-region-name CentralRegion aggregate-add-host ag2 zhiyuan-2

- 8 Create pods, tricircle client is used::

    openstack --os-region-name CentralRegion multiregion networking pod create --region-name CentralRegion
    openstack --os-region-name CentralRegion multiregion networking pod create --region-name RegionOne --availability-zone az1
    openstack --os-region-name CentralRegion multiregion networking pod create --region-name RegionTwo --availability-zone az2

- 9 Create network and boot virtual machines::

    net_id=$(openstack --os-region-name CentralRegion network create --provider-network-type vxlan net1 -c id -f value)
    openstack --os-region-name CentralRegion subnet create --subnet-range 10.0.1.0/24 --network net1 subnet1
    image_id=$(openstack --os-region-name CentralRegion image list -c ID -f value)

    openstack --os-region-name CentralRegion server create --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az1 vm1
    openstack --os-region-name CentralRegion server create --flavor 1 --image $image_id --nic net-id=$net_id --availability-zone az2 vm2

Trouble Shooting
^^^^^^^^^^^^^^^^

- 1 After you run "compute service list" in step5, you only see services in node1, like::

    +----+------------------+-----------+----------+---------+-------+----------------------------+
    | ID | Binary           | Host      | Zone     | Status  | State | Updated At                 |
    +----+------------------+-----------+----------+---------+-------+----------------------------+
    |  5 | nova-scheduler   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:55:52.000000 |
    |  6 | nova-conductor   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:55:59.000000 |
    |  8 | nova-consoleauth | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:56:01.000000 |
    |  1 | nova-conductor   | zhiyuan-1 | internal | enabled | up    | 2017-09-20T06:55:57.000000 |
    |  3 | nova-compute     | zhiyuan-1 | nova     | enabled | up    | 2017-09-20T06:56:00.000000 |
    +----+------------------+-----------+----------+---------+-------+----------------------------+

  Though new cell has been registered in the database, the running n-api process
  in node1 may not recognize it. We find that restarting n-api can solve this
  problem.
