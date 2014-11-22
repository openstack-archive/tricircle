Nova instance mapping_uuid patch
===============================
add instance mapping_uuid attribute patch,it will be patched in cascading level's control node

How can we manage the servers in cascading level? To solve this problem,nova proxy must can get relation of cascading and cascaded server.So we can do this through adding instance attribute mapping_uuid

Key modules
-----------

* adding mapping_uuid column in nova instance table,when nova synchronizes db:

    nova\db\sqlalchemy\migrate_repo\versions\234_add_mapping_uuid_column_to_instance.py
    nova\db\sqlalchemy\models.py
    nova-2014.1\nova\objects\instance.py
    nova\network\neutronv2\api.py

* allowing nova proxy update instance mapping_uuid through conductor
    nova\conductor\manager.py

Requirements
------------
* openstack icehouse has been installed

Installation
------------

We provide two ways to install the instance_mapping_uuid patch code. In this section, we will guide you through installing the instance_mapping_uuid patch.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:

* **Manual Installation**

    - Make sure you have performed backups properly.

    - Navigate to the local repository and copy the contents in 'nova' sub-directory to the corresponding places in existing nova, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/nova $NOVA_PARENT_DIR```
      (replace the $... with actual directory name.)

    - synchronize the nova db.
      ```
      mysql -u root -p$MYSQL_PASS -e "DROP DATABASE if exists nova;
      CREATE DATABASE nova;
      GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'%' IDENTIFIED BY '$NOVA_PASSWORD';
      GRANT ALL PRIVILEGES ON *.* TO 'nova'@'%'IDENTIFIED BY '$NOVA_PASSWORD';
      nova-manage db sync
      ```

    - Done. The nova proxy should be working with a demo configuration.

* **Automatic Installation**

    - Make sure you have performed backups properly.

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

