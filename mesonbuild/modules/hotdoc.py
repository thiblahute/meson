import os
import sys
import subprocess

from mesonbuild import mesonlib
from mesonbuild import interpreter
from mesonbuild import mlog, build
from mesonbuild.coredata import MesonException
from . import ModuleReturnValue
from . import ExtensionModule
from . import get_include_args
from ..dependencies import Dependency, InternalDependency, ExternalProgram


def ensure_list(value):
    if not isinstance(value, list):
        return [value]
    return value


NO_VALUE = "__no value at all__"
class CmdBuilder:
    def __init__(self, cmd, kwargs):
        self.kwargs = kwargs
        self.cmd = cmd

    def add_arg(self, option, types, argname=None, default=NO_VALUE,
                value_processor=None, mandatory=False, force_list=False,
                local_default=NO_VALUE, keep_processed=False):
        if not argname:
            argname = option.strip("-").replace("-", "_")

        value, unprocessed_value = self.get_value(
            types, argname, default, value_processor, mandatory, force_list)

        self.set_value(option, argname, value, unprocessed_value, local_default, keep_processed=keep_processed)

    def set_value(self, option, argname, value, unprocessed_value=None, default=NO_VALUE,
                  keep_processed=False):
        if value != NO_VALUE:
            if isinstance(value, bool):
                self.cmd.append(option)
            elif isinstance(value, list):
                self.cmd.extend([option] + value)
            else:
                self.cmd.extend([option, value])
        elif default != NO_VALUE:
            value = default
        else:
            return

        if keep_processed:
            setattr(self, argname, value)
        else:
            setattr(self, argname, unprocessed_value)

    def add_extra_args(self):
        for arg, value in self.kwargs.items():
            option = "--" + arg.replace("_", "-")
            self.set_value(option, arg, value)

    def get_value(self, types, argname, default=NO_VALUE, value_processor=None,
                  mandatory=False, force_list=False):
        if not isinstance(types, list):
            types = [types]
        try:
            uvalue = value = self.kwargs.pop(argname)
            if value_processor:
                value = value_processor(value)
            for t in types:
                if isinstance(value, t):
                    if force_list and not isinstance(value, list):
                        return [value], uvalue
                    return value, uvalue
            raise MesonException("%s field value %s is not a valid,"
                                " valid types are %s" %(argname, value,
                                                        types))
        except KeyError:
            if mandatory:
                raise MesonException("%s mandatory field not found" % argname)

            if default != NO_VALUE:
                return default, default

        return NO_VALUE, NO_VALUE


class HotDocModule(ExtensionModule):
    def __init__(self):
        super().__init__()
        mlog.log('Detecting HotDoc')
        self.hotdoc = ExternalProgram('hotdoc')
        if not self.hotdoc.found():
            raise MesonException('hotdoc executable not found')

    def generate_doc(self, state, args, kwargs):
        dir(state)
        if len(args) != 1:
            raise MesonException('One positional argument is'
                                 ' required for the project name.')

        fullname = args[0] + '-doc'
        name = args[0]

        def setup_extension_paths(paths):
            if not isinstance(paths, list):
                paths = [paths]
            for path in paths:
                try:
                    subprocess.check_output([sys.executable, os.path.join('setup.py'),
                                            'egg_info'], cwd=path)
                except subprocess.CalledProcessError as e:
                    raise MesonException("Could not setup hotdoc extension %s: %s" % (paths, e))

            return os.pathsep.join(paths)

        cmd_builder = CmdBuilder([], kwargs)
        extra_extension_paths = cmd_builder.get_value([list, str],
                                                      'extra_extensions_paths',
                                                      default="",
                                                      value_processor=setup_extension_paths)

        cmd = self.hotdoc.get_command() + [
            'conf', '--project-name', fullname, "--disable-incremental-build"]
        cmd_builder.cmd = cmd


        if "output" in cmd_builder.kwargs:
            raise MesonException("'output' is not a valid argument for hotdoc targets")

        cmd_builder.add_arg("--output", str, default=os.path.join(state.subdir, fullname))
        def get_abs_path(path):
            if not os.path.isabs(path):
                path = os.path.join(state.environment.get_source_dir(), state.subdir, path)
            return path

        cmd_builder.add_arg("--index", str, mandatory=True,
                            value_processor=get_abs_path,
                            keep_processed=True)
        cmd_builder.add_arg("--sitemap", str, mandatory=True,
                            value_processor=get_abs_path,
                            keep_processed=True)
        cmd_builder.add_arg("--c-sources", list,
                            value_processor=lambda x:[get_abs_path(p) for p in ensure_list(x)],
                            mandatory=False, local_default=[],
                            keep_processed=True)

        dependencies = []
        def extract_cflags(deps):
            cflags = set()
            for dep in ensure_list(deps):
                dep = getattr(dep, "held_object", dep)
                if isinstance(dep, InternalDependency):
                    cflags.update(get_include_args(state.environment, dep.include_directories))
                    cflags.update(extract_cflags(dep.libraries))
                elif isinstance(dep, Dependency):
                    cflags.update(dep.get_compile_args())
                elif isinstance(dep, (build.StaticLibrary, build.SharedLibrary)):
                    dependencies.append(dep)
                    for incd in dep.get_include_dirs():
                        cflags.update(incd.get_incdirs())
                elif isinstance(dep, build.Executable):
                    dependencies.append(dep)

            return [f.strip('-I') for f in cflags]

        cmd_builder.add_arg('--c-include-directories', [Dependency, build.StaticLibrary,
                                              build.SharedLibrary, list],
                            argname="dependencies", local_default=[],
                            force_list=True, value_processor=extract_cflags)

        install, install = cmd_builder.get_value(bool, "install", mandatory=False)

        cmd_builder.add_extra_args()

        jfilename = fullname + '.json'
        jfile = os.path.join(state.subdir, jfilename)
        built_json = mesonlib.File.from_built_file(state.subdir, jfilename)
        cmd = cmd_builder.cmd + ['--output-conf-file', jfile ]
        print("Running %s" % cmd)
        subprocess.check_call(cmd)

        command = [sys.executable, state.environment.get_build_command()]

        res = [build.RunTarget(fullname, command[0], [
            command[1], "--internal", "hotdoc"] +
            self.hotdoc.get_command() + ['run', '--conf-file', jfilename] +
            ['--extra-extension-path=' + p for p in extra_extension_paths if p] +
            ['--subdir', state.subdir],
            dependencies, state.subdir)]
        if install == True:
            res.append(build.RunScript(command, [
                "--internal", "hotdoc",
                "--install", os.path.join(fullname, 'html'),
                '--subdir', state.subdir,
                '--name', name] + self.hotdoc.get_command() +
                ['run', '--conf-file', jfilename]))
        return ModuleReturnValue(interpreter.GeneratedObjectsHolder(built_json), res)

def initialize():
    return HotDocModule()
