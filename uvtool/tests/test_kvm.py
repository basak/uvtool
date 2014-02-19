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

import unittest

import mock

from uvtool.libvirt.kvm import main_ssh


class TestKVM(unittest.TestCase):
    def check_ssh(self, args_hostname, args_login_name, expected_hostname,
        expected_login_name):

        parser = mock.Mock()
        args = mock.Mock()
        args.login_name = args_login_name
        args.name = args_hostname
        args.ssh_arguments = mock.sentinel.ssh_arguments
        with mock.patch('uvtool.libvirt.kvm.ssh') as ssh_mock:
            main_ssh(parser, args)
            ssh_mock.assert_called_with(
                expected_hostname,
                expected_login_name,
                mock.sentinel.ssh_arguments
            )

    def test_ssh_default(self):
        # "uvt-kvm ssh foo" should use user 'ubuntu'
        self.check_ssh('foo', None, 'foo', 'ubuntu')

    def test_ssh_override_with_l_option(self):
        # "uvt-kvm ssh -l bar foo" should use user 'bar'
        self.check_ssh('foo', 'bar', 'foo', 'bar')

    def test_ssh_override_with_at_sign(self):
        # "uvt-kvm ssh bar@foo" should use user 'bar'
        self.check_ssh('bar@foo', None, 'foo', 'bar')

    def test_ssh_override_and_at_in_hostname(self):
        # "uvt-kvm ssh -l baz bar@foo"
        # In this obtuse case, the hostname has an '@' in it, so this should be
        # passed through.
        self.check_ssh('bar@foo', 'baz', 'bar@foo', 'baz')
