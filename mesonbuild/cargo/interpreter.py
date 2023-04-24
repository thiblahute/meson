# SPDX-License-Identifier: Apache-2.0
# Copyright © 2022 Intel Corporation

"""Interpreter for converting Cargo Toml definitions to Meson AST

There are some notable limits here. We don't even try to convert something with
a build.rs, there's so few limits on what Cargo alows a build.rs (basically
none), and no good way for us to convert time. In that case, an actual meson port
will be required.
"""

from __future__ import annotations
import dataclasses
import glob
import importlib
import itertools
import os
import typing as T

from . import builder
from . import version
from .. import mparser
from .._pathlib import Path

if T.TYPE_CHECKING:
    from types import ModuleType

    from . import manifest
    from ..environment import Environment
    from ..wrap import PackageDefinition

# tomllib is present in python 3.11, before that it is a pypi module called tomli,
# we try to import tomllib, then tomli,
# TODO: add a fallback to toml2json
tomllib: T.Optional[ModuleType] = None
for t in ['tomllib', 'tomli']:
    try:
        tomllib = importlib.import_module(t)
    except ImportError:
        pass

def fixup_meson_varname(name: str) -> str:
    """Fixup a meson variable name

    :param name: The name to fix
    :return: the fixed name
    """
    return name.replace('-', '_')

@T.overload
def _fixup_keys(d: manifest.BuildTarget) -> manifest.FixedBuildTarget: ...

@T.overload
def _fixup_keys(d: manifest.Dependency) -> manifest.FixedDependency: ...

@T.overload
def _fixup_keys(d: manifest.Package) -> manifest.FixedPackage: ...

def _fixup_keys(d: T.Union[manifest.BuildTarget, manifest.Dependency, manifest.Package]
                ) -> T.Union[manifest.FixedBuildTarget, manifest.FixedDependency,
                             manifest.FixedPackage]:
    """Replace any - in cargo dictionary keys with _

    :param k: The string to fix
    :return: the fixed string
    """
    return {k.replace('-', '_'): v for k, v in d.items()}


@dataclasses.dataclass
class Package:

    """Representation of a Cargo Package entry, with defaults filled in."""

    name: str
    version: str
    description: str
    resolver: T.Optional[str] = None
    authors: T.List[str] = dataclasses.field(default_factory=list)
    edition: manifest.EDITION = '2015'
    rust_version: T.Optional[str] = None
    documentation: T.Optional[str] = None
    readme: T.Optional[str] = None
    homepage: T.Optional[str] = None
    repository: T.Optional[str] = None
    license: T.Optional[str] = None
    license_file: T.Optional[str] = None
    keywords: T.List[str] = dataclasses.field(default_factory=list)
    categories: T.List[str] = dataclasses.field(default_factory=list)
    workspace: T.Optional[str] = None
    build: T.Optional[str] = None
    links: T.Optional[str] = None
    exclude: T.List[str] = dataclasses.field(default_factory=list)
    include: T.List[str] = dataclasses.field(default_factory=list)
    publish: bool = True
    metadata: T.Dict[str, T.Dict[str, str]] = dataclasses.field(default_factory=dict)
    default_run: T.Optional[str] = None
    autobins: bool = True
    autoexamples: bool = True
    autotests: bool = True
    autobenches: bool = True


@dataclasses.dataclass
class SystemDependency:
    name: T.Optional[str]
    version: T.Optional[T.List[str]] = None
    features: T.Dict[str, T.Dict[str, str]] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_raw(cls, k: str, raw: manifest.DependencyV) -> Dependency:
        """Create a dependency from a raw cargo dictionary"""
        fixed = _fixup_keys(raw)
        fixed = {
            'name': raw.get('name', k),
            'version': version.convert(fixed['version']),
            'features': {k: v for k, v in fixed.items() if k not in ['name', 'version']}
        }

        return cls(**fixed)

