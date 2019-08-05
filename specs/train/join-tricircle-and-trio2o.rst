==================================
Join Tricircle and Trio2o together
==================================

Blueprint
=========

https://blueprints.launchpad.net/tricircle/+spec/join-tricircle-and-trio2o-together

At the very beginning, Tricircle and Tiro2o has the same Poc Stage
Project called OpenStack Cascased Solution[1] by Huawei. After
tests they get divided as two independent project in community.
Tricircle focus on network automation across neutron servers in
multi-region OpenStack Clouds while Trio2o is the api gateway
for transferring nova and cinder rest api. Although they get
independent, however, in many application area such as NFV
and multiple data centers they need to be reunified once
again as their design concept is the same for multi-region
openstack management since the beginning. This blueprint
try to reunite Tricircle and Trio2o as a unified and complete
project dedicated to multi-region OpenStack clouds management.
Problem Description
Tricircle is one of the Community official components and kept
on the pace with every Iterative version. The newest version is
Stein. While Tio2o is out of update and management for a long time.
The newest version is Mitaka. Also there exists a big problem is that
Trio2o re-implement nova and cinder rest-api and cli command. Trio2o
has no python-client. And overlaps may exists for the two project
devstack install script as well,etc.

Implementation
==============
So It is needed to develop  a unified common python-client for the two
project Tricirle and Trio2o to unify and translate cli command and rest
api. Also the two database and tables need to be combined together and
redesigned . Source code and configure files about functions and api
need to be unified planned . Then devstack install scripts as well as
zuul gate jobs need to be merged and verified together.  At last there
need to check the tempest unit tests in an unified path specification.

References
==========

[1].https://wiki.openstack.org/wiki/OpenStack_cascading_solution

[2].https://wiki.openstack.org/wiki/Tricircle

[3].https://wiki.openstack.org/wiki/Trio2o

[4].https://github.com/openstack/tricircle

[5].https://github.com/openstack/python-tricircleclient

[6].https://github.com/openstack/trio2o

[7].https://docs.openstack.org/tricircle/latest/user/readme.html
