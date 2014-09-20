Openstack Cinder Proxy
===============================

 Cinder-Proxy acts as the same role of Cinder-Volume in cascading OpenStack.
 Cinder-Proxy treats cascaded Cinder as its cinder volume,  convert the internal request message from the message bus to restful API calling to cascaded Cinder.


Key modules
-----------

* The new cinder proxy module cinder_proxy,which treats cascaded Cinder as its cinder volume,  convert the internal request message from the message bus to restful API calling to cascaded Cinder:

    cinder/volume/cinder_proxy.py

Requirements
------------
* openstack-cinder-volume-2014.1-14.1 has been installed

Installation
------------

We provide two ways to install the cinder proxy code. In this section, we will guide you through installing the cinder proxy with the minimum configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $CINDER_CONFIG_PARENT_DIR/cinder.conf
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Make sure you have performed backups properly.

    - Navigate to the local repository and copy the contents in 'cinder' sub-directory to the corresponding places in existing cinder, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/cinder $CINDER_PARENT_DIR```
      (replace the $... with actual directory name.)

    - Update the cinder configuration file (e.g. /etc/cinder/cinder.conf) with the minimum option below. If the option already exists, modify its value, otherwise add it to the config file. Check the "Configurations" section below for a full configuration guide.
      ```
      [DEFAULT]
      ...
      ###configuration for Cinder cascading ###
      volume_manager=cinder.volume.cinder_proxy.CinderProxy
      volume_sync_interval=5
      cinder_tenant_name=$CASCADED_ADMIN_TENANT
      cinder_username=$CASCADED_ADMIN_NAME
      cinder_password=$CASCADED_ADMIN_PASSWORD
      keystone_auth_url=http://$GLOBAL_KEYSTONE_IP:5000/v2.0/
      cascading_glance_url=$CASCADING_GLANCE
      cascaded_glance_url=http://$CASCADED_GLANCE
      cascaded_available_zone=$CASCADED_AVAILABLE_ZONE
      cascaded_region_name=$CASCADED_REGION_NAME
      ```

    - Restart the cinder proxy.
      ```service openstack-cinder-volume restart```

    - Done. The cinder proxy should be working with a demo configuration.

* **Automatic Installation**

    - Make sure you have performed backups properly.

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation code should setup the cinder proxy with the minimum configuration below. Check the "Configurations" section for a full configuration guide.
      ```
      [DEFAULT]
      ...
      ###cascade info ###
       ...
      ###configuration for Cinder cascading ###
      volume_manager=cinder.volume.cinder_proxy.CinderProxy
      volume_sync_interval=5
      cinder_tenant_name=$CASCADED_ADMIN_TENANT
      cinder_username=$CASCADED_ADMIN_NAME
      cinder_password=$CASCADED_ADMIN_PASSWORD
      keystone_auth_url=http://$GLOBAL_KEYSTONE_IP:5000/v2.0/
      cascading_glance_url=$CASCADING_GLANCE
      cascaded_glance_url=http://$CASCADED_GLANCE
      cascaded_available_zone=$CASCADED_AVAILABLE_ZONE
      cascaded_region_name=$CASCADED_REGION_NAME
      ```

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Icehouse.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically add the related codes to $CINDER_PARENT_DIR/cinder and modify the related configuration.

    - In case the automatic installation does not work, try to install manually.

Configurations
--------------

* This is a (default) configuration sample for the cinder proxy. Please add/modify these options in /etc/cinder/cinder.conf.
* Note:
    - Please carefully make sure that options in the configuration file are not duplicated. If an option name already exists, modify its value instead of adding a new one of the same name.
    - Please refer to the 'Configuration Details' section below for proper configuration and usage of costs and constraints.

```
[DEFAULT]

...

#
#Options defined in cinder.volume.manager
#

# Default driver to use for the cinder proxy (string value)
volume_manager=cinder.volume.cinder_proxy.CinderProxy


#The cascading level keystone component service url, by which the cinder proxy
#can access to cascading level keystone service
keystone_auth_url=$keystone_auth_url

#The cascading level glance component service url, by which the cinder proxy
#can access to cascading level glance service
cascading_glance_url=$CASCADING_GLANCE

#The cascaded level glance component service url, by which the cinder proxy
#can judge whether the cascading glance image has a location for this cascaded glance
cascaded_glance_url=http://$CASCADED_GLANCE

#The cascaded level region name, which will be set as a parameter when
#the cascaded level component services register endpoint to keystone
cascaded_region_name=$CASCADED_REGION_NAME

#The cascaded level available zone name, which will be set as a parameter when
#forward request to cascaded level cinder. Please pay attention to that value of
#cascaded_available_zone of cinder-proxy must be the same as storage_availability_zone in
#the cascaded level node. And cinder-proxy should be configured to the same storage_availability_zone.
#this configuration could be removed in the future to just use the cinder-proxy storage_availability_zone
#configuration item. but it is up to the admin to make sure the storage_availability_zone in cinder-proxy#and casacdede cinder keep the same value.
cascaded_available_zone=$CASCADED_AVAILABLE_ZONE


