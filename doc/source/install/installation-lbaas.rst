=========================================
Installation guide for LBaaS in Tricircle
=========================================

.. note:: Since Octavia does not support multiple region scenarios, some
   modifications are required to install the Tricircle and Octavia in multiple
   pods. As a result, we will keep updating this document, so as to support
   automatic installation and test for Tricircle and Octavia in multiple regions.

Setup & Installation
^^^^^^^^^^^^^^^^^^^^

- 1 For the node1 in RegionOne, clone the code from Octavia repository to /opt/stack/ .
  Then make some changes to Octavia, so that we can build the management network in multiple regions manually. Here we give the following comment example.

  - First, comment the following lines in the **octavia_init** function in octavia/devstack/plugin.sh .

    `Line 586-588 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L586>`_

    - **build_mgmt_network**
    - **OCTAVIA_AMP_NETWORK_ID=$(openstack network show lb-mgmt-net -f value -c id)**
    - **iniset $OCTAVIA_CONF controller_worker amp_boot_network_list ${OCTAVIA_AMP_NETWORK_ID}**

    `Line 593-595 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L593>`_

    - **if is_service_enabled tempest; then**
    -     **configure_octavia_tempest ${OCTAVIA_AMP_NETWORK_ID}**
    - **fi**

    `Line 602-604 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L602>`_

    - **if is_service_enabled tempest; then**
    -     **configure_octavia_tempest ${OCTAVIA_AMP_NETWORK_ID}**
    - **fi**

    `Line 610 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L610>`_

    - **create_mgmt_network_interface**

    `Line 612 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L612>`_

    - **configure_lb_mgmt_sec_grp**

  - Second, comment the following three lines in the **octavia_start** function in octavia/devstack/plugin.sh .

    `Line 465-467 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L465>`_

    - **if  ! ps aux | grep -q [o]-hm0 && [ $OCTAVIA_NODE != 'api' ] ; then**
    -     **sudo dhclient -v o-hm0 -cf $OCTAVIA_DHCLIENT_CONF**
    - **fi**

- 2 Follow "Multi-pod Installation with DevStack" document `Multi-pod Installation with DevStack <https://docs.openstack.org/tricircle/latest/install/installation-guide.html#multi-pod-installation-with-devstack>`_
  to prepare your local.conf for the node1 in RegionOne, and add the
  following lines before installation. Start DevStack in node1.

    .. code-block:: console

        enable_plugin neutron-lbaas https://github.com/openstack/neutron-lbaas.git
        enable_plugin octavia https://github.com/openstack/octavia.git
        ENABLED_SERVICES+=,q-lbaasv2
        ENABLED_SERVICES+=,octavia,o-cw,o-hk,o-hm,o-api

- 3 If users only want to deploy Octavia in RegionOne, the following two
  steps can be skipped. After the DevStack installation in node1 is completed.
  For the node2 in RegionTwo, clone the code from Octavia repository to
  /opt/stack/. Here we need to modify plugin.sh in five sub-steps.

  - First, since Keystone is installed in RegionOne and shared by other
    regions, we need to comment all **add_load-balancer_roles** lines in
    the **octavia_init** function in octavia/devstack/plugin.sh .

    `Line 597 and Line 606 : <https://github.com/openstack/octavia/blob/master/devstack/plugin.sh#L597>`_

    - **add_load-balancer_roles**

  - Second, the same as Step 1, comment total fourteen lines of creating networking resources in the **octavia_init** function.

  - Third, replace all **'openstack keypair'** with
    **'openstack --os-region-name=$REGION_NAME keypair'**.

  - Fourth, replace all **'openstack image'** with
    **'openstack --os-region-name=$REGION_NAME image'**.

  - Fifth, replace all **'openstack flavor'** with
    **'openstack --os-region-name=$REGION_NAME flavor'**.

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

  - Create security group and rules for load balancer management network.

    .. code-block:: console

        $ openstack --os-region-name CentralRegion security group create lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol icmp lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 22 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 80 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 9443 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol icmpv6 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 22 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 80 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol tcp --dst-port 9443 --ethertype IPv6 --remote-ip ::/0 lb-mgmt-sec-grp

    .. note:: The output in the console is omitted.

  - Create security group and rules for healthy manager

    .. code-block:: console

        $ openstack --os-region-name CentralRegion security group create lb-health-mgr-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol udp --dst-port 5555 lb-health-mgr-sec-grp
        $ openstack --os-region-name CentralRegion security group rule create --protocol udp --dst-port 5555 --ethertype IPv6 --remote-ip ::/0 lb-health-mgr-sec-grp

    .. note:: The output in the console is omitted.

