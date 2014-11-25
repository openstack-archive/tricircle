Openstack Nova Proxy
===============================

 Nova-Proxy acts as the same role of Nova-Compute in cascading OpenStack.
 Nova-Proxy treats cascaded Nova as its hypervisor,  convert the internal request message from the message bus to restful API calling to cascaded Nova.


Key modules
-----------

* The new nova proxy module manager_proxy,which is configured to manage specified Availability Zone cascaded Nova. All VM in the cascaded Nova of this AZ will be bind to the manager_proxy host in the cascading level:

    nova/compute/manager_proxy.py

* The code include clients of various component service(nova neutron cinder glance),through the client you can call cascaded various component service API by restful API

    nova/compute/clients.py

* The solution of that clients gets token or checks token from token:
    nova/compute/compute_context.py
    nova/compute/compute_keystoneclient.py

Requirements
------------
* openstack-nova-compute-2014.2(Juno) has been installed

Installation
------------

We provide two ways to install the nova proxy code. In this section, we will guide you through installing the nova proxy with the minimum configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $NOVA_CONFIG_PARENT_DIR/nova.conf
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Make sure you have performed backups properly.

    - Navigate to the local repository and copy the contents in 'nova' sub-directory to the corresponding places in existing nova, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/nova $NOVA_PARENT_DIR```
      (replace the $... with actual directory name.)

    - Update the nova configuration file (e.g. /etc/nova/nova.conf) with the minimum option below. If the option already exists, modify its value, otherwise add it to the config file. Check the "Configurations" section below for a full configuration guide.
      ```
      [DEFAULT]
      ...
      ###configuration for Nova cascading ###
      proxy_region_name=$proxy_region_name
      cascading_nova_url=$cascading_nova_url
      cascaded_nova_url=$cascaded_nova_url
      cascaded_neutron_url=$cascaded_neutron_url
      cascaded_glance_flag=False
      cascaded_glance_url=$cascaded_glance_url
      os_region_name=$os_region_name
      keystone_auth_url=$keystone_auth_url
      cinder_endpoint_template=$cinder_endpoint_template
      compute_manager=nova.compute.manager_proxy.ComputeManager
      ```

    - Restart the nova proxy.
      ```service nova-compute restart```

    - Done. The nova proxy should be working with a demo configuration.

* **Automatic Installation**

    - Make sure you have performed backups properly.

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should setup the nova proxy with the minimum configuration below. Check the "Configurations" section for a full configuration guide.
      ```
      [DEFAULT]
      ...
      ###cascade info ###
      proxy_region_name=$proxy_region_name
      cascading_nova_url=$cascading_nova_url
      cascaded_nova_url=$cascaded_nova_url
      cascaded_neutron_url=$cascaded_neutron_url
      cascaded_glance_flag=False
      cascaded_glance_url=$cascaded_glance_url
      os_region_name=$os_region_name
      keystone_auth_url=$keystone_auth_url
      cinder_endpoint_template=$cinder_endpoint_template
      compute_manager=nova.compute.manager_proxy.ComputeManager

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically add the related codes to $NOVA_PARENT_DIR/nova and modify the related configuration.

    - In case the automatic installation does not work, try to install manually.

Configurations
--------------

* This is a (default) configuration sample for the nova proxy. Please add/modify these options in /etc/nova/nova.conf.
* Note:
    - Please carefully make sure that options in the configuration file are not duplicated. If an option name already exists, modify its value instead of adding a new one of the same name.
    - Please refer to the 'Configuration Details' section below for proper configuration and usage of costs and constraints.

```
[DEFAULT]

...

#
#Options defined in nova.compute.manager
#

# Default driver to use for the nova proxy (string value)
compute_manager=nova.compute.manager_proxy.ComputeManager

#The region name ,which will be set as a parameter when
#the cascaded level component services register endpoint to keystone
proxy_region_name=$proxy_region_name

#The cascading level nova component service url, by which the nova porxy
#can access to  cascading level nova service
cascading_nova_url=$cascading_nova_url

#The cascaded level nova component service url, by which the nova porxy
#can access to  cascaded level nova service
cascaded_nova_url=$cascaded_nova_url
cascaded_neutron_url=$cascaded_neutron_url

#when cascaded_glance_flag is set to True, the cascaded nova will use casaded glance to
#provide image but not cascading level glance, if it cascaded_glance_flag is set to False
#casacaded Nova will use image from global glance.
cascaded_glance_flag=True or False

#The cascaded level glance service url, by which the nova porxy
#can judge whether cascading glance has a location for this cascaded glance
cascaded_glance_url=$cascaded_glance_url

#The region name ,which will be set as a parameter when
#the cascading level component services register endpoint to keystone
os_region_name=$os_region_name

#The cascading level keystone component service url, by which the nova porxy
#can access to  cascading level keystone service
keystone_auth_url=$keystone_auth_url