@dataclasses.dataclass
class Dependency:

    """Representation of a Cargo Dependency Entry."""

    version: T.List[str]
    registry: T.Optional[str] = None
    git: T.Optional[str] = None
    branch: T.Optional[str] = None
    rev: T.Optional[str] = None
    path: T.Optional[str] = None
    optional: bool = False
    package: T.Optional[str] = None
    default_features: bool = False
    features: T.List[str] = dataclasses.field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: manifest.DependencyV) -> Dependency:
        """Create a dependency from a raw cargo dictionary"""
        if isinstance(raw, str):
            return cls(version.convert(raw))

        fixed = _fixup_keys(raw)
        fixed['version'] = version.convert(fixed['version'])
        return cls(**fixed)


@dataclasses.dataclass
class BuildTarget:

    name: str
    crate_type: manifest.CRATE_TYPE = 'lib'
    path: dataclasses.InitVar[T.Optional[str]] = None

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-test-field
    # True for lib, bin, test
    test: bool = True

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-doctest-field
    # True for lib
    doctest: bool = False

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-bench-field
    # True for lib, bin, benchmark
    bench: bool = True

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-doc-field
    # True for libraries and binaries
    doc: bool = False

    harness: bool = True
    edition: manifest.EDITION = '2015'
    required_features: T.List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Library(BuildTarget):

    """Representation of a Cargo Library Entry."""

    doctest: bool = True
    doc: bool = True
    proc_macro: bool = False
    crate_type: manifest.CRATE_TYPE = 'lib'
    doc_scrape_examples: bool = True
    plugin: bool = False


@dataclasses.dataclass
class Binary(BuildTarget):

    """Representation of a Cargo Bin Entry."""

    doc: bool = True
    crate_type: manifest.CRATE_TYPE = 'bin'


@dataclasses.dataclass
class Test(BuildTarget):

    """Representation of a Cargo Test Entry."""

    bench: bool = True
    crate_type: manifest.CRATE_TYPE = 'bin'


@dataclasses.dataclass
class Benchmark(BuildTarget):

    """Representation of a Cargo Test Entry."""

    test: bool = True
    crate_type: manifest.CRATE_TYPE = 'bin'


@dataclasses.dataclass
class Example(BuildTarget):

    """Representation of a Cargo Example Entry."""

    crate_type: manifest.CRATE_TYPE = 'bin'


@dataclasses.dataclass
class Manifest:

    """Cargo Manifest definition.

    Most of these values map up to the Cargo Manifest, but with default values
    if not provided.

    Cargo subprojects can contain what Meson wants to treat as multiple,
    interdependent, subprojects.

    :param subdir: the subdirectory that this cargo project is in
    :param path: the path within the cargo subproject.
    :param default_features:
        The default features split out of the features dict
    :param wants_defaults:
        If this subproject has been requested with or without defaults.
        Due to the way cargo works, we assume defaults unless it is explicitly
        asked to not have defaults. But if *any* subproject asks for defaults
        then they all get them
    :param enabled_features:
        A list of all enabled features, except the default features
    """

    package: Package
    dependencies: T.Dict[str, Dependency]
    dev_dependencies: T.Dict[str, Dependency]
    build_dependencies: T.Dict[str, Dependency]
    system_dependencies: T.Dict[str, SystemDependency]
    lib: Library
    bin: T.List[Binary]
    test: T.List[Test]
    bench: T.List[Benchmark]
    example: T.List[Example]
    features: T.Dict[str, T.List[str]]
    target: T.Dict[str, T.Dict[str, Dependency]]

    subdir: str
    path: str = ''
    default_features: T.List[str] = dataclasses.field(default_factory=list)
    wants_defaults: T.Optional[bool] = dataclasses.field(default=None, init=False)
    enabled_features: T.List[str] = dataclasses.field(default_factory=list, init=False)


