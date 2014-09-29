Tricircle
===============================

Tricircle is a project for [Openstack cascading solution](https://wiki.openstack.org/wiki/OpenStack_cascading_solution), including the source code of Nova Proxy, Cinder Proxy, Neutron L2/L3 Proxy, Glance sync manager and Ceilometer Proxy(not implemented yet).

The project name "Tricircle" comes from a fractal. See the blog ["OpenStack cascading and fractal"](https://www.linkedin.com/today/post/article/20140729022031-23841540-openstack-cascading-and-fractal) for more information.

Important to know
-----------
* Only about 15k code lines developed for OpenStack cascading.
* The initial source code is for PoC only. Refactory will be done constantly to reach OpenStack acceptance standard.
* DVR-Patch for IceHouse: the PoC source code is based on IceHouse version, while Neutron is a master branch snapshot on July 1, 2014 which include DVR feature, not IceHouse version. The Neutron code is download from github when it was still in the developement and review status. The source code of DVR part is not stable, and not all DVR features are included, for example, N-S functions not ready.
* DVR-Patch is the majority source code in the repository, about 180k. The patch will be remove if OpenStack cascading is developed base on Juno.
* The Neutron cascading using the feature of provider network. But horizon doen't support provider network very well. So you have to use Neutron CLI to create a network. Or set default provide network type to VxLAN, or remove "local", "flat", "VLAN", "GRE" network typedriver from ML2 plugin configuration.
* For Neutron L2/L3 features, only VxLAN/L3 across casacaded OpenStack supported in the current source code. VLAN2VLAN, VLAN2VxLAN and VxLAN2VxLAN across cascaded OpenStack also implemented with IceHouse version but the patch is not ready yet, source code is in the VLAN2VLAN folder.
* The tunneling network for cross OpenStack piggy data path is using VxLAN, it leads to modification on L2 agent and L3 agent, we will refactory it to using GRE for the tunneling network to reduce patch for Juno version.
* If you want to experience VLAN2VLAN, VLAN2VxLAN and VxLAN2VxLAN across cascaded OpenStack, please ask help from PoC team member, see the wiki page [Openstack cascading solution](https://wiki.openstack.org/wiki/OpenStack_cascading_solution) for contact information.
* Glance cascading using Glance V2 API. Only CLI/pythonclient support V2 API, the Horizon doesn't support that version. So image management should be done through CLI, and using V2 only. Otherwise, the glance cascading cannot work properly.
* Glance cascading is not used by default, eg, useing global Glance by default. If Glance cascading is required, configuration is required.
* Refactory the Tricircle source code based on Juno version will be started soon once the Juno version is available.


Key modules
-----------

* Nova proxy

    Similar role like Nova-Compute. Transfer the VM operation to cascaded Nova. Also responsible for attach volume and network to the VM in the cascaded OpenStack.

* Cinder proxy

    Similar role like Cinder-Volume. Transfer the volume operation to cascaded Cinder.

* Neuton proxy

    Including L2 proxy and L3 proxy, Similar role like OVS-Agent/L3-Agent. Finish L2/L3-networking in the cascaded OpenStack, including cross OpenStack networking.

* Glance sync

    Synchronize image among the cascading and policy determined Cascaded OpenStacks

Patches required
------------------

* IceHouse-Patches

    Pacthes for OpenStack IceHouse version, including patches for cascading level and cacscaded level.

Feature Supported
------------------

* Nova cascading
    Launch/Reboot/Terminate/Resize/Rescue/Pause/Un-pause/Suspend/Resume/VNC Console/Attach Volume/Detach Volume/Snapshot/KeyPair/Flavor

* Cinder cascading
    Create Volume/Delete Volume/Attach Volume/Detach Volume/Extend Volume/Create Snapshot/Delete Snapshot/List Snapshots/Create Volume from Snapshot/Create Volume from Image/Create Volume from Volume (Clone)/Create Image from Volume

* Neutron cascading
    Network/Subnet/Port/Router

* Glance cascading
    Only support V2 api. Create Image/Delete Image/List Image/Update Image/Upload Image/Patch Location/VM Snapshot/Image Synchronization

Known Issues
------------------
* Use "admin" role to experience these feature first, multi-tenancy has not been tested well.
* Launch VM only support "boot from image", "boot from volume", "boot from snapshot"
* Flavor only support new created flavor synchronized to the cascaded OpenStack, does not support flavor update synchronization to cascaded OpenStack yet.
* Must make a patch for "Create a volume from image", the patch link: https://bugs.launchpad.net/cinder/+bug/1308058

Installation without Glance cascading
------------

* **Prerequisites**
    - the minimal installation requires three OpenStack IceHouse installated to experience across cascaded OpenStacks L2/L3 function. The minimal setup needs four nodes, see the following picture:

    ![minimal_setup](./minimal_setup.png?raw=true)

    - the cascading OpenStack needs two node, Node1 and Node 2. Add Node1 to AZ1, Node2 to AZ2 in the cascading OpenStack for both Nova and Cinder.

    - It's recommended to name the cascading Openstack region to "Cascading_OpenStack" or "Region1"

    - Node1 is all-in-one OpenStack installation with KeyStone and Glance, Node1 also function as Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent node, and will be replaced to be the proxy node for AZ1.

    - Node2 is general Nova-Compute node with Cinder-Volume, Neutron OVS-Agent/L3-Agent function installed. And will be replaced to be the proxy node for AZ2

    - the all-in-one cascaded OpenStack installed in Node3 function as the AZ1. Node3 will also function as the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent in order to be able to create VMs/Volume/Networking in this AZ1. Glance is only required to be installed if Glance cascading needed. Add Node3 to AZ1 in the cascaded OpenStack both for Nova and Cinder. It's recommended to name the cascaded Openstack region for Node3 to "AZ1"

    - the all-in-one cascaded OpenStack installed in Node4 function as the AZ2. Node3 will also function as the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent in order to be able to create VMs/Volume/Networking in this AZ2. Glance is only required to be installed if Glance cascading needed.Add Node4 to AZ2 in the cascaded OpenStack both for Nova and Cinder.It's recommended to name the cascaded Openstack region for Node4 to "AZ2"

    Make sure the time of these four nodes are synchronized. Because the Nova Proxy/Cinder Proxy/Neutron L2/L3 Proxy will query the cascaded OpenStack using timestamp, incorrect time will lead to VM/Volume/Port status synchronization not work properly.

    Register all services endpoint in the global shared KeyStone.

    Make sure the 3 OpenStack can work independently before cascading introduced, eg. you can boot VM with network, create volume and attach volume in each OpenStack. After verify that 3 OpenStack can work independently, clean all created resources VM/Volume/Network.

    After all OpenStack installation is ready, it's time to install IceHouse pathces both for cascading OpenStack and cascaded OpenStack, and then replace the Nova-Compute/Cinder-Volume/Neutron OVS-Agent/L3-Agent to Nova Proxy / Cinder Proxy / Neutron l2/l3 Proxy.

* **IceHouse pachtes installation step by step**

1. Node1
  - Patches for Nova - instance_mapping_uuid_patch

    This patch is to make the Nova proxy being able to translate the cascading level VM's uuid to cascadede level VM's uuid

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/nova/instance_mapping_uuid_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Cinder - Volume/SnapShot/Backup UUID mapping patch

    This patch is to make the Cinder proxy being able to translate the cascading level (Volume/Snapshot/backup)'s uuid to cascadede level (Volume/Snapshot/backup)'s uuid

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/cinder/instance_mapping_uuid_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - DVR patch

    This patch is to make the Neutron has the DVR(distributed virtual router) feature. Through DVR, all L2/L3 proxy nodes in the cascading level can receive correspoding RPC message, and then convert the command to restful API to cascaded Neutron.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/dvr-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - ml2-mech-driver-cascading patch

    This patch is to make L2 population driver being able to populate the VM's host IP which stored in the port binding profile in the cascaded OpenStack to another cascaded OpenStack.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/ml2-mech-driver-cascading-patch
    ```
    follow README.md instruction to install the patch

2. Node3
  - Patches for Nova - port binding profile update bug: https://bugs.launchpad.net/neutron/+bug/1338202.

    because ml2-mech-driver-cascaded-patch will update the binding profile in the port, and will be flushed to null if you don't fix the bug.

    You can also fix the bug via:

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/icehouse-patches/nova/instance_mapping_uuid_patch/nova/network/neutronv2/
    cp api.py $python_installation_path/site-packages/nova/network/neutronv2/

    ```
    the patch will reserve what has been saved in the port binding profile

  - Patches for Cinder - timestamp-query-patch patch

    This patch is to make the cascaded Cinder being able to execute query with timestamp filter, but not to return all objects.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/cinder/timestamp-query-patch_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - DVR patch

    This patch is to make the Neutron has the DVR(distributed virtual router) feature.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/dvr-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - ml2-mech-driver-cascaded patch

    This patch is to make L2 population driver being able to populate the virtual remote port where the VM located in another OpenStack.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/ml2-mech-driver-cascaded-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - openvswitch-agent patch

    This patch is to get dvr mac crossing openstack for cross OpenStack L3 networking for VLAN-VLAN/VLAN-VxLAN/VxLAN-VxLAN.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/openvswitch-agent-patch
    ```
    follow README.md instruction to install the patch

3. Node4
  - Patches for Nova - port binding profile update bug: https://bugs.launchpad.net/neutron/+bug/1338202.

    because ml2-mech-driver-cascaded-patch will update the binding profile in the port, and will be flushed to null if you don't fix the bug.

    You can also fix the bug via:

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/icehouse-patches/nova/instance_mapping_uuid_patch/nova/network/neutronv2/
    cp api.py $python_installation_path/site-packages/nova/network/neutronv2/

    ```
    the patch will reserve what has been saved in the port binding profile

  - Patches for Cinder - timestamp-query-patch patch

    This patch is to make the cascaded Cinder being able to execute query with timestamp filter, but not to return all objects.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/cinder/timestamp-query-patch_patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - DVR patch

    This patch is to make the Neutron has the DVR(distributed virtual router) feature.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/dvr-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - ml2-mech-driver-cascaded patch

    This patch is to make L2 population driver being able to populate the virtual remote port where the VM located in another OpenStack.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/ml2-mech-driver-cascaded-patch
    ```
    follow README.md instruction to install the patch

  - Patches for Neutron - openvswitch-agent patch

    This patch is to get dvr mac crossing openstack for cross OpenStack L3 networking for VLAN-VLAN/VLAN-VxLAN/VxLAN-VxLAN.

    Navigate to the folder
    ```
    cd ./tricircle/icehouse-patches/neutron/openvswitch-agent-patch
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
    cd ./tricircle/icehouse-patches/glance/glance_location_patch
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


