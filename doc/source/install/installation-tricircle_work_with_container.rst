====================================================
Installation guide for Tricircle work with Container
====================================================

Introduction
^^^^^^^^^^^^

In the `Multi-pod Installation with DevStack <https://docs.openstack.org/tricircle/latest/install/installation-guide.html#multi-pod-installation-with-devstack>`_ ,
we have discussed how to deploy Tricircle in multi-region scenario with DevStack.
However, the previous installation guides have been on how to
manage virtual machines using tricircle and Nova in cross-region
openstack cloud environments. So, multi-region container management
is not supported in Tricircle. Meanwhile, OpenStack uses Zun
component to provide container management service, OpenStack also use
kuyr component and kuryr-libnetwork component to provide container network.
In view of the Tricircle Central_Neutron-Local_Neutron fashion, Tricircle work
with zun and kuryr will provide a cross-region container management solution.
This guide is to describe how tricircle work with container management and how
to deploy a multi-region container environment.


Prerequisite
^^^^^^^^^^^^

In this guide, we need specific versions of the zun project and
kuryr project source code. The source code versions of both projects
must be the Train version and upper. If not, we need to manually change
the source code for both projects. The modification example is as follows:

- 1 Zun Source Code Modification:
    For Zun project, we need modify the **neutron** function
    in /zun/zun/common/clients.py file.
    (The '+' sign represents the added line)

    .. code-block:: console

        def neutron(self):
            if self._neutron:
                return self._neutron

            session = self.keystone().session
            session.verify = self._get_client_option('neutron', 'ca_file') or True
            if self._get_client_option('neutron', 'insecure'):
                session.verify = False
            endpoint_type = self._get_client_option('neutron', 'endpoint_type')
        +   region_name = self._get_client_option('neutron', 'region_name')
            self._neutron = neutronclient.Client(session=session,
                                                 endpoint_type=endpoint_type,
        +                                        region_name=region_name)

            return self._neutron

- 2 Kuryr Source Code Modification:
    For kuryr project, we need modify the **get_neutron_client** function
    in /kuryr/kuryr/lib/utils.py file.
    (The '+' sign represents the added line)

    .. code-block:: console

        def get_neutron_client(*args, **kwargs):
            conf_group = kuryr_config.neutron_group.name
            auth_plugin = get_auth_plugin(conf_group)
            session = get_keystone_session(conf_group, auth_plugin)
            endpoint_type = getattr(getattr(cfg.CONF, conf_group), 'endpoint_type')
        +   region_name = getattr(getattr(cfg.CONF, conf_group), 'region_name')

            return client.Client(session=session,
                                 auth=auth_plugin,
                                 endpoint_type=endpoint_type,
        +                        region_name=region_name)


Setup
^^^^^

In this guide we take two nodes deployment as an example, the node1 run as RegionOne and
Central Region, the node2 run as RegionTwo.

- 1 For the node1 in RegionOne and the node2 in RegionTwo, clone the code from Zun repository
  and Kuryr repository to /opt/stack/ . If the code does not meet the requirements described
  in the Prerequisite Section, modify it with reference to the modification example of the Prerequisite Section.

- 2 Follow "Multi-pod Installation with DevStack" document `Multi-pod Installation with DevStack <https://docs.openstack.org/tricircle/latest/install/installation-guide.html#multi-pod-installation-with-devstack>`_
  to prepare your local.conf for the node1 in RegionOne and the node12 in RegionTwo, and add the
  following lines before installation. Start DevStack in node1 and node2.

    .. code-block:: console

        enable_plugin zun https://git.openstack.org/openstack/zun
        enable_plugin zun-tempest-plugin https://git.openstack.org/openstack/zun-tempest-plugin
        enable_plugin devstack-plugin-container https://git.openstack.org/openstack/devstack-plugin-container
        enable_plugin kuryr-libnetwork https://git.openstack.org/openstack/kuryr-libnetwork

        KURYR_CAPABILITY_SCOPE=local
        KURYR_PROCESS_EXTERNAL_CONNECTIVITY=False

- 3 After DevStack successfully started and finished, we need make some configuration changes to
  Zun component and Kuryr component in node1 and node2.

    - For Zun in node1, modify the /etc/zun/zun.conf

        .. csv-table::
            :header: "Group", "Option", "Value"

            [neutron_client], region_name, RegionOne

    - Restart all the services of Zun in node1.

        .. code-block:: console

            $ sudo systemctl restart devstack@zun*

    - For Kuryr in node1, modify the /etc/kuryr/kuryr.conf

        .. csv-table::
            :header: "Group", "Option", "Value"

            [neutron], region_name, RegionOne

    - Restart all the services of Kuryr in node1.

        .. code-block:: console

            $ sudo systemctl restart devstack@kur*

    - For Zun in node2, modify the /etc/zun/zun.conf

        .. csv-table::
            :header: "Group", "Option", "Value"

            [neutron_client], region_name, RegionTwo

    - Restart all the services of Zun in node2.

        .. code-block:: console

            $ sudo systemctl restart devstack@zun*

    - For Kuryr in node2, modify the /etc/kuryr/kuryr.conf

        .. csv-table::
            :header: "Group", "Option", "Value"

            [neutron], region_name, RegionTwo

    - Restart all the services of Zun in node2.

        .. code-block:: console

            $ sudo systemctl restart devstack@kur*

