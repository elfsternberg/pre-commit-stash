from __future__ import print_function
from functools import reduce
import getopt
import gettext
import operator
import os
import re
import subprocess
import sys
import pprint
from git_lint_options import make_rational_options
from git_lint_config import get_config

_ = gettext.gettext

VERSION = '0.0.4'
NAME = 'git-lint'

def tap(a):
    print("TAP:", a)
    return a

#   ___                              _   _    _          
#  / __|___ _ __  _ __  __ _ _ _  __| | | |  (_)_ _  ___ 
# | (__/ _ \ '  \| '  \/ _` | ' \/ _` | | |__| | ' \/ -_)
#  \___\___/_|_|_|_|_|_\__,_|_||_\__,_| |____|_|_||_\___|
#                                                        

OPTIONS_LIST = [
    ('o', 'only', True,
     _('A comma-separated list of only those linters to run'), ['exclude']),
    ('x', 'exclude', True,
     _('A comma-separated list of linters to skip'), []),
    ('l', 'linters', False,
     _('Show the list of configured linters'), []),
    ('b', 'base', False,
     _('Check all changed files in the repository, not just those in the current directory.'), []),
    ('a', 'all', False,
     _('Scan all files in the repository, not just those that have changed.'), []),
    ('e', 'every', False,
     _('Short for -b -a: scan everything'), []),
    ('w', 'workspace', False,
     _('Scan the workspace'), ['staging']),
    ('s', 'staging', False,
     _('Scan the staging area (useful for pre-commit).'), []),
    ('g', 'changes', False,
     _("Report lint failures only for diff'd sections"), ['complete']),
    ('p', 'complete', False,
     _('Report lint failures for all files'), []),
    ('d', 'dryrun', False,
     _('Dry run - report what would be done, but do not run linters'), []),
    ('c', 'config', True,
     _('Path to config file'), []),
    ('h', 'help', False,
     _('This help message'), []),
    ('v', 'version', False,
     _('Version information'), [])]


# This was a lot shorter and smarter in Hy...
def make_rational_options(optlist, args):

    # OptionTupleList -> (getOptOptions -> dictionaryOfOptions)
    def make_options_rationalizer(optlist):
        """Takes a list of option tuples, and returns a function that takes
            the output of getopt and reduces it to the longopt key and
            associated values as a dictionary.
        """
    
        def make_opt_assoc(prefix, pos):
            def associater(acc, it):
                acc[(prefix + it[pos])] = it[1]
                return acc
            return associater
    
        short_opt_assoc = make_opt_assoc('-', 0)
        long_opt_assoc = make_opt_assoc('--', 1)
    
        def make_full_set(acc, i):
            return long_opt_assoc(short_opt_assoc(acc, i), i)
    
        fullset = reduce(make_full_set, optlist, {})
    
        def rationalizer(acc, it):
            acc[fullset[it[0]]] = it[1]
            return acc
    
        return rationalizer

    
    # (OptionTupleList, dictionaryOfOptions) -> (dictionaryOfOptions, excludedOptions)
    def remove_conflicted_options(optlist, request):
        """Takes our list of option tuples, and a cleaned copy of what was
            requested from getopt, and returns a copy of the request
            without any options that are marked as superseded, along with
            the list of superseded options
        """
        def get_excluded_keys(memo, opt):
            return memo + (len(opt) > 4 and opt[4] or [])
    
        keys = request.keys()
        marked = [option for option in optlist if option[1] in keys]
        exclude = reduce(get_excluded_keys, marked, [])
        excluded = [key for key in keys if key in exclude]
        cleaned = {key: request[key] for key in keys
                   if key not in excluded}
        return (cleaned, excluded)
    
    def shortoptstogo(i):
        return i[0] + (i[2] and ':' or '')

    def longoptstogo(i):
        return i[1] + (i[2] and '=' or '')

    optstringsshort = ''.join([shortoptstogo(opt) for opt in optlist])
    optstringslong = [longoptstogo(opt) for opt in optlist]
    (options, filenames) = getopt.getopt(args[1:], optstringsshort,
                                         optstringslong)

    # Turns what getopt returns into something more human-readable
    rationalize_options = make_options_rationalizer(optlist)

    # Remove any options that are superseded by others.
    (retoptions, excluded) = remove_conflicted_options(
        optlist, reduce(rationalize_options, options, {}))

    return (retoptions, filenames, excluded)

