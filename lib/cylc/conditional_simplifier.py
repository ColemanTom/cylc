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

import re
import ast
import copy
import sys


class ConditionalSimplifier(object):
    """A class to simplify logical expressions"""

    def __init__(self, expr, clean):
        self.raw_expression = expr
        self.clean_list = clean
        self.nested_expr = self.format_expr(self.raw_expression)

    def listify(self, message):
        """Convert a string containing a logical expression to a list"""
        message = message.replace("'", "\"")
        RE_CONDITIONALS = "(&|\||\(|\))"
        tokenised = re.split("(&|\||\(|\))", message)
        listified = ["["]
        for item in tokenised:
            if item.strip() != "" and item.strip() not in ["(", ")"]:
                listified.append("'" + item.strip() + "',")
            elif item.strip() == "(":
                listified.append("[")
            elif item.strip() == ")":
                if listified[-1].endswith(","):
                    listified[-1] = listified[-1][0:-1]
                listified.append("],")
        if listified[-1] == "],":
            listified[-1] = "]"
        listified.append("]")
        listified = (" ").join(listified)
        listified = ast.literal_eval(listified)
        return listified

    def get_bracketed(self, nest_me):
        """Nest a list according to any brackets in it"""
        start = 0
        finish = len(nest_me)
        indices = range(0, len(nest_me))
        for i in indices:
            if nest_me[i] == "(":
                start = i
                break
        else:
            return nest_me
        indices.reverse()
        for i in indices:
            if nest_me[i] == ")":
                finish = i
                break
        bracket_nested = nest_me[0:start + 1]
        bracket_nested.append(self.get_bracketed(nest_me[start + 1:finish]))
        bracket_nested.extend(nest_me[finish:len(nest_me)])
        return bracket_nested

    def get_cleaned(self):
        """Return the simplified logical expression"""
        cleaned = self.nested_expr
        for item in self.clean_list:
            cleaned = self.clean_expr(cleaned, item)
        cleaned = self.flatten_nested_expr(cleaned)
        return cleaned

    def nest_by_oper(self, nest_me, oper):
        """Nest a list based on a specified logical operation"""
        found = False
        for i in range(len(nest_me)):
            if isinstance(nest_me[i], list):
                nest_me[i] = self.nest_by_oper(nest_me[i], oper)
            if nest_me[i] == oper:
                found = i
                break
        if len(nest_me) <= 3:
            return nest_me
        if found:
            nested = nest_me[0:found - 1]
            nested += [nest_me[found - 1:found + 2]]
            if (found + 2) < len(nest_me):
                nested += nest_me[found + 2:]
            return self.nest_by_oper(nested, oper)
        else:
            return nest_me

    def clean_expr(self, nested_list, criterion):
        """Return a list with entries specified by 'criterion' removed"""
        cleaned = copy.deepcopy(nested_list)

        # Make sure that we don't have extraneous nesting.
        while (isinstance(cleaned, list) and len(cleaned) == 1 and
               isinstance(cleaned[0], list)):
            cleaned = cleaned[0]

        if len(cleaned) == 1:
            cleaned = cleaned[0]

        if isinstance(cleaned, str):
            if cleaned == criterion:
                return ""
            else:
                return cleaned

        # Recurse through the nested list and remove criterion.
        found = None
        for i in range(0, len(cleaned)):
            if isinstance(cleaned[i], list):
                cleaned[i] = self.clean_expr(cleaned[i], criterion)
            if cleaned[i] in [criterion, '']:
                found = i
                break

        if found is not None:
            # e.g. [ 'foo', '|', 'bar', '|']
            if found == 0:
                cleaned = cleaned[2:]
            else:
                del cleaned[found - 1:found + 1]
            return self.clean_expr(cleaned, criterion)
        else:
            return cleaned

    def format_expr(self, expr):
        """Carry out list conversion and nesting of a logical expression in
        the correct order."""
        listified = self.listify(expr)
        bracketed = self.get_bracketed(listified)
        nested_by_and = self.nest_by_oper(bracketed, "&")
        nested_by_or = self.nest_by_oper(nested_by_and, "|")
        return nested_by_or

    def flatten_nested_expr(self, expr):
        """Convert a logical expression in a nested list back to a string"""
        flattened = copy.deepcopy(expr)
        for i in range(len(flattened)):
            if isinstance(flattened[i], list):
                flattened[i] = self.flatten_nested_expr(flattened[i])
        if isinstance(flattened, list):
            flattened = (" ").join(flattened)
        flattened = "(" + flattened
        flattened += ")"
        return flattened
