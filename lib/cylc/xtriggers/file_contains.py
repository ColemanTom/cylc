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

"""xtrigger function to check if a file contains specific text.

"""

import re
from cylc.xtriggers import file_exists


def file_contains(text=None, input_file=None, regex=False):
    """Return true if the input_file contains the provided text"""
    if not file_exists.file_exists(path=input_file, host='localhost'):
        return (False, {})
    with open(input_file, 'r') as open_file:
        data = open_file.read()
    result = ''
    if regex:
        match = re.search(text, data)
        satisfied = match is not None
        if satisfied:
            # The result will only contain the first match
            result = match.group()
    else:
        satisfied = text in data
        result = text
    return (satisfied, {'text': result, 'path': input_file})
