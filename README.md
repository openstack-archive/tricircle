Tricircle
===============================

Tricircle is a project for [Openstack cascading solution](https://wiki.openstack.org/wiki/OpenStack_cascading_solution), including the source code of Nova Proxy, Cinder Proxy, Neutron L2/L3 Proxy, Glance sync manager and Ceilometer Proxy(not implemented yet).

The project name "Tricircle" comes from a fractal. See the blog ["OpenStack cascading and fractal"](https://www.linkedin.com/today/post/article/20140729022031-23841540-openstack-cascading-and-fractal) for more information.

Important to know
-----------
* Only about 15k code lines developed for OpenStack cascading.
* The source code now based on Juno is for PoC only. Refactory will be done constantly to reach OpenStack acceptance standard.
* The Neutron cascading using the feature of provider network. But horizon doen't support provider network very well. So you have to use Neutron CLI to create a network.
* Support L2 networking(VxLAN) across cascaded OpenStack, but only p2p remote host IP tunneling supported now.L2 networking through L2GW to reduce population traffic and simplify networking topology will be developed in the near future.
* The L3 networking across casacaded OpenStack will set up tunneling network for piggy data path, useing GRE tunneling over extra_route to brige the router in different cascaded OpenStack.Therefore, the loca L2 network (VLAN,VxLAN) in one cascaded OpenStack can reach L2 network(VLAN,VxLAN) located in another cascaded OpenStack.
* Glance cascading using Glance V2 API. Only CLI/pythonclient support V2 API, the Horizon doesn't support that version. So image management should be done through CLI, and using V2 only. Otherwise, the glance cascading cannot work properly.
* Glance cascading is not used by default, eg, useing global Glance by default. If Glance cascading is required, configuration is required.


Key modules
-----------

* Nova proxy

    The hypervisor driver for Nova running on Nova-Compute node. Transfer the VM operation to cascaded Nova. Also responsible for attach volume and network to the VM in the cascaded OpenStack.

* Cinder proxy

    The Cinder-Volume driver for Cinder running on Cinder-Volume node.. Transfer the volume operation to cascaded Cinder.

* Neuton proxy

    Including L2 proxy and L3 proxy, Similar role like OVS-Agent/L3-Agent. Finish L2/L3-networking in the cascaded OpenStack, including cross OpenStack networking.

* Glance sync

    Synchronize image among the cascading and policy determined Cascaded OpenStacks

Patches required
------------------

* Juno-Patches

    Pacthes for OpenStack Juno version, including patches for cascading level and cacscaded level.

Feature Supported
------------------

* Nova cascading
    Launch/Reboot/Terminate/Resize/Rescue/Pause/Un-pause/Suspend/Resume/VNC Console/Attach Volume/Detach Volume/Snapshot/KeyPair/Flavor

* Cinder cascading
    Create Volume/Delete Volume/Attach Volume/Detach Volume/Extend Volume/Create Snapshot/Delete Snapshot/List Snapshots/Create Volume from Snapshot/Create Volume from Image/Create Volume from Volume (Clone)/Create Image from Volume

* Neutron cascading
    Network/Subnet/Port/Router. Including L2/L3 networking across cascaded OpenStacks

* Glance cascading
    Only support V2 api. Create Image/Delete Image/List Image/Update Image/Upload Image/Patch Location/VM Snapshot/Image Synchronization

Known Issues
------------------
* Use "admin" role to experience these feature first, multi-tenancy has not been tested well.
* Launch VM only support "boot from image", "boot from volume", "boot from snapshot"
* Flavor only support new created flavor synchronized to the cascaded OpenStack, does not support flavor update synchronization to cascaded OpenStack yet.

Installation without Glance cascading
------------

* **Prerequisites**
    - the minimal installation requires three OpenStack Juno installated to experience across cascaded OpenStacks L2/L3 function. The minimal setup needs four nodes, see the following picture:

    ![minimal_setup](./minimal_setup.png?raw=true)

    - the cascading OpenStack needs two node, Node1 and Node 2. Add Node1 to AZ1, Node2 to AZ2 in the cascading OpenStack for both Nova and Cinder.

    - It's recommended to name the cascading Openstack region to "Cascading" or "Region1"

    - Node1 is all-in-one OpenStack installation with KeyStone and Glance, Node1 also function as Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent node, and will be replaced to be the proxy node for AZ1.

    - Node2 is general Nova-Compute node with Cinder-Volume, Neutron OVS-Agent/L3-Agent function installed. And will be replaced to be the proxy node for AZ2

    - the all-in-one cascaded OpenStack installed in Node3 function as the AZ1. Node3 will also function as the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent in order to be able to create VMs/Volume/Networking in this AZ1. Glance is only required to be installed if Glance cascading needed. Add Node3 to AZ1 in the cascaded OpenStack both for Nova and Cinder. It's recommended to name the cascaded Openstack region for Node3 to "AZ1"

    - the all-in-one cascaded OpenStack installed in Node4 function as the AZ2. Node3 will also function as the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent in order to be able to create VMs/Volume/Networking in this AZ2. Glance is only required to be installed if Glance cascading needed.Add Node4 to AZ2 in the cascaded OpenStack both for Nova and Cinder.It's recommended to name the cascaded Openstack region for Node4 to "AZ2"

    Make sure the time of these four nodes are synchronized. Because the Nova Proxy/Cinder Proxy/Neutron L2/L3 Proxy will query the cascaded OpenStack using timestamp, incorrect time will lead to VM/Volume/Port status synchronization not work properly.

    Register all services endpoint in the global shared KeyStone.

    Make sure the 3 OpenStack can work independently before cascading introduced, eg. you can boot VM with network, create volume and attach volume in each OpenStack. After verify that 3 OpenStack can work independently, clean all created resources VM/Volume/Network.

    After all OpenStack installation is ready, it's time to install Juno pathces both for cascading OpenStack and cascaded OpenStack, and then replace the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent to Nova Proxy / Cinder Proxy / Neutron l2/l3 Proxy.

* **Juno pachtes installation step by step**

1. Node1
  - Patches for Nova - instance_mapping_uuid_patch

    This patch is to make the Nova proxy being able to translate the cascading level VM's uuid to cascadede level VM's uuid

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/nova/instance_mapping_uuid_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Cinder - Volume/SnapShot/Backup UUID mapping patch

    This patch is to make the Cinder proxy being able to translate the cascading level (Volume/Snapshot/backup)'s uuid to cascaded level (Volume/Snapshot/backup)'s uuid

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/cinder/uuid-mapping-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - neutron_cascading_l3_patch

    This patch is to enable cross cascaded OpenStack L3 routing over extra route.The mapping between cascaded OpenStack and it's onlink external network which is used for GRE tunneling data path

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/neutron/neutron_cascading_l3_patch
    ```
    follow README.md instruction to install the patch

2. Node3
  - Patches for Cinder - timestamp-query-patch

    This patch is to make the cascaded Cinder being able to execute query with timestamp filter, but not to return all objects.

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/cinder/timestamp-query-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - neutron_cascaded_l3_patch

    This patch is to enable cross cascaded OpenStack L3 routing over extra route..

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/neutron/neutron_cascaded_l3_patch
    ```
    follow README.md instruction to install the patch

3. Node4
  - Patches for Cinder - timestamp-query-patch

    This patch is to make the cascaded Cinder being able to execute query with timestamp filter, but not to return all objects.

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/cinder/timestamp-query-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - neutron_cascaded_l3_patch

    This patch is to enable cross cascaded OpenStack L3 routing over extra route..

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/neutron/neutron_cascaded_l3_patch
    ```
    follow README.md instruction to install the patch

* **Proxy installation step by step**

1. Node1
  - Nova proxy

    Navigate to the  folder
    ```
    cd ./tricircle/novaproxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

  - Cinder proxy

    Navigate to the folder
    ```
    cd ./tricircle/cinderproxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

  - L2 proxy

    Navigate to the  folder
    ```
    cd ./tricircle/neutronproxy/l2-proxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

  - L3 proxy

    Navigate to the folder
    ```
    cd ./tricircle/neutronproxy/l3-proxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

2. Node2
  - Nova proxy

    Navigate to the  folder
    ```
    cd ./tricircle/novaproxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

    Navigate to the  folder
    ```
    cd ./tricircle/icehouse-patches/nova/instance_mapping_uuid_patch/nova/objects
    cp instance.py $python_installation_path/site-packages/nova/objects/
    ```
    This file is a patch for instance UUID mapping used in the proxy nodes.

  - Cinder proxy

    Navigate to the folder
    ```
    cd ./tricircle/cinderproxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

    Navigate to the  folder
    ```
    cd ./tricircle/icehouse-patches/cinder/uuid-mapping-patch/cinder/db/sqlalchemy
    cp models.py $python_installation_path/site-packages/cinder/db/sqlalchemy
    ```
    This file is a patch for instance UUID mapping used in the proxy nodes.


  - L2 proxy

    Navigate to the  folder
    ```
    cd ./tricircle/neutronproxy/l2-proxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting

  - L3 proxy

    Navigate to the folder
    ```
    cd ./tricircle/neutronproxy/l3-proxy
    ```
    follow README.md instruction to install the proxy. Please change the configuration value in the install.sh according to your environment setting


Upgrade to Glance cascading
------------

* **Prerequisites**
    - To experience the glance cascading feature, you can simply upgrade the current installation with several step, see the following picture:

    ![minimal_setup_with_glance_cascading](./minimal_setup_with_glance_cascading.png?raw=true)

1. Node1
  - Patches for Glance - glance_location_patch

    This patch is to make the glance being able to handle http url location. The patch also insert the sync manager to the chain of responsibility.

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/glance/glance_location_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Glance - glance_store_patch

    This patch is to make the glance being able to handle http url location.

    Navigate to the folder
    ```
    cd ./tricircle/juno-patches/glance_store/glance_store_patch
    ```
    follow README.md instruction to install the patch

  - Sync Manager

    Navigate to the  folder
    ```
    cd ./tricircle/glancesync
    ```

    modify the storage scheme configuration for cascading and cascaded level
    ```
    vi ./tricircle/glancesync/etc/glance/glance_store.yaml
    ```

    follow README.md instruction to install the sync manager. Please change the configuration value in the install.sh according to your environment setting, espeically for configuration:
    sync_enabled=True
    sync_server_port=9595
    sync_server_host=127.0.0.1

2. Node3
  - Glance Installation

    Please install Glance in the Node3 as the casacded Glance.
    Register the service endpoint in the KeyStone.
    Change the glance endpoint in nova.conf and cinder.conf to the Glance located in Node3

3. Node4
  - Glance Installation

    Please install Glance in the Node4 as the casacded Glance.
    Register the service endpoint in the KeyStone
    Change the glance endpoint in nova.conf and cinder.conf to the Glance located in Node4

4. Configuration
  - Change Nova proxy configuration on Node1, setting the "cascaded_glance_flag" to True and add "cascaded_glance_url" of Node3 configurantion according to Nova-proxy README.MD instruction
  - Change Cinder proxy configuration on Node1, setting the "glance_cascading_flag" to True and add "cascaded_glance_url" of Node3 configurantion according to Nova-proxy README.MD instruction

  - Change Nova proxy configuration on Node2, setting the "cascaded_glance_flag" to True and add "cascaded_glance_url" of Node4 configurantion according to Nova-proxy README.MD instruction
  - Change Cinder proxy configuration on Node2, setting the "glance_cascading_flag" to True and add "cascaded_glance_url" of Node4 configurantion according to Nova-proxy README.MD instruction

5. Experience Glance cascading
  - Restart all related service
  - Use Glance V2 api to create Image, Upload Image or patch location for Image. Image should be able to sync to distributed Glance if sync_enabled is setting to True
  - Sync image only during first time usage but not uploading or patch location is still in testing phase, may not work properly.
  - Create VM/Volume/etc from Horizon
