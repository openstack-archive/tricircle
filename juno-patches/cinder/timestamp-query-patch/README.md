Cinder timestamp-query-patch
===============================
it will be patched in cascaded level's control node

cinder juno version database has update_at attribute for change_since
query filter function, however cinder db api this version don't support
timestamp query function. So it is needed to make this patch in cascaded level
while syncronization  state between cascading and cascaded openstack level

Key modules
-----------

* adding timestamp query function while list volumes:

    cinder\db\sqlalchemy\api.py


Requirements
------------
* openstack juno has been installed

Installation
------------

We provide two ways to install the timestamp query patch code. In this section, we will guide you through installing the timestamp query  patch.

* **Note:**

    - Make sure you have an existing installation of **Openstack Juno**.
    - We recommend that you Do backup at least the following files before installation, because they are to be overwritten or modified:

* **Manual Installation**

    - Make sure you have performed backups properly.

    - Navigate to the local repository and copy the contents in 'cinder' sub-directory to the corresponding places in existing cinder, e.g.
      ```cp -r $LOCAL_REPOSITORY_DIR/cinder $CINDER_PARENT_DIR```
      (replace the $... with actual directory name.)

    - restart cinder api service

    - Done. The Cinder-Proxy should be working with a demo configuration.

* **Automatic Installation**

    - Make sure you have performed backups properly.

    - Navigate to the installation directory and run installation script.
      ```
      cd $LOCAL_REPOSITORY_DIR/installation
      sudo bash ./install.sh
      ```
      (replace the $... with actual directory name.)

