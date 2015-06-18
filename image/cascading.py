"""Implementation of an cascading image service that uses to sync the image
   from cascading glance to the special cascaded glance.
   """
import logging
import os
import urlparse

from oslo.config import cfg

from nova.image import glance
from nova.image.sync import drivers as drivermgr


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

glance_cascading_opt = [
    cfg.StrOpt('image_copy_dest_location_url',
               default='file:///var/lib/glance/images',
               help=("The path cascaded image_data copy to."),
               deprecated_opts=[cfg.DeprecatedOpt('dest_location_url',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_dest_host',
               default='127.0.0.1',
               help=("The host name where image_data copy to."),
               deprecated_opts=[cfg.DeprecatedOpt('dest_host',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_dest_user',
               default='glance',
               help=("The user name of cascaded glance for copy."),
               deprecated_opts=[cfg.DeprecatedOpt('dest_user',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_dest_password',
               default='openstack',
               help=("The passowrd of cascaded glance for copy."),
               deprecated_opts=[cfg.DeprecatedOpt('dest_password',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_source_location_url',
               default='file:///var/lib/glance/images',
               help=("where the cascaded image data from"),
               deprecated_opts=[cfg.DeprecatedOpt('source_location_url',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_source_host',
               default='0.0.0.1',
               help=("The host name where image_data copy from."),
               deprecated_opts=[cfg.DeprecatedOpt('source_host',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_source_user',
               default='glance',
               help=("The user name of glance for copy."),
               deprecated_opts=[cfg.DeprecatedOpt('source_user',
                                                  group='DEFAULT')]),
    cfg.StrOpt('image_copy_source_password',
               default='openstack',
               help=("The passowrd of glance for copy."),
               deprecated_opts=[cfg.DeprecatedOpt('source_password',
                                                  group='DEFAULT')]),
    ]

CONF.register_opts(glance_cascading_opt)

_V2_IMAGE_CREATE_PROPERTIES = ['container_format', 'disk_format', 'min_disk',
                               'min_ram', 'name', 'protected']


def get_adding_image_properties(image):
    _tags = list(image.tags) or []
    kwargs = {}
    for key in _V2_IMAGE_CREATE_PROPERTIES:
        try:
            value = getattr(image, key, None)
            if value and value != 'None':
                kwargs[key] = value
        except KeyError:
            pass
    if _tags:
        kwargs['tags'] = _tags
    return kwargs


def get_candidate_path(image, scheme='file'):
    locations = image.locations or []
    for loc in locations:
        if loc['url'].startswith(scheme):
            return loc['url'] if scheme != 'file' \
                else loc['url'][len('file://'):]
    return None


def get_copy_driver(scheme_key):
    return drivermgr.get_store_driver(scheme_key)


def get_host_port(url):
    if not url:
        return None, None
    pieces = urlparse.urlparse(url)
    return pieces.netloc.split(":")[0], pieces.netloc.split(":")[1]


class GlanceCascadingService(object):

    def __init__(self, cascading_client=None):
        self._client = cascading_client or glance.GlanceClientWrapper()

    def sync_image(self, context, cascaded_url, cascading_image):
        cascaded_glance_url = cascaded_url
        _host, _port = get_host_port(cascaded_glance_url)
        _cascaded_client = glance.GlanceClientWrapper(context=context,
                                                      host=_host,
                                                      port=_port,
                                                      version=2)

        image_meta = get_adding_image_properties(cascading_image)
        cascaded_image = _cascaded_client.call(context, 2, 'create',
                                               **image_meta)
        image_id = cascading_image.id
        cascaded_id = cascaded_image.id
        candidate_path = get_candidate_path(cascading_image)
        LOG.debug("the candidate path is %s." % (candidate_path))
        # copy image
        try:
            image_loc = self._copy_data(image_id, cascaded_id, candidate_path)
        except Exception as e:
            LOG.exception(("copy image failed, reason=%s") % e)
            raise
        else:
            if not image_loc:
                LOG.exception(("copy image Exception, no cascaded_loc"))
        try:
            # patch loc to the cascaded image
            csd_locs = [{'url': image_loc,
                         'metadata': {}
                        }]
            _cascaded_client.call(context, 2, 'update', cascaded_id,
                                  remove_props=None,
                                  locations=csd_locs)
        except Exception as e:
            LOG.exception(("patch loc to cascaded image Exception, reason: %s"
                            % e))
            raise

        try:
            # patch glance-loc to cascading image
            csg_locs = cascading_image.locations
            glance_loc = '%s/v2/images/%s' % (cascaded_glance_url,
                                              cascaded_id)
            csg_locs.append({'url': glance_loc,
                             'metadata': {'image_id': str(cascaded_id),
                                          'action': 'upload'
                             }
            })
            self._client.call(context, 2, 'update', image_id,
                              remove_props=None, locations=csg_locs)
        except Exception as e:
            LOG.exception(("patch loc to cascading image Exception, reason: %s"
                            % e))
            raise

        return cascaded_id

    @staticmethod
    def _copy_data(cascading_id, cascaded_id, candidate_path):
        source_pieces = urlparse.urlparse(CONF.image_copy_source_location_url)
        dest_pieces = urlparse.urlparse(CONF.image_copy_dest_location_url)
        source_scheme = source_pieces.scheme
        dest_scheme = dest_pieces.scheme
        _key = ('%s:%s' % (source_scheme, dest_scheme))
        copy_driver = get_copy_driver(_key)
        source_path = os.path.join(source_pieces.path, cascading_id)
        dest_path = os.path.join(dest_pieces.path, cascaded_id)

        source_location = {'host': CONF.image_copy_source_host,
                           'login_user': CONF.image_copy_source_user,
                           'login_password': CONF.image_copy_source_password,
                           'path': source_path
        }
        dest_location = {'host': CONF.image_copy_dest_host,
                         'login_user': CONF.image_copy_dest_user,
                         'login_password': CONF.image_copy_dest_password,
                         'path': dest_path
        }
        return copy_driver.copy_to(source_location,
                                   dest_location,
                                   candidate_path=candidate_path)
