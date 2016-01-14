# Copyright 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import urlparse

from requests import Request
from requests import Session

from tricircle.common import client
from tricircle.common import constants as cons
from tricircle.db import api as db_api


# the url could be endpoint registered in the keystone
# or url sent to tricircle service, which is stored in
# pecan.request.url
def get_version_from_url(url):

    components = urlparse.urlsplit(url)

    path = components.path
    pos = path.find('/')

    ver = ''
    if pos == 0:
        path = path[1:]
        i = path.find('/')
        if i >= 0:
            ver = path[:i]
        else:
            ver = path
    elif pos > 0:
        ver = path[:pos]
    else:
        ver = path

    return ver


def get_bottom_url(t_ver, t_url, b_ver, b_endpoint):
    """get_bottom_url

    convert url received by Tricircle service to bottom OpenStack
    request url through the configured endpoint in the KeyStone

    :param t_ver: version of top service
    :param t_url: request url to the top service
    :param b_ver: version of bottom service
    :param b_endpoint: endpoint registered in keystone for bottom service
    :return: request url to bottom service
    """
    t_parse = urlparse.urlsplit(t_url)

    after_ver = t_parse.path

    remove_ver = '/' + t_ver + '/'
    pos = after_ver.find(remove_ver)

    if pos == 0:
        after_ver = after_ver[len(remove_ver):]
    else:
        remove_ver = t_ver + '/'
        pos = after_ver.find(remove_ver)
        if pos == 0:
            after_ver = after_ver[len(remove_ver):]

    if after_ver == t_parse.path:
        # wrong t_url
        return ''

    b_parse = urlparse.urlsplit(b_endpoint)

    scheme = b_parse.scheme
    netloc = b_parse.netloc
    path = '/' + b_ver + '/' + after_ver
    if b_ver == '':
        path = '/' + after_ver
    query = t_parse.query
    fragment = t_parse.fragment

    b_url = urlparse.urlunsplit((scheme,
                                 netloc,
                                 path,
                                 query,
                                 fragment))
    return b_url


def get_pod_service_endpoint(context, pod_name, st):

    pod = db_api.get_pod_by_name(context, pod_name)

    if pod:
        c = client.Client()
        return c.get_endpoint(context, pod['pod_id'], st)

    return ''


def get_pod_service_ctx(context, t_url, pod_name, s_type=cons.ST_NOVA):
    t_ver = get_version_from_url(t_url)
    b_endpoint = get_pod_service_endpoint(context,
                                          pod_name,
                                          s_type)
    b_ver = get_version_from_url(b_endpoint)
    b_url = ''
    if b_endpoint != '':
        b_url = get_bottom_url(t_ver, t_url, b_ver, b_endpoint)

    return {'t_ver': t_ver, 'b_ver': b_ver,
            't_url': t_url, 'b_url': b_url}


def forward_req(context, action, b_headers, b_url, b_body):
    s = Session()
    req = Request(action, b_url,
                  data=b_body,
                  headers=b_headers)
    prepped = req.prepare()

    # do something with prepped.body
    # do something with prepped.headers
    resp = s.send(prepped,
                  timeout=60)

    return resp
