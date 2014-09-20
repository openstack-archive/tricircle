Openstack Neutron-OpenvSwitch-agent
===============================

 Neutron-OpenvSwitch-agent in cascaded OpenStack acts as the same role as the non-cascaded OpenStack.
 Neutron-OpenvSwitch-agent is still Neutron-OpenvSwitch-agent, we modifed only one module ovs_dvr_neutron_agent. Because it is difficult to get dvr mac crossing openstack ,we processed dvr mac specially in cascaded openstack by modifying some code.


Key modules
-----------

* Neutron-OpenvSwitch-agent is still Neutron-OpenvSwitch-agent, we modifed only one module ovs_dvr_neutron_agent. Because it is difficult to get dvr mac crossing openstack ,we processed dvr mac specially in cascaded openstack by modifying some code:

    neutron/plugins/openvswitch/agent/ovs_dvr_neutron_agent.py


Requirements
------------
* openstack-neutron-2014.1-1.1 has been installed and DVR patch has been made.

Installation
------------

We provide two ways to install the Neutron-OpenvSwitch-agent patch. In this section, we will guide you through installing the Neutron-OpenvSwitch-agent without modifying the configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $NEUTRON_PARENT_DIR/neutron
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Navigate to the local repository and copy the contents in 'neutron' sub-directory to the corresponding places in existing neutron, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/neutron $NEUTRON_PARENT_DIR```
      (replace the $... with actual directory name.)
      ```

    - Restart the neutron openvswitch-agent.
      ```service openstack-neutron-openvswitch-agent restart```

    - Done.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should modify the neutron code without modifying the configuration.

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse and DVR patch has been made.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically modify the related codes to $NEUTRON_PARENT_DIR/neutron and not modify the related configuration.

    - In case the automatic installation does not work, try to install manually.
