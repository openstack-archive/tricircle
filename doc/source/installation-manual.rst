===================
Manual Installation
===================

The Tricircle works with Neutron to provide networking automation functionality
across Neutron in multi-region OpenStack deployment. In this guide we discuss
how to manually install the Tricircle with local and central Neutron server.

Local Neutron server, running with the Tricircle local plugin, is responsible
for triggering cross-Neutron networking automation. Every OpenStack instance
has one local Neutron service, registered in the same region with other core
services like Nova, Cinder, Glance, etc. Central Neutron server, running with
the Tricircle central plugin, is responsible for unified resource allocation
and cross-Neutron networking building. Besides regions for each OpenStack
instance, we also need one specific region for central Neutron service. Only
the Tricircle administrator service needs to be registered in this region along
with central Neutron service while other core services are not mandatory.

Installation with Central Neutron Server
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- 1 Install the Tricircle package::

    git clone https://github.com/openstack/tricircle.git
    cd tricircle
    pip install -e .

- 2 Register the Tricircle administrator API to Keystone::

    openstack user create tricircle --password password
    openstack role add --project service --user tricircle service
    openstack service create tricircle --name tricircle --description "Cross Neutron Networking Automation Service"
    service_id=$(openstack service show tricircle -f value -c id)
    service_host=162.3.124.201
    service_port=19999
    service_region=CentralRegion
    service_url=http://$service_host:$service_port/v1.0
    openstack endpoint create $service_id --publicurl $service_url --adminurl $service_url --internalurl $service_url --region $service_region

  change password, service_host, service_port and service_region in the above
  commands to adapt your deployment. OpenStack CLI tool will automatically find
  the endpoints to send to registration requests. If you would like to specify
  the region for endpoints, use::

    openstack --os-region-name <region_name> <command>

- 3 Generate the Tricircle configuration sample::

    cd tricircle
    oslo-config-generator --config-file=etc/api-cfg-gen.conf
    oslo-config-generator --config-file=etc/xjob-cfg-gen.conf

  The generated sample files are located in tricircle/etc

- 4 Configure the Tricircle administrator API::

    cd tricircle/etc
    cp api.conf.sample api.conf

  Edit etc/api.conf, for detail configuration information, please refer to the
  configuration guide. Below only options necessary to be changed are listed.

.. csv-table::
   :header: "Option", "Description", "Example"

   [DEFAULT] tricircle_db_connection, "database connection string for tricircle", mysql+pymysql://root:password@ 127.0.0.1/tricircle?charset=utf8
   [keystone_authtoken] auth_type, "authentication method", password
   [keystone_authtoken] auth_url, "keystone authorization url", http://$keystone_service_host/identity_admin
   [keystone_authtoken] username, "username of service account, needed for password authentication", tricircle
   [keystone_authtoken] password, "password of service account, needed for password authentication", password
   [keystone_authtoken] user_domain_name, "user domain name of service account, needed for password authentication", Default
   [keystone_authtoken] project_name, "project name of service account, needed for password authentication", service
   [keystone_authtoken] project_domain_name, "project domain name of service account, needed for password authentication", Default
   [keystone_authtoken] auth_uri, "complete public Identity API endpoint", http://$keystone_service_host/identity
   [keystone_authtoken] cafile, "A PEM encoded Certificate Authority to use when verifying HTTPs", /opt/stack/data/ca-bundle.pem
   [keystone_authtoken] signing_dir, "Directory used to cache files related to PKI tokens", /var/cache/tricircle
   [keystone_authtoken] memcached_servers, "Optionally specify a list of memcached server(s) to use for caching", $keystone_service_host:11211
   [client] auth_url, "keystone authorization url", http://$keystone_service_host:5000/v3
   [client] identity_url, "keystone service url", http://$keystone_service_host:35357/v3
   [client] auto_refresh_endpoint, "if set to True, endpoint will be automatically refreshed if timeout accessing", True
   [client] top_region_name, "name of central region which client needs to access", CentralRegion
   [client] admin_username, "username of admin account", admin
   [client] admin_password, "password of admin account", password
   [client] admin_tenant, "project name of admin account", demo
   [client] admin_user_domain_name, "user domain name of admin account", Default
   [client] admin_tenant_domain_name, "project name of admin account", Default

.. note:: The Tricircle utilizes the Oslo library to setup service, database,
   log and RPC, please refer to the configuration guide of the corresponding
   Oslo library if you need further configuration of these modules. Change
   keystone_service_host to the address of Keystone service.

- 5 Create the Tricircle database(take mysql as an example)::

    mysql -uroot -p -e "create database tricircle character set utf8;"
    cd tricircle
    tricircle-db-manage --config-file etc/api.conf db_sync

- 6 Start the Tricircle administrator API::

    sudo mkdir /var/cache/tricircle
    sudo chown $(whoami) /var/cache/tricircle/
    cd tricircle
    tricircle-api --config-file etc/api.conf

- 7 Configure the Tricircle Xjob daemon::

    cd tricircle/etc
    cp xjob.conf.sample xjob.conf

  Edit etc/xjob.conf, for detail configuration information, please refer to the
  configuration guide. Below only options necessary to be changed are listed.

.. csv-table::
   :header: "Option", "Description", "Example"

   [DEFAULT] tricircle_db_connection, "database connection string for tricircle", mysql+pymysql://root:password@ 127.0.0.1/tricircle?charset=utf8
   [client] auth_url, "keystone authorization url", http://$keystone_service_host:5000/v3
   [client] identity_url, "keystone service url", http://$keystone_service_host:35357/v3
   [client] auto_refresh_endpoint, "if set to True, endpoint will be automatically refreshed if timeout accessing", True
   [client] top_region_name, "name of central region which client needs to access", CentralRegion
   [client] admin_username, "username of admin account", admin
   [client] admin_password, "password of admin account", password
   [client] admin_tenant, "project name of admin account", demo
   [client] admin_user_domain_name, "user domain name of admin account", Default
   [client] admin_tenant_domain_name, "project name of admin account", Default

