=====================================
Single pod installation with DevStack
=====================================

Now the Tricircle can be played with all-in-one single pod DevStack. For
the resource requirement to setup single pod DevStack, please refer
to `All-In-One Single Machine <http://docs.openstack.org/developer/devstack/guides/single-machine.html>`_ for
installing DevStack in bare metal server
or `All-In-One Single VM <http://docs.openstack.org/developer/devstack/guides/single-vm.html>`_ for
installing DevStack in virtual machine.

- 1 Install DevStack. Please refer to `DevStack document
  <http://docs.openstack.org/developer/devstack/>`_
  on how to install DevStack into single VM or bare metal server.

- 2 In DevStack folder, create a file local.conf, and copy the content of
  https://github.com/openstack/tricircle/blob/master/devstack/local.conf.sample
  to local.conf, change password in the file if needed.

- 3 Run DevStack. In DevStack folder, run::

    ./stack.sh

- 4 After DevStack successfully starts, we need to create environment variables for
  the user (admin user as example in this document). In DevStack folder::

      source openrc admin admin

- 5 Unset the region name environment variable, so that the command can be issued to
  specified region in following commands as needed::

      unset OS_REGION_NAME

- 6 Check if services have been correctly registered. Run::

      openstack --os-region-name=RegionOne endpoint list

  you should get output looks like as following::

        +----------------------------------+---------------+--------------+----------------+
        | ID                               | Region        | Service Name | Service Type   |
        +----------------------------------+---------------+--------------+----------------+
        | 3944592550764e349d0e82dba19a8e64 | RegionOne     | cinder       | volume         |
        | 2ce48c73cca44e66a558ad69f1aa4436 | CentralRegion | tricircle    | Tricircle      |
        | d214b688923a4348b908525266db66ed | RegionOne     | nova_legacy  | compute_legacy |
        | c5dd60f23f2e4442865f601758a73982 | RegionOne     | keystone     | identity       |
        | a99d5742c76a4069bb8621e0303c6004 | RegionOne     | cinderv3     | volumev3       |
        | 8a3c711a24b2443a9a4420bcc302ed2c | RegionOne     | glance       | image          |
        | e136af00d64a4cdf8b6b367210476f49 | RegionOne     | nova         | compute        |
        | 4c3e5d52a90e493ab720213199ab22cd | RegionOne     | neutron      | network        |
        | 8a1312afb6944492b47c5a35f1e5caeb | RegionOne     | cinderv2     | volumev2       |
        | e0a5530abff749e1853a342b5747492e | CentralRegion | neutron      | network        |
        +----------------------------------+---------------+--------------+----------------+

  "CentralRegion" is the region you set in local.conf via CENTRAL_REGION_NAME,
  whose default value is "CentralRegion", we use it as the region for the
  central Neutron server and Tricircle Admin API(ID is
  2ce48c73cca44e66a558ad69f1aa4436 in the above list).
  "RegionOne" is the normal OpenStack region which includes Nova, Cinder,
  Neutron.

- 7 Get token for the later commands. Run::

      openstack --os-region-name=RegionOne token issue

- 8 Create pod instances for the Tricircle to manage the mapping between
  availability zone and OpenStack instances, the "$token" is obtained in the
  step 7::

      curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
          -H "X-Auth-Token: $token" -d '{"pod": {"region_name":  "CentralRegion"}}'

      curl -X POST http://127.0.0.1:19999/v1.0/pods -H "Content-Type: application/json" \
          -H "X-Auth-Token: $token" -d '{"pod": {"region_name":  "RegionOne", "az_name": "az1"}}'

  Pay attention to "region_name" parameter we specify when creating pod. Pod name
  should exactly match the region name registered in Keystone. In the above
  commands, we create pods named "CentralRegion" and "RegionOne".

- 9 Create necessary resources in central Neutron server::

     neutron --os-region-name=CentralRegion net-create net1
     neutron --os-region-name=CentralRegion subnet-create net1 10.0.0.0/24

  Please note that the net1 ID will be used in later step to boot VM.

- 10 Get image ID and flavor ID which will be used in VM booting::

     glance --os-region-name=RegionOne image-list
     nova --os-region-name=RegionOne flavor-list

- 11 Boot a virtual machine::

     nova --os-region-name=RegionOne boot --flavor 1 --image $image_id --nic net-id=$net_id vm1

- 12 Verify the VM is connected to the net1::

     neutron --os-region-name=CentralRegion port-list
     neutron --os-region-name=RegionOne port-list
     nova --os-region-name=RegionOne list

  The IP address of the VM could be found in local Neutron server and central
  Neutron server. The port has same uuid in local Neutron server and central
  Neutron Server.
