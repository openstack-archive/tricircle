Tricircle Configuration Options Updating Module
===============================================

In Tricircle Project, we added many options in the *.conf files for cascading, these options
among nova, glance, neutron, cinder. When deploy the cascading environment, these options should
be modified based on the deployment context(IP, tenant, user, password etc.), so we have to
modify each install scripts(/installation) every time for deployment because the options is
configured by these scripts. It is inconvenient.

This script module is created in order to managing the options in *.conf with a centralized way.
It is independent of the installation scripts, but the scripts can invoke the function in it to
finish the options' configuration.

Composition
------
* **config.py**: the implementation to execute options updating, using python build-in lib:ConfigParser.
* **tricircle.cfg**: the options you want to update are stored here.
* **exec.sh**: a very simple shell commend to invoke the python code.

Usage
-------
- Format of the tricircle.cfg

    The tricircle.cfg is standard python config file(like nova.conf in /etc/nova), it contains
    sections and options in each section like what the *.conf is in it. The only difference is
    the **Naming Conventions** of the section:

    + Every section name start with the openstack service config-file name
    (nova/neutron/glance-api/cinder);

    + If the option to be updated needs in a special section in *.conf, the special section
    (keystone_authtoken e.g) should be added to the end of the section name with '_' ahead of
    it. For example, if the 'auth_host' option in nova.conf need be updated, it should in
    'nova_keystone_authtoken' section in the tricircle.cfg.

- Execution

    After you configured the options in tricircle.cfg, run the commend:
        ```python config.py [openstack-service-name]```
    If you want update all services' options in tricircle.cfg, run ```python config.py all```.

    + **Note**: you can execute multiple times for an option with different value and do
    not worry about it appears multiple times in *.conf, only the latest value in the conf
    file.
