#!/usr/bin/python

# Copyright (C) 2014 Canonical Ltd.
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

KEY_TYPES = ['rsa', 'dsa', 'ecdsa', 'ed25519']

import os
import shutil
import subprocess
import tempfile


def _keygen(key_type, private_path):
    subprocess.check_call([
        'ssh-keygen',
        '-q',
        '-f', private_path,
        '-N', '',
        '-t', key_type,
        '-C', 'root@localhost'
    ])


def read_file(path):
    with open(path, 'rb') as f:
        return f.read()


def generate_ssh_host_keys():
    cloud_init_result = {}
    known_hosts_result = []
    tmp_dir = tempfile.mkdtemp(prefix='uvt-kvm.sshtmp')
    try:
        for key_type in KEY_TYPES:
            private_path = os.path.join(tmp_dir, key_type)
            _keygen(key_type, private_path)

            # ssh-keygen(1) defines that ".pub" is appended
            public_path = private_path + ".pub"

            key_type_utf8 = key_type.encode('utf-8')
            private_ci_key = key_type_utf8 + b'_private'
            public_ci_key = key_type_utf8 + b'_public'

            private_key = read_file(private_path)
            public_key = read_file(public_path)

            cloud_init_result[private_ci_key] = private_key
            cloud_init_result[public_ci_key] = public_key

            known_hosts_result.append(public_key)
    finally:
        shutil.rmtree(tmp_dir)

    return cloud_init_result, b''.join(known_hosts_result)
