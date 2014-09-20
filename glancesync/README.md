Glance Sync Manager
===============================

This is a submodule of Tricircle Project, in which a sync function is added to support the glance images' sync between cascading and cascadeds.
When launching a instance, the nova will search the image which is in the same region with the instance to downland, this can speeded up the whole launching time of the instance.

Key modules
-----------

* Primarily, there is only new module in glance cascading: Sync, which is in the glance/sync package.

    glance/sync/__init__.py :  Adds a ImageRepoProxy class, like store, policy .etc ,  to augment a sync mechanism  layer on top of the api request handling chain.
    glance/sync/base.py : Contains SyncManager object, execute the sync operations.
    glance/sync/utils.py :  Some help functions.
    glance/sync/api/  :     Support a Web Server of sync.
    glance/sync/client/:   Support a client to visit the Web Server , ImageRepoProxy use this client to call the sync requests.
    glance/sync/task/:      Each Sync operation is transformed into a task, we using  queue to store the task an eventlet to handle the task simultaneously.
    glance/sync/store/:    We implements the independent-glance-store, separating the handles of image_data from image_metadata.
    glance/cmd/sync.py:  For the Sync Server starting launch (refer this in /usr/bin/glance-sync).



* **Note:**
    At present, the glance cascading only support v2 version of glance-api;

Requirements
------------

* pexpect>=2.3

Installation
------------
* **Note:**
    - The Installation and configuration guidelines written below is just for the cascading layer of glance. For the cascaded layer,  the glance is installed as normal.

* **Prerequisites**
    - Please install the python package: pexpect>=2.3 ( because we use pxssh for loginng and there is a bug in pxssh, see           https://mail.python.org/pipermail/python-list/2008-February/510054.html, you should fix this before launch the service. )

* **Manual Installation**

    - Make sure you have performed backups properly.
* **Manual Installation**

    1.  Under cascading Openstack, copy these files from glance-patch directory and glancesync directory to suitable place:

        | DIR           | FROM             | TO                                         |
        | ------------- |:-----------------|:-------------------------------------------|
        | glancesync    | glance/          | ${python_install_dir}/glance               |
        | glancesync    | etc/glance/      | /etc/glance/                               |
        | glancesync    | glance-sync      |  /usr/bin/                                 |
        |${glance-patch}| glance/          | ${python_install_dir}/glance               |
        |${glance-patch}|glance.egg-info/entry_points.txt | ${glance_install_egg.info}/ |
        
        ${glance-patch} = `icehouse-patches/glance/glance_location_patch`   ${python_install_dir} is where the openstack installed, e.g. `/usr/lib64/python2.6/site-packages` .
    2.  Add/modify the config options

        | CONFIG_FILE     | OPTION                                             | ADD or MODIFY  |
        | ----------------|:---------------------------------------------------|:--------------:|
        |glance-api.conf  | show_multiple_locations=True                       | M              |
        |glance-api.conf  | sync_server_host=${sync_mgr_host}                  | A              |
        |glance-api.conf  | sync_server_port=9595                              | A              |
        |glance-api.conf  | sync_enabled=True                                  | A              |
        |glance-sync.conf  | cascading_endpoint_url=${glance_api_endpoint_url} | M              |
        |glance-sync.conf  |  sync_strategy=ALL                                | M              |
        |glance-sync.conf  | auth_host=${keystone_host}                        | M              |
    3.  Re-launch services on cacading openstack, like:

        `service openstack-glance-api restart `
        `service openstack-glance-registry restart `
        `python /usr/bin/glance-sync --config-file=/etc/glance/glance-sync.conf & `

* **Automatic Installation**

    1.  Enter the glance-patch installation dir: `cd ./tricircle/icehouse-patches/glance/glance_location_patch/installation` .
    2.  Optional, modify the shell script variable: `_PYTHON_INSTALL_DIR` .
    3.  Run the install script: `sh install.sh`
    4.  Enter the glancesync installation dir: `cd ./tricircle/glancesync/installation` .
    5.  Modify the cascading&cascaded glances' store scheme configuration, which is in the file: `./tricircle/glancesync/etc/glance/glance_store.yaml` .
    6.  Optional, modify the config options in shell script: `sync_enabled=True`, `sync_server_port=9595`, `sync_server_host=127.0.0.1` with the proper values.
    7.  Run the install script: `sh install.sh`

Configurations
--------------

Besides glance-api.conf file, we add some new config files. They are described separately.

    - In glance-api.conf, three options added:

   [DEFAULT]

   # Indicate whether use the image sync, default value is False.
   #If configuring on cascading layer, this value should be True.
   sync_enabled = True

   #The sync server 's port number, default is 9595.
   sync_server_port = 9595

   #The sync server's host name (or ip address)
   sync_server_host = 127.0.0.1

   *Besides, the option show_multiple_locations value should be ture.
    - In glance-sync.conf which newly increased, the options is similar with glance-registry.conf except:

    [DEFAULT]

    #How to sync the image, the value can be ["None", "ALL", "USER"]
    #When "ALL" choosen, means to sync to all the cascaded glances;
    #When "USER" choosen, means according to user's role, project, etc.
    sync_strategy = ALL

    #What the cascading glance endpoint url is .(Note that this value should be consistent with what in keystone).
    cascading_endpoint_url = http://127.0.0.1:9292/

    #when snapshot sync, set the timeout time(second) of snapshot 's status
    #changing into 'active'.
    snapshot_timeout = 300

    #when snapshot sync, set the polling interval time(second) to check the
    #snapshot's status.
    snapshot_sleep_interval = 10

    #When sync task fails, set the retry times.
    task_retry_times = 0

    #When copy image data using 'scp' between filesystmes, set the timeout
    #time of the copy.
    scp_copy_timeout = 3600

    #When snapshot, one can set the specific regions in which the snapshot
    #will sync to. (e.g. physicalOpenstack001, physicalOpenstack002)
    snapshot_region_names =

   - Last but also important, we add a yaml file for config the store backend's copy : glance_store.yaml in cascading glance.
     these config  correspond to various store scheme (at present, only filesystem is supported), the values
     are based on your environment,  so you have to config it before installation or restart the glance-sync
     when modify it.




