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

import distutils.core
import glob

VERSION = '0.1'


distutils.core.setup(
    name="ubuntu-cloud-utils",
    description="Library and tools for using Ubuntu Cloud Images",
    version=VERSION,
    author="Robie Basak",
    license="AGPL3+",
    packages=['ubuntucloud.libvirt'],
    scripts=glob.glob('bin/*'),
    data_files=[
        ('/usr/share/ubuntucloud/libvirt', ['template.xml'])
    ],
)
