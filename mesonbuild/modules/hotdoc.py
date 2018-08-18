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

import os

from mesonbuild import mesonlib
from mesonbuild import mlog, build
from mesonbuild.coredata import MesonException
from . import ModuleReturnValue
from . import ExtensionModule
from . import get_include_args
from . import GirTarget, TypelibTarget
from ..dependencies import Dependency, InternalDependency, ExternalProgram
from ..interpreterbase import FeatureNew, InvalidArguments, noPosargs, noKwargs
from ..interpreter import CustomTargetHolder


def ensure_list(value):
    if not isinstance(value, list):
        return [value]
    return value


MIN_HOTDOC_VERSION = '0.8.100'


class HotdocTargetBuilder:
    def __init__(self, name, state, hotdoc, kwargs):
        self.hotdoc = hotdoc
        self.build_by_default = kwargs.pop('build_by_default', False)
        self.kwargs = kwargs
        self.name = name
        self.state = state

        self.builddir = state.environment.get_build_dir()
        self.sourcedir = state.environment.get_source_dir()
        self.subdir = state.subdir
        self.build_command = state.environment.get_build_command()

        self.cmd = ['conf', '--project-name', name, "--disable-incremental-build",
                    '--output', os.path.join(self.builddir, self.subdir, self.name + '-doc')]

        self._extra_extension_paths = set()
        self.extra_assets = set()
        self._dependencies = []
        self._subprojects = []
        self.index = None
        self.sitemap = ''

    def process_known_arg(self, option, types, argname=None,
                          value_processor=None, mandatory=False,
                          force_list=False):
        if not argname:
            argname = option.strip("-").replace("-", "_")

        value, _ = self.get_value(
            types, argname, None, value_processor, mandatory, force_list)

        self.set_arg_value(option, value)

        return value

    def set_arg_value(self, option, value):
        if value is None:
            return

        if isinstance(value, bool):
            self.cmd.append(option)
        elif isinstance(value, list):
            # Do not do anything on empty lists
            if value:
                if option:
                    self.cmd.extend([option] + value)
                else:
                    self.cmd.extend(value)
        else:
            self.cmd.extend([option, value])

    def process_extra_args(self):
        for arg, value in self.kwargs.items():
            option = "--" + arg.replace("_", "-")
            self.set_arg_value(option, value)

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
            self.cmd.extend(["--extra-extension-path", path])

    def process_extra_extension_paths(self):
        self.get_value([list, str], 'extra_extensions_paths',
                       default="", value_processor=self.setup_extension_paths)

    def replace_dirs_in_string(self, string):
        return string.replace("@SOURCE_ROOT@", self.sourcedir).replace("@BUILD_ROOT@", self.builddir)

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
                self.cmd += ['--include-paths',
                             os.path.join(self.builddir, dep.hotdoc_conf.subdir)]
                self.cmd += ['--extra-assets=' + p for p in dep.extra_assets]
                self.add_extension_paths(dep.extra_extension_paths)
            elif isinstance(dep, build.CustomTarget) or isinstance(dep, build.BuildTarget):
                self._dependencies.append(dep)

        return [f.strip('-I') for f in cflags]

    def process_extra_assets(self):
        self._extra_assets, _ = self.get_value("--extra-assets", (str, list), default=[],
                                               force_list=True)
        for assets_path in self._extra_assets:
            self.cmd.extend(["--extra-assets", assets_path])

    def create_sitemap_if_needed(self, index_name):
        if self.sitemap:
            return

        sitemap_txt = ''
        if self.index is not None:
            sitemap_txt += self.index + '\n\t'
        sitemap_txt += index_name

        self.sitemap = os.path.join(self.builddir, self.subdir, '%s-%s-sitemap.txt' % (
            self.name, self.project_version))
        with open(self.sitemap, 'w') as sitemap:
            sitemap.write(sitemap_txt)

        self.cmd += ['--sitemap', self.sitemap]

    def process_libs(self, libs, languages, lang_prefix=''):
        self.process_dependencies(libs)
        c_includes = []
        for lib in libs:
            for language, compiler in lib.compilers.items():
                if not lang_prefix:
                    languages.append(language)

                sources, _ = self.get_value((str, mesonlib.File, list),
                                            argname='%s%s_sources' % (lang_prefix.replace("-", "_"), language), default=[],
                                            force_list=True, value_processor=self.file_to_path)
                source_filters, _ = self.get_value((str, mesonlib.File, list),
                                            argname='%s%s_sources_filters' % (lang_prefix.replace("-", "_"), language), default=[],
                                            force_list=True, value_processor=self.file_to_path)
                for source in lib.sources:
                    ext = os.path.splitext(source.fname)[1].lstrip('.')
                    if ext in compiler.can_compile_suffixes:
                        sources.append(self.file_to_path(source))

                if language == 'c':
                    for i in reversed(lib.get_include_dirs()):
                        basedir = i.get_curdir()
                        # We should iterate include dirs in reversed orders because
                        # -Ipath will add to begin of array. And without reverse
                        # flags will be added in reversed order.
                        for d in reversed(i.get_incdirs()):
                            # Avoid superfluous '/.' at the end of paths when d is '.'
                            if d not in ('', '.'):
                                expdir = os.path.join(basedir, d)
                            else:
                                expdir = basedir

                            if i.is_system:
                                c_includes.append(os.path.join(self.builddir, expdir))
                            else:
                                c_includes.append(os.path.join(self.builddir, expdir))
                                c_includes.append(os.path.join(self.sourcedir, expdir))

                self.set_arg_value('--%s%s-sources' % (lang_prefix, language),
                    mesonlib.listify(sources, flatten=True))
                if source_filters:
                    self.set_arg_value('--%s%s-sources' % (lang_prefix, language), source_filters)
                self.create_sitemap_if_needed('%s-index' % language)

        if c_includes:
            self.set_arg_value('--c-include-directories', c_includes)

    def process_documented_targets(self):
        languages = mesonlib.listify(self.kwargs.pop('languages', []))
        targets = mesonlib.listify(self.kwargs.pop('documented_targets', []))

        gi_sources = []
        for target in targets:
            target = getattr(target, 'held_object', target)

            if isinstance(target, TypelibTarget):
                pass
            elif isinstance(target, GirTarget):
                self.create_sitemap_if_needed('gi-index')
                self.process_dependencies(target)
                gi_sources.append(os.path.join(self.builddir, target.get_subdir(), target.get_filename()))
                self.process_libs(target.girtargets, languages, 'gi-')
            elif isinstance(target, build.BuildTarget):
                self.process_libs([target], languages)
            else:
                raise InvalidArguments('Target type "%s" not supported.' % target)

        if gi_sources:
            self.cmd += ['--gi-sources'] + gi_sources
            self.cmd.append('--gi-smart-index')
        if languages:
            self.cmd += ['languages'] + languages
            for lang in languages:
                self.cmd.append('--%s-smart-index' % lang)

    def process_subprojects(self):
        _, value = self.get_value([
            list, HotdocTarget], argname="subprojects",
            force_list=True, value_processor=self.process_dependencies)

        if value is not None:
            self._subprojects.extend(value)

    def generate_hotdoc_config(self):
        cwd = os.path.abspath(os.curdir)
        ncwd = os.path.join(self.sourcedir, self.subdir)
        mlog.log('Generating Hotdoc configuration for: ', mlog.bold(self.name))
        os.chdir(ncwd)
        self.hotdoc.run_hotdoc(mesonlib.listify(self.cmd, flatten=True))
        os.chdir(cwd)

    def file_to_path(self, value, res=None):
        if isinstance(value, list):
            if res is None:
                res = []
            for val in value:
                res.append(self.file_to_path(val))

            return res

        if isinstance(value, mesonlib.File):
            return value.absolute_path(self.state.environment.get_source_dir(),
                                       self.state.environment.get_build_dir())
        return value

    def make_relative_path(self, value):
        if not value:
            return value

        if isinstance(value, list):
            res = []
            for val in value:
                res.append(self.make_relative_path(val))
            return res

        if isinstance(value, mesonlib.File):
            return value.absolute_path(self.state.environment.get_source_dir(),
                                       self.state.environment.get_build_dir())

        if os.path.isabs(value):
            return value

        return os.path.relpath(os.path.join(self.state.environment.get_source_dir(), value),
                               self.state.environment.get_build_dir())

    def check_forbiden_args(self):
        for arg in ['conf_file']:
            if arg in self.kwargs:
                raise InvalidArguments('Argument "%s" is forbidden.' % arg)

    def make_targets(self):
        self.check_forbiden_args()
        file_types = (str, mesonlib.File)
        self.project_version = self.process_known_arg("--project-version", (str), mandatory=True)
        self.index = self.process_known_arg("--index", file_types, mandatory=False)
        self.sitemap = self.process_known_arg("--sitemap", file_types, mandatory=False, value_processor=self.file_to_path)
        self.process_known_arg("--html-extra-theme", file_types, value_processor=self.make_relative_path)
        self.process_known_arg("--include-paths", (str, mesonlib.File, list), value_processor=self.make_relative_path)
        self.process_known_arg("--extra-assets", (str, list), force_list=True)
        self.process_known_arg(None, (str, list), "include_paths", force_list=True,
                               value_processor=lambda x: ["--include-paths=%s" % v for v in ensure_list(x)])
        self.process_known_arg('--c-include-directories',
                               [Dependency, build.StaticLibrary, build.SharedLibrary, list], argname="dependencies",
                               force_list=True, value_processor=self.process_dependencies)

        self.process_documented_targets()
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

        self.cmd += ['--conf-file', hotdoc_config_path]
        self.cmd += ['--include-paths', os.path.join(self.builddir, self.subdir)]
        self.cmd += ['--include-paths', os.path.join(self.sourcedir, self.subdir)]

        depfile = os.path.join(self.builddir, self.subdir, self.name + '.deps')
        self.cmd += ['--deps-file-dest', depfile]
        self.generate_hotdoc_config()

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

        try:
            from hotdoc.run_hotdoc import run  # noqa: F401
            self.hotdoc.run_hotdoc = run
        except Exception as e:
            raise MesonException('hotdoc %s required but not found. (%s)' % (
                MIN_HOTDOC_VERSION, e))

    @noKwargs
    def has_extensions(self, state, args, kwargs):
        res = self.hotdoc.run_hotdoc(['--has-extension'] + args) == 0
        return ModuleReturnValue(res, [res])

    def generate_doc(self, state, args, kwargs):
        if len(args) != 1:
            raise MesonException('One positional argument is'
                                 ' required for the project name.')

        project_name = args[0]
        builder = HotdocTargetBuilder(project_name, state, self.hotdoc, kwargs)
        target, install_script = builder.make_targets()
        targets = [HotdocTargetHolder(target, self.interpreter)]
        if install_script:
            targets.append(install_script)

        return ModuleReturnValue(targets[0], targets)


def initialize(interpreter):
    return HotDocModule(interpreter)