#   ___ _ _   
#  / __(_) |_ 
# | (_ | |  _|
#  \___|_|\__|
#             

def get_git_response_raw(cmd):
    fullcmd = (['git'] + cmd)
    process = subprocess.Popen(fullcmd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               universal_newlines=True)
    (out, err) = process.communicate()
    return (out, err, process.returncode)


def get_git_response(cmd):
    (out, error, returncode) = get_git_response_raw(cmd)
    return out


def split_git_response(cmd):
    (out, error, returncode) = get_git_response_raw(cmd)
    return out.splitlines()


def run_git_command(cmd):
    fullcmd = (['git'] + cmd)
    return subprocess.call(fullcmd,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                               universal_newlines=True)


def get_shell_response(fullcmd):
    process = subprocess.Popen(fullcmd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               shell=True,
                               universal_newlines=True)
    (out, err) = process.communicate()
    return (out, err, process.returncode)


def get_git_base():
    (out, error, returncode) = get_git_response_raw(
        ['rev-parse', '--show-toplevel'])
    return returncode == 0 and out.rstrip() or None


def get_git_head():
    empty_repository_hash = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
    (out, err, returncode) = get_git_response_raw(
        ['rev-parse', '--verify HEAD'])
    return (err and empty_repository_hash or 'HEAD')


git_base = get_git_base()
git_head = get_git_head()


#  _   _ _   _ _ _ _   _        
# | | | | |_(_) (_) |_(_)___ ___
# | |_| |  _| | | |  _| / -_|_-<
#  \___/ \__|_|_|_|\__|_\___/__/
#                               

def base_file_cleaner(files):
    return [file.replace(git_base, '', 1) for file in files]


def make_match_filter_matcher(extensions):
    trimmed = [s.strip() for s in reduce(operator.add, 
                                         [ex.split(',') for ex in extensions], [])]
    cleaned = [re.sub(r'^\.', '', s) for s in trimmed]
    return re.compile(r'\.' + '|'.join(cleaned) + r'$')


def make_match_filter(config):
    matcher = make_match_filter_matcher([v.get('match', '')
                                         for v in config.values()])

    def match_filter(path):
        return matcher.search(path)

    return match_filter


#   ___ _           _     _ _     _              
#  / __| |_  ___ __| |__ | (_)_ _| |_ ___ _ _ ___
# | (__| ' \/ -_) _| / / | | | ' \  _/ -_) '_(_-<
#  \___|_||_\___\__|_\_\ |_|_|_||_\__\___|_| /__/
#                                                

def executable_exists(script, label):
    if not len(script):
        sys.exit(
            _('Syntax error in command configuration for {} ').format(label))

    scriptname = script.split(' ').pop(0)
    if not len(scriptname):
        sys.exit(
            _('Syntax error in command configuration for {} ').format(label))

    def is_executable(path):
        return os.path.exists(path) and os.access(path, os.X_OK)

    if scriptname.startswith('/'):
        return is_executable(scriptname) and scriptname or None

    possibles = [path for path in
                 [os.path.join(path, scriptname)
                  for path in os.environ.get('PATH').split(':')]
                 if is_executable(path)]
    return len(possibles) and possibles.pop(0) or None


def get_working_linters(config):
    return set([key for key in config.keys()
                if executable_exists(config[key]['command'], key)])


def print_linters(config):
    print(_('Currently supported linters:'))
    working = get_working_linters(config)
    broken = (set(config.keys()) - working)
    for key in sorted(working):
        print('{:<14} {}'.format(key, config[key].get('comment', '')))
    for key in sorted(broken):
        print('{:<14} {}'.format(key, _('(WARNING: executable not found)')))





#   ___     _     _ _    _          __    __ _ _        
#  / __|___| |_  | (_)__| |_   ___ / _|  / _(_) |___ ___
# | (_ / -_)  _| | | (_-<  _| / _ \  _| |  _| | / -_|_-<
#  \___\___|\__| |_|_/__/\__| \___/_|   |_| |_|_\___/__/
#                                                       

