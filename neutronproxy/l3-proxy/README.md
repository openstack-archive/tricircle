Neutron L3 Proxy
===============================

 L3-Proxy acts as the same role of L3-agent in cascading OpenStack.
 L3-Proxy treats cascaded Neutron-Server as its linux namespaces,  convert the internal request message from the message bus to restful API calling to cascaded neutron-server.


Key modules
-----------

* The new l3 proxy module l3_proxy,which treats cascaded Neutron-Server as its linux namespaces,  convert the internal request message from the message bus to restful API calling to cascaded neutron-server:

    neutron/agent/l3_proxy.py


Requirements
------------
* openstack-neutron-l3-agent-2014.1-1.1 and l2-proxy has been installed

Installation
------------

We provide two ways to install the l3 proxy code. In this section, we will guide you through installing the l3 proxy with the minimum configuration.

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

    - Update the neutron configuration file (e.g. /etc/neutron/l3_proxy_agent.ini) with the minimum option below. If the option already exists, modify its value, otherwise add it to the config file. Check the "Configurations" section below for a full configuration guide and detail explanation for each configuration item.
      ```
      [DEFAULT]
      ...
      ###configuration for neutron cascading ###
      admin_tenant_name = $TENANT_NAME
      admin_user = $USER_NAME
      admin_password = $USER_PWD
      auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      os_region_name = $CASCADEDING_REGION_NAME

      cascaded_os_region_name = $CASCADED_REGION_NAME
      cascaded_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      cascaded_admin_user_name = $USER_NAME
      cascaded_admin_password = $USER_PWD
      cascaded_tenant_name = $CASCADED_TENANT_NAME
      ```

    - Start the neutron l3 proxy.
      ```nohup   /usr/bin/python  /usr/lib64/python2.6/site-packages/neutron/agent/l3_proxy.py --config-file=/etc/neutron/neutron.conf --config-file=/etc/neutron/l3_proxy_agent.ini                     >/dev/null 2>&1 &```

    - Done. The neutron l3 proxy should be working with a demo configuration.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should setup the l3 proxy with the minimum configuration below. Check the "Configurations" section for a full configuration guide and detail explanation for each configuration item.
      ```
      [DEFAULT]
      ...
      ###cascade info ###
      admin_tenant_name = $TENANT_NAME
      admin_user = $USER_NAME
      admin_password = $USER_PWD
      auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      os_region_name = $CASCADEDING_REGION_NAME

      cascaded_os_region_name = $CASCADED_REGION_NAME
      cascaded_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0
      cascaded_admin_user_name = $USER_NAME
      cascaded_admin_password = $USER_PWD
      cascaded_tenant_name = $CASCADED_TENANT_NAME

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically add the related codes to $NEUTRON_PARENT_DIR/neutron and modify the related configuration.

    - In case the automatic installation does not work, try to install manually.

Configurations
--------------

* This is a (default) configuration sample for the l3 proxy. Please add/modify these options in /etc/neutron/l3_proxy_agent.ini.
* Note:
    - Please carefully make sure that options in the configuration file are not duplicated. If an option name already exists, modify its value instead of adding a new one of the same name.
    - Please refer to the 'Configuration Details' section below for proper configuration and usage of costs and constraints.

```
[DEFAULT]

...

#The global keystone component service url, by which the l3 porxy
#can access to global keystone service.
#In future, seperate KeyStone service may be used.
cascaded_auth_url = http://$CASCADING_CONTROL_IP:35357/v2.0

#The region name ,which will be set as a parameter when
#the cascaded level component services register endpoint to keystone
cascaded_os_region_name =$CASCADED_REGION_NAME

# username for connecting to cascaded neutron in admin context (string
# value)
cascaded_admin_user_name=$USER_NAME

# password for connecting to cascaded neutron in admin context (string
# value)
cascaded_admin_password=$USER_PWD

# tenant name for connecting to cascaded neutron in admin context
# (string value)
cascaded_tenant_name=$TENANT_NAME

#The global keystone component service url, by which the l3 porxy
#can access to global keystone service.
#In future, seperate KeyStone service may be used.
auth_url= http://$CASCADING_CONTROL_IP:35357/v2.0

#The region name ,which will be set as a parameter when
#the cascading level component services register endpoint to keystone
os_region_name = $CASCADEDING_REGION_NAME

# username for connecting to cascading neutron in admin context (string
# value)
admin_user= $USER_NAME

# password for connecting to cascading neutron in admin context (string
# value)
admin_password=$USER_PWD

# tenant name for connecting to cascading neutron in admin context
# (string value)
admin_tenant_name=$TENANT_NAME
