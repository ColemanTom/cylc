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
# Test bad job submission, activity log has original command and some stderr
# with the host name written.
CYLC_TEST_IS_GENERIC=false
. "$(dirname "$0")/test_header"
CYLC_TEST_HOST="$( \
    cylc get-global-config -i '[test battery]remote host' 2>'/dev/null')"
if [[ -z "${CYLC_TEST_HOST}" ]]; then
    skip_all '"[test battery]remote host": not defined'
fi
set_test_number 2

install_suite "${TEST_NAME_BASE}" "${TEST_NAME_BASE}"

run_ok "${TEST_NAME_BASE}-validate" \
    cylc validate "${SUITE_NAME}" -s "CYLC_TEST_HOST=${CYLC_TEST_HOST}"
suite_run_ok "${TEST_NAME_BASE}-run" \
    cylc run --debug --reference-test -s "CYLC_TEST_HOST=${CYLC_TEST_HOST}" \
    "${SUITE_NAME}"

ssh -n -oBatchMode=yes -oConnectTimeout=5 "${CYLC_TEST_HOST}" \
    "rm -fr 'cylc-run/${SUITE_NAME}'"
purge_suite "${SUITE_NAME}"
exit
