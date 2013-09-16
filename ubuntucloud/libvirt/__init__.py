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

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import contextlib
import itertools
import os
import shutil
import tempfile

import libvirt
from lxml import etree
from lxml.builder import E


def get_libvirt_pool_object(libvirt_conn, pool_name):
    try:
        pool = libvirt_conn.storagePoolLookupByName(pool_name)
    except libvirt.libvirtError:
        raise RuntimeError("Cannot find pool %s." % repr(pool_name))
    return pool


def create_volume_from_fobj(new_volume_name, fobj, image_type='raw',
        pool_name='default'):
    """Create a new libvirt volume and populate it from a file-like object."""

    try:
        fobj_fileno = fobj.fileno()
    except AttributeError:
        # vol.upload() in create_volume_from_fobj_with_size needs to know the
        # file size in advance. Since fobj doesn't support this (eg. it's an
        # HTTP download), copy the data to a temporary file and use that
        # instead.
        temp_fobj = tempfile.TemporaryFile(prefix='ubuntucloud-libvirt')
        with contextlib.closing(temp_fobj):
            shutil.copyfileobj(fobj, temp_fobj)
            temp_fobj.seek(0)
            return _create_volume_from_fobj_with_size(
                new_volume_name=new_volume_name,
                fobj=temp_fobj,
                fobj_size=os.fstat(temp_fobj.fileno()).st_size,
                image_type=image_type,
                pool_name=pool_name
            )
    else:
        return _create_volume_from_fobj_with_size(
            new_volume_name=new_volume_name,
            fobj=fobj,
            fobj_size=os.fstat(fobj_fileno).st_size,
            image_type=image_type,
            pool_name=pool_name
        )


def _create_volume_from_fobj_with_size(new_volume_name, fobj, fobj_size,
        image_type, pool_name):
    conn = libvirt.open('qemu:///system')
    pool = get_libvirt_pool_object(conn, pool_name)

    if image_type == 'raw':
        extra = [E.allocation(str(fobj_size)), E.capacity(str(fobj_size))]
    elif image_type == 'qcow2':
        extra = [E.capacity('0')]
    else:
        raise NotImplementedError("Unknown image type %r." % image_type)

    new_vol = E.volume(
        E.name(new_volume_name),
        E.target(E.format(type=image_type)),
        *extra
        )
    vol = pool.createXML(etree.tostring(new_vol), 0)

    stream = conn.newStream(0)
    vol.upload(stream, 0, fobj_size, 0)

    def handler(stream_ignored, size, opaque_ignored):
        return fobj.read(size)

    stream.sendAll(handler, None)
    stream.finish()

    return vol


def volume_names_in_pool(pool_name='default'):
    conn = libvirt.open('qemu:///system')
    pool = get_libvirt_pool_object(conn, pool_name)
    return pool.listVolumes()


def delete_volume_by_name(volume_name, pool_name='default'):
    conn = libvirt.open('qemu:///system')
    pool = get_libvirt_pool_object(conn, pool_name)
    volume = pool.storageVolLookupByName(volume_name)
    volume.delete(flags=0)


def have_volume_by_name(volume_name, pool_name='default'):
    conn = libvirt.open('qemu:///system')
    pool = get_libvirt_pool_object(conn, pool_name)
    try:
        volume = pool.storageVolLookupByName(volume_name)
    except libvirt.libvirtError:
        return False
    else:
        return True


def _get_all_domains(conn=None):
    if conn is None:
        conn = libvirt.open('qemu:///system')

    # libvirt in Precise doesn't seem to have a binding for
    # virConnectListAllDomains, and it seems that we must enumerate
    # defined-by-not-running and running instances separately and in different
    # ways.

    for domain_id in conn.listDomainsID():
        yield conn.lookupByID(domain_id)

    for domain_name in conn.listDefinedDomains():
        yield conn.lookupByName(domain_name)


def _domain_element_to_volume_paths(element):
    assert element.tag == 'domain'
    return (
        source.get('file')
        for source in element.xpath(
            "/domain/devices/disk[@type='file']/source[@file]"
        )
    )


def _domain_volume_paths(domain):
    volume_paths = set()

    for flags in [0, libvirt.VIR_DOMAIN_XML_INACTIVE]:
        element = etree.fromstring(domain.XMLDesc(flags))
        volume_paths.update(_domain_element_to_volume_paths(element))

    return frozenset(volume_paths)


def _volume_element_to_volume_paths(element):
    assert element.tag == 'volume'
    return itertools.chain(
        (path.text for path in element.xpath('/volume/target/path')),
        (path.text for path in element.xpath('/volume/backingStore/path')),
    )


def _volume_volume_paths(volume):
    # Volumes can depend on other volumes ("backing stores"), so return all
    # paths a volume needs to function, including the top level one.
    volume_paths = set()

    element = etree.fromstring(volume.XMLDesc(0))
    volume_paths.update(_volume_element_to_volume_paths(element))

    return frozenset(volume_paths)


def _get_all_domain_volume_paths(conn=None):
    if conn is None:
        conn = libvirt.open('qemu:///system')

    all_volume_paths = set()
    for domain in _get_all_domains(conn):
        for path in _domain_volume_paths(domain):
            try:
                volume = conn.storageVolLookupByKey(path)
            except libvirt.libvirtError:
                # ignore a lookup failure, since if a volume doesn't exist,
                # it isn't reasonable to consider what backing volumes it may
                # have
                continue
            all_volume_paths.update(_volume_volume_paths(volume))

    return frozenset(all_volume_paths)


def get_all_domain_volume_names(conn=None, filter_by_dir=None):
    # Limitation: filter_by_dir must currently end in a '/' and be the
    # canonical path as libvirt returns it. Ideally I'd filter by pool instead,
    # but the libvirt API appears to not provide any method to find what pool a
    # volume is in when looked up by key.
    if conn is None:
        conn = libvirt.open('qemu:///system')

    for path in _get_all_domain_volume_paths(conn=conn):
        volume = conn.storageVolLookupByKey(path)
        if filter_by_dir and not volume.path().startswith(filter_by_dir):
            continue
        yield volume.name()
