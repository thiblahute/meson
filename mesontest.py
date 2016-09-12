#!/usr/bin/env python3

# Copyright 2016 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# A tool to run tests in many different ways.

import subprocess, sys, os, argparse
import pickle, statistics, json
from mesonbuild.scripts import meson_test

parser = argparse.ArgumentParser()
parser.add_argument('--repeat', default=1, dest='repeat', type=int,
                    help='Number of times to run the tests.')
parser.add_argument('--wrapper', default='', dest='wrapper',
                    help='Exe wrapper (such as Valgrind) to use')
parser.add_argument('--gdb', default=False, dest='gdb', action='store_true',
                    help='Run test under gdb.')
parser.add_argument('--gdb-arg', default=[], dest='gdb_args', action='append',
                    help='Pass extra arguments to gdb (not including "-ex").')
parser.add_argument('--list', default=False, dest='list', action='store_true',
                    help='List available tests.')
parser.add_argument('tests', nargs='*')

def gdbrun(test, options):
    child_env = os.environ.copy()
    child_env.update(test.env)
    # On success will exit cleanly. On failure gdb will ask user
    # if they really want to exit.
    exe = test.fname
    args = test.cmd_args
    if len(args) > 0:
        argset = ['-ex', 'set args ' + ' '.join(args)]
    else:
        argset = []

    test.gdb_args += options.gdb_args

    res = meson_test.run_single_test(['gdb'], test)
    if (res.returncode == 0 and res.should_fail) or \
        (res.returncode != 0 and not res.should_fail):
        print(res.stdo)
        print(res.stde)
        raise RuntimeError('Test failed.')


def run(args):
    datafile = 'meson-private/meson_test_setup.dat'
    options = parser.parse_args(args)
    if options.wrapper != '':
        wrap = options.wrapper.split(' ')
    else:
        wrap = []
    if options.gdb and len(options.wrapper) > 0:
        print('Can not specify both a wrapper and gdb.')
        return 1
    tests = pickle.load(open(datafile, 'rb'))
    if options.list:
        for i in tests:
            print(i.name)
        return 0
    for t in tests:
        if t.name in options.tests:
            for i in range(options.repeat):
                print('Running: %s %d/%d' % (t.name, i+1, options.repeat))
                if options.gdb:
                    gdbrun(t, options)
                else:
                    res = meson_test.run_single_test(wrap, t)
                    if (res.returncode == 0 and res.should_fail) or \
                        (res.returncode != 0 and not res.should_fail):
                        print(res.stdo)
                        print(res.stde)
                        raise RuntimeError('Test failed.')

if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
