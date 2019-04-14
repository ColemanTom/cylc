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

"""xtrigger function to check if a remote file contains specific text.

"""

import os
import shutil
from tempfile import mkdtemp
from cylc.cylc_subproc import procopen
from cylc.xtriggers import file_exists, file_contains


def remote_file_contains(user=None, host=None, path=None,
                         text=None, regex=False):
    """Return true if the file on the remote host contains the provided text"""

    # Construct a dictionary of arguments for the remote file check call. Do
    # this so that this function does not need to know the default values and
    # only passes in specified items.
    remote_check_args = {}
    if user:
        remote_check_args['user'] = user
    if host:
        remote_check_args['host'] = host
    if path:
        remote_check_args['path'] = path
    # If the remote file doesn't exist, then, skip any other checks
    if not file_exists.file_exists(**remote_check_args):
        return (False, {})

    # Copy the file over, wrapped in try/finally block to ensure it is deleted
    tmpdir = None
    result = (False, {})
    try:
        tmpdir = mkdtemp()
        tmpfile = os.path.join(tmpdir, 'tmpfile')
        cmd = ['rsync', '--timeout=1800',
               '--rsh=ssh -oBatchMode=yes -oConnectTimeout=10',
               file_exists.get_fully_specified_remote_path(user, host, path),
               tmpfile]
        devnull = open(os.devnull, 'wb')
        proc = procopen(cmd, stdout=devnull, stderr=devnull)
        if proc.wait() == 0:
            result = file_contains.file_contains(text=text, input_file=tmpfile,
                                                 regex=regex)
            result[1]['host'] = host
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir)

    return result
