#!/usr/bin/env python

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

import re, os, sys
import taskdef
from cylc.cfgspec.suite import get_suitecfg
from cylc.cycling.loader import (get_point, get_interval_cls,
                                 get_sequence, get_sequence_cls,
                                 init_cyclers, INTEGER_CYCLING_TYPE)
from envvar import check_varnames, expandvars
from copy import deepcopy, copy
from output import outputx
from graphnode import graphnode, GraphNodeError
from print_tree import print_tree
from prerequisites.conditionals import TriggerExpressionError
from regpath import RegPath
from trigger import triggerx
from parsec.util import replicate, pdeepcopy
import TaskID
from C3MRO import C3
from parsec.OrderedDict import OrderedDict
import flags

"""
Parse and validate the suite definition file, do some consistency
checking, then construct task proxy objects and graph structures.
"""

CLOCK_OFFSET_RE = re.compile('(\w+)\s*\(\s*([-+]*\s*[\d.]+)\s*\)')
TRIGGER_TYPES = [ 'submit', 'submit-fail', 'start', 'succeed', 'fail', 'finish' ]

try:
    import graphing
except ImportError:
    graphing_disabled = True
else:
    graphing_disabled = False


class Replacement(object):
    """A class to remember match group information in re.sub() calls"""
    def __init__(self, replacement):
        self.replacement = replacement
        self.substitutions = []
        self.match_groups = []

    def __call__(self, match):
        matched = match.group(0)
        replaced = match.expand(self.replacement)
        self.substitutions.append((matched, replaced))
        self.match_groups.append( match.groups() )
        return replaced


class SuiteConfigError( Exception ):
    """
    Attributes:
        message - what the problem is.
        TODO - element - config element causing the problem
    """
    def __init__( self, msg ):
        self.msg = msg
    def __str__( self ):
        return repr(self.msg)

class TaskNotDefinedError( SuiteConfigError ):
    pass

# TODO: separate config for run and non-run purposes?

