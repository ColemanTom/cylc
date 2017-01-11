#!/bin/bash
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
#-------------------------------------------------------------------------------
# Test remote job logs retrieval, requires compatible version of cylc on remote
# job host.
CYLC_TEST_IS_GENERIC=false
. "$(dirname "$0")/test_header"
HOST=$(cylc get-global-config -i '[test battery]remote host' 2>'/dev/null')
if [[ -z "${HOST}" ]]; then
    skip_all '"[test battery]remote host": not defined'
fi
set_test_number 4
OPT_SET=
if [[ "${TEST_NAME_BASE}" == *-globalcfg ]]; then
    create_test_globalrc "" "
[hosts]
    [[${HOST}]]
        retrieve job logs = True
        retrieve job logs retry delays = PT5S"
    OPT_SET='-s GLOBALCFG=True'
else
    create_test_globalrc
fi

install_suite "${TEST_NAME_BASE}" "${TEST_NAME_BASE}"

run_ok "${TEST_NAME_BASE}-validate" \
    cylc validate ${OPT_SET} -s "HOST=${HOST}" "${SUITE_NAME}"
suite_run_ok "${TEST_NAME_BASE}-run" \
    cylc run --reference-test --debug ${OPT_SET} -s "HOST=${HOST}" "${SUITE_NAME}"

SUITE_RUN_DIR="$(cylc get-global-config '--print-run-dir')/${SUITE_NAME}"

sed "/'job-logs-retrieve'/!d" \
    "${SUITE_RUN_DIR}/log/job/1/t1/"{01,02,03}"/job-activity.log" \
    >'edited-activities.log'
cmp_ok 'edited-activities.log' <<'__LOG__'
[('job-logs-retrieve', 1) ret_code] 0
[('job-logs-retrieve', 2) ret_code] 0
[('job-logs-retrieve', 3) ret_code] 0
__LOG__

grep -F 'will run after' "${SUITE_RUN_DIR}/log/suite/log" \
    | cut -d' ' -f 4-10 | sort >"edited-log"
if [[ "${TEST_NAME_BASE}" == *-globalcfg ]]; then
    cmp_ok 'edited-log' <<'__LOG__'
[t1.1] -('job-logs-retrieve', 1) will run after PT5S
[t1.1] -('job-logs-retrieve', 2) will run after PT5S
[t1.1] -('job-logs-retrieve', 3) will run after PT5S
__LOG__
else
    cmp_ok 'edited-log' <'/dev/null'  # P0Y not displayed
fi

ssh -n -oBatchMode=yes -oConnectTimeout=5 "${HOST}" \
    "rm -rf 'cylc-run/${SUITE_NAME}'"
purge_suite "${SUITE_NAME}"
exit
