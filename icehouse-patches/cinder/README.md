Cinder create volume from image bug
===============================
Openstack cascade current is developed based on Icehouse version. While
in Icehouse version there is a bug about creating volume from image and uploading volume to image.
Please referer to the http links https://bugs.launchpad.net/cinder/+bug/1308058 for details.
This bug is recommended to fix in cascaded cinder.

Key modules
-----------

* when create volume from image or upload volume to image, cinder will call a function in glance.py
to check image metadata, while not all the metadata will be included from glance image information.
As a result, in the function _extract_attributes included in file,not all the element such as "cheksum"
will be validated :

    cinder/image/glance.py


Requirements
------------
* openstack icehouse has been installed

Installation
------------

We suggest a way to fix the cinder-image-metadata bug. In this section,
we will guide you through fix this image metadata bug.

* **Note:**

    - Make sure you have an existing installation of **Openstack Icehouse**.
    - We recommend that you Do backup at least the following files before installation,
      because they are to be overwritten or modified.

* **Manual Installation as the OpenStack Community suggest**

    mofify  "output[attr] = getattr(image, attr)" to  "output[attr] = getattr(image, attr, None)"
    in _extract_attributes cinder/image/glance.py,Line 434 around





