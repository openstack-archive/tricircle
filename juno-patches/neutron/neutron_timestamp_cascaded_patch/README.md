Openstack Neutron timestamp_cascaded_patch
===============================

 Neutron timestamp_cascaded_patch is mainly used to provide query filter 'sinces_change' for "list ports" API. To achieve the goal, we add three fields ('created_at'/'updated_at'/'delete_at') for ports table in neutron DB, and modify few lines of code in _apply_filters_to_query() function. This patch should be made to the Cascaded Neutron nodes.


Key modules
-----------

* add three fields ('created_at'/'updated_at'/'delete_at') for ports table, and modify few lines of code in _apply_filters_to_query() function:
    neutron/db/migration/alembic_migrations/versions/238cf36dab26_add_port_timestamp_revision.py
        neutron/db/migration/core_init_ops.py
        neutron/db/common_db_mixin.py
        neutron/db/models_v2.py

Requirements
------------
* openstack neutron-2014.2 has been installed.

Installation
------------

We provide two ways to install the Neutron timestamp_cascaded_patch. In this section, we will guide you through installing the Neutron timestamp_cascaded_patch without modifying the configuration.

* **Note:**

    - Make sure you have an existing installation of **Openstack Neutron of Juno Version**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:
        $NEUTRON_PARENT_DIR/neutron
        (replace the $... with actual directory names.)

* **Manual Installation**

    - Navigate to the local repository and copy the contents in 'neutron' sub-directory to the corresponding places in existing neutron, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/neutron $NEUTRON_PARENT_DIR```
      (replace the $... with actual directory name.)

    - Upgrade DB
      ```neutron-db-manage --config-file $CONFIG_FILE_PATH/neutron.conf --config-file $CONFIG_FILE_PATH/plugins/ml2/ml2_conf.ini upgrade head```
      (replace the $... with actual directory name.)

    - Restart the neutron-server.
      ```service neutron-server restart```

    - Done.

* **Automatic Installation**

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

    - Done. The installation script will automatically modify the neutron code, upgrade DB and restart neutron-server.

* **Troubleshooting**

    In case the automatic installation process is not complete, please check the followings:

    - Make sure your OpenStack version is Juno.

    - Check the variables in the beginning of the install.sh scripts. Your installation directories may be different from the default values we provide.

    - The installation code will automatically modify the related codes to $NEUTRON_PARENT_DIR/neutron.

    - In case the automatic installation does not work, try to install manually.