- 4 Then, we must create environment variables for the admin user and use the admin project.

    .. code-block:: console

        $ source openrc admin admin
        $ unset OS_REGION_NAME

- 5 Finally, use tricircle client to create pods for multi-region.

    .. code-block:: console

        $ openstack --os-region-name CentralRegion multiregion networking pod create --region-name CentralRegion
        $ openstack --os-region-name CentralRegion multiregion networking pod create --region-name RegionOne --availability-zone az1
        $ openstack --os-region-name CentralRegion multiregion networking pod create --region-name RegionTwo --availability-zone az2


How to play
^^^^^^^^^^^

- 1 Create container glance image in RegionOne and RegionTwo.

    - Get docker image from Docker Hub. Run these command in the node1 and the node2.

        .. code-block:: console

            $ docker pull cirros
            $ docker save cirros -o /opt/stack/container_cirros

    - Use glance client to create container image.

        .. code-block:: console

            $ glance --os-region-name=RegionOne image-create --file /opt/stack/container_cirros --container-format=docker --disk-format=raw --name container_cirros --progress
            $ glance --os-region-name=RegionTwo image-create --file /opt/stack/container_cirros --container-format=docker --disk-format=raw --name container_cirros --progress

            $ openstack --os-region-name RegionOne image list

            +--------------------------------------+--------------------------+--------+
            | ID                                   | Name                     | Status |
            +--------------------------------------+--------------------------+--------+
            | 11186baf-4381-4e52-956c-22878b0642df | cirros-0.4.0-x86_64-disk | active |
            | 87864205-4352-4a2c-b9b1-ca95df52c93c | container_cirros         | active |
            +--------------------------------------+--------------------------+--------+

            $ openstack --os-region-name RegionTwo image list

            +--------------------------------------+--------------------------+--------+
            | ID                                   | Name                     | Status |
            +--------------------------------------+--------------------------+--------+
            | cd062c19-bb3a-4f60-b5ef-9688eb67b3da | container_cirros         | active |
            | cf4a2dc7-6d6e-4b7e-a772-44247246e1ff | cirros-0.4.0-x86_64-disk | active |
            +--------------------------------------+--------------------------+--------+

