===================
Configuration Guide
===================
A brief introduction to configure Tricircle service. Only the
configuration items for Tricircle will be described here. Logging,
messaging, database, keystonemiddleware etc configuration which are
generated from OpenStack Oslo library, will not be described here. Since
these configuration items are common to Nova, Cinder, Neutron. Please
refer to corresponding description from Nova, Cinder or Neutron.

Common Options
==============
In the common configuration options, the group of "client" need to be
configured in Admin API, XJob, Local Plugin and Central Plugin. The
"tricircle_db_connection" should be configured in Admin API, XJob and
Central Plugin.

.. _Common:

.. list-table:: Description of common configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``tricircle_db_connection`` = ``None``
     - (String) database connection string for Tricircle, for example, mysql+pymysql://root:password@127.0.0.1/tricircle?charset=utf8
   * - **[client]**
     -
   * - ``admin_password`` = ``None``
     - (String) password of admin account, needed when auto_refresh_endpoint set to True, for example, password.
   * - ``admin_tenant`` = ``None``
     - (String) tenant name of admin account, needed when auto_refresh_endpoint set to True, for example, demo.
   * - ``admin_tenant_domain_name`` = ``Default``
     - (String) tenant domain name of admin account, needed when auto_refresh_endpoint set to True.
   * - ``admin_user_domain_name`` = ``Default``
     - (String) user domain name of admin account, needed when auto_refresh_endpoint set to True.
   * - ``admin_username`` = ``None``
     - (String) username of admin account, needed when auto_refresh_endpoint set to True.
   * - ``auth_url`` = ``http://127.0.0.1:5000/v3``
     - (String) keystone authorization url, for example, http://$service_host:5000/v3
   * - ``auto_refresh_endpoint`` = ``True``
     - (Boolean) if set to True, endpoint will be automatically refreshed if timeout accessing endpoint.
   * - ``ew_bridge_cidr`` = ``100.0.0.0/9``
     - (String) cidr pool of the east-west bridge network, for example, 100.0.0.0/9
   * - ``identity_url`` = ``http://127.0.0.1:35357/v3``
     - (String) keystone service url, for example, http://$service_host:35357/v3
   * - ``neutron_timeout`` = ``60``
     - (Integer) timeout for neutron client in seconds.
   * - ``ns_bridge_cidr`` = ``100.128.0.0/9``
     - (String) cidr pool of the north-south bridge network, for example, 100.128.0.0/9
   * - ``top_region_name`` = ``None``
     - (String) region name of Central Neutron in which client needs to access, for example, CentralRegion.




Tricircle Admin API Settings
============================

Tricircle Admin API servers for managing the mapping between OpenStack instances
and availability zone, retrieving object uuid routing and exposing API for
maintenance. The following items should be configured in Tricircle's api.conf.

.. _Tricircle-Admin_API:

.. list-table:: Description of Tricircle Admin API configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``api_workers`` = ``1``
     -  (Integer) The port to bind to
   * - ``auth_strategy`` = ``keystone``
     -  (String) The type of authentication to use
   * - ``bind_host`` = ``0.0.0.0``
     -  (String) The host IP to bind to
   * - ``bind_port`` = ``19999``
     -  (Integer) The port to bind to


Tricircle XJob Settings
=======================

Tricircle XJob serves for receiving and processing cross OpenStack
functionality and other async jobs from Admin API or Tricircle Central
Neutron Plugin. The following items should be configured in Tricircle's
xjob.conf.

.. _Tricircle-Xjob:

.. list-table:: Description of Tricircle XJob configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``periodic_enable`` = ``True``
     - (Boolean) Enable periodic tasks
   * - ``periodic_fuzzy_delay`` = ``60``
     - (Integer) Range of seconds to randomly delay when starting the periodic task scheduler to reduce stampeding. (Disable by setting to 0)
   * - ``report_interval`` = ``10``
     - (Integer) Seconds between nodes reporting state to datastore
   * - ``host`` = ``tricircle.xhost``
     - (String) The host name for RPC server, each node should have different host name.
   * - ``job_run_expire`` = ``180``
     - (Integer) Running job is considered expires after this time, in seconds
   * - ``workers`` = ``1``
     - (Integer) Number of workers
   * - ``worker_handle_timeout`` = ``1800``
     - (Integer) Timeout for worker's one turn of processing, in seconds
   * - ``worker_sleep_time`` = ``60``
     - (Float) Seconds a worker sleeps after one run in a loop
   * - ``redo_time_span`` = ``172800``
     - (Integer) Time span in seconds, we calculate the latest job timestamp by
       subtracting this time span from the current timestamp, jobs created
       between these two timestamps will be redone

