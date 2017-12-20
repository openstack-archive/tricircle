=========================================
Installation guide for LBaaS in Tricircle
=========================================

.. note:: Since Octavia does not support multiple region scenarios, some
   modifications are required to install the Tricircle and Octavia in multiple
   pods. As a result, we will keep updating this document, so as to support
   automatic installation and test for Tricircle and Octavia in multiple regions.

Setup & Installation
^^^^^^^^^^^^^^^^^^^^

- 1 For the node1 in RegionOne, clone the code from Octavia repository to
  /opt/stack/. Then comment three lines, i.e., **build_mgmt_network**,
  **create_mgmt_network_interface**, and **configure_lb_mgmt_sec_grp** in the
  **octavia_start** function in octavia/devstack/plugin.sh, so that we can build
  the management network in multiple regions manually.

- 2 Follow "Multi-pod Installation with DevStack" document `Multi-pod Installation with DevStack <https://docs.openstack.org/tricircle/latest/install/installation-guide.html#multi-pod-installation-with-devstack>`_
  to prepare your local.conf for the node1 in RegionOne, and add the
  following lines before installation. Start DevStack in node1.

.. code-block:: console

  enable_plugin neutron-lbaas https://github.com/openstack/neutron-lbaas.git
  enable_plugin octavia https://github.com/openstack/octavia.git
  ENABLED_SERVICES+=,q-lbaasv2
  ENABLED_SERVICES+=,octavia,o-cw,o-hk,o-hm,o-api

- 3 If users only want to deploy Octavia in RegionOne, the following two
  steps can be skipped. After the installation in node1 is complete. For
  the node2 in RegionTwo, clone the code from Octavia repository to
  /opt/stack/. Here we need to modify plugin.sh in five sub-steps.

  - First, since Keystone is installed in RegionOne and shared by other
    regions, we need to comment the function of creating Octavia roles, i.e.,
    **add_load-balancer_roles**.

  - Second, the same as Step 1, comment three lines of creating networking
    resources, i.e., **build_mgmt_network**, **create_mgmt_network_interface**,
    and **configure_lb_mgmt_sec_grp** in the **octavia_start** function in
    octavia/devstack/plugin.sh.

  - Third, replace 'openstack keypair' with
    'openstack --os-region-name=$REGION_NAME keypair'.

  - Fourth, replace
    'openstack image' with 'openstack --os-region-name=$REGION_NAME image'.

  - Fifth, replace 'openstack flavor' with
    'openstack --os-region-name=$REGION_NAME flavor'.

- 4 Follow "Multi-pod Installation with DevStack" document `Multi-pod Installation with DevStack <https://docs.openstack.org/tricircle/latest/install/installation-guide.html#multi-pod-installation-with-devstack>`_
  to prepare your local.conf for the node2 in RegionTwo, and add the
  following lines before installation. Start DevStack in node2.

.. code-block:: console

  enable_plugin neutron-lbaas https://github.com/openstack/neutron-lbaas.git
  enable_plugin octavia https://github.com/openstack/octavia.git
  ENABLED_SERVICES+=,q-lbaasv2
  ENABLED_SERVICES+=,octavia,o-cw,o-hk,o-hm,o-api

Prerequisite
^^^^^^^^^^^^

- 1 After DevStack successfully starts, we must create environment variables
  for the admin user and use the admin project, since Octavia controller will
  use admin account to query and use the management network as well as
  security group created in the following steps

.. code-block:: console

    $ source openrc admin admin

- 2 Then unset the region name environment variable, so that the command can be
  issued to specified region in following commands as needed.

.. code-block:: console

    $ unset OS_REGION_NAME

- 3 Before configure LBaaS, we need to create pods in CentralRegion, i.e., node1.

.. code-block:: console

    $ openstack multiregion networking pod create --region-name CentralRegion
    $ openstack multiregion networking pod create --region-name RegionOne --availability-zone az1
    $ openstack multiregion networking pod create --region-name RegionTwo --availability-zone az2

Configuration
^^^^^^^^^^^^^

- 1 Create security groups.

Create security group and rules for load balancer management network.

.. code-block:: console

    $ openstack --os-region-name=CentralRegion security group create lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol icmp lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol tcp --dst-port 22 lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol tcp --dst-port 9443 lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol icmpv6 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol tcp --dst-port 22 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol tcp --dst-port 9443 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp

.. note:: The output in the console is omitted.

Create security group and rules for healthy manager

.. code-block:: console

    $ openstack --os-region-name=CentralRegion security group create lb-health-mgr-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol udp --dst-port 5555 lb-health-mgr-sec-grp
    $ openstack --os-region-name=CentralRegion security group rule create --protocol udp --dst-port 5555 --ethertype IPv6 --remote-ip ::/0 lb-health-mgr-sec-grp

.. note:: The output in the console is omitted.


- 2 Configure LBaaS in node1