def _create_project(package: Package, build: builder.Builder, env: Environment) -> mparser.FunctionNode:
    """Create a function call

    :param package: The Cargo package to generate from
    :param filename: The full path to the file
    :param meson_version: The generating meson version
    :return: a FunctionNode
    """
    args: T.List[mparser.BaseNode] = []
    args.extend([
        build.string(package.name),
        build.string('rust'),
    ])
    kwargs: T.Dict[str, mparser.BaseNode] = {
        'version': build.string(package.version),
        # Always assume that the generated meson is using the lastest features
        'meson_version': build.string(f'>= {env.coredata.version}'),
        'default_options': build.array([build.string(f'rust_std={package.edition}')]),
    }
    if package.license:
        kwargs['license'] = build.string(package.license)

    return build.function('project', args, kwargs)


def _convert_manifest(raw_manifest: manifest.Manifest, subdir: str, path: str = '') -> Manifest:
    # We need to set the name field if it's not set manually,
    # including if oether fields are set in the lib section
    lib = _fixup_keys(raw_manifest.get('lib', {}))
    lib.setdefault('name', raw_manifest['package']['name'])

    # Remove default options from the features set (if any), and store them
    # separately
    features = raw_manifest.get('features', {}).copy()
    defaults = features.pop('default', [])

    return Manifest(
        Package(**_fixup_keys(raw_manifest['package'])),

        {k: Dependency.from_raw(v) for k, v in raw_manifest.get('dependencies', {}).items()},
        {k: Dependency.from_raw(v) for k, v in raw_manifest.get('dev-dependencies', {}).items()},
        {k: Dependency.from_raw(v) for k, v in raw_manifest.get('build-dependencies',{}).items()},
        {k: SystemDependency.from_raw(k, d) for k, d in raw_manifest['package'].get('metadata', {}).get('system-deps', {}).items()},
        # XXX: is this default name right?
        Library(**lib),
        [Binary(**_fixup_keys(b)) for b in raw_manifest.get('bin', {})],
        [Test(**_fixup_keys(b)) for b in raw_manifest.get('test', {})],
        [Benchmark(**_fixup_keys(b)) for b in raw_manifest.get('bench', {})],
        [Example(**_fixup_keys(b)) for b in raw_manifest.get('example', {})],
        features,
        {k: {k2: Dependency.from_raw(v2) for k2, v2 in v['dependencies'].items()}
         for k, v in raw_manifest.get('target', {}).items()},
        subdir=subdir,
        path=path,
        default_features=defaults,
    )


def _load_manifests(subdir: str) -> T.Dict[str, Manifest]:
    filename = os.path.join(subdir, 'Cargo.toml')
    with open(filename, 'rb') as f:
        raw = tomllib.load(f)

    manifests: T.Dict[str, Manifest] = {}

    if 'package' in raw:
        raw_manifest = T.cast('manifest.Manifest', raw)
        m = _convert_manifest(raw_manifest, subdir)
        manifests[m.package.name] = m
    else:
        raw_manifest = T.cast('manifest.VirtualManifest', raw)

    if 'workspace' in raw_manifest:
        # XXX: need to verify that python glob and cargo globbing are the
        # same and probably write  a glob implementation. Blarg

        # We need to chdir here to make the glob work correctly
        pwd = os.getcwd()
        os.chdir(subdir)
        try:
            members = list(itertools.chain.from_iterable(
                glob.glob(m) for m in raw_manifest['workspace']['members']))
        finally:
            os.chdir(pwd)
        if 'exclude' in raw_manifest['workspace']:
            members = (x for x in members if x not in raw_manifest['workspace']['exclude'])

        for m in members:
            filename = os.path.join(subdir, m, 'Cargo.toml')
            with open(filename, 'rb') as f:
                raw = tomllib.load(f)

            raw_manifest = T.cast('manifest.Manifest', raw)
            man = _convert_manifest(raw_manifest, subdir, m)
            manifests[man.package.name] = man

    return manifests


def load_all_manifests(subproject_dir: str) -> T.Dict[str, Manifest]:
    """Find all cargo subprojects, and load them

    :param subproject_dir: Directory to look for subprojects in
    :return: A dictionary of rust project names to Manifests
    """
    manifests: T.Dict[str, Manifest] = {}
    for p in Path(subproject_dir).iterdir():
        if p.is_dir() and (p / 'Cargo.toml').exists():
            manifests.update(_load_manifests(str(p)))
    return manifests

