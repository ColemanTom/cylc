#!/usr/bin/env python2

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

"""xtrigger function to check a remote suite state.

"""

from datetime import datetime, timedelta
import os
import sqlite3
from cylc.cycling.util import add_offset
from cylc.cfgspec.glbl_cfg import glbl_cfg
from cylc.dbstatecheck import CylcSuiteDBChecker
from isodatetime.parsers import TimePointParser, DurationParser


def suite_state(suite, task, point, offset=None, status='succeeded',
                message=None, cylc_run_dir=None, debug=False,
                delay=None):
    """Connect to a suite DB and query the requested task state.

    Reports satisfied only if the remote suite state has been achieved, and
    if a delay has been specified, that the task reached that state at least
    'delay' time ago.

    If the 'delay' argument is used, it is advised to pair it with either a
    message or a status with only one option, such as 'succeeded' or 'failed'.
    If 'delay' is paired with a status such as 'start', then the delay will
    apply to the latest of the acceptable statuses (e.g. running, retrying,
    failed, succeeded). This could mean the delay is longer than desired.

    Returns all suite state args to pass on to triggering tasks.

    """
    # As status has a default, make message take precedence over status
    # if message is defined
    if message is not None:
        status = None

    cylc_run_dir = os.path.expandvars(
        os.path.expanduser(
            cylc_run_dir or glbl_cfg().get_host_item('run directory')))
    if offset is not None:
        point = str(add_offset(point, offset))
    try:
        checker = CylcSuiteDBChecker(cylc_run_dir, suite)
    except (OSError, sqlite3.Error):
        # Failed to connect to DB; target suite may not be started.
        return (False, None)
    fmt = checker.get_remote_point_format()
    if fmt:
        my_parser = TimePointParser()
        point = str(my_parser.parse(point, dump_format=fmt))

    satisfied = checker.task_state_met(task, point, message=message,
                                       status=status)

    # Extract the last time the condition was met and check if the
    # desired length of time to wait has been met
    time_remaining = 0

    if satisfied and delay is not None:
        my_parser = DurationParser()
        delay_as_seconds = int(my_parser.parse(delay).get_seconds())
        time_met = checker.get_last_time_state_met(task, point,
                                                   message=message,
                                                   status=status)
        # satisfied is no longer true, the task state must have been
        # reset in the time taken to get here
        if time_met is None:
            satisfied = False
        else:
            wait_time = time_met + timedelta(seconds=delay_as_seconds)
            time_remaining = (wait_time - datetime.utcnow()).total_seconds()
            satisfied = time_remaining <= 0

    results = {
        'suite': suite,
        'task': task,
        'point': point,
        'offset': offset,
        'status': status,
        'message': message,
        'cylc_run_dir': cylc_run_dir,
        'remaining_wait': max(0, time_remaining)
    }
    return (satisfied, results)
