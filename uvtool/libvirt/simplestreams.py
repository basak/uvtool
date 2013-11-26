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

import argparse
import base64
import codecs
import collections
import errno
import json
import os
import subprocess
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


class Metadata(object):
    def __init__(self, metadata_dir=METADATA_DIR):
        self.metadata_dir = metadata_dir
        # Deliberately do not create metadata_dir as a side-effect here, since
        # this class is instantiated below when the module is loaded, and we
        # want to be able to test this module without the side-effect of it
        # affecting the system metadata directory.

    def _metadata_path(self, encoded_libvirt_image_name):
        return os.path.join(self.metadata_dir, encoded_libvirt_image_name)

    def __contains__(self, encoded_libvirt_image_name):
        return os.path.exists(self._metadata_path(encoded_libvirt_image_name))

    def __delitem__(self, encoded_libvirt_image_name):
        os.unlink(self._metadata_path(encoded_libvirt_image_name))

    def __setitem__(self, encoded_libvirt_image_name, metadata):
        mkdir_p(self.metadata_dir)
        with codecs.open(
                self._metadata_path(encoded_libvirt_image_name), 'wb',
                encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)

    def __getitem__(self, encoded_libvirt_image_name):
        with codecs.open(
                self._metadata_path(encoded_libvirt_image_name), 'rb',
                encoding='utf-8') as f:
            return json.load(f)

    def keys(self):
        try:
            return os.listdir(self.metadata_dir)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            return []

    def items(self):
        return [(key, self[key]) for key in self.keys()]


pool_metadata = Metadata(METADATA_DIR)

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


def purge_pool(conn=None):
    '''Delete all volumes and metadata with prejudice.

    This removes images from the pool whether they are in use or not.

    '''
    # Remove all metadata first. If this is interrupted, then it just looks
    # like there are volumes waiting to be cleaned up.
    for key in pool_metadata.keys():
        del pool_metadata[key]

    # Remove actual volumes themselves
    if conn is None:
        conn = libvirt.open('qemu:///system')
    pool = uvtool.libvirt.get_libvirt_pool_object(conn, LIBVIRT_POOL_NAME)
    for volume_name in pool.listVolumes():
        volume = pool.storageVolLookupByName(volume_name)
        volume.delete()


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
                not encoded_libvirt_name in pool_metadata):
            uvtool.libvirt.delete_volume_by_name(
                encoded_libvirt_name, pool_name=LIBVIRT_POOL_NAME)


def _load_products(path=None, content_id=None, clean=False):
    # If clean evaluates to True, then remove any metadata files for which
    # the corresponding volume is missing.
    def new_product():
        return {'versions': {}}
    products = collections.defaultdict(new_product)
    for encoded_libvirt_name_string, metadata in pool_metadata.items():
        encoded_libvirt_name_bytes = encoded_libvirt_name_string.encode(
            'utf-8')
        if not uvtool.libvirt.have_volume_by_name(
                encoded_libvirt_name_bytes, pool_name=LIBVIRT_POOL_NAME):
            if clean:
                del pool_metadata[encoded_libvirt_name_string]
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
        pool_metadata[encoded_libvirt_name] = (
            simplestreams.util.products_exdata(src, pedigree)
        )

    def remove_version(self, data, src, target, pedigree):
        product_name, version_name = pedigree
        if self.verbose:
            print("Removing: %s %s" % (product_name, version_name))
        encoded_libvirt_name = _encode_libvirt_pool_name(
            product_name, version_name)
        del pool_metadata[encoded_libvirt_name]
        uvtool.libvirt.delete_volume_by_name(
            encoded_libvirt_name, pool_name=LIBVIRT_POOL_NAME)


def main_sync(args):
    (mirror_url, initial_path) = simplestreams.util.path_from_mirror_url(
        args.mirror_url, args.path)

    def policy(content, path):
        if initial_path.endswith('sjson') and not args.no_authentication:
            return simplestreams.util.read_signed(
                content, keyring=args.keyring)
        else:
            return content

    smirror = simplestreams.mirrors.UrlMirrorReader(
        mirror_url, policy=policy)

    filter_list = simplestreams.filters.get_filters(
        ['datatype=image-downloads', 'ftype=disk1.img'] + args.filters
    )
    tmirror = LibvirtMirror(filter_list, verbose=args.verbose)
    tmirror.sync(smirror, initial_path)
    clean_extraneous_images()


def main_query(args):
    result = query(args.filters)
    print(*result, sep="\n")


def main_purge(args):
    purge_pool()


def main(argv=None):
    print(
        "Warning: this CLI is experimental and may change.",
        file=sys.stderr
    )
    system_arch = subprocess.check_output(
        ['dpkg', '--print-architecture']).decode().strip()
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='store_true')
    subparsers = parser.add_subparsers()

    sync_subparser = subparsers.add_parser('sync')
    sync_subparser.set_defaults(func=main_sync)
    sync_subparser.add_argument(
        '--path', default=None,
        help='sync from index or products file in mirror'
    )
    sync_subparser.add_argument(
        '--keyring',
        help='keyring to be specified to gpg via --keyring',
        default='/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg'
    )
    sync_subparser.add_argument('--source', dest='mirror_url',
        default='https://cloud-images.ubuntu.com/releases/')
    sync_subparser.add_argument('--no-authentication', action='store_true')
    sync_subparser.add_argument('filters', nargs='*', metavar='filter',
        default=["arch=%s" % system_arch])

    query_subparser = subparsers.add_parser('query')
    query_subparser.set_defaults(func=main_query)
    query_subparser.add_argument(
        'filters', nargs='*', default=[], metavar='filter')

    purge_subparser = subparsers.add_parser('purge')
    purge_subparser.set_defaults(func=main_purge)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
