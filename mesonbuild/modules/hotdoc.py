# Copyright 2018 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''This module provides helper functions for generating documentation using hotdoc'''

import json
import os
import subprocess
from collections import OrderedDict

from mesonbuild import mesonlib
from mesonbuild import mlog, build
from mesonbuild.coredata import MesonException
from . import ModuleReturnValue
from . import ExtensionModule
from . import get_include_args
from ..dependencies import Dependency, InternalDependency, ExternalProgram
from ..interpreterbase import FeatureNew, InvalidArguments, noPosargs, noKwargs
from ..interpreter import CustomTargetHolder, OverrideProgram


def ensure_list(value):
    if not isinstance(value, list):
        return [value]
    return value


MIN_HOTDOC_VERSION = '0.8.100'


def has_extension(hotdoc, *args):
    if not isinstance(getattr(hotdoc, "held_object", hotdoc), OverrideProgram):
        try:
            subprocess.check_output(hotdoc.get_command() + ['--has-extension=%s' % extension for extension in args])
        except (MesonException, FileNotFoundError, subprocess.CalledProcessError):
            return False
    return True


class HotdocTargetBuilder:
    def __init__(self, name, state, hotdoc, interpreter, kwargs):
        self.hotdoc = interpreter.find_program_impl('hotdoc', wanted='>=' + MIN_HOTDOC_VERSION)
        self.build_by_default = kwargs.pop('build_by_default', False)
        self.kwargs = kwargs
        self.name = name
        self.state = state
        self.interpreter = interpreter
        self.include_paths = OrderedDict()

        self.builddir = state.environment.get_build_dir()
        self.sourcedir = state.environment.get_source_dir()
        self.subdir = state.subdir
        self.build_command = state.environment.get_build_command()

        self._extra_extension_paths = set()
        self.extra_assets = set()
        self._dependencies = []
        self._subprojects = []
        self.json = {'project_name': name, 'output': os.path.join(self.builddir, self.subdir, self.name + '-doc')}

    def process_known_arg(self, option, types, argname=None,
                          value_processor=None, mandatory=False,
                          force_list=False):
        if not argname:
            argname = option.strip("-").replace("-", "_")

        value, _ = self.get_value(
            types, argname, None, value_processor, mandatory, force_list)

        self.set_arg_value(option, value)

    def set_arg_value(self, option, value):
        if value is None or option is None:
            return

        if option in self.json:
            assert isinstance(self.json[option], list)
            self.json[option].append(value)

            return
        self.json[option] = value

    def check_extra_arg_type(self, arg, value):
        value = getattr(value, 'held_object', value)
        if isinstance(value, list):
            for v in value:
                self.check_extra_arg_type(arg, v)
            return

        valid_types = (str, bool, mesonlib.File, build.IncludeDirs, build.CustomTarget, build.BuildTarget)
        if not isinstance(value, valid_types):
            raise InvalidArguments('Argument "%s=%s" should be of type: %s.' % (
                arg, value, [t.__name__ for t in valid_types]))

    def process_extra_args(self):
        for arg, value in self.kwargs.items():
            self.check_extra_arg_type(arg, value)
            self.set_arg_value(arg, value)

    def get_value(self, types, argname, default=None, value_processor=None,
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
            raise MesonException("%s field value %s is not valid,"
                                 " valid types are %s" % (argname, value,
                                                          types))
        except KeyError:
            if mandatory:
                raise MesonException("%s mandatory field not found" % argname)

            if default is not None:
                return default, default

        return None, None

    def setup_extension_paths(self, paths):
        if not isinstance(paths, list):
            paths = [paths]

        for path in paths:
            self.add_extension_paths([path])

        return []

    def add_extension_paths(self, paths):
        for path in paths:
            if path in self._extra_extension_paths:
                continue

            self._extra_extension_paths.add(path)
            self.add_to_list('extra_extension_path', path)

    def process_extra_extension_paths(self):
        self.get_value([list, str], 'extra_extensions_paths',
                       default="", value_processor=self.setup_extension_paths)

    def replace_dirs_in_string(self, string):
        return string.replace("@SOURCE_ROOT@", self.sourcedir).replace("@BUILD_ROOT@", self.builddir)

    def process_gi_c_source_roots(self):
        if has_extension(self.hotdoc, 'gi-extension'):
            return

        value, _ = self.get_value([list, str], 'gi_c_source_roots', default=[], force_list=True)
        value.extend([
            os.path.join(self.state.environment.get_source_dir(),
                         self.interpreter.subproject_dir, self.state.subproject),
            os.path.join(self.state.environment.get_build_dir(), self.interpreter.subproject_dir, self.state.subproject)
        ])

        self.json['gi_c_source_roots'] = value

    def process_dependencies(self, deps):
        cflags = set()
        for dep in mesonlib.listify(ensure_list(deps)):
            dep = getattr(dep, "held_object", dep)
            if isinstance(dep, InternalDependency):
                inc_args = get_include_args(dep.include_directories)
                cflags.update([self.replace_dirs_in_string(x)
                               for x in inc_args])
                cflags.update(self.process_dependencies(dep.libraries))
                cflags.update(self.process_dependencies(dep.sources))
                cflags.update(self.process_dependencies(dep.ext_deps))
            elif isinstance(dep, Dependency):
                cflags.update(dep.get_compile_args())
            elif isinstance(dep, (build.StaticLibrary, build.SharedLibrary)):
                self._dependencies.append(dep)
                for incd in dep.get_include_dirs():
                    cflags.update(incd.get_incdirs())
            elif isinstance(dep, HotdocTarget):
                # Recurse in hotdoc target dependencies
                self.process_dependencies(dep.get_target_dependencies())
                self._subprojects.extend(dep.subprojects)
                self.process_dependencies(dep.subprojects)
                self.add_include_path(os.path.join(self.builddir, dep.hotdoc_conf.subdir))
                self.add_to_list('extra_assets', list(dep.extra_assets))
                self.add_extension_paths(dep.extra_extension_paths)
            elif isinstance(dep, build.CustomTarget) or isinstance(dep, build.BuildTarget):
                self._dependencies.append(dep)

        return [f.strip('-I') for f in cflags]

    def add_to_list(self, key, val):
        l = self.json.get(key, [])
        l.extend(val)
        self.json[key] = l

    def process_extra_assets(self):
        self._extra_assets, _ = self.get_value("--extra-assets", (str, list), default=[],
                                               force_list=True)
        self.add_to_list('extra_assets', list(self.extra_assets))

    def process_subprojects(self):
        _, value = self.get_value([
            list, HotdocTarget], argname="subprojects",
            force_list=True, value_processor=self.process_dependencies)

        if value is not None:
            self._subprojects.extend(value)

    def stringify_value(self, value, is_path):
        if isinstance(value, mesonlib.File):
            return value.absolute_path(self.state.environment.get_source_dir(),
                                    self.state.environment.get_build_dir())
        elif isinstance(value, build.IncludeDirs):
            res = []
            for inc_dir in value.get_incdirs():
                res.append(os.path.join(self.sourcedir, value.get_curdir(), inc_dir))
                res.append(os.path.join(self.builddir, value.get_curdir(), inc_dir))

            return res
        elif isinstance(value, build.CustomTarget) or isinstance(value, build.BuildTarget):
            return self.interpreter.backend.get_target_filename_abs(value)
        elif is_path and isinstance(value, str):
            return os.path.abspath(value)

        return value

    def save_config(self, config_path):
        config = {}
        for key, value in self.json.items():
            key = key.replace('-', '_')
            is_path = key.endswith('index') or key.endswith('sources') or key == 'include_paths'
            if isinstance(value, list):
                reslist = []
                value = mesonlib.listify(value, flatten=True)
                for v in value:
                    reslist.append(self.stringify_value(v, is_path))
                value = reslist
            else:
                value = self.stringify_value(value, is_path)

            if isinstance(value, str) and (key.endswith('sources') or key == 'extra_c_flags'):
                value = [value]

            # stringify_value might return nested lists
            if isinstance(value, list):
                value = mesonlib.listify(value, flatten=True)

            config[key] = value

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)


    def generate_hotdoc_config(self, path):
        cwd = os.path.abspath(os.curdir)
        ncwd = os.path.join(self.sourcedir, self.subdir)
        mlog.log('Generating Hotdoc configuration for: ', mlog.bold(self.name))
        os.chdir(ncwd)
        self.save_config(path)
        os.chdir(cwd)

    def ensure_file(self, value):
        if isinstance(value, list):
            res = []
            for val in value:
                res.append(self.ensure_file(val))
            return res

        if not isinstance(value, mesonlib.File):
            return mesonlib.File.from_source_file(self.sourcedir, self.subdir, value)

        return value

    def ensure_dir(self, value):
        if os.path.isabs(value):
            _dir = value
        else:
            _dir = os.path.join(self.sourcedir, self.subdir, value)

        if not os.path.isdir(_dir):
            raise InvalidArguments('"%s" is not a directory.' % _dir)

        return os.path.relpath(_dir, os.path.join(self.builddir, self.subdir))

    def check_forbiden_args(self):
        for arg in ['conf_file']:
            if arg in self.kwargs:
                raise InvalidArguments('Argument "%s" is forbidden.' % arg)

    def add_include_path(self, path):
        self.include_paths[path] = path

    def make_targets(self):
        self.check_forbiden_args()
        file_types = (str, mesonlib.File)
        self.process_known_arg("index", file_types, mandatory=True, value_processor=self.ensure_file)
        self.process_known_arg("project_version", str, mandatory=True)
        self.process_known_arg("sitemap", file_types, mandatory=True, value_processor=self.ensure_file)
        self.process_known_arg("html_extra_theme", str, value_processor=self.ensure_dir)
        self.process_known_arg(None, list, "include_paths", force_list=True,
                               value_processor=lambda x: [self.add_include_path(self.ensure_dir(v)) for v in ensure_list(x)])
        self.process_known_arg('c_include_directories',
                               [Dependency, build.StaticLibrary, build.SharedLibrary, list], argname="dependencies",
                               force_list=True, value_processor=self.process_dependencies)
        self.process_gi_c_source_roots()
        self.process_extra_assets()
        self.process_extra_extension_paths()
        self.process_subprojects()

        install, install = self.get_value(bool, "install", mandatory=False)
        self.process_extra_args()

        fullname = self.name + '-doc'
        hotdoc_config_name = fullname + '.json'
        hotdoc_config_path = os.path.join(
            self.builddir, self.subdir, hotdoc_config_name)
        with open(hotdoc_config_path, 'w') as f:
            f.write('{}')

        self.add_include_path(os.path.join(self.builddir, self.subdir))
        self.add_include_path(os.path.join(self.sourcedir, self.subdir))

        depfile = os.path.join(self.builddir, self.subdir, self.name + '.deps')
        self.json['deps_file_dest'] = depfile
        self.json['include_paths'] = list(self.include_paths.keys())

        if self.state.environment.coredata.get_builtin_option('werror'):
            self.json['fatal_warnings'] = True
        self.generate_hotdoc_config(hotdoc_config_path)

        target_cmd = self.build_command + ["--internal", "hotdoc"] + \
            self.hotdoc.get_command() + ['run', '--conf-file', hotdoc_config_name] + \
            ['--builddir', os.path.join(self.builddir, self.subdir)]

        target = HotdocTarget(fullname,
                              subdir=self.subdir,
                              subproject=self.state.subproject,
                              hotdoc_conf=mesonlib.File.from_built_file(
                                  self.subdir, hotdoc_config_name),
                              extra_extension_paths=self._extra_extension_paths,
                              extra_assets=self._extra_assets,
                              subprojects=self._subprojects,
                              command=target_cmd,
                              depends=self._dependencies,
                              output=fullname,
                              depfile=os.path.basename(depfile),
                              build_by_default=self.build_by_default)

        install_script = None
        if install is True:
            install_script = HotdocRunScript(self.build_command, [
                "--internal", "hotdoc",
                "--install", os.path.join(fullname, 'html'),
                '--name', self.name,
                '--builddir', os.path.join(self.builddir, self.subdir)] +
                self.hotdoc.get_command() +
                ['run', '--conf-file', hotdoc_config_name])

        return (target, install_script)