Networking Setting for Tricircle
================================
To make the networking automation work, two plugins need to be configured:
Tricircle Central Neutron Plugin and Tricircle Local Neutron Plugin.

**Tricircle Central Neutron Plugin**

The Tricircle Central Neutron Plugin serves for tenant level L2/L3 networking
automation across multiple OpenStack instances. The following items should be
configured in central Neutron's neutron.conf.

.. _Central Neutron:

.. list-table:: Description of Central Neutron configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``core_plugin`` = ``None``
     - (String) core plugin central Neutron server uses, should be set to tricircle.network.central_plugin.TricirclePlugin
   * - **[tricircle]**
     -
   * - ``bridge_network_type`` = ``vlan``
     - (String) Type of l3 bridge network, this type should be enabled in tenant_network_types and is not local type, for example, vlan.
   * - ``default_region_for_external_network`` = ``RegionOne``
     - (String) Default region where the external network belongs to, it must exist, for example, RegionOne.
   * - ``network_vlan_ranges`` = ``None``
     - (String) List of <physical_network>:<vlan_min>:<vlan_max> or <physical_network> specifying physical_network names usable for VLAN provider and tenant networks, as well as ranges of VLAN tags on each available for allocation to tenant networks, for example,bridge:2001:3000.
   * - ``tenant_network_types`` = ``local,vlan``
     - (String) Ordered list of network_types to allocate as tenant networks. The default value "local" is useful for single pod connectivity. For example, local and vlan.
   * - ``type_drivers`` = ``local,vlan``
     - (String) List of network type driver entry points to be loaded from the tricircle.network.type_drivers namespace. For example, local and vlan.



**Tricircle Local Neutron Plugin**

The Tricircle Local Neutron Plugin serves for cross Neutron networking
automation triggering. It is a shim layer between real core plugin and
Neutron API server. The following items should be configured in local
Neutron's neutron.conf

.. _Local Neutron:

.. list-table:: Description of Local Neutron configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description and Example
   * - **[DEFAULT]**
     -
   * - ``core_plugin`` = ``None``
     - (String) core plugin local Neutron server uses, should be set to tricircle.network.local_plugin.TricirclePlugin
   * - **[tricircle]**
     -
   * - ``central_neutron_url`` = ``None``
     - (String) Central Neutron server url, for example, http://$service_host:9696
   * - ``real_core_plugin`` = ``None``
     - (String) The core plugin the Tricircle local plugin will invoke, for example, neutron.plugins.ml2.plugin.Ml2Plugin


**Tricircle Local Neutron L3 Plugin**

In multiple OpenStack clouds, if the external network is located in the
first OpenStack cloud, but the port which will be associated with one
floating ip is located in the second OpenStack cloud, then the network for
this port may not be able to be added to the router in the first OpenStack.
In Tricircle, to address this scenario, a bridge network will be used
to connect the routers in these two OpenStack clouds if the network is not
a cross Neutron L2 network. To make it happen, the Tricircle Local Neutron L3
Plugin or other L3 service plugin should be able to associate a floating ip to
a port whose network is not directly attached to the router. TricircleL3Plugin
is inherited from Neutron original L3RouterPlugin, and overrides the original
"get_router_for_floatingip" implementation to allow associating a floating ip
to a port whose network is not directly attached to the router. If you want
to configure local Neutron to use original L3RouterPlugin, then you need to
patch the function "get_router_for_floatingip" as what has been done in
TricircleL3Plugin.

If only cross Neutron L2 networking is needed in the deployment, it's not
necessary to configure the service plugins.

The following item should be configured in local Neutron's neutron.conf

.. _Local Neutron:

.. list-table:: Description of Local Neutron configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description and Example
   * - **[DEFAULT]**
     -
   * - ``service_plugins`` = ``None``
     - (String) service plugins local Neutron server uses, can be set to tricircle.network.local_l3_plugin.TricircleL3Plugin
