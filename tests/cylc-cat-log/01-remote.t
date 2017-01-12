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
# Test "cylc cat-log" for remote tasks.
CYLC_TEST_IS_GENERIC=false
. $(dirname $0)/test_header
#-------------------------------------------------------------------------------
RC_ITEM='[test battery]remote host'
export CYLC_TEST_HOST=$(cylc get-global-config -i "${RC_ITEM}" 2>'/dev/null')
if [[ -z $CYLC_TEST_HOST ]]; then
    skip_all '"[test battery]remote host": not defined'
fi
set_test_number 14
create_test_globalrc "" "
[hosts]
   [[$CYLC_TEST_HOST]]
       retrieve job logs = False"
install_suite $TEST_NAME_BASE $TEST_NAME_BASE
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-validate
run_ok $TEST_NAME cylc validate $SUITE_NAME
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-run
suite_run_ok $TEST_NAME cylc run --debug $SUITE_NAME
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-task-out
cylc cat-log -o $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok '^the quick brown fox$' $TEST_NAME.out
#-------------------------------------------------------------------------------
TEST_NAME=$TEST_NAME_BASE-task-job
cylc cat-log $SUITE_NAME a-task.1 >$TEST_NAME.out
contains_ok $TEST_NAME.out - << __END__
# SCRIPT:
# Write to task stdout log
echo "the quick brown fox"
# Write to task stderr log
echo "jumped over the lazy dog" >&2
# Write to a custom log file
echo "drugs and money" > \${CYLC_TASK_LOG_ROOT}.custom-log
__END__
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-err
cylc cat-log -e $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "jumped over the lazy dog" $TEST_NAME.out
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-status
cylc cat-log -u $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "CYLC_BATCH_SYS_NAME=background" $TEST_NAME.out
#-------------------------------------------------------------------------------
# local
TEST_NAME=$TEST_NAME_BASE-task-activity
cylc cat-log -a $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok '\[job-submit ret_code\] 0' $TEST_NAME.out
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-custom
cylc cat-log -c 'job.custom-log' $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "drugs and money" $TEST_NAME.out
#-------------------------------------------------------------------------------
# local
TEST_NAME=$TEST_NAME_BASE-task-list-local-NN
cylc cat-log --list-local $SUITE_NAME a-task.1 >$TEST_NAME.out
cmp_ok $TEST_NAME.out <<__END__
job
job-activity.log
__END__
#-------------------------------------------------------------------------------
# local
TEST_NAME=$TEST_NAME_BASE-task-list-local-01
cylc cat-log --list-local -s 1 $SUITE_NAME a-task.1 >$TEST_NAME.out
cmp_ok $TEST_NAME.out <<__END__
job
job-activity.log
__END__
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-list-remote-NN
cylc cat-log --list-remote $SUITE_NAME a-task.1 >$TEST_NAME.out
cmp_ok $TEST_NAME.out <<__END__
job
job.custom-log
job.err
job.out
job.status
__END__
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-log-dir-NN
cylc cat-log --list-remote -l $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "$SUITE_NAME/log/job/1/a-task/NN$" $TEST_NAME.out
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-log-dir-01
cylc cat-log --list-remote -l -s 1 $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "$SUITE_NAME/log/job/1/a-task/01$" $TEST_NAME.out
#-------------------------------------------------------------------------------
# remote
TEST_NAME=$TEST_NAME_BASE-task-job-path
cylc cat-log -l $SUITE_NAME a-task.1 >$TEST_NAME.out
grep_ok "$SUITE_NAME/log/job/1/a-task/NN/job$" $TEST_NAME.out
#-------------------------------------------------------------------------------
# Clean up the task host.
ssh -n -oBatchMode=yes -oConnectTimeout=5 "${CYLC_TEST_HOST}" \
    "rm -rf 'cylc-run/${SUITE_NAME}'"
purge_suite $SUITE_NAME
exit