class HotdocTargetHolder(CustomTargetHolder):
    def __init__(self, target, interp):
        super().__init__(target, interp)
        self.methods.update({'config_path': self.config_path_method})

    @noPosargs
    @noKwargs
    def config_path_method(self, *args, **kwargs):
        conf = self.held_object.hotdoc_conf.absolute_path(self.interpreter.environment.source_dir,
                                                          self.interpreter.environment.build_dir)
        return self.interpreter.holderify(conf)


class HotdocTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, hotdoc_conf, extra_extension_paths, extra_assets,
                 subprojects, **kwargs):
        super().__init__(name, subdir, subproject, kwargs, absolute_paths=True)
        self.hotdoc_conf = hotdoc_conf
        self.extra_extension_paths = extra_extension_paths
        self.extra_assets = extra_assets
        self.subprojects = subprojects

    def __getstate__(self):
        # Make sure we do not try to pickle subprojects
        res = self.__dict__.copy()
        res['subprojects'] = []

        return res


class HotdocRunScript(build.RunScript):
    def __init__(self, script, args):
        super().__init__(script, args)


class HotDocModule(ExtensionModule):
    @FeatureNew('Hotdoc Module', '0.48.0')
    def __init__(self, interpreter):
        super().__init__(interpreter)
        self.hotdoc = ExternalProgram('hotdoc')
        if not self.hotdoc.found():
            raise MesonException('hotdoc executable not found')

    @noKwargs
    def has_extensions(self, state, args, kwargs):
        # Handle overridden g-ir-scanner
        res = has_extension(self.hotdoc, *args)
        return ModuleReturnValue(res, [res])

    def generate_doc(self, state, args, kwargs):
        if len(args) != 1:
            raise MesonException('One positional argument is'
                                 ' required for the project name.')

        project_name = args[0]
        builder = HotdocTargetBuilder(project_name, state, self.hotdoc, self.interpreter, kwargs)
        target, install_script = builder.make_targets()
        targets = [HotdocTargetHolder(target, self.interpreter)]
        if install_script:
            targets.append(install_script)

        return ModuleReturnValue(targets[0], targets)


def initialize(interpreter):
    return HotDocModule(interpreter)
