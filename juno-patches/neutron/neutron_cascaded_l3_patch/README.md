Openstack Neutron cascaded_l3_patch
===============================

 Neutron cascaded_l3_patch is mainly used to achieve L3 communications crossing OpenStack. To solve the problem, we add 'onlink' field for extra route of router based on the ip range in neutron-server, and add GRE Tunnel in l3-agent. This patch should be made to the Cascaded Neutron nodes.


Key modules
-----------

* We add GRE Tunnel in l3-agent by modifying some files:
    neutron/agent/linux/ip_lib.py
	neutron/agent/l3_agent.py

* We add 'onlink' field for extra route of router based on the ip range in neutron-server by modifying some files:
        neutron/common/config.py
        neutron/db/extraroute_db.py


Requirements
------------
* openstack neutron-2014.2 has been installed.

Installation
------------

We provide two ways to install the Neutron cascaded_l3_patch. In this section, we will guide you through installing the Neutron cascaded_l3_patch with modifying the configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Neutron of Juno Version**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $NEUTRON_PARENT_DIR/neutron
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Navigate to the local repository and copy the contents in 'neutron' sub-directory to the corresponding places in existing neutron, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/neutron $NEUTRON_PARENT_DIR```
      (replace the $... with actual directory name.)
      ```
    - you can modify neutron config file
            $CONFIG_FILE_PATH/plugins/ml2/ml2_conf.ini
                Modify the value of firewall_driver option as:
                    [securitygroup]
                    firewall_driver=neutron.agent.firewall.NoopFirewallDriver

            $CONFIG_FILE_PATH/l3_agent.ini
                Modify the value of agent_mode option as:
                    [DEFAULT]
                    agent_mode=dvr_snat

            $CONFIG_FILE_PATH/neutron.conf, you can also don't modify
	        Default value of 3gw_extern_net_ip_range option in config file, is
                    l3gw_extern_net_ip_range=100.64.0.0/16

    - Restart the neutron-server and neutron-l3-agent.
      ```service neutron-server restart```
      ```service neutron-l3-agent restart```

    - Done.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation script will automatically modify the neutron code and the configurations.

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Juno.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically modify the related codes to $NEUTRON_PARENT_DIR/neutron and the related configuration.

    - In case the automatic installation does not work, try to install manually.
