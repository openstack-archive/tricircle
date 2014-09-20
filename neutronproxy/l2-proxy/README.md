Neutron L2 Proxy
===============================

 L2-Proxy acts as the same role of Openvswitch-agent in cascading OpenStack.
 L2-Proxy treats cascaded Neutron-Server as its openvswitch,  convert the internal request message from the message bus to restful API calling to cascaded Neutron-Server.


Key modules
-----------

* The new l2 proxy module l2_proxy,which treats cascaded Neutron-server as its openvswitch,  convert the internal request message from the message bus to restful API calling to cascaded Neutron:

    neutron/plugins/l2_proxy/agent/l2_proxy.py

* The code include clients of various component service(nova neutron cinder glance),through the client you can call cascaded various component service API by restful API

    neutron/plugins/l2_proxy/agent/clients.py

* The solution of that clients gets token or checks token from token:
    neutron/plugins/l2_proxy/agent/neutron_proxy_context.py
    neutron/plugins/l2_proxy/agent/neutron_keystoneclient.py

Requirements
------------
* openstack-neutron-openvswitch-agent-2014.1-1.1 has been installed

Installation
------------

We provide two ways to install the l2 proxy code. In this section, we will guide you through installing the neutron l2 proxy with the minimum configuration.

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

    - Update the neutron configuration file (e.g. /etc/neutron/plugins/l2_proxy_agent/l2_cascading_proxy.ini) with the minimum option below. If the option already exists, modify its value, otherwise add it to the config file. Check the "Configurations" section below for a full configuration guide and detail explanation for each configuration item.
      ```
      [DEFAULT]
      ...
      ###configuration for neutron cascading ###
      keystone_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      neutron_user_name = $USER_NAME
      neutron_password = $USER_PWD
      neutron_tenant_name = $TENANT_NAME
      os_region_name = $CASCADED_REGION_NAME

      cascading_os_region_name = $CASCADEDING_REGION_NAME
      cascading_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      cascading_user_name = $USER_NAME
      cascading_password = $USER_PWD
      cascading_tenant_name = $TENANT_NAME
      ```

    - Start the neutron l2 proxy.
      ```nohup  /usr/bin/python /usr/lib64/python2.6/site-packages/neutron/plugins/l2_proxy/agent/l2_proxy.py --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/plugins/l2_proxy_agent/l2_cascading_proxy.ini        >/dev/null 2>&1 &```

    - Done. The neutron l2 proxy should be working with a demo configuration.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should setup the l2 proxy with the minimum configuration below. Check the "Configurations" section for a full configuration guide  and detail explanation for each configuration item.
      ```
      [DEFAULT]
      ...
      ###cascade info ###
      keystone_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      neutron_user_name = $USER_NAME
      neutron_password = $USER_PWD
      neutron_tenant_name = $TENANT_NAME
      os_region_name = $CASCADED_REGION_NAME

      cascading_os_region_name = $CASCADEDING_REGION_NAME
      cascading_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      cascading_user_name = $USER_NAME
      cascading_password = $USER_PWD
      cascading_tenant_name = $TENANT_NAME

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically add the related codes to $NEUTRON_PARENT_DIR/nova and modify the related configuration.

    - In case the automatic installation does not work, try to install manually.

Configurations
--------------

* This is a (default) configuration sample for the l2 proxy. Please add/modify these options in /etc/neutron/plugins/l2_proxy_agent/l2_cascading_proxy.ini.
* Note:
    - Please carefully make sure that options in the configuration file are not duplicated. If an option name already exists, modify its value instead of adding a new one of the same name.
    - Please refer to the 'Configuration Details' section below for proper configuration and usage of costs and constraints.

```
[DEFAULT]

...

#The global keystone component service url, by which the l2 porxy
#can access to global keystone service
#In future, seperate KeyStone service may be used.
keystone_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0

#The region name ,which will be set as a parameter when
#the cascaded level component services register endpoint to keystone
os_region_name=$CASCADED_REGION_NAME

# username for connecting to cascaded neutron in admin context (string
# value)
neutron_user_name=$USER_NAME

# password for connecting to cascaded neutron in admin context (string
# value)
neutron_user_password=$USER_PWD

# tenant name for connecting to cascaded neutron in admin context
# (string value)
neutron_tenant_name=$TENANT_NAME

#The global keystone component service url, by which the l2 porxy
#can access to global keystone service
#In future, seperate KeyStone service may be used.
cascading_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0

#The region name ,which will be set as a parameter when
#the cascading level component services register endpoint to keystone
cascading_os_region_name = $CASCADEDING_REGION_NAME

# username for connecting to cascading neutron in admin context (string
# value)
cascading_user_name = $USER_NAME

# password for connecting to cascading neutron in admin context (string
# value)
cascading_user_password=$USER_PWD

# tenant name for connecting to cascading neutron in admin context
# (string value)
cascading_tenant_name=$TENANT_NAME
