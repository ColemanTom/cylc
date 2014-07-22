#!/bin/bash
#C: THIS FILE IS PART OF THE CYLC SUITE ENGINE.
#C: Copyright (C) 2008-2014 Hilary Oliver, NIWA
#C: 
#C: This program is free software: you can redistribute it and/or modify
#C: it under the terms of the GNU General Public License as published by
#C: the Free Software Foundation, either version 3 of the License, or
#C: (at your option) any later version.
#C:
#C: This program is distributed in the hope that it will be useful,
#C: but WITHOUT ANY WARRANTY; without even the implied warranty of
#C: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#C: GNU General Public License for more details.
#C:
#C: You should have received a copy of the GNU General Public License
#C: along with this program.  If not, see <http://www.gnu.org/licenses/>.
#-------------------------------------------------------------------------------
# Test default runahead limit behaviour is still the same
. $(dirname $0)/test_header
#-------------------------------------------------------------------------------
set_test_number 4
#-------------------------------------------------------------------------------
install_suite $TEST_NAME_BASE default-future
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-validate
run_ok $TEST_NAME cylc validate -v $SUITE_NAME
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-run
run_fail $TEST_NAME cylc run --debug $SUITE_NAME
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-check-fail
DB=$(cylc get-global-config --print-run-dir)/$SUITE_NAME/cylc-suite.db
RUNAHEAD=$(sqlite3 $DB "select max(cycle) from task_states")
# manual comparison for the test
if [[ "$RUNAHEAD" == "20100101T0600Z" ]]; then
    ok $TEST_NAME
else
    fail $TEST_NAME
fi 
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-check-timeout
LOG=$(cylc get-global-config --print-run-dir)/$SUITE_NAME/log/suite/log
run_ok $TEST_NAME grep 'suite timed out after' $LOG
#-------------------------------------------------------------------------------
purge_suite $SUITE_NAME
