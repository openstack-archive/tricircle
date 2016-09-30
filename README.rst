=========
Tricircle
=========

The Tricircle provides an OpenStack API gateway and networking automation
funtionality to allow multiple OpenStack instances, spanning in one site or
multiple sites or in hybrid cloud, to be managed as a single OpenStack cloud.

The Tricircle and these managed OpenStack instances will use shared KeyStone
(with centralized or distributed deployment) or federated KeyStones for
identity management.

The Tricircle presents one big region to the end user in KeyStone. And each
OpenStack instance called a pod is a sub-region of the Tricircle in
KeyStone, and usually not visible to end user directly.

The Tricircle acts as OpenStack API gateway, can handle OpenStack API calls,
schedule one proper OpenStack instance if needed during the API calls handling,
forward the API calls to the appropriate OpenStack instance, and deal with
tenant level L2/L3 networking across OpenStack instances automatically. So it
doesn't matter on which bottom OpenStack instance the VMs for the tenant are
running, they can communicate with each other via L2 or L3.

The end user can see avaialbility zone(AZ) and use AZ to provision
VM, Volume, even Network through the Tricircle. One AZ can include many
OpenStack instances, the Tricircle can schedule and bind OpenStack instance
for the tenant inside one AZ. A tenant's resources could be bound to multiple
specific bottom OpenStack instances in one or multiple AZs automatically.

* Free software: Apache license
* Design documentation: `Tricircle Design Blueprint <https://docs.google.com/document/d/18kZZ1snMOCD9IQvUKI5NVDzSASpw-QKj7l2zNqMEd3g/>`_
* Wiki: https://wiki.openstack.org/wiki/tricircle
* Installation with DevStack: https://github.com/openstack/tricircle/blob/stable/newton/doc/source/installation.rst
* Tricircle Admin API documentation: https://github.com/openstack/tricircle/blob/stable/newton/doc/source/api_v1.rst
* Source: https://github.com/openstack/tricircle
* Bugs: http://bugs.launchpad.net/tricircle
* Blueprints: https://launchpad.net/tricircle
