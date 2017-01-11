import os
import shutil
import subprocess

from . import destdir_join

def run(argv):
    if argv[0] == "install":
        os.environ['HOTDOC_EXTENSION_PATH'] = argv[3]
        args = argv[4:]
    else:
        os.environ['HOTDOC_EXTENSION_PATH'] = argv[1]
        args = argv[2:]

    builddir = os.environ['MESON_BUILD_ROOT']
    res = subprocess.call(args, cwd=builddir)

    if res != 0:
        exit(res)

    if argv[0] == "install":
        name = argv[2]

        source_dir = os.path.join(builddir, argv[1], "html")
        destdir = os.environ.get('DESTDIR', '')
        installdir = destdir_join(destdir,
                                  os.path.join(os.environ['MESON_INSTALL_PREFIX'],
                                  'share/doc/', name, "html"))

        shutil.rmtree(installdir, ignore_errors=True)
        shutil.copytree(source_dir, installdir)