- 2 Create container network in CentralRegion.

    - Create a net in CentralRegion.

        .. code-block:: console

            $ openstack --os-region-name CentralRegion network create container-net

            +---------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
            | Field                     | Value                                                                                                                                                                |
            +---------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
            | admin_state_up            | UP                                                                                                                                                                   |
            | availability_zone_hints   |                                                                                                                                                                      |
            | availability_zones        | None                                                                                                                                                                 |
            | created_at                | None                                                                                                                                                                 |
            | description               | None                                                                                                                                                                 |
            | dns_domain                | None                                                                                                                                                                 |
            | id                        | 5e73dda5-902b-4322-b5b6-4121437fde26                                                                                                                                 |
            | ipv4_address_scope        | None                                                                                                                                                                 |
            | ipv6_address_scope        | None                                                                                                                                                                 |
            | is_default                | None                                                                                                                                                                 |
            | is_vlan_transparent       | None                                                                                                                                                                 |
            | location                  | cloud='', project.domain_id='default', project.domain_name=, project.id='2f314a39de10467bb62745bd96c5fe4d', project.name='admin', region_name='CentralRegion', zone= |
            | mtu                       | None                                                                                                                                                                 |
            | name                      | container-net                                                                                                                                                        |
            | port_security_enabled     | False                                                                                                                                                                |
            | project_id                | 2f314a39de10467bb62745bd96c5fe4d                                                                                                                                     |
            | provider:network_type     | vxlan                                                                                                                                                                |
            | provider:physical_network | None                                                                                                                                                                 |
            | provider:segmentation_id  | 1070                                                                                                                                                                 |
            | qos_policy_id             | None                                                                                                                                                                 |
            | revision_number           | None                                                                                                                                                                 |
            | router:external           | Internal                                                                                                                                                             |
            | segments                  | None                                                                                                                                                                 |
            | shared                    | False                                                                                                                                                                |
            | status                    | ACTIVE                                                                                                                                                               |
            | subnets                   |                                                                                                                                                                      |
            | tags                      |                                                                                                                                                                      |
            | updated_at                | None                                                                                                                                                                 |
            +---------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+

    -  Create a subnet in container-net

        .. code-block:: console

            $ openstack --os-region-name CentralRegion subnet create --subnet-range 10.0.60.0/24 --network container-net container-subnet

            +-------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
            | Field             | Value                                                                                                                                                                |
            +-------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
            | allocation_pools  | 10.0.60.2-10.0.60.254                                                                                                                                                |
            | cidr              | 10.0.60.0/24                                                                                                                                                         |
            | created_at        | 2019-12-10T07:13:21Z                                                                                                                                                 |
            | description       |                                                                                                                                                                      |
            | dns_nameservers   |                                                                                                                                                                      |
            | enable_dhcp       | True                                                                                                                                                                 |
            | gateway_ip        | 10.0.60.1                                                                                                                                                            |
            | host_routes       |                                                                                                                                                                      |
            | id                | b7a7adbd-afd3-4449-9cbc-fbce16c7a2e7                                                                                                                                 |
            | ip_version        | 4                                                                                                                                                                    |
            | ipv6_address_mode | None                                                                                                                                                                 |
            | ipv6_ra_mode      | None                                                                                                                                                                 |
            | location          | cloud='', project.domain_id='default', project.domain_name=, project.id='2f314a39de10467bb62745bd96c5fe4d', project.name='admin', region_name='CentralRegion', zone= |
            | name              | container-subnet                                                                                                                                                     |
            | network_id        | 5e73dda5-902b-4322-b5b6-4121437fde26                                                                                                                                 |
            | prefix_length     | None                                                                                                                                                                 |
            | project_id        | 2f314a39de10467bb62745bd96c5fe4d                                                                                                                                     |
            | revision_number   | 0                                                                                                                                                                    |
            | segment_id        | None                                                                                                                                                                 |
            | service_types     | None                                                                                                                                                                 |
            | subnetpool_id     | None                                                                                                                                                                 |
            | tags              |                                                                                                                                                                      |
            | updated_at        | 2019-12-10T07:13:21Z                                                                                                                                                 |
            +-------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------+