class config( object ):
    def __init__( self, suite, fpath, template_vars=[],
            template_vars_file=None, owner=None, run_mode='live',
            validation=False, strict=False, collapsed=[],
            cli_start_tag=None, is_restart=False, is_reload=False,
            write_proc=True ):

        self.suite = suite  # suite name
        self.fpath = fpath  # suite definition
        self.fdir  = os.path.dirname(fpath)
        self.owner = owner
        self.run_mode = run_mode
        self.strict = strict
        self.naked_dummy_tasks = []
        self.edges = []
        self.taskdefs = {}
        self.validation = validation
        self.cli_start_tag = cli_start_tag
        self.is_restart = is_restart
        self.first_graph = True
        self.clock_offsets = {}
        self.suite_polling_tasks = {}
        self.triggering_families = []

        self.async_repeating_edges = []
        self.async_repeating_tasks = []
        self.cycling_tasks = []

        self.sequences = []
        self.actual_first_ctime = None

        self.runahead_limit = None

        # runtime hierarchy dicts keyed by namespace name:
        self.runtime = {
                # lists of parent namespaces
                'parents' : {},
                # lists of C3-linearized ancestor namespaces
                'linearized ancestors' : {},
                # lists of first-parent ancestor namepaces
                'first-parent ancestors' : {},
                # lists of all descendant namespaces
                # (not including the final tasks)
                'descendants' : {},
                # lists of all descendant namespaces from the first-parent hierarchy
                # (first parents are collapsible in suite visualization)
                'first-parent descendants' : {},
                }
        # tasks
        self.leaves = []
        # one up from root
        self.feet = []

        # parse, upgrade, validate the suite, but don't expand with default items
        self.pcfg = get_suitecfg( fpath, force=is_reload,
                tvars=template_vars, tvars_file=template_vars_file,
                write_proc=write_proc )
        self.cfg = self.pcfg.get(sparse=True)

        if 'cycling' not in self.cfg['scheduling']:
            # Auto-detect integer cycling for pure async graph suites.
            dependency_map = self.cfg.get('scheduling', {}).get(
                'dependencies', {})
            if dependency_map.get('graph'):
                # There is an async graph setting.
                for item, value in dependency_map.items():
                    if item == 'graph':
                        continue
                    if value.get('graph'):
                        break
                else:
                    # There aren't any other graphs, so set integer cycling.
                    self.cfg['scheduling']['cycling'] = INTEGER_CYCLING_TYPE
                    if 'initial cycle time' not in self.cfg['scheduling']:
                        self.cfg['scheduling']['initial cycle time'] = "1"
                    if 'final cycle time' not in self.cfg['scheduling']:
                        self.cfg['scheduling']['final cycle time'] = "1"

        # allow test suites with no [runtime]:
        if 'runtime' not in self.cfg:
            self.cfg['runtime'] = {}

        if 'root' not in self.cfg['runtime']:
            self.cfg['runtime']['root'] = {}

        if flags.verbose:
            print "Expanding [runtime] name lists"
        # If a runtime section heading is a list of names then the
        # subsequent config applies to each member.
        for item in self.cfg['runtime'].keys():
            if re.search( ',', item ):
                # list of task names
                # remove trailing commas and spaces
                tmp = item.rstrip(', ')
                task_names = re.split(' *, *', tmp )
            else:
                # a single task name
                continue
            # generate task configuration for each list member
            for name in task_names:
                self.cfg['runtime'][name] = pdeepcopy( self.cfg['runtime'][item] )
            # delete the original multi-task section
            del self.cfg['runtime'][item]

        # check var names before inheritance to avoid repetition
        self.check_env_names()

        # do sparse inheritance
        self.compute_family_tree()
        self.compute_inheritance()

        #self.print_inheritance() # (debugging)

        # filter task environment variables after inheritance
        self.filter_env()

        # now expand with defaults
        self.cfg = self.pcfg.get( sparse=False )

        init_cyclers(self.cfg)

        # [special tasks]: parse clock-offsets, and replace families with members
        if flags.verbose:
            print "Parsing [special tasks]"
        for type in self.cfg['scheduling']['special tasks']:
            result = copy( self.cfg['scheduling']['special tasks'][type] )
            for item in self.cfg['scheduling']['special tasks'][type]:
                if type != 'clock-triggered':
                    name = item
                    extn = ''
                else:
                    m = re.match( CLOCK_OFFSET_RE, item )
                    if m:
                        name, offset = m.groups()
                        try:
                            float( offset )
                        except ValueError:
                            raise SuiteConfigError, "ERROR: Illegal clock-triggered task spec: " + item
                        extn = '(' + offset + ')'
                    else:
                        raise SuiteConfigError, "ERROR: Illegal clock-triggered task spec: " + item
                if name in self.runtime['descendants']:
                    # is a family
                    result.remove( item )
                    for member in self.runtime['descendants'][name]:
                        if member in self.runtime['descendants']:
                            # is a sub-family
                            continue
                        result.append( member + extn )
                        if type == 'clock-triggered':
                            self.clock_offsets[ member ] = float( offset )
                elif type == 'clock-triggered':
                    self.clock_offsets[ name ] = float( offset )
            self.cfg['scheduling']['special tasks'][type] = result

        self.collapsed_families_rc = self.cfg['visualization']['collapsed families']
        if is_reload:
            # on suite reload retain an existing state of collapse
            # (used by the "cylc graph" viewer)
            self.closed_families = collapsed
            fromrc = False
        else:
            self.closed_families = self.collapsed_families_rc
            fromrc = True
        for cfam in self.closed_families:
            if cfam not in self.runtime['descendants']:
                self.closed_families.remove( cfam )
                if fromrc and flags.verbose:
                    print >> sys.stderr, 'WARNING, [visualization][collapsed families]: family ' + cfam + ' not defined'

        # check for run mode override at suite level
        if self.cfg['cylc']['force run mode']:
            self.run_mode = self.cfg['cylc']['force run mode']

        self.process_directories()

        self.load_graph()

        if not self.graph_found:
            raise SuiteConfigError, 'No suite dependency graph defined.'

        self.compute_runahead_limit()

        self.configure_queues()

        # Warn or abort (if --strict) if naked dummy tasks (no runtime
        # section) are found in graph or queue config.
        if len( self.naked_dummy_tasks ) > 0:
            if self.strict or flags.verbose:
                print >> sys.stderr, 'WARNING: naked dummy tasks detected (no entry under [runtime]):'
                for ndt in self.naked_dummy_tasks:
                    print >> sys.stderr, '  +', ndt
            if self.strict:
                raise SuiteConfigError, 'ERROR: strict validation fails naked dummy tasks'

        if self.validation:
            self.check_tasks()

        # initial and final cycles for visualization
        vict = self.cfg['visualization']['initial cycle time'] or \
                str( self.get_actual_first_ctime( self.cfg['scheduling']['initial cycle time'] ))
        self.cfg['visualization']['initial cycle time'] = vict

        vict_rh = None
        if vict and self.runahead_limit:
            vict_rh = str( get_point( vict ) + self.runahead_limit )
        
        vfct = self.cfg['visualization']['final cycle time'] or vict_rh or vict
        self.cfg['visualization']['final cycle time'] = vfct

        ngs = self.cfg['visualization']['node groups']

        # If any existing node group member is a family, include its descendants too.
        replace = {}
        for ng, mems in ngs.items():
            replace[ng] = []
            for mem in mems:
                replace[ng] += [mem]
                if mem in self.runtime['descendants']:
                    replace[ng] += self.runtime['descendants'][mem]
        for ng in replace:
            ngs[ng] = replace[ng]

        # Define family node groups automatically so that family and
        # member nodes can be styled together using the family name.
        # Users can override this for individual nodes or sub-groups.
        for fam in self.runtime['descendants']:
            if fam not in ngs:
                ngs[fam] = [fam] + self.runtime['descendants'][fam]

        if flags.verbose:
            print "Checking [visualization] node attributes"
            # 1. node groups should contain valid namespace names
            nspaces = self.cfg['runtime'].keys()
            bad = {}
            for ng,mems in ngs.items():
                n_bad = []
                for m in mems:
                    if m not in nspaces:
                        n_bad.append(m)
                if n_bad:
                    bad[ng] = n_bad
            if bad:
                print >> sys.stderr, "  WARNING: undefined node group members"
                for ng,mems in bad.items():
                    print >> sys.stderr, " + " + ng + ":", ','.join(mems)

            # 2. node attributes must refer to node groups or namespaces
            bad = []
            for na in self.cfg['visualization']['node attributes']:
                if na not in ngs and na not in nspaces:
                    bad.append(na)
            if bad:
                print >> sys.stderr, "  WARNING: undefined node attribute targets"
                for na in bad:
                    print >> sys.stderr, " + " + na

        # (Note that we're retaining 'default node attributes' even
        # though this could now be achieved by styling the root family,
        # because putting default attributes for root in the suite.rc spec
        # results in root appearing last in the ordered dict of node
        # names, so it overrides the styling for lesser groups and
        # nodes, whereas the reverse is needed - fixing this would
        # require reordering task_attr in lib/cylc/graphing.py).

        self.leaves = self.get_task_name_list()
        for ns, ancestors in self.runtime['first-parent ancestors'].items():
            try:
                foot = ancestors[-2] # one back from 'root'
            except IndexError:
                pass
            else:
                if foot not in self.feet:
                    self.feet.append(foot)

    def check_env_names( self ):
        # check for illegal environment variable names
         bad = {}
         for label in self.cfg['runtime']:
             res = []
             if 'environment' in self.cfg['runtime'][label]:
                 res = check_varnames( self.cfg['runtime'][label]['environment'] )
             if res:
                 bad[label] = res
         if bad:
             print >> sys.stderr, "ERROR, bad env variable names:"
             for label, vars in bad.items():
                 print >> sys.stderr, 'Namespace:', label
                 for var in vars:
                     print >> sys.stderr, "  ", var
             raise SuiteConfigError("Illegal env variable name(s) detected" )

    def filter_env( self ):
        # filter environment variables after sparse inheritance
        for name, ns in self.cfg['runtime'].items():
            try:
                oenv = ns['environment']
            except KeyError:
                # no environment to filter
                continue

            try:
                fincl = ns['environment filter']['include']
            except KeyError:
                # empty include-filter means include all
                fincl = []

            try:
                fexcl = ns['environment filter']['exclude']
            except KeyError:
                # empty exclude-filter means exclude none
                fexcl = []

            if not fincl and not fexcl:
                # no filtering to do
                continue

            nenv = OrderedDict()
            for key, val in oenv.items():
                if ( not fincl or key in fincl ) and key not in fexcl:
                    nenv[key] = val
            ns['environment'] = nenv

    def compute_family_tree( self ):
        first_parents = {}
        demoted = {}
        for name in self.cfg['runtime']:
            if name == 'root':
                self.runtime['parents'][name] = []
                first_parents[name] = []
                continue
            # get declared parents, with implicit inheritance from root.
            pts = self.cfg['runtime'][name].get( 'inherit', ['root'] )
            for p in pts:
                if p == "None":
                    # see just below
                    continue
                if p not in self.cfg['runtime']:
                    raise SuiteConfigError, "ERROR, undefined parent for " + name +": " + p
            if pts[0] == "None":
                if len(pts) == 1:
                    raise SuiteConfigError, "ERROR: null parentage for " + name
                demoted[name] = pts[1]
                pts = pts[1:]
                first_parents[name] = ['root']
            else:
                first_parents[name] = [ pts[0] ]
            self.runtime['parents'][name] = pts

        if flags.verbose and demoted:
            print "First parent(s) demoted to secondary:"
            for n,p in demoted.items():
                print " +", p, "as parent of '" + n + "'"

        c3 = C3( self.runtime['parents'] )
        c3_single = C3( first_parents )

        for name in self.cfg['runtime']:
            self.runtime['linearized ancestors'][name] = c3.mro(name)
            self.runtime['first-parent ancestors'][name] = c3_single.mro(name)

        for name in self.cfg['runtime']:
            ancestors = self.runtime['linearized ancestors'][name]
            for p in ancestors[1:]:
                if p not in self.runtime['descendants']:
                    self.runtime['descendants'][p] = []
                if name not in self.runtime['descendants'][p]:
                    self.runtime['descendants'][p].append(name)
            first_ancestors = self.runtime['first-parent ancestors'][name]
            for p in first_ancestors[1:]:
                if p not in self.runtime['first-parent descendants']:
                    self.runtime['first-parent descendants'][p] = []
                if name not in self.runtime['first-parent descendants'][p]:
                    self.runtime['first-parent descendants'][p].append(name)

        #for name in self.cfg['runtime']:
        #    print name, self.runtime['linearized ancestors'][name]

    def compute_inheritance( self, use_simple_method=True ):
        if flags.verbose:
            print "Parsing the runtime namespace hierarchy"

        results = {}
        n_reps = 0

        already_done = {} # to store already computed namespaces by mro

        for ns in self.cfg['runtime']:
            # for each namespace ...

            hierarchy = copy(self.runtime['linearized ancestors'][ns])
            hierarchy.reverse()

            result = {}

            if use_simple_method:
                # Go up the linearized MRO from root, replicating or
                # overriding each namespace element as we go.
                for name in hierarchy:
                    replicate( result, self.cfg['runtime'][name] )
                    n_reps += 1

            else:
                # As for the simple method, but store the result of each
                # completed MRO (full or partial) as we go, and re-use
                # these wherever possible. This ought to be a lot more
                # efficient for big namespaces (e.g. lots of environment
                # variables) in deep hiearchies, but results may vary...
                prev_shortcut = False
                mro = []
                for name in hierarchy:
                    mro.append(name)
                    i_mro = '*'.join(mro)
                    if i_mro in already_done:
                        ad_result = already_done[i_mro]
                        prev_shortcut = True
                    else:
                        if prev_shortcut:
                            prev_shortcut = False
                            # copy ad_result (to avoid altering already_done)
                            result = {}
                            replicate(result,ad_result) # ...and use stored
                            n_reps += 1
                        # override name content into tmp
                        replicate( result, self.cfg['runtime'][name] )
                        n_reps += 1
                        # record this mro as already done
                        already_done[i_mro] = result

            results[ns] = result

        # replace pre-inheritance namespaces with the post-inheritance result
        self.cfg['runtime'] = results

        # uncomment this to compare the simple and efficient methods
        # print '  Number of namespace replications:', n_reps

    def print_inheritance(self):
        # (use for debugging)
        for foo in self.runtime:
            print '  ', foo
            for item, val in self.runtime[foo].items():
                print '  ', '  ', item, val

    def compute_runahead_limit( self ):
        rfactor = self.cfg['scheduling']['runahead factor']
        if not rfactor:
            # no runahead limit!
            return
        try:
            rfactor = int( rfactor )
        except ValueError:
            raise SuiteConfigError, "ERROR, illegal runahead limit: " + str(rfactor)

        rlim = None
        intervals = []
        offsets = []
        for seq in self.sequences:
            i = seq.get_interval()
            if i:
                intervals.append( i )
            offsets.append( seq.get_offset() )

        if intervals:
            rlim = min( intervals ) * rfactor
        if offsets:
           min_offset = min( offsets )
           if min_offset < get_interval_cls().get_null():
               # future triggers...
               if abs(min_offset) >= rlim:
                   #... that extend past the default rl
                   # set to offsets plus one minimum interval
                   rlim = abs(min_offset) + rlim

        self.runahead_limit = rlim
        if flags.verbose:
            print "Runahead limit:", self.runahead_limit

    def get_runahead_limit( self ):
        # may be None (no cycling tasks)
        return self.runahead_limit

    def get_config( self, args, sparse=False ):
        return self.pcfg.get( args, sparse )

    def adopt_orphans( self, orphans ):
        # Called by the scheduler after reloading the suite definition
        # at run time and finding any live task proxies whose
        # definitions have been removed from the suite. Keep them
        # in the default queue and under the root family, until they
        # run their course and disappear.
        queues = self.cfg['scheduling']['queues']
        for orphan in orphans:
            self.runtime['linearized ancestors'][orphan] = [ orphan, 'root' ]
            queues['default']['members'].append( orphan )

    def configure_queues( self ):
        """ Replace family names with members, in internal queues,
         and remove assigned members from the default queue. """

        if flags.verbose:
            print "Configuring internal queues"

        # NOTE: this method modifies the parsed config dict itself.

        queues = self.cfg['scheduling']['queues']
        # add all tasks to the default queue
        queues['default']['members'] = self.get_task_name_list()
        #print 'INITIAL default', queues['default']['members']
        for queue in queues:
            if queue == 'default':
                continue
            # assign tasks to queue and remove them from default
            qmembers = []
            for qmember in queues[queue]['members']:
                if qmember in self.runtime['descendants']:
                    # qmember is a family so replace it with member tasks. Note that
                    # self.runtime['descendants'][fam] includes sub-families too.
                    for fmem in self.runtime['descendants'][qmember]:
                        if qmember not in qmembers:
                            try:
                                queues['default']['members'].remove( fmem )
                            except ValueError:
                                # no need to check for naked dummy tasks here as
                                # families are defined by runtime entries.
                                if flags.verbose and fmem not in self.runtime['descendants']:
                                    # family members that are themselves families should be ignored as we only need tasks in the queues.
                                    print >> sys.stderr, '  WARNING, queue ' + queue + ': ignoring ' + fmem + ' of family ' + qmember + ' (task not used in the graph)'
                            else:
                                qmembers.append( fmem )
                else:
                    # qmember is a task
                    if qmember not in qmembers:
                        try:
                            queues['default']['members'].remove( qmember )
                        except ValueError:
                            if flags.verbose:
                                print >> sys.stderr, '  WARNING, queue ' + queue + ': ignoring ' + qmember + ' (task not used in the graph)'
                            if qmember not in self.cfg['runtime']:
                                self.naked_dummy_tasks.append( qmember )
                        else:
                            qmembers.append(qmember)
            queues[queue]['members'] = qmembers
        if flags.verbose:
            if len( queues.keys() ) > 1:
                for queue in queues:
                    print "  +", queue, queues[queue]['members']
            else:
                print " + All tasks assigned to the 'default' queue"

    def get_parent_lists( self ):
        return self.runtime['parents']

    def get_first_parent_ancestors( self, pruned=False ):
        if pruned:
            # prune non-task namespaces from ancestors dict
            pruned_ancestors = {}
            for key,val in self.runtime['first-parent ancestors'].items():
                if key not in self.taskdefs:
                    continue
                pruned_ancestors[key] = val
            return pruned_ancestors
        else:
            return self.runtime['first-parent ancestors']

    def get_linearized_ancestors( self ):
        return self.runtime['linearized ancestors']

    def get_first_parent_descendants( self ):
        return self.runtime['first-parent descendants']

    def define_inheritance_tree( self, tree, hierarchy, titles=False ):
        # combine inheritance hierarchies into a tree structure.
        for rt in hierarchy:
            hier = copy(hierarchy[rt])
            hier.reverse()
            foo = tree
            for item in hier:
                if item not in foo:
                    foo[item] = {}
                foo = foo[item]

    def add_tree_titles( self, tree ):
        for key,val in tree.items():
            if val == {}:
                if 'title' in self.cfg['runtime'][key]:
                    tree[key] = self.cfg['runtime'][key]['title']
                else:
                    tree[key] = 'No title provided'
            elif isinstance(val, dict):
                self.add_tree_titles( val )

    def get_namespace_list( self, which ):
        names = []
        if which == 'graphed tasks':
            # tasks used only in the graph
            names = self.taskdefs.keys()
        elif which == 'all namespaces':
            # all namespaces
            names = self.cfg['runtime'].keys()
        elif which == 'all tasks':
            for ns in self.cfg['runtime']:
                if ns not in self.runtime['descendants']:
                    # tasks have no descendants
                    names.append( ns )
        result = {}
        for ns in names:
            if 'title' in self.cfg['runtime'][ns]:
                # the runtime dict is sparse at this stage.
                result[ns] = self.cfg['runtime'][ns]['title']
            else:
                # no need to flesh out the full runtime just for title
                result[ns] = "No title provided"

        return result

    def get_mro( self, ns ):
        try:
            mro = self.runtime['linearized ancestors'][ns]
        except KeyError:
            mro = ["ERROR: no such namespace: " + ns ]
        return mro

    def print_first_parent_tree( self, pretty=False, titles=False ):
        # find task namespaces (no descendants)
        tasks = []
        for ns in self.cfg['runtime']:
            if ns not in self.runtime['descendants']:
                tasks.append(ns)

        pruned_ancestors = self.get_first_parent_ancestors( pruned=True )
        tree = {}
        self.define_inheritance_tree( tree, pruned_ancestors, titles=titles )
        padding = ''
        if titles:
            self.add_tree_titles(tree)
            # compute pre-title padding
            maxlen = 0
            for ns in pruned_ancestors:
                items = copy(pruned_ancestors[ns])
                items.reverse()
                for i in range(0,len(items)):
                    tmp = 2*i + 1 + len(items[i])
                    if i == 0:
                        tmp -= 1
                    if tmp > maxlen:
                        maxlen = tmp
            padding = maxlen * ' '

        print_tree( tree, padding=padding, use_unicode=pretty )

    def process_directories(self):
        os.environ['CYLC_SUITE_NAME'] = self.suite
        os.environ['CYLC_SUITE_REG_PATH'] = RegPath( self.suite ).get_fpath()
        os.environ['CYLC_SUITE_DEF_PATH'] = self.fdir

    def set_trigger( self, task_name, right, output_name=None, offset=None,
                     cycle_point=None, asyncid_pattern=None,
                     suicide=False, base_interval=None ):
        trig = triggerx(task_name)
        trig.set_suicide(suicide)
        if output_name:
            try:
                # check for internal outputs
                trig.set_special( self.cfg['runtime'][task_name]['outputs'][output_name],
                                  base_interval=base_interval )
            except KeyError:
                # There is no matching output defined under the task runtime section
                if output_name == 'submit':
                    # OK, task:submit
                    trig.set_type('submitted' )
                elif output_name == 'submit-fail':
                    # OK, task:submit-fail
                    trig.set_type('submit-failed' )
                elif output_name == 'fail':
                    # OK, task:fail
                    trig.set_type('failed' )
                elif output_name == 'start':
                    # OK, task:start
                    trig.set_type('started')
                elif output_name == 'succeed':
                    # OK, task:succeed
                    trig.set_type('succeeded')
                else:
                    # ERROR
                    raise SuiteConfigError, "ERROR: '" + task_name + "' does not define output '" + output_name  + "'"
            else:
                # There is a matching output defined under the task runtime section
                if self.run_mode != 'live':
                    # Ignore internal outputs: dummy tasks will not report them finished.
                    return None
        else:
            # default: task succeeded
            trig.set_type( 'succeeded' )

        if offset:
            trig.set_offset( str(offset) ) # TODO ISO - CONSISTENT SET_OFFSET INPUT 

        if cycle_point:
            trig.set_cycle_point( cycle_point )

        # Should the following be 'elif' with offset?
        if task_name in self.async_repeating_tasks: 
            trig.set_async_repeating( asyncid_pattern)
            if trig.suicide:
                raise SuiteConfigError, "ERROR, '" + task_name + "': suicide triggers not implemented for repeating async tasks"
            if trig.type:
                raise SuiteConfigError, "ERROR, '" + task_name + "': '" + trig.type + "' triggers not implemented for repeating async tasks"
        elif task_name in self.cycling_tasks:
            trig.set_cycling()

        return trig

    def check_tasks( self ):
        # Call after all tasks are defined.
        # ONLY IF VALIDATING THE SUITE
        # because checking conditional triggers below may be slow for
        # huge suites (several thousand tasks).
        # Note:
        #   (a) self.cfg['runtime'][name]
        #       contains the task definition sections of the suite.rc file.
        #   (b) self.taskdefs[name]
        #       contains tasks that will be used, defined by the graph.
        # Tasks (a) may be defined but not used (e.g. commented out of the graph)
        # Tasks (b) may not be defined in (a), in which case they are dummied out.

        if flags.verbose:
            print "Checking for defined tasks not used in the graph"
            for name in self.cfg['runtime']:
                if name not in self.taskdefs:
                    if name not in self.runtime['descendants']:
                        # any family triggers have have been replaced with members by now.
                        print >> sys.stderr, '  WARNING: task "' + name + '" is not used in the graph.'

        # warn if listed special tasks are not defined
        for type in self.cfg['scheduling']['special tasks']:
            for name in self.cfg['scheduling']['special tasks'][type]:
                if type == 'clock-triggered':
                    name = re.sub('\(.*\)','',name)
                elif type == 'sequential':
                    if name not in self.cycling_tasks:
                        raise SuiteConfigError, 'ERROR: sequential tasks must be cycling tasks: ' + name
                if re.search( '[^0-9a-zA-Z_]', name ):
                    raise SuiteConfigError, 'ERROR: Illegal ' + type + ' task name: ' + name
                if name not in self.taskdefs and name not in self.cfg['runtime']:
                    raise SuiteConfigError, 'ERROR: special task "' + name + '" is not defined.'

        try:
            import Pyro.constants
        except:
            print >> sys.stderr, "WARNING, INCOMPLETE VALIDATION: Pyro is not installed"
            return

        # Instantiate tasks and force evaluation of conditional trigger expressions.
        if flags.verbose:
            print "Instantiating tasks to check trigger expressions"
        for name in self.taskdefs.keys():
            type = self.taskdefs[name].type
            # TODO ISO - THIS DOES NOT GET ALL GRAPH SECTIONS:
            tag = get_point( self.cfg['scheduling']['initial cycle time'] )
            try:
                # instantiate a task
                itask = self.taskdefs[name].get_task_class()( tag, 'waiting', None, True, validate=True )
            except TypeError, x:
                raise
                # This should not happen as we now explicitly catch use
                # of synchronous special tasks in an asynchronous graph.
                # But in principle a clash of multiply inherited base
                # classes due to choice of "special task" modifiers
                # could cause a TypeError.
                raise SuiteConfigError, '(inconsistent use of special tasks?)'
            except Exception, x:
                raise
                raise SuiteConfigError, 'ERROR, failed to instantiate task ' + str(name)
            if not itask.tag:
                if flags.verbose:
                    print " + Task out of bounds for " + str(tag) + ": " + itask.name
                continue

            # force trigger evaluation now
            try:
                itask.prerequisites.eval_all()
            except TriggerExpressionError, x:
                print >> sys.stderr, x
                raise SuiteConfigError, "ERROR, " + name + ": invalid trigger expression."
            except Exception, x:
                print >> sys.stderr, x
                raise SuiteConfigError, 'ERROR, ' + name + ': failed to evaluate triggers.'
            if flags.verbose:
                print "  + " + itask.id + " ok"

        # Check custom command scripting is not defined for automatic suite polling tasks
        for l_task in self.suite_polling_tasks:
            try:
                cs = self.pcfg.getcfg( sparse=True )['runtime'][l_task]['command scripting']
            except:
                pass
            else:
                if cs:
                    print cs
                    # (allow explicit blanking of inherited scripting)
                    raise SuiteConfigError( "ERROR: command scripting cannot be defined for automatic suite polling task " + l_task )


    def get_coldstart_task_list( self ):
        # TODO - automatically determine this by parsing the dependency graph?
        # For now user must define this:
        return self.cfg['scheduling']['special tasks']['cold-start']

    def get_startup_task_list( self ):
        return self.async_repeating_tasks

    def get_task_name_list( self ):
        # return a list of all tasks used in the dependency graph
        return self.taskdefs.keys()

    def get_asynchronous_task_name_list( self ):
        names = []
        for tn in self.taskdefs:
            if self.taskdefs[tn].type == 'async_repeating' or \
                    self.taskdefs[tn].type == 'async_daemon':
                names.append(tn)
        return names

    def replace_family_triggers( self, line_in, fam, members, orig='' ):
        # Replace family trigger expressions with member trigger expressions.
        # The replacements below handle optional [T-n] cycle offsets.

        if orig and orig not in line_in:
            return line_in
        line = line_in
        paren_open = ''
        paren_close = ''
        connector = ' & '
        if orig.endswith( '-all' ):
            pass
        elif orig.endswith( '-any' ):
            connector = ' | '
            paren_open = '( '
            paren_close = ' )'
        elif orig != '':
            print >> sys.stderr, line
            raise SuiteConfigError, 'ERROR, illegal family trigger type: ' + orig
        repl = orig[:-4]

        # TODO - can we use Replacement here instead of findall and sub:
        m = re.findall( "(!){0,1}" + r"\b" + fam + r"\b(\[.*?]){0,1}" + orig, line )
        m.sort() # put empty offset '' first ...
        m.reverse() # ... then last
        for grp in m:
            exclam, foffset = grp
            if fam not in self.triggering_families:
                self.triggering_families.append(fam)
            mems = paren_open + connector.join( [ exclam + i + foffset + repl for i in members ] ) + paren_close
            line = re.sub( exclam + r"\b" + fam + r"\b" + re.escape(foffset) + orig, mems, line )
        return line

    def process_graph_line( self, line, section, ttype, seq,
                            tasks_to_prune=None,
                            return_all_dependencies=False ):
        """Extract dependent pairs from the suite.rc dependency text.
        
        Extract dependent pairs from the suite.rc textual dependency
        graph to use in constructing graphviz graphs.

        Return a list of dependencies involving 'start-up' tasks
        (backwards compatibility) or all dependencies if
        return_all_dependencies keyword argument is True.

        line is the line of text within the 'graph' attribute of
        this dependency section.
        section is the text describing this dependency section (e.g.
        T00).
        ttype is either 'cycling' or an async indicator.
        seq is the sequence generated from 'section' given the initial
        and final cycle time.
        tasks_to_prune, if not None, is a list of tasks to remove
        from dependency expressions (backwards compatibility for
        start-up tasks and async graph tasks).
        return_all_dependencies, if True, indicates that all
        dependencies between tasks in this graph should be returned.
        Otherwise, just return tasks_to_prune dependencies, if any.

        'A => B => C'    : [A => B], [B => C]
        'A & B => C'     : [A => C], [B => C]
        'A => C & D'     : [A => C], [A => D]
        'A & B => C & D' : [A => C], [A => D], [B => C], [B => D]

        '&' groups aren't really "conditional expressions"; they're
        equivalent to adding another line:
        'A & B => C'
        is the same as:
        'A => C' and 'B => C'

        An 'or' on the right side is an ERROR:
        'A = > B | C' # ?!

        """

        if tasks_to_prune is None:
            tasks_to_prune = []

        orig_line = line

        ## SYNONYMS FOR TRIGGER-TYPES, e.g. 'fail' = 'failure' = 'failed' (NOT USED)
        ## we can replace synonyms here with the standard type designator:
        # line = re.sub( r':succe(ss|ed|eded){0,1}\b', '', line )
        # line = re.sub( r':fail(ed|ure){0,1}\b', ':fail', line )
        # line = re.sub( r':start(ed){0,1}\b', ':start', line )
        # Replace "foo:finish(ed)" or "foo:complete(ed)" with "( foo | foo:fail )"
        # line = re.sub(  r'\b(\w+(\[.*?]){0,1}):(complete(d){0,1}|finish(ed){0,1})\b', r'( \1 | \1:fail )', line )

        # Find any dependence on other suites, record the polling target
        # info and replace with just the local task name, e.g.:
        # "foo<SUITE::TASK:fail> => bar"  becomes "foo => bar"
        # (and record that foo must automatically poll for TASK in SUITE)
        repl = Replacement( '\\1' )
        line = re.sub( '(\w+)(<([\w\.\-]+)::(\w+)(:\w+)?>)', repl, line )
        for item in repl.match_groups:
            l_task, r_all, r_suite, r_task, r_status = item
            if r_status:
                r_status = r_status[1:]
            else: # default
                r_status = 'succeed'
            self.suite_polling_tasks[ l_task ] = ( r_suite, r_task, r_status, r_all )

        # REPLACE FAMILY NAMES WITH MEMBER DEPENDENCIES
        # Sort so that longer family names get expanded first.
        # This expands e.g. FOO-BAR before FOO in FOO-BAR:succeed-all => baz.
        for fam in reversed(sorted(self.runtime['descendants'])):
            members = copy(self.runtime['descendants'][fam])
            for member in copy(members):
                # (another copy here: don't remove items from the iterating list)
                # remove family names from the member list, leave just tasks
                # (allows using higher-level family names in the graph)
                if member in self.runtime['descendants']:
                    members.remove(member)
            # Note, in the regular expressions below, the word boundary
            # marker before the time offset pattern is required to close
            # the match in the no-offset case (offset and no-offset
            # cases are being matched by the same regular expression).

            # raw strings (r'\bfoo\b') are needed to protect special
            # backslashed re markers like \b from being interpreted as
            # normal escapeded characters.

            if fam not in line:
                continue

            # Replace family triggers with member triggers
            for trig_type in TRIGGER_TYPES:
                line = self.replace_family_triggers( line, fam, members, ':'+trig_type + '-all' )
                line = self.replace_family_triggers( line, fam, members, ':'+trig_type + '-any' )

            if re.search( r"\b" + fam + r"\b:", line ):
                # fam:illegal
                print >> sys.stderr, line
                raise SuiteConfigError, 'ERROR, illegal family trigger detected'

            if re.search( r"\b" + fam + r"\b[^:].*=>", line ) or re.search( r"\b" + fam + "\s*=>$", line ):
                # plain family names are not allowed on the left of a trigger
                print >> sys.stderr, line
                raise SuiteConfigError, 'ERROR, family triggers must be qualified, e.g. ' + fam + ':succeed-all'

            # finally replace plain family names on the right of a trigger
            line = self.replace_family_triggers( line, fam, members )

        # any remaining use of '-all' or '-any' implies a family trigger
        # on a non-family task, which is illegal.
        if '-a' in line: # ('-' is not legal in task names so this gets both cases)
            print >> sys.stderr, line
            raise SuiteConfigError, "ERROR: family triggers cannot be used on non-family namespaces"

        # Replace "foo:finish" with "( foo:succeed | foo:fail )"
        line = re.sub(  r'\b(\w+(\[.*?]){0,1}):finish\b', r'( \1:succeed | \1:fail )', line )

        if flags.verbose and line != orig_line:
            print 'Graph line substitutions occurred:'
            print '  IN:', orig_line
            print '  OUT:', line

        # Split line on dependency arrows.
        tasks = re.split( '\s*=>\s*', line )
        # NOTE:  we currently use only one kind of arrow, but to use
        # several kinds we can split the string like this:
        #     tokens = re.split( '\s*(=[>x])\s*', line ) # a => b =x c
        #     tasks = tokens[0::2]                       # [a, b, c]
        #     arrow = tokens[1::2]                       # [=>, =x]

        # Check for missing task names, e.g. '=> a => => b =>; this
        # results in empty or blank strings in the list of task names.
        arrowerr = False
        for task in tasks:
            if re.match( '^\s*$', task ):
                arrowerr = True
                break
        if arrowerr:
            print >> sys.stderr, orig_line
            raise SuiteConfigError, "ERROR: missing task name in graph line?"

        # get list of pairs
        special_dependencies = []
        for i in [0] + range( 1, len(tasks)-1 ):
            lexpression = tasks[i]

            if len(tasks) == 1:
                # single node: no rhs group
                rgroup = None
                if re.search( '\|', lexpression ):
                    print >> sys.stderr, orig_line
                    raise SuiteConfigError, "ERROR: Lone node groups cannot contain OR conditionals: " + lexpression
            else:
                rgroup = tasks[i+1]

            if rgroup:
                # '|' (OR) is not allowed on the right side
                if re.search( '\|', rgroup ):
                    print >> sys.stderr, orig_line
                    raise SuiteConfigError, "ERROR: OR '|' is not legal on the right side of dependencies: " + rgroup

                # (T+/-N) offsets not allowed on the right side (as yet)
                if re.search( '\[\s*T\s*[+-]\s*\w+\s*\]', rgroup ):
                    print >> sys.stderr, orig_line
                    raise SuiteConfigError, "ERROR: time offsets are not legal on the right side of dependencies: " + rgroup

                # now split on '&' (AND) and generate corresponding pairs
                rights = re.split( '\s*&\s*', rgroup )
            else:
                rights = [None]

            new_rights = []
            for r in rights:
                if r:
                    # ignore output labels on the right (for chained
                    # tasks they are only meaningful on the left)
                    new_rights.append( re.sub( ':\w+', '', r ))
                else:
                    # retain None's in order to handle lone nodes on the left
                    new_rights.append( None )

            rights = new_rights

            # extract task names from lexpression
            nstr = re.sub( '[(|&)]', ' ', lexpression )
            nstr = nstr.strip()
            lnames = re.split( ' +', nstr )

            # detect and fail and self-dependence loops (foo => foo)
            for r_name in rights:
                if r_name in lnames:
                    print >> sys.stderr, "Self-dependence detected in '" + r_name + "':"
                    print >> sys.stderr, "  line:", line
                    print >> sys.stderr, "  from:", orig_line
                    raise SuiteConfigError, "ERROR: self-dependence loop detected"

            for rt in rights:
                # foo => '!bar' means task bar should suicide if foo succeeds.
                suicide = False
                if rt and rt.startswith('!'):
                    r = rt[1:]
                    suicide = True
                else:
                    r = rt

                asyncid_pattern = None
                if ttype != 'cycling':
                    for n in lnames + [r]:
                        if not n:
                            continue
                        try:
                            name = graphnode(
                                n, base_interval=seq.get_interval()).name
                        except GraphNodeError, x:
                            print >> sys.stderr, orig_line
                            raise SuiteConfigError, str(x)
                        if ttype == 'async_repeating':
                            if name not in self.async_repeating_tasks:
                                self.async_repeating_tasks.append(name)
                            m = re.match( '^ASYNCID:(.*)$', section )
                            asyncid_pattern = m.groups()[0]

                if ttype == 'cycling':
                    for n in list(lnames):
                        try:
                            name = graphnode(
                                n, base_interval=seq.get_interval()).name
                        except GraphNodeError, x:
                            print >> sys.stderr, orig_line
                            raise SuiteConfigError, str(x)            
                        if name in tasks_to_prune or return_all_dependencies:
                            special_dependencies.append((name, r))
                        if name in tasks_to_prune:
                            lnames.remove(n)

                if not self.validation and not graphing_disabled:
                    # edges not needed for validation
                    self.generate_edges( lexpression, lnames, r, ttype, seq, suicide )
                self.generate_taskdefs( orig_line, lnames, r, ttype, section,
                                        asyncid_pattern, seq.get_interval() )
                self.generate_triggers( lexpression, lnames, r, seq,
                                         asyncid_pattern, suicide )
        return special_dependencies
            

    def generate_edges( self, lexpression, lnames, right, ttype, seq, suicide=False ):
        """Add nodes from this graph section to the abstract graph edges structure."""
        conditional = False
        if re.search( '\|', lexpression ):
            # plot conditional triggers differently
            conditional = True

        for left in lnames:
            sasl = left in self.async_repeating_tasks
            e = graphing.edge( left, right, seq, sasl, suicide, conditional )
            if ttype == 'async_repeating':
                if e not in self.async_repeating_edges:
                    self.async_repeating_edges.append( e )
            else:
                self.edges.append(e)

    def generate_taskdefs( self, line, lnames, right, ttype, section, asyncid_pattern,
                           base_interval ):
        for node in lnames + [right]:
            if not node:
                # if right is None, lefts are lone nodes
                # for which we still define the taskdefs
                continue
            try:
                my_taskdef_node = graphnode( node, base_interval=base_interval )
            except GraphNodeError, x:
                print >> sys.stderr, line
                raise SuiteConfigError, str(x)

            name = my_taskdef_node.name
            offset = my_taskdef_node.offset

            if name not in self.cfg['runtime']:
                # naked dummy task, implicit inheritance from root
                self.naked_dummy_tasks.append( name )
                self.cfg['runtime'][name] = self.cfg['runtime']['root']
                if 'root' not in self.runtime['descendants']:
                    # (happens when no runtimes are defined in the suite.rc)
                    self.runtime['descendants']['root'] = []
                if 'root' not in self.runtime['first-parent descendants']:
                    # (happens when no runtimes are defined in the suite.rc)
                    self.runtime['first-parent descendants']['root'] = []
                self.runtime['parents'][name] = ['root']
                self.runtime['linearized ancestors'][name] = [name, 'root']
                self.runtime['first-parent ancestors'][name] = [name, 'root']
                self.runtime['descendants']['root'].append(name)
                self.runtime['first-parent descendants']['root'].append(name)

            # check task name legality and create the taskdef
            if name not in self.taskdefs:
                try:
                    self.taskdefs[ name ] = self.get_taskdef( name )
                except taskdef.DefinitionError, x:
                    print >> sys.stderr, line
                    raise SuiteConfigError, str(x)

            # TODO - setting type should be consolidated to get_taskdef()
            if ttype == 'async_repeating':
                self.taskdefs[name].asyncid_pattern = asyncid_pattern
                if name == self.cfg['scheduling']['dependencies'][section]['daemon']:
                    self.taskdefs[name].type = 'async_daemon'
                else:
                    self.taskdefs[name].type = 'async_repeating'
            elif ttype == 'cycling':
                self.taskdefs[name].cycling = True
                if name not in self.cycling_tasks:
                    self.cycling_tasks.append(name)

            if name in self.suite_polling_tasks:
                self.taskdefs[name].suite_polling_cfg = {
                        'suite'  : self.suite_polling_tasks[name][0],
                        'task'   : self.suite_polling_tasks[name][1],
                        'status' : self.suite_polling_tasks[name][2] }

            seq = get_sequence( section,
                self.cfg['scheduling']['initial cycle time'],
                self.cfg['scheduling']['final cycle time'] )
           
            if not offset and not my_taskdef_node.is_absolute:
                # Note: this removes all offset sequences...
                self.taskdefs[ name ].add_sequence( seq )

            if self.run_mode == 'live':
                # register any explicit internal outputs
                if 'outputs' in self.cfg['runtime'][name]:
                    for lbl,msg in self.cfg['runtime'][name]['outputs'].items():
                        outp = outputx(msg)
                        self.taskdefs[ name ].outputs.append( outp )

    def generate_triggers( self, lexpression, lnames, right, seq, asyncid_pattern, suicide ):
        if not right:
            # lefts are lone nodes; no more triggers to define.
            return

        base_interval = seq.get_interval()

        conditional = False
        if re.search( '\|', lexpression ):
            conditional = True
            # For single triggers or '&'-only ones, which will be the
            # vast majority, we needn't use conditional prerequisites
            # (they may be less efficient due to python eval at run time).

        ctrig = {}
        cname = {}
        for left in lnames:
            # (GraphNodeError checked above)
            cycle_point = None
            lnode = graphnode(left, base_interval=base_interval)
            if lnode.intercycle:
                self.taskdefs[lnode.name].intercycle = True
                if (lnode.offset is not None and
                        lnode.offset >
                        self.taskdefs[lnode.name].intercycle_offset):
                    self.taskdefs[lnode.name].intercycle_offset = lnode.offset
            if lnode.offset_is_from_ict:
                last_point = seq.get_stop_point()
                first_point = self.taskdefs[lnode.name].ict - lnode.offset
                if first_point and last_point is not None:
                    self.taskdefs[lnode.name].intercycle_offset = (last_point - first_point)
                else:
                    self.taskdefs[lnode.name].intercycle_offset = None
                cycle_point = first_point
            trigger = self.set_trigger( lnode.name, right, lnode.output, lnode.offset, cycle_point, asyncid_pattern, suicide, seq.get_interval() )
            if not trigger:
                continue
            if not conditional:
                self.taskdefs[right].add_trigger( trigger, seq )
                continue

            # CONDITIONAL TRIGGERS
            if trigger.async_repeating:
                # (extend taskdef.py:tclass_add_prerequisites to allow this)
                raise SuiteConfigError, 'ERROR, ' + left + ': repeating async tasks are not allowed in conditional triggers.'
            # Use fully qualified name for the expression label
            # (task name is not unique, e.g.: "F | F:fail => G")
            label = re.sub( '[-\[\]:]', '_', left )
            label = re.sub( '\+', 'x', label ) # future triggers
            ctrig[label] = trigger
            cname[label] = lnode.name

        if not conditional:
            return

        # Replace some chars for later use in regular expressions.
        expr = re.sub( '[-\[\]:]', '_', lexpression )
        expr = re.sub( '\+', 'x', expr ) # future triggers
        self.taskdefs[right].add_conditional_trigger( ctrig, expr, seq )

    def get_actual_first_ctime( self, start_ctime ):
        # Get actual first cycle time for the suite (get all
        # sequences to adjust the putative start time upward)
        if self.actual_first_ctime:
            # already computed
            return self.actual_first_ctime
        ctime = get_point(start_ctime)
        adjusted = []
        for seq in self.sequences:
            foo = seq.get_first_point( ctime )
            if foo:
                adjusted.append( foo )
        if len( adjusted ) > 0:
            adjusted.sort()
            self.actual_first_ctime = adjusted[0]
        else:
            self.actual_first_ctime = ctime
        return self.actual_first_ctime

    def get_graph_raw( self, start_ctime_str, stop_str, raw=False,
            group_nodes=[], ungroup_nodes=[], ungroup_recursive=False,
            group_all=False, ungroup_all=False ):
        """Convert the abstract graph edges held in self.edges (etc.) to
        actual edges for a concrete range of cycle times."""

        members = self.runtime['first-parent descendants']
        hierarchy = self.runtime['first-parent ancestors']

        if self.first_graph:
            self.first_graph = False
            if not self.collapsed_families_rc and not ungroup_all:
                # initially default to collapsing all families if
                # "[visualization]collapsed families" not defined
                group_all = True

        if group_all:
            # Group all family nodes
            if self.collapsed_families_rc:
                self.closed_families = copy(self.collapsed_families_rc)
            else:
                for fam in members:
                    if fam != 'root':
                        if fam not in self.closed_families:
                            self.closed_families.append( fam )
        elif ungroup_all:
            # Ungroup all family nodes
            self.closed_families = []
        elif len(group_nodes) > 0:
            # Group chosen family nodes
            for node in group_nodes:
                parent = hierarchy[node][1]
                if parent not in self.closed_families:
                    if parent != 'root':
                        self.closed_families.append( parent )
        elif len(ungroup_nodes) > 0:
            # Ungroup chosen family nodes
            for node in ungroup_nodes:
                if node not in self.runtime['descendants']:
                    # not a family node
                    continue
                if node in self.closed_families:
                    self.closed_families.remove(node)
                if ungroup_recursive:
                    for fam in copy(self.closed_families):
                        if fam in members[node]:
                            self.closed_families.remove(fam)

        # Now define the concrete graph edges (pairs of nodes) for plotting.
        gr_edges = []

        for e in self.async_repeating_edges:
            right = e.get_right(1, False, False, [] )
            left  = e.get_left( 1, False, False, [] )
            nl, nr = self.close_families( left, right )
            gr_edges.append( (nl, nr, False, e.suicide, e.conditional) )

        start_ctime = get_point( start_ctime_str )

        actual_first_ctime = self.get_actual_first_ctime( start_ctime )

        startup_exclude_list = self.get_coldstart_task_list()

        stop = get_point( stop_str )

        for e in self.edges:
            # Get initial cycle time for this sequence
            i_ctime = e.sequence.get_first_point( start_ctime )
            if not i_ctime:
                # out of bounds
                continue
            ctime = deepcopy(i_ctime)

            while True: 
                # Loop over cycles generated by this sequence
                if not ctime or ctime > stop:
                    break

                not_initial_cycle = ( ctime != i_ctime )

                r_id = e.get_right(ctime, start_ctime, not_initial_cycle, raw,
                                   startup_exclude_list )
                l_id = e.get_left( ctime, start_ctime, not_initial_cycle, raw,
                                   startup_exclude_list,
                                   e.sequence.get_interval() )

                action = True

                if l_id == None and r_id == None:
                    # nothing to add to the graph
                    action = False

                if l_id != None and not e.sasl:
                    # check that l_id is not earlier than start time
                    tmp, lctime = TaskID.split(l_id)
                    ## NOTE BUG GITHUB #919
                    ##sct = start_ctime
                    sct = actual_first_ctime
                    lct = get_point(lctime)
                    if sct > lct:
                        action = False

                if action:
                    nl, nr = self.close_families( l_id, r_id )
                    gr_edges.append( ( nl, nr, False, e.suicide, e.conditional ) )

                # increment the cycle time
                ctime = e.sequence.get_next_point_on_sequence( ctime )

        return gr_edges

    def get_graph( self, start_ctime, stop, raw=False, group_nodes=[],
            ungroup_nodes=[], ungroup_recursive=False, group_all=False,
            ungroup_all=False, ignore_suicide=False ):

        gr_edges = self.get_graph_raw( start_ctime, stop, raw,
                group_nodes, ungroup_nodes, ungroup_recursive,
                group_all, ungroup_all )

        graph = graphing.CGraph( self.suite, self.suite_polling_tasks, self.cfg['visualization'] )
        graph.add_edges( gr_edges, ignore_suicide )

        return graph

    def get_node_labels( self, start_ctime, stop, raw ):
        graph = self.get_graph( start_ctime, stop, raw=raw, ungroup_all=True )
        return [ i.attr['label'].replace('\\n','.') for i in graph.nodes() ]

    def close_families( self, nlid, nrid ):
        # Generate final node names, replacing family members with
        # family nodes if requested.

        members = self.runtime['first-parent descendants']

        lname, ltag = None, None
        rname, rtag = None, None
        nr, nl = None, None
        if nlid:
            one, two = TaskID.split(nlid)
            lname = one
            ltag = two
            nl = nlid
        if nrid:
            one, two = TaskID.split(nrid)
            rname = one
            rtag = two
            nr = nrid

        # for nested families, only consider the outermost one
        clf = copy( self.closed_families )
        for i in self.closed_families:
            for j in self.closed_families:
                if i in members[j]:
                    # i is a member of j
                    if i in clf:
                        clf.remove( i )

        for fam in clf:
            if lname in members[fam] and rname in members[fam]:
                # l and r are both members of fam
                #nl, nr = None, None  # this makes 'the graph disappear if grouping 'root'
                nl,nr = TaskID.get(fam,tag), TaskID.get(fam,rtag)
                break
            elif lname in members[fam]:
                # l is a member of fam
                nl = TaskID.get(fam,ltag)
            elif rname in members[fam]:
                # r is a member of fam
                nr = TaskID.get(fam,rtag)

        return nl, nr

    def load_graph( self ):
        if flags.verbose:
            print "Parsing the dependency graph"

        start_up_tasks = self.cfg['scheduling']['special tasks']['start-up']
        initial_tasks = list(start_up_tasks)

        self.graph_found = False

        # Set up our backwards-compatibility handling of async graphs.
        async_graph = self.cfg['scheduling']['dependencies']['graph']
        if async_graph:
            section = get_sequence_cls().get_async_expr()
            async_dependencies = self.parse_graph(
                section, async_graph,
                return_all_dependencies=True
            )
            for left, right in async_dependencies:
                if left:
                    initial_tasks.append(left)
                if right:
                    initial_tasks.append(right)

        # Create a stack of sections (sequence strings) and graphs.
        items = []
        for item, value in self.cfg['scheduling']['dependencies'].items():
            if item == 'graph':
                continue
            items.append((item, value, initial_tasks, False))

        start_up_tasks_graphed = []
        while items:
            item, value, tasks_to_prune, is_inserted = items.pop(0)

            # If the section consists of more than one sequence, split it up.
            if re.search("(?![^(]+\)),", item):
                new_items = re.split("(?![^(]+\)),", item)
                for new_item in new_items:
                    items.append((new_item.strip(), value,
                                  tasks_to_prune, False))
                continue

            try:
                graph = value['graph']
            except KeyError:
                continue
            if not graph:
                continue

            section = item
            if is_inserted:
                print "INSERTED DEPENDENCIES REPLACEMENT:"
                print "[[[" + section + "]]]"
                print "    " + 'graph = """' + graph + '"""' 
            special_dependencies = self.parse_graph(
                section, graph,
                tasks_to_prune=tasks_to_prune
            )
            if special_dependencies and tasks_to_prune:
                section_seq = get_sequence(
                    section,
                    self.cfg['scheduling']['initial cycle time'],
                    self.cfg['scheduling']['final cycle time']
                )
                first_point = section_seq.get_first_point(
                    get_point(self.cfg['scheduling']['initial cycle time'])
                )
                graph_text = ""
                for left, right in special_dependencies:
                    graph_text += left + "[] => " + right + "\n"
                    if (left in start_up_tasks and
                            left not in start_up_tasks_graphed):
                        # Start-up tasks need their own explicit section.
                        items.append((get_sequence_cls().get_async_expr(),
                                     {"graph": left}, [], True))
                        start_up_tasks_graphed.append(left)
                graph_text = graph_text.rstrip()
                section = get_sequence_cls().get_async_expr(first_point)
                items.append((section, {"graph": graph_text}, [], True))
                                

    def parse_graph( self, section, graph, tasks_to_prune=None,
                     return_all_dependencies=False ):
        self.graph_found = True

        if re.match( '^ASYNCID:', section ):
            ttype = 'async_repeating'
            # TODO ISO - THIS IS NOW BROKEN?
        else:
            ttype = 'cycling'
            sec = section

        seq = get_sequence( sec,
                self.cfg['scheduling']['initial cycle time'],
                self.cfg['scheduling']['final cycle time'] )

        if seq not in self.sequences:
            self.sequences.append(seq)

        # split the graph string into successive lines
        lines = re.split( '\s*\n\s*', graph )
        special_dependencies = []
        for xline in lines:
            # strip comments
            line = re.sub( '#.*', '', xline )
            # ignore blank lines
            if re.match( '^\s*$', line ):
                continue
            # strip leading or trailing spaces
            line = re.sub( '^\s*', '', line )
            line = re.sub( '\s*$', '', line )
            # generate pygraphviz graph nodes and edges, and task definitions
            special_dependencies.extend(self.process_graph_line(
                line, section, ttype, seq,
                tasks_to_prune=tasks_to_prune,
                return_all_dependencies=return_all_dependencies
            ))
        if ttype == 'cycling':
            return special_dependencies
        return []

    def get_taskdef( self, name ):
        # (DefinitionError caught above)

        # get the dense task runtime
        try:
            rtcfg = self.cfg['runtime'][name]
        except KeyError:
            raise SuiteConfigError, "Task not found: " + name

        ict = self.cli_start_tag or self.cfg['scheduling']['initial cycle time']
        # We may want to put in some handling for cases of changing the
        # initial cycle via restart (accidentally or otherwise).

        # Get the taskdef object for generating the task proxy class
        taskd = taskdef.taskdef( name, rtcfg, self.run_mode, get_point(ict) )

        # TODO - put all taskd.foo items in a single config dict
        # SET COLD-START TASK INDICATORS
        if name in self.cfg['scheduling']['special tasks']['cold-start']:
            taskd.modifiers.append( 'oneoff' )
            taskd.is_coldstart = True

        # SET CLOCK-TRIGGERED TASKS
        if name in self.clock_offsets:
            taskd.modifiers.append( 'clocktriggered' )
            taskd.clocktriggered_offset = self.clock_offsets[name]

        taskd.sequential = name in self.cfg['scheduling']['special tasks']['sequential']

        foo = copy(self.runtime['linearized ancestors'][ name ])
        foo.reverse()
        taskd.namespace_hierarchy = foo

        return taskd

    def get_task_proxy( self, name, ctime, state, stopctime, startup, submit_num, exists ):
        try:
            tdef = self.taskdefs[name]
        except KeyError:
            raise TaskNotDefinedError("ERROR, No such task name: " + name )
        return tdef.get_task_class()( ctime, state, stopctime, startup, submit_num=submit_num, exists=exists )

    def get_task_proxy_raw( self, name, tag, state, stoptag, startup, submit_num, exists ):
        # Used by 'cylc submit' to submit tasks defined by runtime
        # config but not currently present in the graph (so we must
        # assume that the given tag is valid for the task).
        try:
            truntime = self.cfg['runtime'][name]
        except KeyError:
            raise TaskNotDefinedError("ERROR, task not defined: " + name )
        tdef = self.get_taskdef( name )
        # TODO ISO - TEST THIS (did set 'tdef.hours' from tag)
        return tdef.get_task_class()( tag, state, stoptag, startup, submit_num=submit_num, exists=exists )

    def get_task_class( self, name ):
        return self.taskdefs[name].get_task_class()