def _lookup_dependency_name(name: str, wrap: T.Optional[PackageDefinition]) -> str:
    if wrap and wrap.cargo_crates_map:
        return wrap.cargo_crates_map.get(name, name)
    return name


def _create_lib(cargo: Manifest, build: builder.Builder, env: Environment) -> T.List[mparser.BaseNode]:
    kw: T.Dict[str, mparser.BaseNode] = {}
    dependencies = []
    depmap = {}
    if cargo.dependencies:
        for name, dependency in cargo.dependencies.items():
            dependencies += [build.identifier(f'dep_{fixup_meson_varname(name)}')]

            if name != dependency.package and dependency.package:
                depmap[dependency.package.replace('-', '_')] = name
    dependency_map = {}
    if depmap:
        dependency_map = {
            'rust_dependency_map': build.dict({build.string(k): build.string(v) for k, v in depmap.items()})
        }

    if cargo.system_dependencies:
        dependencies += [build.identifier(f'dep_{n}') for n in cargo.system_dependencies]

    kw['dependencies'] = build.array(dependencies)

    # FIXME: Add support for nostd and disabling default features
    rust_args = [build.string('--cfg'), build.string(f'feature="default"')]
    rust_args += [build.string('--cfg'), build.string(f'feature="std"')]
    rust_args += [build.string('--cfg'), build.string(f'feature="alloc"')]

    # FIXME: currently assuming that an rlib is being generated, which is
    # the most common.
    return [
        build.assign(
            build.function(
                'static_library',
                [
                    build.string(fixup_meson_varname(cargo.package.name)),
                    build.string(os.path.join('src', 'lib.rs')),
                ],
                kw | {'pic': build.bool(True)} | dependency_map |
                {
                    'rust_args': build.array(rust_args),
                },
            ),
            'lib'
        ),

        build.assign(
            build.function(
                'declare_dependency',
                kw={'link_with': build.identifier('lib')} | kw,
            ),
            'dep'
        ),


        build.method(
            'override_dependency', build.identifier('meson'),
            pos=[build.string(_lookup_dependency_name(cargo.package.name, env.wrap_resolver.wrap)), build.identifier('dep')],
        )
    ]

def interpret(cargo: Manifest, env: Environment) -> mparser.CodeBlockNode:
    filename = os.path.join(cargo.subdir, cargo.path, 'Cargo.toml')
    build = builder.Builder(filename)

    ast: T.List[mparser.BaseNode] = [
        _create_project(cargo.package, build, env),
        build.assign(build.function('import', [build.string('unstable-rust')]), 'rust'),
    ]

    if cargo.dependencies:
        for name, dep in cargo.dependencies.items():
            kw = {
                'version': build.array([build.string(s) for s in dep.version]),
                'required': build.bool(not dep.optional),
            }
            ast.extend([
                build.assign(
                    build.function(
                        'dependency',
                        [build.string(_lookup_dependency_name(name, env.wrap_resolver.wrap))],
                        kw,
                    ),
                    f'dep_{fixup_meson_varname(name)}',
                ),
            ])

    if cargo.system_dependencies:
        for name, dep in cargo.system_dependencies.items():
            kw = {}
            if dep.version is not None:
                kw |= {
                    'version': build.array([build.string(s) for s in dep.version]),
                }
            ast.extend([
                build.assign(
                    build.function(
                        'dependency',
                        [build.string(dep.name)],
                        kw,
                    ),
                    f'dep_{name}',
                ),
            ])

    # Libs are always auto-discovered and there's no other way to handle them,
    # which is unfortunate for reproducability
    if os.path.exists(os.path.join(env.source_dir, cargo.subdir, cargo.path, 'src', 'lib.rs')):
        ast.extend(_create_lib(cargo, build, env))

    # XXX: make this not awful
    block = builder.block(filename)
    block.lines = ast
    return block