- 2 Configure LBaaS in node1

  - Create an amphora management network in CentralRegion

    .. code-block:: console

        $ openstack --os-region-name CentralRegion network create lb-mgmt-net1

        +---------------------------+--------------------------------------+
        | Field                     | Value                                |
        +---------------------------+--------------------------------------+
        | admin_state_up            | UP                                   |
        | availability_zone_hints   |                                      |
        | availability_zones        | None                                 |
        | created_at                | None                                 |
        | description               | None                                 |
        | dns_domain                | None                                 |
        | id                        | 9c3bd3f7-b581-4686-b35a-434b2fe5c1d5 |
        | ipv4_address_scope        | None                                 |
        | ipv6_address_scope        | None                                 |
        | is_default                | None                                 |
        | is_vlan_transparent       | None                                 |
        | location                  | None                                 |
        | mtu                       | None                                 |
        | name                      | lb-mgmt-net1                         |
        | port_security_enabled     | False                                |
        | project_id                | d3b83ed3f2504a8699c9528a2297fea7     |
        | provider:network_type     | vxlan                                |
        | provider:physical_network | None                                 |
        | provider:segmentation_id  | 1094                                 |
        | qos_policy_id             | None                                 |
        | revision_number           | None                                 |
        | router:external           | Internal                             |
        | segments                  | None                                 |
        | shared                    | False                                |
        | status                    | ACTIVE                               |
        | subnets                   |                                      |
        | tags                      |                                      |
        | updated_at                | None                                 |
        +---------------------------+--------------------------------------+

  - Create a subnet in lb-mgmt-net1

    .. code-block:: console

        $ openstack --os-region-name CentralRegion subnet create --subnet-range 192.168.10.0/24 --network lb-mgmt-net1 lb-mgmt-subnet1

        +-------------------+--------------------------------------+
        | Field             | Value                                |
        +-------------------+--------------------------------------+
        | allocation_pools  | 192.168.10.2-192.168.10.254          |
        | cidr              | 192.168.10.0/24                      |
        | created_at        | 2019-01-01T06:31:10Z                 |
        | description       |                                      |
        | dns_nameservers   |                                      |
        | enable_dhcp       | True                                 |
        | gateway_ip        | 192.168.10.1                         |
        | host_routes       |                                      |
        | id                | 84562c3a-55be-4c0f-9e50-3a5206670077 |
        | ip_version        | 4                                    |
        | ipv6_address_mode | None                                 |
        | ipv6_ra_mode      | None                                 |
        | location          | None                                 |
        | name              | lb-mgmt-subnet1                      |
        | network_id        | 9c3bd3f7-b581-4686-b35a-434b2fe5c1d5 |
        | project_id        | d3b83ed3f2504a8699c9528a2297fea7     |
        | revision_number   | 0                                    |
        | segment_id        | None                                 |
        | service_types     | None                                 |
        | subnetpool_id     | None                                 |
        | tags              |                                      |
        | updated_at        | 2019-01-01T06:31:10Z                 |
        +-------------------+--------------------------------------+

  - Create the health management interface for Octavia in RegionOne.

    .. code-block:: console

        $ id_and_mac=$(openstack --os-region-name CentralRegion port create --security-group lb-health-mgr-sec-grp --device-owner Octavia:health-mgr --network lb-mgmt-net1 octavia-health-manager-region-one-listen-port | awk '/ id | mac_address / {print $4}')
        $ id_and_mac=($id_and_mac)
        $ MGMT_PORT_ID=${id_and_mac[0]}
        $ MGMT_PORT_MAC=${id_and_mac[1]}
        $ MGMT_PORT_IP=$(openstack --os-region-name RegionOne port show -f value -c fixed_ips $MGMT_PORT_ID | awk '{FS=",| "; gsub(",",""); gsub("'\''",""); for(i = 1; i <= NF; ++i) {if ($i ~ /^ip_address/) {n=index($i, "="); if (substr($i, n+1) ~ "\\.") print substr($i, n+1)}}}')
        $ openstack --os-region-name RegionOne port set --host $(hostname)  $MGMT_PORT_ID
        $ sudo ovs-vsctl -- --may-exist add-port ${OVS_BRIDGE:-br-int} o-hm0 -- set Interface o-hm0 type=internal -- set Interface o-hm0 external-ids:iface-status=active -- set Interface o-hm0 external-ids:attached-mac=$MGMT_PORT_MAC -- set Interface o-hm0 external-ids:iface-id=$MGMT_PORT_ID -- set Interface o-hm0 external-ids:skip_cleanup=true
        $ OCTAVIA_DHCLIENT_CONF=/etc/octavia/dhcp/dhclient.conf
        $ sudo ip link set dev o-hm0 address $MGMT_PORT_MAC
        $ sudo dhclient -v o-hm0 -cf $OCTAVIA_DHCLIENT_CONF

        Listening on LPF/o-hm0/fa:16:3e:54:16:8e
        Sending on   LPF/o-hm0/fa:16:3e:54:16:8e
        Sending on   Socket/fallback
        DHCPDISCOVER on o-hm0 to 255.255.255.255 port 67 interval 3 (xid=0xd3e7353)
        DHCPREQUEST of 192.168.10.194 on o-hm0 to 255.255.255.255 port 67 (xid=0x53733e0d)
        DHCPOFFER of 192.168.10.194 from 192.168.10.2
        DHCPACK of 192.168.10.194 from 192.168.10.2
        bound to 192.168.10.194 -- renewal in 42514 seconds.

        $ sudo iptables -I INPUT -i o-hm0 -p udp --dport 5555 -j ACCEPT

    .. note:: As shown in the console, DHCP server allocates 192.168.10.194 as the
        IP of the health management interface, i.e., 0-hm. Hence, we need to
        modify the /etc/octavia/octavia.conf file to make Octavia aware of it and
        use the resources we just created, including health management interface,
        amphora security group and so on.

    .. csv-table::
        :header: "Option", "Description", "Example"

        [health_manager] bind_ip, "the ip of health manager in RegionOne", 192.168.10.194
        [health_manager] bind_port, "the port health manager listens on", 5555
        [health_manager] controller_ip_port_list, "the ip and port of health manager binds in RegionOne", 192.168.10.194:5555
        [controller_worker] amp_boot_network_list, "the id of amphora management network in RegionOne", "query neutron to obtain it, i.e., the id of lb-mgmt-net1 in this doc"
        [controller_worker] amp_secgroup_list, "the id of security group created for amphora in central region", "query neutron to obtain it, i.e., the id of lb-mgmt-sec-grp"
        [neutron] service_name, "The name of the neutron service in the keystone catalog", neutron
        [neutron] endpoint, "Central neutron endpoint if override is necessary", http://192.168.57.9:20001/
        [neutron] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", CentralRegion
        [neutron] endpoint_type, "Endpoint type", public
        [nova] service_name, "The name of the nova service in the keystone catalog", nova
        [nova] endpoint, "Custom nova endpoint if override is necessary", http://192.168.57.9/compute/v2.1
        [nova] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionOne
        [nova] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public
        [glance] service_name, "The name of the glance service in the keystone catalog", glance
        [glance] endpoint, "Custom glance endpoint if override is necessary", http://192.168.57.9/image
        [glance] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionOne
        [glance] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public

    Restart all the services of Octavia in node1.

    .. code-block:: console

        $ sudo systemctl restart devstack@o-*

- 2 If users only deploy Octavia in RegionOne, this step can be skipped.
  Configure LBaaS in node2.

  - Create an amphora management network in CentralRegion

    .. code-block:: console

        $ openstack --os-region-name CentralRegion network create lb-mgmt-net2

        +---------------------------+--------------------------------------+
        | Field                     | Value                                |
        +---------------------------+--------------------------------------+
        | admin_state_up            | UP                                   |
        | availability_zone_hints   |                                      |
        | availability_zones        | None                                 |
        | created_at                | None                                 |
        | description               | None                                 |
        | dns_domain                | None                                 |
        | id                        | 6494d887-25a8-4b07-8422-93f7acc21ecd |
        | ipv4_address_scope        | None                                 |
        | ipv6_address_scope        | None                                 |
        | is_default                | None                                 |
        | is_vlan_transparent       | None                                 |
        | location                  | None                                 |
        | mtu                       | None                                 |
        | name                      | lb-mgmt-net2                         |
        | port_security_enabled     | False                                |
        | project_id                | d3b83ed3f2504a8699c9528a2297fea7     |
        | provider:network_type     | vxlan                                |
        | provider:physical_network | None                                 |
        | provider:segmentation_id  | 1085                                 |
        | qos_policy_id             | None                                 |
        | revision_number           | None                                 |
        | router:external           | Internal                             |
        | segments                  | None                                 |
        | shared                    | False                                |
        | status                    | ACTIVE                               |
        | subnets                   |                                      |
        | tags                      |                                      |
        | updated_at                | None                                 |
        +---------------------------+--------------------------------------+

  - Create a subnet in lb-mgmt-net2

    .. code-block:: console

        $ openstack --os-region-name CentralRegion subnet create --subnet-range 192.168.20.0/24 --network lb-mgmt-net2 lb-mgmt-subnet2

        +-------------------+--------------------------------------+
        | Field             | Value                                |
        +-------------------+--------------------------------------+
        | allocation_pools  | 192.168.20.2-192.168.20.254          |
        | cidr              | 192.168.20.0/24                      |
        | created_at        | 2019-01-01T06:53:28Z                 |
        | description       |                                      |
        | dns_nameservers   |                                      |
        | enable_dhcp       | True                                 |
        | gateway_ip        | 192.168.20.1                         |
        | host_routes       |                                      |
        | id                | de2e9e76-e3c8-490f-b030-4374b22c2d95 |
        | ip_version        | 4                                    |
        | ipv6_address_mode | None                                 |
        | ipv6_ra_mode      | None                                 |
        | location          | None                                 |
        | name              | lb-mgmt-subnet2                      |
        | network_id        | 6494d887-25a8-4b07-8422-93f7acc21ecd |
        | project_id        | d3b83ed3f2504a8699c9528a2297fea7     |
        | revision_number   | 0                                    |
        | segment_id        | None                                 |
        | service_types     | None                                 |
        | subnetpool_id     | None                                 |
        | tags              |                                      |
        | updated_at        | 2019-01-01T06:53:28Z                 |
        +-------------------+--------------------------------------+

  - Create the health management interface for Octavia in RegionTwo.

    .. code-block:: console

        $ id_and_mac=$(openstack --os-region-name CentralRegion port create --security-group lb-health-mgr-sec-grp --device-owner Octavia:health-mgr --network lb-mgmt-net2 octavia-health-manager-region-two-listen-port | awk '/ id | mac_address / {print $4}')
        $ id_and_mac=($id_and_mac)
        $ MGMT_PORT_ID=${id_and_mac[0]}
        $ MGMT_PORT_MAC=${id_and_mac[1]}
        $ MGMT_PORT_IP=$(openstack --os-region-name RegionTwo port show -f value -c fixed_ips $MGMT_PORT_ID | awk '{FS=",| "; gsub(",",""); gsub("'\''",""); for(i = 1; i <= NF; ++i) {if ($i ~ /^ip_address/) {n=index($i, "="); if (substr($i, n+1) ~ "\\.") print substr($i, n+1)}}}')
        $ openstack --os-region-name RegionTwo port set --host $(hostname) $MGMT_PORT_ID
        $ sudo ovs-vsctl -- --may-exist add-port ${OVS_BRIDGE:-br-int} o-hm0 -- set Interface o-hm0 type=internal -- set Interface o-hm0 external-ids:iface-status=active -- set Interface o-hm0 external-ids:attached-mac=$MGMT_PORT_MAC -- set Interface o-hm0 external-ids:iface-id=$MGMT_PORT_ID -- set Interface o-hm0 external-ids:skip_cleanup=true
        $ OCTAVIA_DHCLIENT_CONF=/etc/octavia/dhcp/dhclient.conf
        $ sudo ip link set dev o-hm0 address $MGMT_PORT_MAC
        $ sudo dhclient -v o-hm0 -cf $OCTAVIA_DHCLIENT_CONF

        Listening on LPF/o-hm0/fa:16:3e:c0:bf:30
        Sending on   LPF/o-hm0/fa:16:3e:c0:bf:30
        Sending on   Socket/fallback
        DHCPDISCOVER on o-hm0 to 255.255.255.255 port 67 interval 3 (xid=0xad6d3a1a)
        DHCPREQUEST of 192.168.20.3 on o-hm0 to 255.255.255.255 port 67 (xid=0x1a3a6dad)
        DHCPOFFER of 192.168.20.3 from 192.168.20.2
        DHCPACK of 192.168.20.3 from 192.168.20.2
        bound to 192.168.20.3 -- renewal in 37208 seconds.

        $ sudo iptables -I INPUT -i o-hm0 -p udp --dport 5555 -j ACCEPT

    .. note:: The ip allocated by DHCP server, i.e., 192.168.20.3 in this case,
        is the bound and listened by health manager of Octavia. Please note that
        it will be used in the configuration file of Octavia.

    Modify the /etc/octavia/octavia.conf in node2.

    .. csv-table::
        :header: "Option", "Description", "Example"

        [health_manager] bind_ip, "the ip of health manager in RegionTwo", 192.168.20.3
        [health_manager] bind_port, "the port health manager listens on in RegionTwo", 5555
        [health_manager] controller_ip_port_list, "the ip and port of health manager binds in RegionTwo", 192.168.20.3:5555
        [controller_worker] amp_boot_network_list, "the id of amphora management network in RegionTwo", "query neutron to obtain it, i.e., the id of lb-mgmt-net2 in this doc"
        [controller_worker] amp_secgroup_list, "the id of security group created for amphora in central region", "query neutron to obtain it, i.e., the id of lb-mgmt-sec-grp"
        [neutron] service_name, "The name of the neutron service in the keystone catalog", neutron
        [neutron] endpoint, "Central neutron endpoint if override is necessary", http://192.168.57.9:20001/
        [neutron] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", CentralRegion
        [neutron] endpoint_type, "Endpoint type", public
        [nova] service_name, "The name of the nova service in the keystone catalog", nova
        [nova] endpoint, "Custom nova endpoint if override is necessary", http://192.168.57.10/compute/v2.1
        [nova] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionTwo
        [nova] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public
        [glance] service_name, "The name of the glance service in the keystone catalog", glance
        [glance] endpoint, "Custom glance endpoint if override is necessary", http://192.168.57.10/image
        [glance] region_name, "Region in Identity service catalog to use for communication with the OpenStack services", RegionTwo
        [glance] endpoint_type, "Endpoint type in Identity service catalog to use for communication with the OpenStack services", public

    Restart all the services of Octavia in node2.

    .. code-block:: console

        $ sudo systemctl restart devstack@o-*

  - By now, we finish installing LBaaS.

How to play
^^^^^^^^^^^

- 1 LBaaS members in one network and in same region

    Here we take VxLAN as an example.

  - Create net1 in CentralRegion

    .. code-block:: console

        $ openstack --os-region-name CentralRegion network create net1

        +---------------------------+--------------------------------------+
        | Field                     | Value                                |
        +---------------------------+--------------------------------------+
        | admin_state_up            | UP                                   |
        | availability_zone_hints   |                                      |
        | availability_zones        | None                                 |
        | created_at                | None                                 |
        | description               | None                                 |
        | dns_domain                | None                                 |
        | id                        | 9dcdcb56-358f-40b1-9e3f-6ed6bae6db7d |
        | ipv4_address_scope        | None                                 |
        | ipv6_address_scope        | None                                 |
        | is_default                | None                                 |
        | is_vlan_transparent       | None                                 |
        | location                  | None                                 |
        | mtu                       | None                                 |
        | name                      | net1                                 |
        | port_security_enabled     | False                                |
        | project_id                | d3b83ed3f2504a8699c9528a2297fea7     |
        | provider:network_type     | vxlan                                |
        | provider:physical_network | None                                 |
        | provider:segmentation_id  | 1102                                 |
        | qos_policy_id             | None                                 |
        | revision_number           | None                                 |
        | router:external           | Internal                             |
        | segments                  | None                                 |
        | shared                    | False                                |
        | status                    | ACTIVE                               |
        | subnets                   |                                      |
        | tags                      |                                      |
        | updated_at                | None                                 |
        +---------------------------+--------------------------------------+

  - Create a subnet in net1

    .. code-block:: console

        $ openstack --os-region-name CentralRegion subnet create --subnet-range 10.0.10.0/24 --gateway none --network net1 subnet1

        +-------------------+--------------------------------------+
        | Field             | Value                                |
        +-------------------+--------------------------------------+
        | allocation_pools  | 10.0.10.1-10.0.10.254                |
        | cidr              | 10.0.10.0/24                         |
        | created_at        | 2019-01-01T07:22:45Z                 |
        | description       |                                      |
        | dns_nameservers   |                                      |
        | enable_dhcp       | True                                 |
        | gateway_ip        | None                                 |
        | host_routes       |                                      |
        | id                | 39ccf811-b188-4ccf-a643-dd7669a413c2 |
        | ip_version        | 4                                    |
        | ipv6_address_mode | None                                 |
        | ipv6_ra_mode      | None                                 |
        | location          | None                                 |
        | name              | subnet1                              |
        | network_id        | 9dcdcb56-358f-40b1-9e3f-6ed6bae6db7d |
        | project_id        | d3b83ed3f2504a8699c9528a2297fea7     |
        | revision_number   | 0                                    |
        | segment_id        | None                                 |
        | service_types     | None                                 |
        | subnetpool_id     | None                                 |
        | tags              |                                      |
        | updated_at        | 2019-01-01T07:22:45Z                 |
        +-------------------+--------------------------------------+

    .. note:: To enable adding instances as members with VIP, amphora adds a
        new route table to route the traffic sent from VIP to its gateway. However,
        in Tricircle, the gateway obtained from central neutron is not the real
        gateway in local neutron. As a result, we did not set any gateway for
        the subnet temporarily. We will remove the limitation in the future.

  - List all available flavors in RegionOne

    .. code-block:: console

        $ openstack --os-region-name RegionOne flavor list

        +----+-----------+-------+------+-----------+-------+-----------+
        | ID | Name      |   RAM | Disk | Ephemeral | VCPUs | Is Public |
        +----+-----------+-------+------+-----------+-------+-----------+
        | 1  | m1.tiny   |   512 |    1 |         0 |     1 | True      |
        | 2  | m1.small  |  2048 |   20 |         0 |     1 | True      |
        | 3  | m1.medium |  4096 |   40 |         0 |     2 | True      |
        | 4  | m1.large  |  8192 |   80 |         0 |     4 | True      |
        | 42 | m1.nano   |    64 |    0 |         0 |     1 | True      |
        | 5  | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
        | 84 | m1.micro  |   128 |    0 |         0 |     1 | True      |
        | c1 | cirros256 |   256 |    0 |         0 |     1 | True      |
        | d1 | ds512M    |   512 |    5 |         0 |     1 | True      |
        | d2 | ds1G      |  1024 |   10 |         0 |     1 | True      |
        | d3 | ds2G      |  2048 |   10 |         0 |     2 | True      |
        | d4 | ds4G      |  4096 |   20 |         0 |     4 | True      |
        +----+-----------+-------+------+-----------+-------+-----------+

  - List all available images in RegionOne

    .. code-block:: console

        $ openstack --os-region-name RegionOne image list

        +--------------------------------------+--------------------------+--------+
        | ID                                   | Name                     | Status |
        +--------------------------------------+--------------------------+--------+
        | 471ed2cb-8004-4973-9210-b96463b2c668 | amphora-x64-haproxy      | active |
        | 85d165f0-bc7a-43d5-850b-4a8e89e57a66 | cirros-0.3.6-x86_64-disk | active |
        +--------------------------------------+--------------------------+--------+

  - Create two instances, i.e., backend1 and backend2, in RegionOne, which reside in subnet1.

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
        | OS-EXT-SRV-ATTR:reservation_id       | r-0m1suyvm                                                      |
        | OS-EXT-SRV-ATTR:root_device_name     | -                                                               |
        | OS-EXT-SRV-ATTR:user_data            | -                                                               |
        | OS-EXT-STS:power_state               | 0                                                               |
        | OS-EXT-STS:task_state                | scheduling                                                      |
        | OS-EXT-STS:vm_state                  | building                                                        |
        | OS-SRV-USG:launched_at               | -                                                               |
        | OS-SRV-USG:terminated_at             | -                                                               |
        | accessIPv4                           |                                                                 |
        | accessIPv6                           |                                                                 |
        | adminPass                            | 7poPJnDxV3Mz                                                    |
        | config_drive                         |                                                                 |
        | created                              | 2019-01-01T07:30:26Z                                            |
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
        | id                                   | d330f73f-2d78-4f59-8ea2-6fa1b878d6a5                            |
        | image                                | cirros-0.3.6-x86_64-disk (85d165f0-bc7a-43d5-850b-4a8e89e57a66) |
        | key_name                             | -                                                               |
        | locked                               | False                                                           |
        | metadata                             | {}                                                              |
        | name                                 | backend1                                                        |
        | os-extended-volumes:volumes_attached | []                                                              |
        | progress                             | 0                                                               |
        | security_groups                      | default                                                         |
        | status                               | BUILD                                                           |
        | tags                                 | []                                                              |
        | tenant_id                            | d3b83ed3f2504a8699c9528a2297fea7                                |
        | trusted_image_certificates           | -                                                               |
        | updated                              | 2019-01-01T07:30:27Z                                            |
        | user_id                              | fdf37c6259544a9294ae8463e9be063c                                |
        +--------------------------------------+-----------------------------------------------------------------+

        $ nova --os-region-name=RegionOne list

        +--------------------------------------+----------+--------+------------+-------------+------------------+
        | ID                                   | Name     | Status | Task State | Power State | Networks         |
        +--------------------------------------+----------+--------+------------+-------------+------------------+
        | d330f73f-2d78-4f59-8ea2-6fa1b878d6a5 | backend1 | ACTIVE | -          | Running     | net1=10.0.10.152 |
        | 72a4d0b0-88bc-41c5-9cb1-0965a5f3008f | backend2 | ACTIVE | -          | Running     | net1=10.0.10.176 |
        +--------------------------------------+----------+--------+------------+-------------+------------------+

  - Console in the instances with user 'cirros' and password of 'cubswin:)'.
    Then run the following commands to simulate a web server.

    .. note::

        If using cirros 0.4.0 and above, Console in the instances with user
        'cirros' and password of 'gocubsgo'.

    .. code-block:: console

        $ sudo ip netns exec dhcp-$net1_id ssh cirros@10.0.10.152
        $ sudo ip netns exec dhcp-$net1_id ssh cirros@10.0.10.176

        $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
        $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

    The Octavia installed in node1 and node2 are two standalone services,
    here we take RegionOne as an example.

  - Create a load balancer for subnet1 in RegionOne.

    .. code-block:: console

        $ openstack --os-region-name RegionOne loadbalancer create --name lb1 --vip-subnet-id $subnet1_id

        +---------------------+--------------------------------------+
        | Field               | Value                                |
        +---------------------+--------------------------------------+
        | admin_state_up      | True                                 |
        | created_at          | 2019-01-01T07:37:46                  |
        | description         |                                      |
        | flavor              |                                      |
        | id                  | bbb5480a-a6ec-4cea-a77d-4872a94aca5c |
        | listeners           |                                      |
        | name                | lb1                                  |
        | operating_status    | OFFLINE                              |
        | pools               |                                      |
        | project_id          | d3b83ed3f2504a8699c9528a2297fea7     |
        | provider            | amphora                              |
        | provisioning_status | PENDING_CREATE                       |
        | updated_at          | None                                 |
        | vip_address         | 10.0.10.189                          |
        | vip_network_id      | 9dcdcb56-358f-40b1-9e3f-6ed6bae6db7d |
        | vip_port_id         | 759370eb-5f50-4229-be7e-0ca7aefe04db |
        | vip_qos_policy_id   | None                                 |
        | vip_subnet_id       | 39ccf811-b188-4ccf-a643-dd7669a413c2 |
        +---------------------+--------------------------------------+

    Create a listener for the load balancer after the status of the load
    balancer is 'ACTIVE'. Please note that it may take some time for the
    load balancer to become 'ACTIVE'.

    .. code-block:: console

        $ openstack --os-region-name RegionOne loadbalancer list

        +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+
        | id                                   | name | project_id                       | vip_address | provisioning_status | provider |
        +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+
        | bbb5480a-a6ec-4cea-a77d-4872a94aca5c | lb1  | d3b83ed3f2504a8699c9528a2297fea7 | 10.0.10.189 | ACTIVE              | amphora  |
        +--------------------------------------+------+----------------------------------+-------------+---------------------+----------+

        $ openstack --os-region-name RegionOne loadbalancer listener create --protocol HTTP --protocol-port 80 --name listener1 lb1

        +---------------------------+--------------------------------------+
        | Field                     | Value                                |
        +---------------------------+--------------------------------------+
        | admin_state_up            | True                                 |
        | connection_limit          | -1                                   |
        | created_at                | 2019-01-01T07:44:21                  |
        | default_pool_id           | None                                 |
        | default_tls_container_ref | None                                 |
        | description               |                                      |
        | id                        | ec9d2e51-25ab-4c50-83cb-15f726d366ec |
        | insert_headers            | None                                 |
        | l7policies                |                                      |
        | loadbalancers             | bbb5480a-a6ec-4cea-a77d-4872a94aca5c |
        | name                      | listener1                            |
        | operating_status          | OFFLINE                              |
        | project_id                | d3b83ed3f2504a8699c9528a2297fea7     |
        | protocol                  | HTTP                                 |
        | protocol_port             | 80                                   |
        | provisioning_status       | PENDING_CREATE                       |
        | sni_container_refs        | []                                   |
        | timeout_client_data       | 50000                                |
        | timeout_member_connect    | 5000                                 |
        | timeout_member_data       | 50000                                |
        | timeout_tcp_inspect       | 0                                    |
        | updated_at                | None                                 |
        +---------------------------+--------------------------------------+

  - Create a pool for the listener after the status of the load balancer is 'ACTIVE'.

    .. code-block:: console

        $ openstack --os-region-name RegionOne loadbalancer pool create --lb-algorithm ROUND_ROBIN --listener listener1 --protocol HTTP --name pool1

        +---------------------+--------------------------------------+
        | Field               | Value                                |
        +---------------------+--------------------------------------+
        | admin_state_up      | True                                 |
        | created_at          | 2019-01-01T07:46:21                  |
        | description         |                                      |
        | healthmonitor_id    |                                      |
        | id                  | 7560b064-cdbe-4fa2-ae50-f66ad67fb575 |
        | lb_algorithm        | ROUND_ROBIN                          |
        | listeners           | ec9d2e51-25ab-4c50-83cb-15f726d366ec |
        | loadbalancers       | bbb5480a-a6ec-4cea-a77d-4872a94aca5c |
        | members             |                                      |
        | name                | pool1                                |
        | operating_status    | OFFLINE                              |
        | project_id          | d3b83ed3f2504a8699c9528a2297fea7     |
        | protocol            | HTTP                                 |
        | provisioning_status | PENDING_CREATE                       |
        | session_persistence | None                                 |
        | updated_at          | None                                 |
        +---------------------+--------------------------------------+

  - Add two instances to the pool as members, after the status of the load
    balancer is 'ACTIVE'.

    .. code-block:: console

        $  openstack --os-region-name RegionOne loadbalancer member create --subnet $subnet1_id --address $backend1_ip  --protocol-port 80 pool1

        +---------------------+--------------------------------------+
        | Field               | Value                                |
        +---------------------+--------------------------------------+
        | address             | 10.0.10.152                          |
        | admin_state_up      | True                                 |
        | created_at          | 2019-01-01T07:49:04                  |
        | id                  | 4e6ce567-0710-4a29-a98f-ab766e4963ab |
        | name                |                                      |
        | operating_status    | NO_MONITOR                           |
        | project_id          | d3b83ed3f2504a8699c9528a2297fea7     |
        | protocol_port       | 80                                   |
        | provisioning_status | PENDING_CREATE                       |
        | subnet_id           | 39ccf811-b188-4ccf-a643-dd7669a413c2 |
        | updated_at          | None                                 |
        | weight              | 1                                    |
        | monitor_port        | None                                 |
        | monitor_address     | None                                 |
        | backup              | False                                |
        +---------------------+--------------------------------------+

        $ openstack --os-region-name RegionOne loadbalancer member create --subnet $subnet1_id --address $backend2_ip  --protocol-port 80 pool1

        +---------------------+--------------------------------------+
        | Field               | Value                                |
        +---------------------+--------------------------------------+
        | address             | 10.0.10.176                          |
        | admin_state_up      | True                                 |
        | created_at          | 2019-01-01T07:50:06                  |
        | id                  | 1e8ab609-a7e9-44af-b37f-69b494b40d01 |
        | name                |                                      |
        | operating_status    | NO_MONITOR                           |
        | project_id          | d3b83ed3f2504a8699c9528a2297fea7     |
        | protocol_port       | 80                                   |
        | provisioning_status | PENDING_CREATE                       |
        | subnet_id           | 39ccf811-b188-4ccf-a643-dd7669a413c2 |
        | updated_at          | None                                 |
        | weight              | 1                                    |
        | monitor_port        | None                                 |
        | monitor_address     | None                                 |
        | backup              | False                                |
        +---------------------+--------------------------------------+

  - Verify load balancing. Request the VIP twice.

    .. code-block:: console

        $ sudo ip netns exec dhcp-$net1_id curl -v $VIP

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.152
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.176
        * Closing connection 0

- 2 LBaaS members in one network but in different regions

  - List all available flavors in RegionTwo

    .. code-block:: console

        $ openstack --os-region-name RegionTwo flavor list

        +----+-----------+-------+------+-----------+-------+-----------+
        | ID | Name      |   RAM | Disk | Ephemeral | VCPUs | Is Public |
        +----+-----------+-------+------+-----------+-------+-----------+
        | 1  | m1.tiny   |   512 |    1 |         0 |     1 | True      |
        | 2  | m1.small  |  2048 |   20 |         0 |     1 | True      |
        | 3  | m1.medium |  4096 |   40 |         0 |     2 | True      |
        | 4  | m1.large  |  8192 |   80 |         0 |     4 | True      |
        | 42 | m1.nano   |    64 |    0 |         0 |     1 | True      |
        | 5  | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
        | 84 | m1.micro  |   128 |    0 |         0 |     1 | True      |
        | c1 | cirros256 |   256 |    0 |         0 |     1 | True      |
        | d1 | ds512M    |   512 |    5 |         0 |     1 | True      |
        | d2 | ds1G      |  1024 |   10 |         0 |     1 | True      |
        | d3 | ds2G      |  2048 |   10 |         0 |     2 | True      |
        | d4 | ds4G      |  4096 |   20 |         0 |     4 | True      |
        +----+-----------+-------+------+-----------+-------+-----------+

  - List all available images in RegionTwo

    .. code-block:: console

        $ openstack --os-region-name RegionTwo image list

        +--------------------------------------+--------------------------+--------+
        | ID                                   | Name                     | Status |
        +--------------------------------------+--------------------------+--------+
        | 471ed2cb-8004-4973-9210-b96463b2c668 | amphora-x64-haproxy      | active |
        | 85d165f0-bc7a-43d5-850b-4a8e89e57a66 | cirros-0.3.6-x86_64-disk | active |
        +--------------------------------------+--------------------------+--------+

  - Create an instance in RegionTwo, which resides in subnet1

    .. code-block:: console

        $ nova --os-region-name=RegionTwo boot --flavor 1 --image $image_id --nic net-id=$net1_id backend3

        +-------------------------------------+-----------------------------------------------------------------+
        | Field                               | Value                                                           |
        +-------------------------------------+-----------------------------------------------------------------+
        | OS-DCF:diskConfig                   | MANUAL                                                          |
        | OS-EXT-AZ:availability_zone         | az2                                                             |
        | OS-EXT-SRV-ATTR:host                | None                                                            |
        | OS-EXT-SRV-ATTR:hypervisor_hostname | None                                                            |
        | OS-EXT-SRV-ATTR:instance_name       |                                                                 |
        | OS-EXT-STS:power_state              | NOSTATE                                                         |
        | OS-EXT-STS:task_state               | scheduling                                                      |
        | OS-EXT-STS:vm_state                 | building                                                        |
        | OS-SRV-USG:launched_at              | None                                                            |
        | OS-SRV-USG:terminated_at            | None                                                            |
        | accessIPv4                          |                                                                 |
        | accessIPv6                          |                                                                 |
        | addresses                           |                                                                 |
        | adminPass                           | rpV9MLzPGSvB                                                    |
        | config_drive                        |                                                                 |
        | created                             | 2019-01-01T07:56:41Z                                            |
        | flavor                              | m1.tiny (1)                                                     |
        | hostId                              |                                                                 |
        | id                                  | b27539fb-4c98-4f0c-b3f8-bc6744659f67                            |
        | image                               | cirros-0.3.6-x86_64-disk (85d165f0-bc7a-43d5-850b-4a8e89e57a66) |
        | key_name                            | None                                                            |
        | name                                | backend3                                                        |
        | progress                            | 0                                                               |
        | project_id                          | d3b83ed3f2504a8699c9528a2297fea7                                |
        | properties                          |                                                                 |
        | security_groups                     | name='default'                                                  |
        | status                              | BUILD                                                           |
        | updated                             | 2019-01-01T07:56:42Z                                            |
        | user_id                             | fdf37c6259544a9294ae8463e9be063c                                |
        | volumes_attached                    |                                                                 |
        +-------------------------------------+-----------------------------------------------------------------+

  - Console in the instances with user 'cirros' and password of 'cubswin:)'.
    Then run the following commands to simulate a web server.

    .. code-block:: console

        $ sudo ip netns exec dhcp-$net1_id ssh cirros@$backend3_ip

        $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
        $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

  - Add backend3 to the pool as a member, after the status of the load balancer is 'ACTIVE'.

    .. code-block:: console

        $ openstack --os-region-name RegionOne loadbalancer member create --subnet $subnet1_id --address $backend3_ip --protocol-port 80 pool1

  - Verify load balancing. Request the VIP three times.

    .. note:: Please note if the subnet is created in the region, just like the
        cases before this step, either unique name or id of the subnet can be
        used as hint. But if the subnet is not created yet, like the case for
        backend3, users are required to use subnet id as hint instead of subnet
        name. Because the subnet is not created in RegionOne, local neutron needs
        to query central neutron for the subnet with id.

    .. code-block:: console

        $ sudo ip netns exec dhcp- curl -v $VIP

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.152
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.176
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.186
        * Closing connection 0

- 3 LBaaS across members in different networks and different regions

  - Create net2 in CentralRegion

    .. code-block:: console

        $ openstack --os-region-name CentralRegion network create net2

        +---------------------------+--------------------------------------+
        | Field                     | Value                                |
        +---------------------------+--------------------------------------+
        | admin_state_up            | UP                                   |
        | availability_zone_hints   |                                      |
        | availability_zones        | None                                 |
        | created_at                | None                                 |
        | description               | None                                 |
        | dns_domain                | None                                 |
        | id                        | f0ea9608-2d6e-4272-a596-2dc3a725eddc |
        | ipv4_address_scope        | None                                 |
        | ipv6_address_scope        | None                                 |
        | is_default                | None                                 |
        | is_vlan_transparent       | None                                 |
        | location                  | None                                 |
        | mtu                       | None                                 |
        | name                      | net2                                 |
        | port_security_enabled     | False                                |
        | project_id                | d3b83ed3f2504a8699c9528a2297fea7     |
        | provider:network_type     | vxlan                                |
        | provider:physical_network | None                                 |
        | provider:segmentation_id  | 1088                                 |
        | qos_policy_id             | None                                 |
        | revision_number           | None                                 |
        | router:external           | Internal                             |
        | segments                  | None                                 |
        | shared                    | False                                |
        | status                    | ACTIVE                               |
        | subnets                   |                                      |
        | tags                      |                                      |
        | updated_at                | None                                 |
        +---------------------------+--------------------------------------+

  - Create a subnet in net2

    .. code-block:: console

        $ openstack --os-region-name CentralRegion subnet create --subnet-range 10.0.20.0/24 --gateway none --network net2 subnet2

        +-------------------+--------------------------------------+
        | Field             | Value                                |
        +-------------------+--------------------------------------+
        | allocation_pools  | 10.0.20.1-10.0.20.254                |
        | cidr              | 10.0.20.0/24                         |
        | created_at        | 2019-01-01T07:59:53Z                 |
        | description       |                                      |
        | dns_nameservers   |                                      |
        | enable_dhcp       | True                                 |
        | gateway_ip        | None                                 |
        | host_routes       |                                      |
        | id                | 4c05a73d-fa1c-46a9-982f-6683b0d1cb2a |
        | ip_version        | 4                                    |
        | ipv6_address_mode | None                                 |
        | ipv6_ra_mode      | None                                 |
        | location          | None                                 |
        | name              | subnet2                              |
        | network_id        | f0ea9608-2d6e-4272-a596-2dc3a725eddc |
        | project_id        | d3b83ed3f2504a8699c9528a2297fea7     |
        | revision_number   | 0                                    |
        | segment_id        | None                                 |
        | service_types     | None                                 |
        | subnetpool_id     | None                                 |
        | tags              |                                      |
        | updated_at        | 2019-01-01T07:59:53Z                 |
        +-------------------+--------------------------------------+

  - List all available flavors in RegionTwo

    .. code-block:: console

        $ openstack --os-region-name RegionTwo flavor list

        +----+-----------+-------+------+-----------+-------+-----------+
        | ID | Name      |   RAM | Disk | Ephemeral | VCPUs | Is Public |
        +----+-----------+-------+------+-----------+-------+-----------+
        | 1  | m1.tiny   |   512 |    1 |         0 |     1 | True      |
        | 2  | m1.small  |  2048 |   20 |         0 |     1 | True      |
        | 3  | m1.medium |  4096 |   40 |         0 |     2 | True      |
        | 4  | m1.large  |  8192 |   80 |         0 |     4 | True      |
        | 42 | m1.nano   |    64 |    0 |         0 |     1 | True      |
        | 5  | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
        | 84 | m1.micro  |   128 |    0 |         0 |     1 | True      |
        | c1 | cirros256 |   256 |    0 |         0 |     1 | True      |
        | d1 | ds512M    |   512 |    5 |         0 |     1 | True      |
        | d2 | ds1G      |  1024 |   10 |         0 |     1 | True      |
        | d3 | ds2G      |  2048 |   10 |         0 |     2 | True      |
        | d4 | ds4G      |  4096 |   20 |         0 |     4 | True      |
        +----+-----------+-------+------+-----------+-------+-----------+

  - List all available images in RegionTwo

    .. code-block:: console

        $ openstack --os-region-name RegionTwo image list

        +--------------------------------------+--------------------------+--------+
        | ID                                   | Name                     | Status |
        +--------------------------------------+--------------------------+--------+
        | 471ed2cb-8004-4973-9210-b96463b2c668 | amphora-x64-haproxy      | active |
        | 85d165f0-bc7a-43d5-850b-4a8e89e57a66 | cirros-0.3.6-x86_64-disk | active |
        +--------------------------------------+--------------------------+--------+

  - Create an instance in RegionTwo, which resides in subnet2

    .. code-block:: console

        $ nova --os-region-name=RegionTwo boot --flavor 1 --image $image_id --nic net-id=$net2_id backend4

        +-------------------------------------+-----------------------------------------------------------------+
        | Field                               | Value                                                           |
        +-------------------------------------+-----------------------------------------------------------------+
        | OS-DCF:diskConfig                   | MANUAL                                                          |
        | OS-EXT-AZ:availability_zone         | az2                                                             |
        | OS-EXT-SRV-ATTR:host                | None                                                            |
        | OS-EXT-SRV-ATTR:hypervisor_hostname | None                                                            |
        | OS-EXT-SRV-ATTR:instance_name       |                                                                 |
        | OS-EXT-STS:power_state              | NOSTATE                                                         |
        | OS-EXT-STS:task_state               | scheduling                                                      |
        | OS-EXT-STS:vm_state                 | building                                                        |
        | OS-SRV-USG:launched_at              | None                                                            |
        | OS-SRV-USG:terminated_at            | None                                                            |
        | accessIPv4                          |                                                                 |
        | accessIPv6                          |                                                                 |
        | addresses                           |                                                                 |
        | adminPass                           | jHY5xdqgxezb                                                    |
        | config_drive                        |                                                                 |
        | created                             | 2019-01-01T08:02:50Z                                            |
        | flavor                              | m1.tiny (1)                                                     |
        | hostId                              |                                                                 |
        | id                                  | 43bcdc80-6492-4a88-90dd-a979c73219a1                            |
        | image                               | cirros-0.3.6-x86_64-disk (85d165f0-bc7a-43d5-850b-4a8e89e57a66) |
        | key_name                            | None                                                            |
        | name                                | backend4                                                        |
        | progress                            | 0                                                               |
        | project_id                          | d3b83ed3f2504a8699c9528a2297fea7                                |
        | properties                          |                                                                 |
        | security_groups                     | name='default'                                                  |
        | status                              | BUILD                                                           |
        | updated                             | 2019-01-01T08:02:51Z                                            |
        | user_id                             | fdf37c6259544a9294ae8463e9be063c                                |
        | volumes_attached                    |                                                                 |
        +-------------------------------------+-----------------------------------------------------------------+

  - Console in the instances with user 'cirros' and password of 'cubswin:)'. Then run the following commands to simulate a web server.

    .. code-block:: console

        $ sudo ip netns exec dhcp-$net2_id ssh cirros@$backend4_ip

        $ MYIP=$(ifconfig eth0| grep 'inet addr'| awk -F: '{print $2}'| awk '{print $1}')
        $ while true; do echo -e "HTTP/1.0 200 OK\r\n\r\nWelcome to $MYIP" | sudo nc -l -p 80 ; done&

  - Add the instance to the pool as a member, after the status of the load balancer is 'ACTIVE'.

    .. code-block:: console

        $ openstack --os-region-name RegionOne loadbalancer member create --subnet $subnet2_id --address $backend4_ip --protocol-port 80 pool1

  - Verify load balancing. Request the VIP four times.

    .. code-block:: console

        $ sudo ip netns exec dhcp- curl -v $VIP

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.152
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.176
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.10.186
        * Closing connection 0

        * Rebuilt URL to: 10.0.10.189/
        *   Trying 10.0.10.189...
        * Connected to 10.0.10.189 (10.0.10.189) port 80 (#0)
        > GET / HTTP/1.1
        > Host: 10.0.10.189
        > User-Agent: curl/7.47.0
        > Accept: */*
        >
        * HTTP 1.0, assume close after body
        < HTTP/1.0 200 OK
        <
        Welcome to 10.0.20.64
        * Closing connection 0