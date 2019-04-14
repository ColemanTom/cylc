# -*- coding: utf-8 -*-

# THIS FILE IS PART OF THE CYLC SUITE ENGINE.
# Copyright (C) 2008-2019 NIWA & British Crown (Met Office) & Contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""xtrigger function to check if a remote file exists.

"""

import os
from cylc.cylc_subproc import procopen

LOCAL_HOST_EQUIVALENTS = ('localhost', '127.0.0.1')


def file_exists(user=None, host='localhost', path=os.sep):
    """Return true if the path exists

    file_type can be one of 'any', 'file', 'dir'
    """
    results_dict = {'host': host, 'path': path}
    if host in LOCAL_HOST_EQUIVALENTS:
        # We assume that everthing is world readable and we do not
        # need to escalate privileges to see the file, so 'user' does
        # not matter
        return (os.path.exists(path), results_dict)

    path = get_fully_specified_remote_path(user, host, path)
    cmd = ['rsync', '--timeout=300',
           '--rsh=ssh -oBatchMode=yes -oConnectTimeout=10', path]
    devnull = open(os.devnull, 'wb')
    proc = procopen(cmd, stdout=devnull, stderr=devnull)
    return (proc.wait() == 0, results_dict)


def get_fully_specified_remote_path(user, host, path):
    """Construct full path to remote file"""
    path = '{host}:{path}'.format(host=host, path=path)
    if user:
        path = '{user}@{path}'.format(user=user, path=path)
    return path
