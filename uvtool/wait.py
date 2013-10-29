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

from __future__ import print_function
from __future__ import unicode_literals

import argparse
import contextlib
import functools
import socket
import sys
import time

import pyinotify

import uvtool.libvirt

SSH_PORT = 22


class LeaseModifyWaiter(object):
    def __init__(self):
        self.wm = pyinotify.WatchManager()
        self.notifier = pyinotify.Notifier(self.wm, pyinotify.ProcessEvent())

    def start_watching(self):
        self.wdd = self.wm.add_watch(
            uvtool.libvirt.LIBVIRT_DNSMASQ_LEASE_FILE, pyinotify.IN_MODIFY)

    def wait(self, timeout):
        if self.notifier.check_events(timeout=(timeout*1000)):
            self.notifier.read_events()
            self.notifier.process_events()
            return True
        else:
            return False

    def close(self):
        self.wm.close()


def lease_has_mac(mac):
    return uvtool.libvirt.mac_to_ip(mac) is not None


def wait_for_libvirt_dnsmasq_lease(mac, timeout):
    # Shortcut check to save inotify setup
    if lease_has_mac(mac):
        return True

    timeout_time = time.time() + timeout
    waiter = LeaseModifyWaiter()
    with contextlib.closing(waiter):
        waiter.start_watching()
        # Check after we've set up a watch to avoid the race of something
        # happening between the last check and the watch starting
        if lease_has_mac(mac):
            return True
        current_time = time.time()
        while current_time < timeout_time:
            remaining_time_to_timeout = timeout_time - current_time
            waiter.wait(timeout=remaining_time_to_timeout)
            if lease_has_mac(mac):
                return True
            current_time = time.time()
        return False


def has_open_ssh_port(host, timeout=4):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with contextlib.closing(s):
        s.settimeout(timeout)
        try:
            s.connect((host, SSH_PORT))
        except:
            return False
        else:
            return True


def poll_for_true(fn, interval, timeout):
    timeout_time = time.time() + timeout
    while time.time() < timeout_time:
        if fn():
            return True
        # This could do with a little more care to ensure that we never
        # sleep beyond timeout_time.
        time.sleep(interval)
    return False


def wait_for_open_ssh_port(host, interval, timeout):
    return poll_for_true(
        functools.partial(has_open_ssh_port, host),
        interval, timeout
    )


def main_libvirt_dnsmasq_lease(parser, args):
    if not wait_for_libvirt_dnsmasq_lease(mac=args.mac, timeout=args.timeout):
        print("cloud-wait: timed out", file=sys.stderr)
        sys.exit(1)


def main_ssh(parser, args):
    if not wait_for_open_ssh_port(args.host, args.interval, args.timeout):
        print("cloud-wait: timed out", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=float, default=120.0)
    subparsers = parser.add_subparsers()

    libvirt_dnsmasq_lease_parser = subparsers.add_parser(
        'libvirt-dnsmasq-lease')
    libvirt_dnsmasq_lease_parser.set_defaults(func=main_libvirt_dnsmasq_lease)
    libvirt_dnsmasq_lease_parser.add_argument('mac')

    ssh_parser = subparsers.add_parser('ssh')
    ssh_parser.set_defaults(func=main_ssh)
    ssh_parser.add_argument('--interval', type=float, default=8.0)
    ssh_parser.add_argument('host')

    args = parser.parse_args()
    args.func(parser, args)


if __name__ == '__main__':
    main()