.. note:: The Tricircle utilizes the Oslo library to setup service, database,
   log and RPC, please refer to the configuration guide of the corresponding
   Oslo library if you need further configuration of these modules. Change
   keystone_service_host to the address of Keystone service.

- 8 Start the Tricircle Xjob daemon::

    cd tricircle
    tricircle-xjob --config-file etc/xjob.conf

- 9 Setup central Neutron server

  In this guide we assume readers are familiar with how to install Neutron
  server, so we just briefly discuss the steps and extra configuration needed
  by central Neutron server. For detail information about the configuration
  options in "client" and "tricircle" groups, please refer to the configuration
  guide. Neutron server can be installed alone, or you can install a full
  OpenStack instance then remove or stop other services.

  - install Neutron package

  - configure central Neutron server

    edit neutron.conf

  .. csv-table::
     :header: "Option", "Description", "Example"

     [database] connection, "database connection string for central Neutron server", mysql+pymysql://root:password@ 127.0.0.1/neutron?charset=utf8
     [DEFAULT] bind_port, "Port central Neutron server binds to", change to a different value rather than 9696 if you run central and local Neutron server in the same host
     [DEFAULT] core_plugin, "core plugin central Neutron server uses", tricircle.network.central_plugin.TricirclePlugin
     [DEFAULT] service_plugins, "service plugin central Neutron server uses", "(leave empty)"
     [DEFAULT] tricircle_db_connection, "database connection string for tricircle", mysql+pymysql://root:password@ 127.0.0.1/tricircle?charset=utf8
     [client] auth_url, "keystone authorization url", http://$keystone_service_host:5000/v3
     [client] identity_url, "keystone service url", http://$keystone_service_host:35357/v3
     [client] auto_refresh_endpoint, "if set to True, endpoint will be automatically refreshed if timeout accessing", True
     [client] top_region_name, "name of central region which client needs to access", CentralRegion
     [client] admin_username, "username of admin account", admin
     [client] admin_password, "password of admin account", password
     [client] admin_tenant, "project name of admin account", demo
     [client] admin_user_domain_name, "user domain name of admin account", Default
     [client] admin_tenant_domain_name, "project name of admin account", Default
     [tricircle] type_drivers, "list of network type driver entry points to be loaded", "local,vlan"
     [tricircle] tenant_network_types, "ordered list of network_types to allocate as tenant networks", "local,vlan"
     [tricircle] network_vlan_ranges, "physical_network names and VLAN tags range usable of VLAN provider", "bridge:2001:3000"
     [tricircle] bridge_network_type, "l3 bridge network type which is enabled in tenant_network_types and is not local type", vlan
     [tricircle] enable_api_gateway, "whether the API gateway is enabled", False

  .. note:: Change keystone_service_host to the address of Keystone service.

  - create database for central Neutron server

  - register central Neutron server endpoint in Keystone, central Neutron
    should be registered in the same region with the Tricircle

  - start central Neutron server

Installation with Local Neutron Server
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- 1 Install the Tricircle package::

    git clone https://github.com/openstack/tricircle.git
    cd tricircle
    pip install -e .

- 2 Setup local Neutron server

  In this guide we assume readers have already installed a complete OpenStack
  instance running services like Nova, Cinder, Neutron, etc, so we just discuss
  how to configure Neutron server to work with the Tricircle. For detail
  information about the configuration options in "client" and "tricircle"
  groups, please refer to the configuration guide. After the change, you just
  restart the Neutron server.

  - configure local Neutron server

    edit neutron.conf.

    .. note::

      Pay attention to the service_plugins configuration item, make sure
      the plugin which is configured can support associating a floating ip to
      a port whose network is not directly attached to the router.
      TricircleL3Plugin is inherited from Neutron original L3RouterPlugin,
      and overrides the original "get_router_for_floatingip" implementation
      to allow associating a floating ip to a port whose network is not
      directly attached to the router. If you want to configure local Neutron
      to use original L3RouterPlugin, then you need to patch the function
      "get_router_for_floatingip" as what has been done in TricircleL3Plugin.

      If only cross Neutron L2 networking is needed in the deployment, it's
      not necessary to configure the service plugins.

  .. csv-table::
     :header: "Option", "Description", "Example"

     [DEFAULT] core_plugin, "core plugin local Neutron server uses", tricircle.network.local_plugin.TricirclePlugin
     [DEFAULT] service_plugins, "service plugins local Neutron server uses", tricircle.network.local_l3_plugin.TricircleL3Plugin
     [client] auth_url, "keystone authorization url", http://$keystone_service_host:5000/v3
     [client] identity_url, "keystone service url", http://$keystone_service_host:35357/v3
     [client] auto_refresh_endpoint, "if set to True, endpoint will be automatically refreshed if timeout accessing", True
     [client] top_region_name, "name of central region which client needs to access", CentralRegion
     [client] admin_username, "username of admin account", admin
     [client] admin_password, "password of admin account", password
     [client] admin_tenant, "project name of admin account", demo
     [client] admin_user_domain_name, "user domain name of admin account", Default
     [client] admin_tenant_domain_name, "project name of admin account", Default
     [tricircle] real_core_plugin, "the core plugin the Tricircle local plugin invokes", neutron.plugins.ml2.plugin.Ml2Plugin
     [tricircle] central_neutron_url, "central Neutron server url", http://$neutron_service_host:9696

  .. note:: Change keystone_service_host to the address of Keystone service,
     and neutron_service_host to the address of central Neutron service.
