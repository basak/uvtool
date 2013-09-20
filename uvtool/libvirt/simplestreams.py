#!/usr/bin/python

# Keep Ubuntu Cloud images synced to a local libvirt storage pool.

# Copyright (C) 2013 Canonical Ltd.
# Author: Robie Basak <robie.basak@canonical.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# This is written using Python 2 because libvirt bindings were not available
# for Python 3 at the time of writing.

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import base64
import codecs
import collections
import errno
import json
import os
import sys

import libvirt

import simplestreams.filters
import simplestreams.mirrors
import simplestreams.util

import uvtool.libvirt

LIBVIRT_POOL_NAME = 'uvtool'
IMAGE_DIR = '/var/lib/uvtool/libvirt/images/' # must end in '/'; see use
METADATA_DIR = '/var/lib/uvtool/libvirt/metadata'


def mkdir_p(path):
    """Create path if it doesn't exist already"""
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def metadata_path(encoded_libvirt_image_name):
    return os.path.join(METADATA_DIR, encoded_libvirt_image_name)


def have_metadata(encoded_libvirt_image_name):
    return os.path.exists(metadata_path(encoded_libvirt_image_name))


def remove_metadata(encoded_libvirt_image_name):
    os.unlink(metadata_path(encoded_libvirt_image_name))


def set_metadata(encoded_libvirt_image_name, metadata):
    mkdir_p(METADATA_DIR)
    with codecs.open(
            metadata_path(encoded_libvirt_image_name), 'wb',
            encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)


def get_metadata(encoded_libvirt_image_name):
    with codecs.open(
            metadata_path(encoded_libvirt_image_name), 'rb',
            encoding='utf-8') as f:
        return json.load(f)


BASE64_PREFIX = 'x-uvt-b64-'

def _encode_libvirt_pool_name(product_name, version_name):
    return BASE64_PREFIX + base64.b64encode(
        (' '.join([product_name, version_name])).encode(), b'-_'
    )


def _decode_libvirt_pool_name(encoded_pool_name):
    if not encoded_pool_name.startswith(BASE64_PREFIX):
        raise ValueError(
            "Volume name cannot be parsed for simplestreams identity: %s" %
            repr(encoded_pool_name)
        )
    return base64.b64decode(
        encoded_pool_name[len(BASE64_PREFIX):],
        altchars=b'-_'
    ).split(None, 1)


def clean_extraneous_images():
    conn = libvirt.open('qemu:///system')
    pool = uvtool.libvirt.get_libvirt_pool_object(conn, LIBVIRT_POOL_NAME)
    encoded_libvirt_pool_names = uvtool.libvirt.volume_names_in_pool(
        LIBVIRT_POOL_NAME)
    volume_names_in_use = frozenset(
        uvtool.libvirt.get_all_domain_volume_names(
            filter_by_dir=IMAGE_DIR)
    )
    for encoded_libvirt_name in encoded_libvirt_pool_names:
        if (encoded_libvirt_name not in volume_names_in_use and
                not have_metadata(encoded_libvirt_name)):
            pool.storageVolLookupByName(encoded_libvirt_name).delete(0)


def _load_products(path=None, content_id=None, clean=False):
    # If clean evaluates to True, then remove any metadata files for which
    # the corresponding volume is missing.
    def new_product():
        return {'versions': {}}
    products = collections.defaultdict(new_product)
    try:
        metadata_list = os.listdir(METADATA_DIR)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
        # If the directory doesn't exist, then we have no metadata, and don't
        # need to populate the products dict.
    else:
        for encoded_libvirt_name_string in metadata_list:
            metadata = get_metadata(encoded_libvirt_name_string)
            encoded_libvirt_name_bytes = encoded_libvirt_name_string.encode(
                'utf-8')
            if not uvtool.libvirt.have_volume_by_name(
                    encoded_libvirt_name_bytes, pool_name=LIBVIRT_POOL_NAME):
                if clean:
                    remove_metadata(encoded_libvirt_name_string)
                continue
            product, version = _decode_libvirt_pool_name(
                encoded_libvirt_name_bytes)
            assert(product == metadata['product_name'])
            assert(version == metadata['version_name'])
            products[product]['versions'][version] = {
                'items': { 'disk1.img': metadata }
            }
    return {'content_id': content_id, 'products': products}


class LibvirtQuery(simplestreams.mirrors.BasicMirrorWriter):
    def __init__(self, filters):
        super(LibvirtQuery, self).__init__()
        self.filters = filters
        self.result = []

    def load_products(self, path=None, content_id=None):
        return {'content_id': content_id, 'products': {}}

    def filter_item(self, data, src, target, pedigree):
        return simplestreams.filters.filter_item(
            self.filters, data, src, pedigree)

    def insert_item(self, data, src, target, pedigree, contentsource):
        product_name, version_name, item_name = pedigree
        self.result.append((product_name, version_name))


def query(filter_args):
    query = LibvirtQuery(simplestreams.filters.get_filters(filter_args))
    query.sync_products(None, src=_load_products())
    return (_encode_libvirt_pool_name(product_name, version_name)
        for product_name, version_name in query.result)


class LibvirtMirror(simplestreams.mirrors.BasicMirrorWriter):
    def __init__(self, filters, verbose=False):
        super(LibvirtMirror, self).__init__({'max_items': 1})
        self.filters = filters
        self.verbose = verbose

    def load_products(self, path=None, content_id=None):
        return _load_products(path=path, content_id=content_id, clean=True)

    def filter_index_entry(self, data, src, pedigree):
        return data['datatype'] == 'image-downloads'

    def filter_item(self, data, src, target, pedigree):
        return simplestreams.filters.filter_item(
            self.filters, data, src, pedigree)

    def insert_item(self, data, src, target, pedigree, contentsource):
        product_name, version_name, item_name = pedigree
        assert(item_name == 'disk1.img')
        if self.verbose:
            print("Adding: %s %s" % (product_name, version_name))
        encoded_libvirt_name = _encode_libvirt_pool_name(
            product_name, version_name)
        if not uvtool.libvirt.have_volume_by_name(
                encoded_libvirt_name, pool_name=LIBVIRT_POOL_NAME):
            uvtool.libvirt.create_volume_from_fobj(
                encoded_libvirt_name, contentsource, image_type='qcow2',
                pool_name=LIBVIRT_POOL_NAME
            )
        set_metadata(
            encoded_libvirt_name,
            simplestreams.util.products_exdata(src, pedigree)
        )

    def remove_version(self, data, src, target, pedigree):
        product_name, version_name = pedigree
        if self.verbose:
            print("Removing: %s %s" % (product_name, version_name))
        encoded_libvirt_name = _encode_libvirt_pool_name(
            product_name, version_name)
        remove_metadata(encoded_libvirt_name)
        uvtool.libvirt.delete_volume_by_name(
            encoded_libvirt_name, pool_name=LIBVIRT_POOL_NAME)
