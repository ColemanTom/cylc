#!/usr/bin/env python2

# THIS FILE IS PART OF THE CYLC SUITE ENGINE.
# Copyright (C) 2008-2020 NIWA & British Crown (Met Office) & Contributors.
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

import unittest
import mock
from cylc.dbstatecheck import CylcSuiteDBChecker


class TestCylcSuiteDBChecker(unittest.TestCase):
    """Unit tests for the CylcSuiteDBChecker class"""

    @mock.patch("sqlite3.connect")
    @mock.patch("os.path.exists")
    def setUp(self, mock_connect, mock_pathexists):
        mock_pathexists.return_value = True
        self.db = CylcSuiteDBChecker("/tmp", "none")

    def test__setup_task_query_no_status_message(self):
        arg, where = self.db._setup_task_query("task", 1)
        self.assertEqual(arg, ["task", 1])
        self.assertEqual(where, ["name==?", "cycle==?"])

    def test__setup_task_query_simple_status_no_cycle(self):
        arg, where = self.db._setup_task_query("task", status="succeeded")
        self.assertEqual(arg, ["task", "succeeded"])
        self.assertEqual(where, ["name==?", "(status==?)"])

    def test__setup_task_query_complex_status_no_task_rename_status(self):
        arg, where = self.db._setup_task_query(cycle=1, status="finish",
                                               status_label="event")
        self.assertEqual(arg, [1, "failed", "succeeded"])
        self.assertEqual(where, ["cycle==?", "(event==? OR event==?)"])
