Cinder uuid-mapping-patch
===============================

it will be patched in cascading level's control node

Cascading  level  node  can  manage volume/snapshot/backup/ in cascaded level node,
because of the mapping_uuid stored in cascading level represent the relationship of
volume/snapshot/bakcup

Key modules
-----------

* adding mapping_uuid column in cinder volume /cinder snapshot /cinder backup  table,
  when cinder synchronizes db:

    cinder\db\sqlalchemy\migrate_repo\versions\023_add_mapping_uuid.py
    cinder\db\sqlalchemy\migrate_repo\versions\024_snapshots_add_mapping_uuid.py
    cinder\db\sqlalchemy\migrate_repo\versions\025_backup_add_mapping_uuid.py
    cinder\db\sqlalchemy\models.py


Requirements
------------
* openstack icehouse has been installed

Installation
------------

We provide two ways to install the mapping-uuid-patch code. In this section, we will guide you through installing the instance_mapping_uuid patch.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:

* **Manual Installation**

    - Make sure you have performed backups properly.

    - Navigate to the local repository and copy the contents in 'cinder' sub-directory to the corresponding places in existing nova, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/cinder $NOVA_PARENT_DIR```
      (replace the $... with actual directory name.)

    - synchronize the cinder db.
      ```
      mysql -u root -p$MYSQL_PASS -e "DROP DATABASE if exists cinder;
      CREATE DATABASE cinder;
      GRANT ALL PRIVILEGES ON cinder.* TO 'cinder'@'%' IDENTIFIED BY $MYSQL_PASS;
      GRANT ALL PRIVILEGES ON *.* TO 'cinder'@'%'IDENTIFIED BY $MYSQL_PASS;
      cinder-manage db sync
      ```

    - Done. The cinder proxy should be working with a demo configuration.

* **Automatic Installation**

    - Make sure you have performed backups properly.

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

