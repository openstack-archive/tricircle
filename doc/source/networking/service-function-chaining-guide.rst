===============================
Service Function Chaining Guide
===============================

Service Function Chaining provides the ability to define an ordered list of
network services (e.g. firewalls, load balancers). These services are then
“stitched” together in the network to create a service chain.


Installation
^^^^^^^^^^^^

After installing tricircle, please refer to
https://docs.openstack.org/developer/networking-sfc/installation.html
to install networking-sfc.

Configuration
^^^^^^^^^^^^^

- 1 Configure central Neutron server

  After installing the Tricircle and networing-sfc, enable the service plugins
  in central Neutron server by adding them in ``neutron.conf.0``
  (typically found in ``/etc/neutron/``)::

    service_plugins=networking_sfc.services.flowclassifier.plugin.FlowClassifierPlugin,tricircle.network.central_sfc_plugin.TricircleSfcPlugin

  In the same configuration file, specify the driver to use in the plugins. ::

    [sfc]
    drivers = tricircle_sfc

    [flowclassifier]
    drivers = tricircle_fc

- 2 Configure local Neutron

  Please refer to https://docs.openstack.org/developer/networking-sfc/installation.html#Configuration
  to config local networking-sfc.


How to play
^^^^^^^^^^^

- 1 Create pods via Tricircle Admin API

- 2 Create necessary resources in central Neutron server ::

    neutron --os-region-name=CentralRegion net-create --provider:network_type vxlan net1
    neutron --os-region-name=CentralRegion subnet-create net1 10.0.0.0/24
    neutron --os-region-name=CentralRegion port-create net1 --name p1
    neutron --os-region-name=CentralRegion port-create net1 --name p2
    neutron --os-region-name=CentralRegion port-create net1 --name p3
    neutron --os-region-name=CentralRegion port-create net1 --name p4
    neutron --os-region-name=CentralRegion port-create net1 --name p5
    neutron --os-region-name=CentralRegion port-create net1 --name p6

  Please note that network type must be vxlan.

- 3 Get image ID and flavor ID which will be used in VM booting. In the following step,
  the VM will boot from RegionOne and RegionTwo. ::

    glance --os-region-name=RegionOne image-list
    nova --os-region-name=RegionOne flavor-list
    glance --os-region-name=RegionTwo image-list
    nova --os-region-name=RegionTwo flavor-list

- 4 Boot virtual machines ::

    openstack --os-region-name=RegionOne server create --flavor 1 --image $image1_id --nic port-id=$p1_id vm_src
    openstack --os-region-name=RegionOne server create --flavor 1 --image $image1_id --nic port-id=$p2_id --nic port-id=$p3_id vm_sfc1
    openstack --os-region-name=RegionTwo server create --flavor 1 --image $image2_id --nic port-id=$p4_id --nic port-id=$p5_id vm_sfc2
    openstack --os-region-name=RegionTwo server create --flavor 1 --image $image2_id --nic port-id=$p6_id vm_dst

- 5 Create port pairs in central Neutron server ::

    neutron --os-region-name=CentralRegion port-pair-create --ingress p2 --egress p3 pp1
    neutron --os-region-name=CentralRegion port-pair-create --ingress p4 --egress p5 pp2

- 6 Create port pair groups in central Neutron server ::

    neutron --os-region-name=CentralRegion port-pair-group-create --port-pair pp1 ppg1
    neutron --os-region-name=CentralRegion port-pair-group-create --port-pair pp2 ppg2

- 7 Create flow classifier in central Neutron server ::

    neutron --os-region-name=CentralRegion flow-classifier-create --source-ip-prefix 10.0.0.0/24 --logical-source-port p1 fc1

- 8 Create port chain in central Neutron server ::

    neutron --os-region-name=CentralRegion port-chain-create --flow-classifier fc1 --port-pair-group ppg1 --port-pair-group ppg2 pc1

- 9 Show result in CentralRegion, RegionOne and RegionTwo ::

    neutron --os-region-name=CentralRegion port-chain-list
    neutron --os-region-name=RegionOne port-chain-list
    neutron --os-region-name=RegionTwo port-chain-list

  You will find a same port chain in each region.

- 10 Check if the port chain is working

  In vm_dst, ping the p1's ip address, it should fail.

  Enable vm_sfc1, vm_sfc2's forwarding function ::

    sudo sh
    echo 1 > /proc/sys/net/ipv4/ip_forward

  Add the following route for vm_sfc1, vm_sfc2 ::

    sudo ip route add $p6_ip_address dev eth1

  In vm_dst, ping the p1's ip address, it should be successfully this time.

  .. note:: Not all images will bring up the second NIC, so you can ssh into vm, use
     "ifconfig -a" to check whether all NICs are up, and bring up all NICs if necessary.
     In CirrOS you can type the following command to bring up one NIC. ::

       sudo cirros-dhcpc up $nic_name