def get_filelist(cmdline, extras):
    """ Returns the list of files against which we'll run the linters. """

    
    def base_file_filter(files):
        """ Return the full path for all files """
        return [os.path.join(git_base, file) for file in files]


    def cwd_file_filter(files):
        """ Return the full path for only those files in the cwd and down """
        gitcwd = os.path.join(os.path.relpath(os.getcwd(), git_base), '')
        return base_file_filter([file for file in files
                                 if file.startswith(gitcwd)])


    def check_for_conflicts(filesets):
        """ Scan list of porcelain files for merge conflic state. """
        MERGE_CONFLICT_PAIRS = set(['DD', 'DU', 'AU', 'AA', 'UD', 'UA', 'UU'])
        status_pairs = set(['' + f[0] + f[1] for f in filesets])
        if len(status_pairs & MERGE_CONFLICT_PAIRS):
            sys.exit(
                _('Current repository contains merge conflicts. Linters will not be run.'))
        return filesets


    def remove_submodules(files):
        """ Remove all submodules from the list of files git-lint cares about. """

        fixer_re = re.compile('^(\\.\\.\\/)+')
        submodules = split_git_response(['submodule', 'status'])
        submodule_names = [fixer_re.sub('', submodule.split(' ')[2])
                           for submodule in submodules]
        return [file for file in files if (file not in submodule_names)]


    def get_porcelain_status():
        """ Return the status of all files in the system. """
        cmd = ['status', '-z', '--porcelain',
               '--untracked-files=all', '--ignore-submodules=all']
        stream = [entry for entry in get_git_response(cmd).split(u'\x00')
                  if len(entry) > 0]

        def parse_stream(acc, stream):
            """Parse the list of files.  T

            The list is null-terminated, but is not columnar.  If
            there's an 'R' in the index state, it means the file was
            renamed and the old name is added as a column, so it's a
            special case as we accumulate the list of files.
            """

            if len(stream) == 0:
                return acc
            entry = stream.pop(0)
            (index, workspace, filename) = (entry[0], entry[1], entry[3:])
            if index == 'R':
                stream.pop(0)
            return parse_stream(acc + [(index, workspace, filename)], stream)

        return check_for_conflicts(parse_stream([], stream))


    def staging_list():
        """ Return the list of files added or modified to the stage """

        return [filename for (index, workspace, filename) in get_porcelain_status()
                if index in ['A', 'M']]


    def working_list():
        """ Return the list of files that have been modified in the workspace.  
        
        Includes the '?' to include files that git is not currently tracking.
        """
        return [filename for (index, workspace, filename) in get_porcelain_status()
                if workspace in ['A', 'M', '?']]


    def all_list():
        """ Return all the files git is currently tracking for this repository. """
        cmd = ['ls-tree', '--name-only', '--full-tree', '-r', '-z', git_head]
        return [file for file in get_git_response(cmd).split(u'\x00')
                if len(file) > 0]

    if len(extras):
        cwd = os.path.abspath(os.getcwd())
        extras_fullpathed = set([os.path.join(cwd, f) for f in extras])
        not_found = set([f for f in extras_fullpathed if not os.path.isfile(f)])
        for f in not_found:
            print(_("File not found: {}").format(f))
        return [os.path.relpath(f, cwd) for f in (extras_fullpathed - not_found)]
    
    working_directory_trans = cwd_file_filter
    if 'base' in cmdline or 'every' in cmdline:
        working_directory_trans = base_file_filter

    file_list_generator = working_list
    if 'all' in keys:
        file_list_generator = all_list
    if 'staging' in keys:
        file_list_generator = staging_list

    return working_directory_trans(remove_submodules(file_list_generator()))


#  ___ _             _                                                
# / __| |_ __ _ __ _(_)_ _  __ _  __ __ ___ _ __ _ _ __ _ __  ___ _ _ 
# \__ \  _/ _` / _` | | ' \/ _` | \ V  V / '_/ _` | '_ \ '_ \/ -_) '_|
# |___/\__\__,_\__, |_|_||_\__, |  \_/\_/|_| \__,_| .__/ .__/\___|_|  
#              |___/       |___/                  |_|  |_|            

def pick_stash_runner(cmdline):
    """Choose a runner.

    This is the operation that will run the linters.  It exists to
    provide a way to stash the repository, then restore it when
    complete.  If possible, it attempts to restore the access and
    modification times of the file in order to comfort IDEs that are
    constantly monitoring file times.
    """

    def staging_wrapper(run_linters):
        def time_gather(f):
            stats = os.stat(f)
            return (f, (stats.atime, stats.mtime))

        times = [time_gather(file) for file in files]
        run_git_command(['stash', '--keep-index'])

        results = run_linters()
        run_git_command(['reset', '--hard'])
        run_git_command(['stash', 'pop', '--quiet', '--index'])

        for (filename, timepair) in times:
            os.utime(filename, timepair)
        return results

    
    def workspace_wrapper(run_linters):
        return run_linters()

    return 'staging' in cmdline and staging_wrapper or workspace_wrapper

