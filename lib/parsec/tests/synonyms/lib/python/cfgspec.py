#!/usr/bin/env python

# THIS FILE IS PART OF THE CYLC SUITE ENGINE.
# Copyright (C) 2008-2017 NIWA
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

from parsec.validate import validator as vdr

SPEC = {
        'boolean' : {
            '__MANY__' : { '__MANY__' : vdr( vtype="boolean" ) },
            }, 
        'integer' : { 
            '__MANY__' : { '__MANY__' : vdr( vtype="integer" ) },
            },
        'float'   : { 
            '__MANY__' : { '__MANY__' : vdr( vtype="float"   ) },
            },
        'string'  : {
            '__MANY__' : { '__MANY__' : vdr( vtype="string"  ) },
            },
        'string_list' : {
            '__MANY__' : { '__MANY__'   : vdr( vtype="string_list" ) },
            },
        'float_list' : {
            '__MANY__' : { '__MANY__' : vdr( vtype="float_list", allow_zeroes=False   ) },
            },
        'integer_list' : {
            '__MANY__' : { '__MANY__' : vdr( vtype="integer_list", allow_zeroes=False   ) },
            },
        }
