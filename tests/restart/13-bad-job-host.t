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
# Test restarting a suite when the host of a submitted or running job is not
# available. https://github.com/cylc/cylc/issues/1327
CYLC_TEST_IS_GENERIC=false
. "$(dirname "$0")/test_header"
export CYLC_TEST_HOST=$( \
    cylc get-global-config -i '[test battery]remote host' 2>'/dev/null')
if [[ -z "${CYLC_TEST_HOST}" ]]; then
    skip_all '"[test battery]remote host": not defined'
fi
set_test_number 4
install_suite "${TEST_NAME_BASE}" bad-job-host
#-------------------------------------------------------------------------------
run_ok "${TEST_NAME_BASE}-validate" cylc validate "${SUITE_NAME}"
suite_run_ok "${TEST_NAME_BASE}-run" cylc run --debug "${SUITE_NAME}"
# Modify DB with garbage host
CYLC_SUITE_RUN_DIR="$(cylc get-global-config --print-run-dir)/${SUITE_NAME}"
for DB_NAME in 'cylc-suite.db' 'cylc-suite-private.db'; do
    sqlite3 "${CYLC_SUITE_RUN_DIR}/${DB_NAME}" \
        'UPDATE task_jobs SET user_at_host="garbage" WHERE name=="t-remote";'
done
suite_run_ok "${TEST_NAME_BASE}-restart" cylc restart --debug "${SUITE_NAME}"
grep_ok 'ERROR - garbage: initialisation did not complete' \
    "${CYLC_SUITE_RUN_DIR}/log/suite/err"
#-------------------------------------------------------------------------------
ssh -n -oBatchMode=yes -oConnectTimeout=5 "${CYLC_TEST_HOST}" \
    "rm -rf 'cylc-run/${SUITE_NAME}'"
purge_suite "${SUITE_NAME}"
exit
