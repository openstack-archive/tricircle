Openstack Neutron DVR patch
===============================

 To solve the scalability problem in the OpenStack Neutron Deployment and to distribute the Network Node load to other Compute Nodes, some people proposed a solusion which is named DVR(Distributed Virtual Router).Distributed Virtual Router solves both the problems by providing a solution that would fit into the existing model.

 DVR feature code has been merged into the neutron master branch, Neutron Juno release version would have expected the DVR characteristic. This patch was download from DVR branch on 1st June.


Key modules
-----------

    * L2 Agent Doc

    https://docs.google.com/document/d/1depasJSnGZPOnRLxEC_PYsVLcGVFXZLqP52RFTe21BE/edit#heading=h.5w7clq272tji

    * L3 Agent Doc

    https://docs.google.com/document/d/1jCmraZGirmXq5V1MtRqhjdZCbUfiwBhRkUjDXGt5QUQ/edit

    Addressed by: https://review.openstack.org/84223
        * Add L3 Extension for Distributed Routers

    Addressed by: https://review.openstack.org/87730
        * L2 Agent/ML2 Plugin changes for L3 DVR

    Addressed by: https://review.openstack.org/88442
        * Add 'ip neigh' to ip_lib

    Addressed by: https://review.openstack.org/89413
        * Modify L3 Agent for Distributed Routers

    Addressed by: https://review.openstack.org/89694
        * Add L3 Scheduler Changes for Distributed Routers

    Addressed by: https://review.openstack.org/93233
        * Add 'ip rule add from' to ip_lib

    Addressed by: https://review.openstack.org/96389
        * Addressed merge conflict

    Addressed by: https://review.openstack.org/97028
        * Refactor some router-related methods

    Addressed by: https://review.openstack.org/97275
        * Allow L3 base to handle extensions on router creation

    Addressed by: https://review.openstack.org/102101
        * L2 Model additions to support DVR

    Addressed by: https://review.openstack.org/102332
        * RPC additions to support DVR

    Addressed by: https://review.openstack.org/102398
        * ML2 additions to support DVR

Requirements
------------
* openstack-neutron-server-2014.1-1.1 has been installed
* oslo.db-0.2.0 has been installed
* sqlalchemy-migrate-0.9.1 has been installed

Installation
------------

We provide two ways to install the DVR patch code. In this section, we will guide you through installing the neutron DVR code with the minimum configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $NEUTRON_CONFIG_PARENT_DIR/neutron.conf
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Navigate to the local repository and copy the contents in 'neutron' sub-directory to the corresponding places in existing neutron, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/neutron $NEUTRON_PARENT_DIR```
      (replace the $... with actual directory name.)

    - Navigate to the local repository and copy the contents in 'etc' sub-directory to the corresponding places in existing neutron, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/etc $NEUTRON_CONFIG_DIR```
      (replace the $... with actual directory name.)

    - Update the neutron configuration file (e.g. /etc/neutron/l3_agent.ini, /etc/neutron/plugins/openvswitch/ovs_neutron_plugin.ini) with the minimum option below. If the option already exists, modify its value, otherwise add it to the config file. Check the "Configurations" section below for a full configuration guide.
    1)update l3 agent configurations(/etc/neutron/l3_agent.ini)
      ```
      [DEFAULT]
      ...
      distributed_agent=True
      ```
    2)update openvswitch agent configurations(/etc/neutron/plugins/openvswitch/ovs_neutron_plugin.ini)
    ```
      [AGENT]
      ...
      enable_distributed_routing = True
      ```

    - Remove the neutron DB

    - Create the neutron DB
      ```neutron-db-manage --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/plugins/ml2/ml2_conf.ini upgrade head```

    - Restart the neutron-server/openvswitch-agent/l3-agent.
      ```service openstack-neutron restart```
      ```service openstack-neutron-openvswitch-agent restart```
      ```service openstack-neutron-l3-agent restart```

    - Done.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should setup the DVR code without the minimum configuration modifying. Check the "Configurations" section for a full configuration guide.
    1)update l3 agent configurations(/etc/neutron/l3_agent.ini)
      ```
      [DEFAULT]
      ...
      distributed_agent=True
      ```
    2)update openvswitch agent configurations(/etc/neutron/plugins/openvswitch/ovs_neutron_plugin.ini)
    ```
      [AGENT]
      ...
      enable_distributed_routing = True
     ```

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically add the related codes to $NEUTRON_PARENT_DIR/nova but not modify the related configuration, you should update the related configurations manually.
    - In case the automatic installation does not work, try to install manually.

Configurations
--------------

* This is a (default) configuration sample for the l2 proxy. Please add/modify these options in (/etc/neutron/l3_agent.ini, /etc/neutron/plugins/openvswitch/ovs_neutron_plugin.ini).
* Note:
    - Please carefully make sure that options in the configuration file are not duplicated. If an option name already exists, modify its value instead of adding a new one of the same name.
    - Please refer to the 'Configuration Details' section below for proper configuration and usage of costs and constraints.

    1)add or update l3 agent configurations(/etc/neutron/l3_agent.ini)
      ```
      [DEFAULT]
      ...
      #Enables distributed router agent function
      distributed_agent=True
      ```
    2)add or update openvswitch agent configurations(/etc/neutron/plugins/openvswitch/ovs_neutron_plugin.ini)
    ```
      [AGENT]
      ...
      #Make the l2 agent run in dvr mode
      enable_distributed_routing = True
      ```