Create an amphora management network in CentralRegion

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create lb-mgmt-net1

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   |                                      |
    | id                        | f8aa5dde-92f8-4c0c-81a7-54e6b3202d8e |
    | name                      | lb-mgmt-net1                         |
    | project_id                | a9541f8689054dc681e0234fa4315950     |
    | provider:network_type     | vxlan                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  | 1018                                 |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a9541f8689054dc681e0234fa4315950     |
    +---------------------------+--------------------------------------+

Create a subnet in lb-mgmt-net1

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name lb-mgmt-subnet1 lb-mgmt-net1 192.168.1.0/24

    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "192.168.1.2", "end": "192.168.1.254"} |
    | cidr              | 192.168.1.0/24                                   |
    | created_at        | 2017-09-18T11:49:25Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | True                                             |
    | gateway_ip        | 192.168.1.1                                      |
    | host_routes       |                                                  |
    | id                | f04bad05-c610-490a-b9f7-12c0590e788c             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | lb-mgmt-subnet1                                  |
    | network_id        | f8aa5dde-92f8-4c0c-81a7-54e6b3202d8e             |
    | project_id        | a9541f8689054dc681e0234fa4315950                 |
    | revision_number   | 0                                                |
    | subnetpool_id     |                                                  |
    | tags              |                                                  |
    | tenant_id         | a9541f8689054dc681e0234fa4315950                 |
    | updated_at        | 2017-09-18T11:49:25Z                             |
    +-------------------+--------------------------------------------------+

Create the health management interface for Octavia in RegionOne.

.. code-block:: console

    $ id_and_mac=$(neutron --os-region-name=CentralRegion port-create --name octavia-health-manager-region-one-listen-port --security-group lb-health-mgr-sec-grp --device-owner Octavia:health-mgr --binding:host_id=$(hostname) lb-mgmt-net1 $PORT_FIXED_IP | awk '/ id | mac_address / {print $4}')
    $ id_and_mac=($id_and_mac)
    $ MGMT_PORT_ID=${id_and_mac[0]}
    $ MGMT_PORT_MAC=${id_and_mac[1]}
    $ MGMT_PORT_IP=$(openstack --os-region-name=RegionOne port show -f value -c fixed_ips $MGMT_PORT_ID | awk '{FS=",| "; gsub(",",""); gsub("'\''",""); for(i = 1; i <= NF; ++i) {if ($i ~ /^ip_address/) {n=index($i, "="); if (substr($i, n+1) ~ "\\.") print substr($i, n+1)}}}')
    $ neutron --os-region-name=RegionOne port-update --binding:host_id=$(hostname) $MGMT_PORT_ID
    $ sudo ovs-vsctl -- --may-exist add-port ${OVS_BRIDGE:-br-int} o-hm0 -- set Interface o-hm0 type=internal -- set Interface o-hm0 external-ids:iface-status=active -- set Interface o-hm0 external-ids:attached-mac=$MGMT_PORT_MAC -- set Interface o-hm0 external-ids:iface-id=$MGMT_PORT_ID -- set Interface o-hm0 external-ids:skip_cleanup=true
    $ OCTAVIA_DHCLIENT_CONF=/etc/octavia/dhcp/dhclient.conf
    $ sudo ip link set dev o-hm0 address $MGMT_PORT_MAC
    $ sudo dhclient -v o-hm0 -cf $OCTAVIA_DHCLIENT_CONF

    Listening on LPF/o-hm0/fa:16:3e:ea:1a:c9
    Sending on   LPF/o-hm0/fa:16:3e:ea:1a:c9
    Sending on   Socket/fallback
    DHCPDISCOVER on o-hm0 to 255.255.255.255 port 67 interval 3 (xid=0xae9d2b51)
    DHCPREQUEST of 192.168.1.5 on o-hm0 to 255.255.255.255 port 67 (xid=0x512b9dae)
    DHCPOFFER of 192.168.1.5 from 192.168.1.2
    DHCPACK of 192.168.1.5 from 192.168.1.2
    bound to 192.168.1.5 -- renewal in 38734 seconds.

    $ sudo iptables -I INPUT -i o-hm0 -p udp --dport 5555 -j ACCEPT


.. note:: As shown in the console, DHCP server allocates 192.168.1.5 as the
   IP of the health management interface, i.e., 0-hm. Hence, we need to
   modify the /etc/octavia/octavia.conf file to make Octavia aware of it and
   use the resources we just created, including health management interface,
   amphora security group and so on.

.. csv-table::
   :header: "Option", "Description", "Example"

   [health_manager] bind_ip, "the ip of health manager in RegionOne", 192.168.1.5
   [health_manager] bind_port, "the port health manager listens on", 5555
   [health_manager] controller_ip_port_list, "the ip and port of health manager binds in RegionOne", 192.168.1.5:5555
   [controller_worker] amp_boot_network_list, "the id of amphora management network in RegionOne", "query neutron to obtain it, i.e., the id of lb-mgmt-net1 in this doc"
   [controller_worker] amp_secgroup_list, "the id of security group created for amphora in central region", "query neutron to obtain it, i.e., the id of lb-mgmt-sec-grp"
   [neutron] service_name, "The name of the neutron service in the keystone catalog", neutron
   [neutron] endpoint, "Central neutron endpoint if override is necessary", http://192.168.56.5:20001/
   [neutron] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", CentralRegion
   [neutron] endpoint_type, "Endpoint type", public
   [nova] service_name, "The name of the nova service in the keystone catalog", nova
   [nova] endpoint, "Custom nova endpoint if override is necessary", http://192.168.56.5/compute/v2.1
   [nova] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionOne
   [nova] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public
   [glance] service_name, "The name of the glance service in the keystone catalog", glance
   [glance] endpoint, "Custom glance endpoint if override is necessary", http://192.168.56.5/image
   [glance] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionOne
   [glance] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public

Restart all the services of Octavia in node1.

.. code-block:: console

    $ sudo systemctl restart devstack@o-*

- 2 If users only deploy Octavia in RegionOne, this step can be skipped.
  Configure LBaaS in node2.

Create an amphora management network in CentralRegion

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create lb-mgmt-net2

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   |                                      |
    | id                        | 6b2859b7-2b24-4e7c-a340-2e638de9b452 |
    | name                      | lb-mgmt-net2                         |
    | project_id                | a9541f8689054dc681e0234fa4315950     |
    | provider:network_type     | vxlan                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  | 1054                                 |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a9541f8689054dc681e0234fa4315950     |
    +---------------------------+--------------------------------------+

Create a subnet in lb-mgmt-net2

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create --name lb-mgmt-subnet2 lb-mgmt-net2 192.168.2.0/24

    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "192.168.2.2", "end": "192.168.2.254"} |
    | cidr              | 192.168.2.0/24                                   |
    | created_at        | 2017-09-18T11:55:38Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | True                                             |
    | gateway_ip        | 192.168.2.1                                      |
    | host_routes       |                                                  |
    | id                | e92408d7-6110-4da4-b073-2b1a23b866a1             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | lb-mgmt-subnet2                                  |
    | network_id        | 6b2859b7-2b24-4e7c-a340-2e638de9b452             |
    | project_id        | a9541f8689054dc681e0234fa4315950                 |
    | revision_number   | 0                                                |
    | subnetpool_id     |                                                  |
    | tags              |                                                  |
    | tenant_id         | a9541f8689054dc681e0234fa4315950                 |
    | updated_at        | 2017-09-18T11:55:38Z                             |
    +-------------------+--------------------------------------------------+

