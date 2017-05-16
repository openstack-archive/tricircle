====================
VLAN aware VMs Guide
====================

VLAN aware VM is a VM that sends and receives VLAN tagged frames over its vNIC.
The main point of that is to overcome the limitations of the current one vNIC
per network model. A VLAN (or other encapsulation) aware VM can differentiate
between traffic of many networks by different encapsulation types and IDs,
instead of using many vNICs. This approach scales to higher number of networks
and enables dynamic handling of network attachments (without hotplugging vNICs).

Installation
^^^^^^^^^^^^

No additional installation required, Please refer to the Tricircle
installation guide to install Tricircle then configure Neutron server to
enable trunk extension.

Configuration
^^^^^^^^^^^^^

- 1 Configure central Neutron server

  Edit neutron.conf, add the following configuration then restart central
  Neutron server

 .. csv-table::
    :header: "Option", "Description", "Example"

    [DEFAULT] service_plugins, "service plugin central Neutron server uses", tricircle.network.central_trunk_plugin. TricircleTrunkPlugin

- 2 Configure local Neutron server

  Edit neutron.conf, add the following configuration then restart local
  Neutron server

 .. csv-table::
    :header: "Option", "Description", "Example"

    [DEFAULT] service_plugins, "service plugin central Neutron server uses", trunk

How to play
^^^^^^^^^^^

- 1 Create pods via Tricircle Admin API

- 2 Create necessary resources in central Neutron server ::

    neutron --os-region-name=CentralRegion net-create --provider:network_type vlan net1
    neutron --os-region-name=CentralRegion subnet-create net1 10.0.1.0/24
    neutron --os-region-name=CentralRegion port-create net1 --name p1
    neutron --os-region-name=CentralRegion net-create --provider:network_type vlan net2
    neutron --os-region-name=CentralRegion subnet-create net2 10.0.2.0/24
    neutron --os-region-name=CentralRegion port-create net2 --name p2

  Please note that network type must be vlan, the port p1, p2 and net2's provider
  segmentation_id  will be used in later step to create trunk and boot vm.

- 3 Create trunk in central Neutron server ::

    openstack --os-region-name=CentralRegion network trunk create trunk1 --parent-port p1 --subport port=p2,segmentation-type=vlan,segmentation-id=$net2_segment_id

- 4 Get image ID and flavor ID which will be used in VM booting. In the following step,
  the trunk is to be used in the VM in RegionOne, you can replace RegionOne to other
  region's name if you want to boot VLAN aware VM in other region. ::

    glance --os-region-name=RegionOne image-list
    nova --os-region-name=RegionOne flavor-list

- 5 Boot virtual machines ::

    nova --os-region-name=RegionOne boot --flavor 1 --image $image1_id --nic port-id=$p1_id vm1

- 6 Show result on CentralRegion and RegionOne ::

    openstack --os-region-name=CentralRegion network trunk show trunk1
    openstack --os-region-name=RegionOne network trunk show trunk1

  The result will be the same, except for the trunk id.