- 3 Create container in RegionOne and RegionTwo.

    .. note:: We can give container a specific command to run it continually, e.g. "sudo nc -l -p 5000" .


    .. code-block:: console

        $ openstack --os-region-name RegionOne appcontainer run --name container01 --net network=$container_net_id --image-driver glance $RegionTwo_container_cirros_id sudo nc -l -p 5000

        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
        | Field             | Value                                                                                                                                                                                                           |
        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
        | tty               | False                                                                                                                                                                                                           |
        | addresses         | None                                                                                                                                                                                                            |
        | links             | [{u'href': u'http://192.168.1.81/v1/containers/ca67055c-635d-4603-9b0b-19c16eed7ef9', u'rel': u'self'}, {u'href': u'http://192.168.1.81/containers/ca67055c-635d-4603-9b0b-19c16eed7ef9', u'rel': u'bookmark'}] |
        | image             | 87864205-4352-4a2c-b9b1-ca95df52c93c                                                                                                                                                                            |
        | labels            | {}                                                                                                                                                                                                              |
        | disk              | 0                                                                                                                                                                                                               |
        | security_groups   | None                                                                                                                                                                                                            |
        | image_pull_policy | None                                                                                                                                                                                                            |
        | user_id           | 57df611fd8c7415dad6d2530bf962ecd                                                                                                                                                                                |
        | uuid              | ca67055c-635d-4603-9b0b-19c16eed7ef9                                                                                                                                                                            |
        | hostname          | None                                                                                                                                                                                                            |
        | auto_heal         | False                                                                                                                                                                                                           |
        | environment       | {}                                                                                                                                                                                                              |
        | memory            | 0                                                                                                                                                                                                               |
        | project_id        | 2f314a39de10467bb62745bd96c5fe4d                                                                                                                                                                                |
        | privileged        | False                                                                                                                                                                                                           |
        | status            | Creating                                                                                                                                                                                                        |
        | workdir           | None                                                                                                                                                                                                            |
        | healthcheck       | None                                                                                                                                                                                                            |
        | auto_remove       | False                                                                                                                                                                                                           |
        | status_detail     | None                                                                                                                                                                                                            |
        | cpu_policy        | shared                                                                                                                                                                                                          |
        | host              | None                                                                                                                                                                                                            |
        | image_driver      | glance                                                                                                                                                                                                          |
        | task_state        | None                                                                                                                                                                                                            |
        | status_reason     | None                                                                                                                                                                                                            |
        | name              | container01                                                                                                                                                                                                     |
        | restart_policy    | None                                                                                                                                                                                                            |
        | ports             | None                                                                                                                                                                                                            |
        | command           | [u'sudo', u'nc', u'-l', u'-p', u'5000']                                                                                                                                                                         |
        | runtime           | None                                                                                                                                                                                                            |
        | registry_id       | None                                                                                                                                                                                                            |
        | cpu               | 0.0                                                                                                                                                                                                             |
        | interactive       | False                                                                                                                                                                                                           |
        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

        $ openstack --os-region-name RegionOne appcontainer list

        +--------------------------------------+-------------+--------------------------------------+---------+------------+------------+-------+
        | uuid                                 | name        | image                                | status  | task_state | addresses  | ports |
        +--------------------------------------+-------------+--------------------------------------+---------+------------+------------+-------+
        | ca67055c-635d-4603-9b0b-19c16eed7ef9 | container01 | 87864205-4352-4a2c-b9b1-ca95df52c93c | Running | None       | 10.0.60.62 | []    |
        +--------------------------------------+-------------+--------------------------------------+---------+------------+------------+-------+


        $ openstack --os-region-name RegionTwo appcontainer run --name container02 --net network=$container_net_id --image-driver glance $RegionTwo_container_cirros_id sudo nc -l -p 5000

        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
        | Field             | Value                                                                                                                                                                                                           |
        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
        | tty               | False                                                                                                                                                                                                           |
        | addresses         | None                                                                                                                                                                                                            |
        | links             | [{u'href': u'http://192.168.1.82/v1/containers/c359e48c-7637-4d9f-8219-95a4577683c3', u'rel': u'self'}, {u'href': u'http://192.168.1.82/containers/c359e48c-7637-4d9f-8219-95a4577683c3', u'rel': u'bookmark'}] |
        | image             | cd062c19-bb3a-4f60-b5ef-9688eb67b3da                                                                                                                                                                            |
        | labels            | {}                                                                                                                                                                                                              |
        | disk              | 0                                                                                                                                                                                                               |
        | security_groups   | None                                                                                                                                                                                                            |
        | image_pull_policy | None                                                                                                                                                                                                            |
        | user_id           | 57df611fd8c7415dad6d2530bf962ecd                                                                                                                                                                                |
        | uuid              | c359e48c-7637-4d9f-8219-95a4577683c3                                                                                                                                                                            |
        | hostname          | None                                                                                                                                                                                                            |
        | auto_heal         | False                                                                                                                                                                                                           |
        | environment       | {}                                                                                                                                                                                                              |
        | memory            | 0                                                                                                                                                                                                               |
        | project_id        | 2f314a39de10467bb62745bd96c5fe4d                                                                                                                                                                                |
        | privileged        | False                                                                                                                                                                                                           |
        | status            | Creating                                                                                                                                                                                                        |
        | workdir           | None                                                                                                                                                                                                            |
        | healthcheck       | None                                                                                                                                                                                                            |
        | auto_remove       | False                                                                                                                                                                                                           |
        | status_detail     | None                                                                                                                                                                                                            |
        | cpu_policy        | shared                                                                                                                                                                                                          |
        | host              | None                                                                                                                                                                                                            |
        | image_driver      | glance                                                                                                                                                                                                          |
        | task_state        | None                                                                                                                                                                                                            |
        | status_reason     | None                                                                                                                                                                                                            |
        | name              | container02                                                                                                                                                                                                     |
        | restart_policy    | None                                                                                                                                                                                                            |
        | ports             | None                                                                                                                                                                                                            |
        | command           | [u'sudo', u'nc', u'-l', u'-p', u'5000']                                                                                                                                                                         |
        | runtime           | None                                                                                                                                                                                                            |
        | registry_id       | None                                                                                                                                                                                                            |
        | cpu               | 0.0                                                                                                                                                                                                             |
        | interactive       | False                                                                                                                                                                                                           |
        +-------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

        $ openstack --os-region-name RegionTwo appcontainer list

        +--------------------------------------+-------------+--------------------------------------+---------+------------+-------------+-------+
        | uuid                                 | name        | image                                | status  | task_state | addresses   | ports |
        +--------------------------------------+-------------+--------------------------------------+---------+------------+-------------+-------+
        | c359e48c-7637-4d9f-8219-95a4577683c3 | container02 | cd062c19-bb3a-4f60-b5ef-9688eb67b3da | Running | None       | 10.0.60.134 | []    |
        +--------------------------------------+-------------+--------------------------------------+---------+------------+-------------+-------+

- 4 Execute container in RegionOne and RegionTwo.

    .. code-block:: console

        $ openstack --os-region-name RegionOne appcontainer exec --interactive container01 /bin/sh
        $ openstack --os-region-name RegionTwo appcontainer exec --interactive container02 /bin/sh

- 5 By now, we successfully created multi-region container scenario. So we can do something
  on cross-region container, e.g. 1) RegionOne container ping RegionTwo container 2) Cross-Region Container Load Balancing.