Create the health management interface for Octavia in RegionTwo.

.. code-block:: console

    $ id_and_mac=$(neutron --os-region-name=CentralRegion port-create --name octavia-health-manager-region-one-listen-port --security-group lb-health-mgr-sec-grp --device-owner Octavia:health-mgr --binding:host_id=$(hostname) lb-mgmt-net2 $PORT_FIXED_IP | awk '/ id | mac_address / {print $4}')
    $ id_and_mac=($id_and_mac)
    $ MGMT_PORT_ID=${id_and_mac[0]}
    $ MGMT_PORT_MAC=${id_and_mac[1]}
    $ MGMT_PORT_IP=$(openstack --os-region-name=RegionTwo port show -f value -c fixed_ips $MGMT_PORT_ID | awk '{FS=",| "; gsub(",",""); gsub("'\''",""); for(i = 1; i <= NF; ++i) {if ($i ~ /^ip_address/) {n=index($i, "="); if (substr($i, n+1) ~ "\\.") print substr($i, n+1)}}}')
    $ neutron --os-region-name=RegionTwo port-update --binding:host_id=$(hostname) $MGMT_PORT_ID
    $ sudo ovs-vsctl -- --may-exist add-port ${OVS_BRIDGE:-br-int} o-hm0 -- set Interface o-hm0 type=internal -- set Interface o-hm0 external-ids:iface-status=active -- set Interface o-hm0 external-ids:attached-mac=$MGMT_PORT_MAC -- set Interface o-hm0 external-ids:iface-id=$MGMT_PORT_ID -- set Interface o-hm0 external-ids:skip_cleanup=true
    $ OCTAVIA_DHCLIENT_CONF=/etc/octavia/dhcp/dhclient.conf
    $ sudo ip link set dev o-hm0 address $MGMT_PORT_MAC
    $ sudo dhclient -v o-hm0 -cf $OCTAVIA_DHCLIENT_CONF

    Listening on LPF/o-hm0/fa:16:3e:c3:7c:2b
    Sending on   LPF/o-hm0/fa:16:3e:c3:7c:2b
    Sending on   Socket/fallback
    DHCPDISCOVER on o-hm0 to 255.255.255.255 port 67 interval 3 (xid=0xc75c651f)
    DHCPREQUEST of 192.168.2.11 on o-hm0 to 255.255.255.255 port 67 (xid=0x1f655cc7)
    DHCPOFFER of 192.168.2.11 from 192.168.2.2
    DHCPACK of 192.168.2.11 from 192.168.2.2
    bound to 192.168.2.11 -- renewal in 35398 seconds.

    $ sudo iptables -I INPUT -i o-hm0 -p udp --dport 5555 -j ACCEPT

.. note:: The ip allocated by DHCP server, i.e., 192.168.2.11 in this case,
   is the bound and listened by health manager of Octavia. Please note that
   it will be used in the configuration file of Octavia.

Modify the /etc/octavia/octavia.conf in node2.

.. csv-table::
   :header: "Option", "Description", "Example"

   [health_manager] bind_ip, "the ip of health manager in RegionTwo", 192.168.2.11
   [health_manager] bind_port, "the port health manager listens on in RegionTwo", 5555
   [health_manager] controller_ip_port_list, "the ip and port of health manager binds in RegionTwo", 192.168.2.11:5555
   [controller_worker] amp_boot_network_list, "the id of amphora management network in RegionTwo", "query neutron to obtain it, i.e., the id of lb-mgmt-net2 in this doc"
   [controller_worker] amp_secgroup_list, "the id of security group created for amphora in central region", "query neutron to obtain it, i.e., the id of lb-mgmt-sec-grp"
   [neutron] service_name, "The name of the neutron service in the keystone catalog", neutron
   [neutron] endpoint, "Central neutron endpoint if override is necessary", http://192.168.56.6:20001/
   [neutron] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", CentralRegion
   [neutron] endpoint_type, "Endpoint type", public
   [nova] service_name, "The name of the nova service in the keystone catalog", nova
   [nova] endpoint, "Custom nova endpoint if override is necessary", http://192.168.56.6/compute/v2.1
   [nova] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionTwo
   [nova] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public
   [glance] service_name, "The name of the glance service in the keystone catalog", glance
   [glance] endpoint, "Custom glance endpoint if override is necessary", http://192.168.56.6/image
   [glance] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionTwo
   [glance] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public

Restart all the services of Octavia in node2.

.. code-block:: console

    $ sudo systemctl restart devstack@o-*

By now, we finish installing LBaaS.

How to play
^^^^^^^^^^^

- 1 LBaaS members in one network and in same region

Here we take VxLAN as an example.

Create net1 in CentralRegion

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create net1

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   |                                      |
    | id                        | ff495200-dd0e-4fd5-8d5f-e750d6da2beb |
    | name                      | net1                                 |
    | project_id                | a9541f8689054dc681e0234fa4315950     |
    | provider:network_type     | vxlan                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  | 1096                                 |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a9541f8689054dc681e0234fa4315950     |
    +---------------------------+--------------------------------------+

Create a subnet in net1

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24 --name subnet1 --no-gateway

    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.1.2", "end": "10.0.1.254"} |
    | cidr              | 10.0.1.0/24                                |
    | created_at        | 2017-09-18T12:11:03Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        |                                            |
    | host_routes       |                                            |
    | id                | 86587e20-dfb4-4192-a59a-d523d2c5f932       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              | subnet1                                    |
    | network_id        | ff495200-dd0e-4fd5-8d5f-e750d6da2beb       |
    | project_id        | a9541f8689054dc681e0234fa4315950           |
    | revision_number   | 0                                          |
    | subnetpool_id     |                                            |
    | tags              |                                            |
    | tenant_id         | a9541f8689054dc681e0234fa4315950           |
    | updated_at        | 2017-09-18T12:11:03Z                       |
    +-------------------+--------------------------------------------+

.. note:: To enable adding instances as members with VIP, amphora adds a
   new route table to route the traffic sent from VIP to its gateway. However,
   in Tricircle, the gateway obtained from central neutron is not the real
   gateway in local neutron. As a result, we did not set any gateway for
   the subnet temporarily. We will remove the limitation in the future.

List all available flavors in RegionOne

.. code-block:: console

    $ nova --os-region-name=RegionOne flavor-list

    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | ID | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | 1  | m1.tiny   | 512       | 1    | 0         |      | 1     | 1.0         | True      |
    | 2  | m1.small  | 2048      | 20   | 0         |      | 1     | 1.0         | True      |
    | 3  | m1.medium | 4096      | 40   | 0         |      | 2     | 1.0         | True      |
    | 4  | m1.large  | 8192      | 80   | 0         |      | 4     | 1.0         | True      |
    | 42 | m1.nano   | 64        | 0    | 0         |      | 1     | 1.0         | True      |
    | 5  | m1.xlarge | 16384     | 160  | 0         |      | 8     | 1.0         | True      |
    | 84 | m1.micro  | 128       | 0    | 0         |      | 1     | 1.0         | True      |
    | c1 | cirros256 | 256       | 0    | 0         |      | 1     | 1.0         | True      |
    | d1 | ds512M    | 512       | 5    | 0         |      | 1     | 1.0         | True      |
    | d2 | ds1G      | 1024      | 10   | 0         |      | 1     | 1.0         | True      |
    | d3 | ds2G      | 2048      | 10   | 0         |      | 2     | 1.0         | True      |
    | d4 | ds4G      | 4096      | 20   | 0         |      | 4     | 1.0         | True      |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+

List all available images in RegionOne

.. code-block:: console

    $ glance --os-region-name=RegionOne image-list

    +--------------------------------------+--------------------------+
    | ID                                   | Name                     |
    +--------------------------------------+--------------------------+
    | 1b2a0cba-4801-4096-934c-2ccd0940d35c | amphora-x64-haproxy      |
    | 05ba1898-32ad-4418-a51c-c0ded215e221 | cirros-0.3.5-x86_64-disk |
    +--------------------------------------+--------------------------+

Create two instances, i.e., backend1 and backend2, in RegionOne, which reside in subnet1.

.. code-block:: console

    $ nova --os-region-name=RegionOne boot --flavor 1 --image $image_id --nic net-id=$net1_id backend1
    $ nova --os-region-name=RegionOne boot --flavor 1 --image $image_id --nic net-id=$net1_id backend2

    +--------------------------------------+-----------------------------------------------------------------+
    | Property                             | Value                                                           |
    +--------------------------------------+-----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                          |
    | OS-EXT-AZ:availability_zone          |                                                                 |
    | OS-EXT-SRV-ATTR:host                 | -                                                               |
    | OS-EXT-SRV-ATTR:hostname             | backend1                                                        |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                               |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                 |
    | OS-EXT-SRV-ATTR:kernel_id            |                                                                 |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                               |
    | OS-EXT-SRV-ATTR:ramdisk_id           |                                                                 |
    | OS-EXT-SRV-ATTR:reservation_id       | r-0xj1w004                                                      |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
    | OS-EXT-SRV-ATTR:user_data            | -                                                               |
    | OS-EXT-STS:power_state               | 0                                                               |
    | OS-EXT-STS:task_state                | scheduling                                                      |
    | OS-EXT-STS:vm_state                  | building                                                        |
    | OS-SRV-USG:launched_at               | -                                                               |
    | OS-SRV-USG:terminated_at             | -                                                               |
    | accessIPv4                           |                                                                 |
    | accessIPv6                           |                                                                 |
    | adminPass                            | 3EzRqv8dBWY7                                                    |
    | config_drive                         |                                                                 |
    | created                              | 2017-09-18T12:28:10Z                                            |
    | description                          | -                                                               |
    | flavor:disk                          | 1                                                               |
    | flavor:ephemeral                     | 0                                                               |
    | flavor:extra_specs                   | {}                                                              |
    | flavor:original_name                 | m1.tiny                                                         |
    | flavor:ram                           | 512                                                             |
    | flavor:swap                          | 0                                                               |
    | flavor:vcpus                         | 1                                                               |
    | hostId                               |                                                                 |
    | host_status                          |                                                                 |
    | id                                   | 9e13d9d1-393d-401d-a3a8-c76fb8171bcd                            |
    | image                                | cirros-0.3.5-x86_64-disk (05ba1898-32ad-4418-a51c-c0ded215e221) |
    | key_name                             | -                                                               |
    | locked                               | False                                                           |
    | metadata                             | {}                                                              |
    | name                                 | backend1                                                        |
    | os-extended-volumes:volumes_attached | []                                                              |
    | progress                             | 0                                                               |
    | security_groups                      | default                                                         |
    | status                               | BUILD                                                           |
    | tags                                 | []                                                              |
    | tenant_id                            | a9541f8689054dc681e0234fa4315950                                |
    | updated                              | 2017-09-18T12:28:24Z                                            |
    | user_id                              | eab4a9d4da144e43bb1cacc8fad6f057                                |
    +--------------------------------------+-----------------------------------------------------------------+

Console in the instances with user 'cirros' and password of 'cubswin:)'. Then run the following commands to simulate a web server.

.. code-block:: console

    $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
    $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

The Octavia installed in node1 and node2 are two standalone services,
here we take RegionOne as an example.

Create a load balancer for subnet1 in RegionOne.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-loadbalancer-create --name lb1 subnet1

    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | admin_state_up      | True                                 |
    | description         |                                      |
    | id                  | bfdf4dc6-8e1f-43fe-b83d-5fd26878826f |
    | listeners           |                                      |
    | name                | lb1                                  |
    | operating_status    | OFFLINE                              |
    | pools               |                                      |
    | provider            | octavia                              |
    | provisioning_status | PENDING_CREATE                       |
    | tenant_id           | 460439b4f4d846a4b505139f347a2358     |
    | vip_address         | 10.0.1.10                            |
    | vip_port_id         | a0a98ec1-d4dc-42a3-bedd-de2fb571b9e7 |
    | vip_subnet_id       | 14b6ac12-d4d1-4b16-b40b-ae50d365e8e0 |
    +---------------------+--------------------------------------+

Create a listener for the load balancer after the status of the load
balancer is 'ACTIVE'. Please note that it may take some time for the
load balancer to become 'ACTIVE'.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-loadbalancer-list

    +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+
    | id                                   | name | tenant_id                        | vip_address | provisioning_status | provider |
    +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+
    | bfdf4dc6-8e1f-43fe-b83d-5fd26878826f | lb1  | a9541f8689054dc681e0234fa4315950 | 10.0.1.10   | ACTIVE              | octavia  |
    +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+

    $ neutron --os-region-name=RegionOne lbaas-listener-create --loadbalancer lb1 --protocol HTTP --protocol-port 80 --name listener1
    +---------------------------+------------------------------------------------+
    | Field                     | Value                                          |
    +---------------------------+------------------------------------------------+
    | admin_state_up            | True                                           |
    | connection_limit          | -1                                             |
    | default_pool_id           |                                                |
    | default_tls_container_ref |                                                |
    | description               |                                                |
    | id                        | ad090bb1-ef9d-430b-a6e3-07c5d279b4a5           |
    | loadbalancers             | {"id": "bfdf4dc6-8e1f-43fe-b83d-5fd26878826f"} |
    | name                      | listener1                                      |
    | protocol                  | HTTP                                           |
    | protocol_port             | 80                                             |
    | sni_container_refs        |                                                |
    | tenant_id                 | 460439b4f4d846a4b505139f347a2358               |
    +---------------------------+------------------------------------------------+

Create a pool for the listener after the status of the load balancer is 'ACTIVE'.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-pool-create --lb-algorithm ROUND_ROBIN --listener listener1 --protocol HTTP --name pool1

    +---------------------+------------------------------------------------+
    | Field               | Value                                          |
    +---------------------+------------------------------------------------+
    | admin_state_up      | True                                           |
    | description         |                                                |
    | healthmonitor_id    |                                                |
    | id                  | 710b321d-d829-4d9b-8f63-1f295a6fb922           |
    | lb_algorithm        | ROUND_ROBIN                                    |
    | listeners           | {"id": "ad090bb1-ef9d-430b-a6e3-07c5d279b4a5"} |
    | loadbalancers       | {"id": "bfdf4dc6-8e1f-43fe-b83d-5fd26878826f"} |
    | members             |                                                |
    | name                | pool1                                          |
    | protocol            | HTTP                                           |
    | session_persistence |                                                |
    | tenant_id           | a9541f8689054dc681e0234fa4315950               |
    +---------------------+------------------------------------------------+

Add two instances to the pool as members, after the status of the load
balancer is 'ACTIVE'.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-member-create --subnet $subnet1_id --address $backend1_ip  --protocol-port 80 pool1

    +----------------+--------------------------------------+
    | Field          | Value                                |
    +----------------+--------------------------------------+
    | address        | 10.0.1.6                             |
    | admin_state_up | True                                 |
    | id             | d882e60a-f093-435b-bed1-c81a57862144 |
    | name           |                                      |
    | protocol_port  | 80                                   |
    | subnet_id      | 86587e20-dfb4-4192-a59a-d523d2c5f932 |
    | tenant_id      | 460439b4f4d846a4b505139f347a2358     |
    | weight         | 1                                    |
    +----------------+--------------------------------------+

    $ neutron --os-region-name=RegionOne lbaas-member-create --subnet $subnet1_id --address $backend2_ip  --protocol-port 80 pool1

    +----------------+--------------------------------------+
    | Field          | Value                                |
    +----------------+--------------------------------------+
    | address        | 10.0.1.7                             |
    | admin_state_up | True                                 |
    | id             | 12914f63-604f-43ed-be1c-76d35bbb2af7 |
    | name           |                                      |
    | protocol_port  | 80                                   |
    | subnet_id      | 86587e20-dfb4-4192-a59a-d523d2c5f932 |
    | tenant_id      | 460439b4f4d846a4b505139f347a2358     |
    | weight         | 1                                    |
    +----------------+--------------------------------------+

Verify load balancing. Request the VIP twice.

.. code-block:: console

    $ sudo ip netns exec dhcp-$net1_id curl -v $VIP

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.6
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.7
    * Closing connection 0

- 2 LBaaS members in one network but in different regions


List all available flavors in RegionTwo

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

List all available images in RegionTwo

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list

    +--------------------------------------+--------------------------+
    | ID                                   | Name                     |
    +--------------------------------------+--------------------------+
    | 488f77c4-5986-494e-958a-1007761339a4 | amphora-x64-haproxy      |
    | 211fc21c-aa07-4afe-b8a7-d82ce0e5f7b7 | cirros-0.3.5-x86_64-disk |
    +--------------------------------------+--------------------------+

Create an instance in RegionTwo, which resides in subnet1

.. code-block:: console

    $ nova --os-region-name=RegionTwo boot --flavor 1 --image $image_id --nic net-id=$net1_id backend3

    +--------------------------------------+-----------------------------------------------------------------+
    | Property                             | Value                                                           |
    +--------------------------------------+-----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                          |
    | OS-EXT-AZ:availability_zone          |                                                                 |
    | OS-EXT-SRV-ATTR:host                 | -                                                               |
    | OS-EXT-SRV-ATTR:hostname             | backend3                                                        |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                               |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                 |
    | OS-EXT-SRV-ATTR:kernel_id            |                                                                 |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                               |
    | OS-EXT-SRV-ATTR:ramdisk_id           |                                                                 |
    | OS-EXT-SRV-ATTR:reservation_id       | r-hct8v7fz                                                      |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
    | OS-EXT-SRV-ATTR:user_data            | -                                                               |
    | OS-EXT-STS:power_state               | 0                                                               |
    | OS-EXT-STS:task_state                | scheduling                                                      |
    | OS-EXT-STS:vm_state                  | building                                                        |
    | OS-SRV-USG:launched_at               | -                                                               |
    | OS-SRV-USG:terminated_at             | -                                                               |
    | accessIPv4                           |                                                                 |
    | accessIPv6                           |                                                                 |
    | adminPass                            | hL5rLbGGUZ2C                                                    |
    | config_drive                         |                                                                 |
    | created                              | 2017-09-18T12:46:07Z                                            |
    | description                          | -                                                               |
    | flavor:disk                          | 1                                                               |
    | flavor:ephemeral                     | 0                                                               |
    | flavor:extra_specs                   | {}                                                              |
    | flavor:original_name                 | m1.tiny                                                         |
    | flavor:ram                           | 512                                                             |
    | flavor:swap                          | 0                                                               |
    | flavor:vcpus                         | 1                                                               |
    | hostId                               |                                                                 |
    | host_status                          |                                                                 |
    | id                                   | 00428610-db5e-478f-88f0-ae29cc2e6898                            |
    | image                                | cirros-0.3.5-x86_64-disk (211fc21c-aa07-4afe-b8a7-d82ce0e5f7b7) |
    | key_name                             | -                                                               |
    | locked                               | False                                                           |
    | metadata                             | {}                                                              |
    | name                                 | backend3                                                        |
    | os-extended-volumes:volumes_attached | []                                                              |
    | progress                             | 0                                                               |
    | security_groups                      | default                                                         |
    | status                               | BUILD                                                           |
    | tags                                 | []                                                              |
    | tenant_id                            | a9541f8689054dc681e0234fa4315950                                |
    | updated                              | 2017-09-18T12:46:12Z                                            |
    | user_id                              | eab4a9d4da144e43bb1cacc8fad6f057                                |
    +--------------------------------------+-----------------------------------------------------------------+

Console in the instances with user 'cirros' and password of 'cubswin:)'.
Then run the following commands to simulate a web server.

.. code-block:: console

    $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
    $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

Add backend3 to the pool as a member, after the status of the load balancer is 'ACTIVE'.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-member-create --subnet $subnet1_id --address $backend3_ip --protocol-port 80 pool1

Verify load balancing. Request the VIP three times.

.. note:: Please note if the subnet is created in the region, just like the
   cases before this step, either unique name or id of the subnet can be
   used as hint. But if the subnet is not created yet, like the case for
   backend3, users are required to use subnet id as hint instead of subnet
   name. Because the subnet is not created in RegionOne, local neutron needs
   to query central neutron for the subnet with id.

.. code-block:: console

    $ sudo ip netns exec dhcp- curl -v $VIP

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.6
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.7
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.14
    * Closing connection 0

- 3 LBaaS across members in different networks and different regions

Create net2 in CentralRegion

.. code-block:: console

    $ neutron --os-region-name=CentralRegion net-create net2

    +---------------------------+--------------------------------------+
    | Field                     | Value                                |
    +---------------------------+--------------------------------------+
    | admin_state_up            | True                                 |
    | availability_zone_hints   |                                      |
    | id                        | d1664cb9-daf2-49f8-91a9-4fa9701a5845 |
    | name                      | net2                                 |
    | project_id                | a9541f8689054dc681e0234fa4315950     |
    | provider:network_type     | vxlan                                |
    | provider:physical_network |                                      |
    | provider:segmentation_id  | 1033                                 |
    | router:external           | False                                |
    | shared                    | False                                |
    | status                    | ACTIVE                               |
    | subnets                   |                                      |
    | tenant_id                 | a9541f8689054dc681e0234fa4315950     |
    +---------------------------+--------------------------------------+

Create a subnet in net2

.. code-block:: console

    $ neutron --os-region-name=CentralRegion subnet-create net2 10.0.2.0/24 --name subnet2 --no-gateway

    +-------------------+--------------------------------------------+
    | Field             | Value                                      |
    +-------------------+--------------------------------------------+
    | allocation_pools  | {"start": "10.0.2.2", "end": "10.0.2.254"} |
    | cidr              | 10.0.2.0/24                                |
    | created_at        | 2017-09-18T12:14:39Z                       |
    | description       |                                            |
    | dns_nameservers   |                                            |
    | enable_dhcp       | True                                       |
    | gateway_ip        |                                            |
    | host_routes       |                                            |
    | id                | cc1a74fd-5a41-4b30-9b6c-e241e8d912ef       |
    | ip_version        | 4                                          |
    | ipv6_address_mode |                                            |
    | ipv6_ra_mode      |                                            |
    | name              | subnet2                                    |
    | network_id        | d1664cb9-daf2-49f8-91a9-4fa9701a5845       |
    | project_id        | a9541f8689054dc681e0234fa4315950           |
    | revision_number   | 0                                          |
    | subnetpool_id     |                                            |
    | tags              |                                            |
    | tenant_id         | a9541f8689054dc681e0234fa4315950           |
    | updated_at        | 2017-09-18T12:14:39Z                       |
    +-------------------+--------------------------------------------+

List all available flavors in RegionTwo

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

List all available images in RegionTwo

.. code-block:: console

    $ glance --os-region-name=RegionTwo image-list

    +--------------------------------------+--------------------------+
    | ID                                   | Name                     |
    +--------------------------------------+--------------------------+
    | 488f77c4-5986-494e-958a-1007761339a4 | amphora-x64-haproxy      |
    | 211fc21c-aa07-4afe-b8a7-d82ce0e5f7b7 | cirros-0.3.5-x86_64-disk |
    +--------------------------------------+--------------------------+

Create an instance in RegionTwo, which resides in subnet2

.. code-block:: console

    $ nova --os-region-name=RegionTwo boot --flavor 1 --image $image_id --nic net-id=$net2_id backend4

    +--------------------------------------+-----------------------------------------------------------------+
    | Property                             | Value                                                           |
    +--------------------------------------+-----------------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                          |
    | OS-EXT-AZ:availability_zone          |                                                                 |
    | OS-EXT-SRV-ATTR:host                 | -                                                               |
    | OS-EXT-SRV-ATTR:hostname             | backend4                                                        |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                               |
    | OS-EXT-SRV-ATTR:instance_name        |                                                                 |
    | OS-EXT-SRV-ATTR:kernel_id            |                                                                 |
    | OS-EXT-SRV-ATTR:launch_index         | 0                                                               |
    | OS-EXT-SRV-ATTR:ramdisk_id           |                                                                 |
    | OS-EXT-SRV-ATTR:reservation_id       | r-rrdab98o                                                      |
    | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
    | OS-EXT-SRV-ATTR:user_data            | -                                                               |
    | OS-EXT-STS:power_state               | 0                                                               |
    | OS-EXT-STS:task_state                | scheduling                                                      |
    | OS-EXT-STS:vm_state                  | building                                                        |
    | OS-SRV-USG:launched_at               | -                                                               |
    | OS-SRV-USG:terminated_at             | -                                                               |
    | accessIPv4                           |                                                                 |
    | accessIPv6                           |                                                                 |
    | adminPass                            | iPGJ7eeSAfhf                                                    |
    | config_drive                         |                                                                 |
    | created                              | 2017-09-22T12:48:35Z                                            |
    | description                          | -                                                               |
    | flavor:disk                          | 1                                                               |
    | flavor:ephemeral                     | 0                                                               |
    | flavor:extra_specs                   | {}                                                              |
    | flavor:original_name                 | m1.tiny                                                         |
    | flavor:ram                           | 512                                                             |
    | flavor:swap                          | 0                                                               |
    | flavor:vcpus                         | 1                                                               |
    | hostId                               |                                                                 |
    | host_status                          |                                                                 |
    | id                                   | fd7d8ba5-fb37-44db-808e-6760a0683b2f                            |
    | image                                | cirros-0.3.5-x86_64-disk (211fc21c-aa07-4afe-b8a7-d82ce0e5f7b7) |
    | key_name                             | -                                                               |
    | locked                               | False                                                           |
    | metadata                             | {}                                                              |
    | name                                 | backend4                                                        |
    | os-extended-volumes:volumes_attached | []                                                              |
    | progress                             | 0                                                               |
    | security_groups                      | default                                                         |
    | status                               | BUILD                                                           |
    | tags                                 | []                                                              |
    | tenant_id                            | a9541f8689054dc681e0234fa4315950                                |
    | updated                              | 2017-09-22T12:48:41Z                                            |
    | user_id                              | eab4a9d4da144e43bb1cacc8fad6f057                                |
    +--------------------------------------+-----------------------------------------------------------------+

Console in the instances with user 'cirros' and password of 'cubswin:)'. Then run the following commands to simulate a web server.

.. code-block:: console

    $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
    $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

Add the instance to the pool as a member, after the status of the load balancer is 'ACTIVE'.

.. code-block:: console

    $ neutron --os-region-name=RegionOne lbaas-member-create --subnet $subnet2_id --address $backend4_ip --protocol-port 80 pool1

Verify load balancing. Request the VIP four times.

.. code-block:: console

    $ sudo ip netns exec dhcp- curl -v $VIP

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.6
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.7
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.1.14
    * Closing connection 0

    * Rebuilt URL to: 10.0.1.10/
    *   Trying 10.0.1.10...
    * Connected to 10.0.1.10 (10.0.1.10) port 80 (#0)
    > GET / HTTP/1.1
    > Host: 10.0.1.10
    > User-Agent: curl/7.47.0
    > Accept: */*
    >
    * HTTP 1.0, assume close after body
    < HTTP/1.0 200 OK
    <
    Welcome to 10.0.2.4
    * Closing connection 0