#  ___             _ _     _
# | _ \_  _ _ _   | (_)_ _| |_   _ __  __ _ ______
# |   / || | ' \  | | | ' \  _| | '_ \/ _` (_-<_-<
# |_|_\\_,_|_||_| |_|_|_||_\__| | .__/\__,_/__/__/
#                               |_|

def run_external_linter(filename, linter, linter_name):

    """Run one linter against one file.

    If the result matches the error condition specified in the
    configuration file, return the error code and messages, either
    return nothing.
    """

    def encode_shell_messages(prefix, messages):
        return ['{}{}'.format(prefix, line)
                for line in messages.splitlines()]


    cmd = linter['command'] + ' "' + filename + '"'
    (out, err, returncode) = get_shell_response(cmd)
    failed = ((out and (linter.get('condition', 'error') == 'output')) or err or (not (returncode == 0)))
    if not failed:
        return (filename, linter_name, 0, [])

    prefix = linter.get('print', False) and '\t{}:'.format(filename) or '\t'
    output = encode_shell_messages(prefix, out) + (err and encode_shell_messages(prefix, err) or [])
    return (filename, linter_name, (returncode or 1), output)



def run_one_linter(linter, filenames):

    """ Runs one linter against a set of files

    Creates a match filter for the linter, extract the files to be
    linted, and runs the linter against each file, returning the
    result as a list of successes and failures.  Failures have a
    return code and the output of the lint process.
    """
    linter_name, config = list(linter.items()).pop()
    match_filter = make_match_filter(linter)
    files = set([file for file in filenames if match_filter(file)])
    return [run_external_linter(file, config, linter_name) for file in files]


def build_lint_runner(linters, filenames):

    """ Returns a function to run a set of linters against a set of filenames

    This returns a function because it's going to be wrapped in a
    runner to better handle stashing and restoring a staged commit.
    """
    def lint_runner():
        keys = sorted(linters.keys())
        return reduce(operator.add,
                      [run_one_linter({key: linters[key]}, filenames) for key in keys], [])
    return lint_runner


#  __  __      _
# |  \/  |__ _(_)_ _
# | |\/| / _` | | ' \
# |_|  |_\__,_|_|_||_|
#


def run_gitlint(cmdline, config, extras):

    def build_config_subset(keys):
        """ Returns a subset of the configuration, with only those linters mentioned in keys """
        return {item[0]: item[1] for item in config.items() if item[0] in keys}

    """ Runs the requested linters """
    all_files = get_filelist(cmdline, extras)
    stash_runner = pick_runner(cmdline)
    is_lintable = make_match_filter(config)
    lintable_files = set([file for file in all_files if lintable(file)])
    unlintable_files = (set(all_files) - lintable_files)

    working_linters = get_working_linters(config)
    broken_linters = (set(config) - set(working_linters))
    cant_lint_filter = make_match_filter(build_config_subset(broken_linters))
    cant_lint_files = set([file for file in lintable_files if cant_lint_filter(file)])
    lint_runner = build_lint_runner(build_config_subset(working_linters), lintable_files)

    results = stash_runner(lint_runner)

    print(list(results))
    return max(*[i[2] for i in results if len(i)])


def print_help():
    print(_('Usage: {} [options] [filenames]').format(NAME))
    for item in OPTIONS_LIST:
        print(' -{:<1}  --{:<12}  {}'.format(item[0], item[1], item[3]))
    return sys.exit()


def print_version():
    print('{} {} Copyright (c) 2009, 2016 Kennth M. "Elf" Sternberg'.format(NAME, VERSION))


def main(*args):
    if git_base is None:
        sys.exit(_('A git repository was not found.'))

    (cmdline, filenames, excluded_commands) = make_rational_options(OPTIONS_LIST, args)

    if len(excluded_commands) > 0:
        print(_('These command line options were ignored due to option precedence.'))
        for exc in excluded_commands:
            print "\t{}".format(exc)

    try:
        config = get_config(cmdline, git_base)

        if 'help' in cmdline:
            print_help()
            return 0

        if 'version' in cmdline:
            print_version()
            return 0

        if 'linters' in cmdline:
            print_linters(config)
            return 0

        return run_gitlint(cmdline, config, filenames)

    except getopt.GetoptError as err:
        print_help(OPTIONS_LIST)
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main(*sys.argv))
