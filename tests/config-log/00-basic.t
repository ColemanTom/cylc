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
# Test suite config logging.
. $(dirname $0)/test_header
#-------------------------------------------------------------------------------
set_test_number 8
#-------------------------------------------------------------------------------
install_suite $TEST_NAME_BASE $TEST_NAME_BASE
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-val
run_ok $TEST_NAME cylc validate $SUITE_NAME
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-run
suite_run_ok $TEST_NAME cylc run $SUITE_NAME
#-------------------------------------------------------------------------------
# Wait till the suite is finished
TEST_NAME=$TEST_NAME_BASE-monitor
RUN_DIR=$(cylc get-global-config --print-run-dir)/$SUITE_NAME
run_ok $TEST_NAME timeout 30 \
  $(cylc get-directory $SUITE_NAME)/bin/file-watcher.sh $RUN_DIR/suite-stopping
#-------------------------------------------------------------------------------
# Check for three dumped configs.
TEST_NAME=$TEST_NAME_BASE-logs
LOG_DIR=${RUN_DIR}/log/suiterc
ls $LOG_DIR | sed -e 's/.*-//g' > logs.txt
cmp_ok logs.txt <<__END__
run.rc
reload.rc
restart.rc
__END__
#-------------------------------------------------------------------------------
# The run and reload logs should be identical.
TEST_NAME=$TEST_NAME_BASE-comp1
RUN_LOG=$(ls $LOG_DIR/*run.rc)
REL_LOG=$(ls $LOG_DIR/*reload.rc)
RES_LOG=$(ls $LOG_DIR/*restart.rc)
cmp_ok $RUN_LOG $REL_LOG
run_ok "${TEST_NAME_BASE}-validate-run-rc" cylc validate "${RUN_LOG}"
run_ok "${TEST_NAME_BASE}-validate-restart-rc" cylc validate "${RES_LOG}"
#-------------------------------------------------------------------------------
# The run and restart logs should differ in the suite description.
TEST_NAME=$TEST_NAME_BASE-comp1
sort $RUN_LOG $RES_LOG | uniq -u > diff.txt
cmp_ok diff.txt <<__END__
description = the weather is bad
description = the weather is good
__END__
#-------------------------------------------------------------------------------
purge_suite $SUITE_NAME
