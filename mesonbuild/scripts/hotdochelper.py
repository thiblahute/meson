import os
import shutil
import subprocess

from . import destdir_join

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--install')
parser.add_argument('--extra-extension-path', action="append", default=[])
parser.add_argument('--name')
parser.add_argument('--subdir')
parser.add_argument('--project-version')


def run(argv):
    options, args = parser.parse_known_args(argv)
    subenv = os.environ.copy()

    for ext_path in options.extra_extension_path:
        os.environ['PYTHONPATH'] = os.environ.get('PYTHONPATH', '') + ':' + ext_path

    builddir = os.path.join(os.environ['MESON_BUILD_ROOT'], options.subdir)
    print("===> Running(%s) %s" % (builddir, ' '.join(args)))
    res = subprocess.call(args, cwd=builddir, env=subenv)

    if res != 0:
        exit(res)

    if options.install:
        source_dir = os.path.join(builddir, options.install)
        destdir = os.environ.get('DESTDIR', '')
        installdir = destdir_join(destdir,
                                  os.path.join(os.environ['MESON_INSTALL_PREFIX'],
                                  'share/doc/', options.name, "html"))

        shutil.rmtree(installdir, ignore_errors=True)
        shutil.copytree(source_dir, installdir)
