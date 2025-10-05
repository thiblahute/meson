from __future__ import annotations

import os, subprocess
import argparse
import tempfile
import shutil
import sys
import itertools
import typing as T

from pathlib import Path
from . import build, minstall
from .mesonlib import (EnvironmentVariables, MesonException, join_args, is_windows, setup_vsenv,
                       get_wine_shortpath, MachineChoice, relpath)
from .options import OptionKey
from . import mlog


if T.TYPE_CHECKING:
    from .backend.backends import InstallData

POWERSHELL_EXES = {'pwsh.exe', 'powershell.exe'}

# Note: when adding arguments, please also add them to the completion
# scripts in $MESONSRC/data/shell-completions/
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('-C', dest='builddir', type=Path, default='.',
                        help='Path to build directory')
    parser.add_argument('--workdir', '-w', type=Path, default=None,
                        help='Directory to cd into before running (default: builddir, Since 1.0.0)')
    parser.add_argument('--dump', nargs='?', const=True,
                        help='Only print required environment (Since 0.62.0) ' +
                             'Takes an optional file path (Since 1.1.0)')
    parser.add_argument('--dump-format', default='export',
                        choices=['sh', 'export', 'vscode'],
                        help='Format used with --dump (Since 1.1.0)')
    parser.add_argument('devcmd', nargs=argparse.REMAINDER, metavar='command',
                        help='Command to run in developer environment (default: interactive shell)')

def get_windows_shell() -> T.Optional[str]:
    mesonbuild = Path(__file__).parent
    script = mesonbuild / 'scripts' / 'cmd_or_ps.ps1'
    for shell in POWERSHELL_EXES:
        try:
            command = [shell, '-noprofile', '-executionpolicy', 'bypass', '-file', str(script)]
            result = subprocess.check_output(command)
            return result.decode().strip()
        except (subprocess.CalledProcessError, OSError):
            pass
    return None

def reduce_winepath(env: T.Dict[str, str]) -> None:
    winepath = env.get('WINEPATH')
    if not winepath:
        return
    winecmd = shutil.which('wine64') or shutil.which('wine')
    if not winecmd:
        return
    env['WINEPATH'] = get_wine_shortpath([winecmd], winepath.split(';'))
    mlog.log('Meson detected wine and has set WINEPATH accordingly')

def get_env(b: build.Build, dump_fmt: T.Optional[str]) -> T.Tuple[T.Dict[str, str], T.Set[str]]:
    extra_env = EnvironmentVariables()
    extra_env.set('MESON_DEVENV', ['1'])
    extra_env.set('MESON_PROJECT_NAME', [b.project_name])

    sysroot = b.environment.properties[MachineChoice.HOST].get_sys_root()
    if sysroot:
        extra_env.set('QEMU_LD_PREFIX', [sysroot])

    env = {} if dump_fmt else os.environ.copy()
    default_fmt = '${0}' if dump_fmt in {'sh', 'export'} or (dump_fmt and dump_fmt.startswith('devenv')) else None
    varnames = set()
    for i in itertools.chain(b.devenv, {extra_env}):
        env = i.get_env(env, default_fmt)
        varnames |= i.get_names()

    reduce_winepath(env)

    return env, varnames

def bash_completion_files(b: build.Build, install_data: 'InstallData') -> T.List[str]:
    from .dependencies.pkgconfig import PkgConfigDependency
    result = []
    dep = PkgConfigDependency('bash-completion', b.environment,
                              {'required': False, 'silent': True, 'version': '>=2.10'})
    if dep.found():
        prefix = b.environment.coredata.optstore.get_value_for(OptionKey('prefix'))
        assert isinstance(prefix, str), 'for mypy'
        datadir = b.environment.coredata.optstore.get_value_for(OptionKey('datadir'))
        assert isinstance(datadir, str), 'for mypy'
        datadir_abs = os.path.join(prefix, datadir)
        completionsdir = dep.get_variable(pkgconfig='completionsdir', pkgconfig_define=(('datadir', datadir_abs),))
        assert isinstance(completionsdir, str), 'for mypy'
        completionsdir_path = Path(completionsdir)
        for f in install_data.data:
            if completionsdir_path in Path(f.install_path).parents:
                result.append(f.path)
    return result

def add_gdb_auto_load(autoload_path: Path, gdb_helper: str, fname: Path) -> None:
    # Copy or symlink the GDB helper into our private directory tree
    destdir = autoload_path / fname.parent
    destdir.mkdir(parents=True, exist_ok=True)
    try:
        if is_windows():
            shutil.copy(gdb_helper, str(destdir / os.path.basename(gdb_helper)))
        else:
            os.symlink(gdb_helper, str(destdir / os.path.basename(gdb_helper)))
    except (FileExistsError, shutil.SameFileError):
        pass

def write_gdb_script(privatedir: Path, install_data: 'InstallData', workdir: Path) -> None:
    if not shutil.which('gdb'):
        return
    bdir = privatedir.parent
    autoload_basedir = privatedir / 'gdb-auto-load'
    autoload_path = Path(autoload_basedir, *bdir.parts[1:])
    have_gdb_helpers = False
    for d in install_data.data:
        if d.path.endswith('-gdb.py') or d.path.endswith('-gdb.gdb') or d.path.endswith('-gdb.scm'):
            # This GDB helper is made for a specific shared library, search if
            # we have it in our builddir.
            libname = Path(d.path).name.rsplit('-', 1)[0]
            for t in install_data.targets:
                path = Path(t.fname)
                if path.name == libname:
                    add_gdb_auto_load(autoload_path, d.path, path)
                    have_gdb_helpers = True
    if have_gdb_helpers:
        gdbinit_line = f'add-auto-load-scripts-directory {autoload_basedir}\n'
        gdbinit_path = bdir / '.gdbinit'
        first_time = False
        try:
            with gdbinit_path.open('r+', encoding='utf-8') as f:
                if gdbinit_line not in f.readlines():
                    f.write(gdbinit_line)
                    first_time = True
        except FileNotFoundError:
            gdbinit_path.write_text(gdbinit_line, encoding='utf-8')
            first_time = True
        if first_time:
            gdbinit_path = gdbinit_path.resolve()
            workdir_path = workdir.resolve()
            rel_path = Path(relpath(gdbinit_path, workdir_path))
            mlog.log('Meson detected GDB helpers and added config in', mlog.bold(str(rel_path)))
            mlog.log('To load it automatically you might need to:')
            mlog.log(' - Add', mlog.bold(f'add-auto-load-safe-path {gdbinit_path.parent}'),
                     'in', mlog.bold('~/.gdbinit'))
            if gdbinit_path.parent != workdir_path:
                mlog.log(' - Change current workdir to', mlog.bold(str(rel_path.parent)),
                         'or use', mlog.bold(f'--init-command {rel_path}'))

def dump(devenv: T.Dict[str, str], varnames: T.Set[str], dump_format: T.Optional[str],
         output: T.Optional[T.TextIO] = None) -> None:
    for name in varnames:
        print(f'{name}="{devenv[name]}"', file=output)
        if dump_format == 'export':
            print(f'export {name}', file=output)

def generate_devenv_script(shell_type: str, devenv: T.Dict[str, str], varnames: T.Set[str],
                           project_name: str, output_path: Path, builddir: Path) -> None:
    """Generate a sourceable devenv script for the specified shell type."""

    # Collect environment variable changes (only the ones we're modifying)
    env_exports = [(var, devenv[var]) for var in sorted(varnames)]

    # Generate shell-specific code
    if shell_type == 'sh':
        restore_vars_lines = []
        for var, _ in env_exports:
            old_var = f'_OLD_MESON_{var}'
            restore_vars_lines.extend([
                f'    if ! [ -z "${{{old_var}+_}}" ] ; then',
                f'        if [ "${{{old_var}}}" = "__NOT__SET__" ] ; then',
                f'            unset {var}',
                '        else',
                f'            {var}="${{{old_var}}}"',
                f'            export {var}',
                '        fi',
                f'        unset {old_var}',
                '    fi',
            ])
        restore_vars = '\n'.join(restore_vars_lines)

        export_vars_lines = []
        for var, value in env_exports:
            # Escape backslashes, quotes, and dollars, but keep $VAR references intact
            safe_value = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$')
            # Un-escape $VAR patterns to allow variable expansion
            import re
            safe_value = re.sub(r'\\\$([A-Z_][A-Z0-9_]*)', r'$\1', safe_value)
            export_vars_lines.extend([
                f'_OLD_MESON_{var}="${{{var}:-__NOT__SET__}}"',
                f'export _OLD_MESON_{var}',
                f'{var}="{safe_value}"',
                f'export {var}',
            ])
        export_vars = '\n'.join(export_vars_lines)
        template_name = 'devenv.sh.template'
        replacements = {
            'restore_vars': restore_vars,
            'export_vars': export_vars,
            'project_name': project_name,
            'builddir': str(builddir.resolve()),
        }

    elif shell_type == 'fish':
        restore_vars_lines = []
        for var, _ in env_exports:
            old_var = f'_OLD_MESON_{var}'
            restore_vars_lines.extend([
                f'    if set -q {old_var}',
                f'        if test "${old_var}" = "__NOT__SET__"',
                f'            set -e {var}',
                '        else',
                f'            set -gx {var} "${old_var}"',
                '        end',
                f'        set -e {old_var}',
                '    end',
            ])
        restore_vars = '\n'.join(restore_vars_lines)

        export_vars_lines = []
        for var, value in env_exports:
            # Escape backslashes and quotes, but keep $VAR references intact
            safe_value = value.replace('\\', '\\\\').replace('"', '\\"')
            old_var = f'_OLD_MESON_{var}'
            export_vars_lines.extend([
                f'if set -q {var}',
                f'    set -gx {old_var} "${var}"',
                'else',
                f'    set -gx {old_var} "__NOT__SET__"',
                'end',
                f'set -gx {var} "{safe_value}"',
            ])
        export_vars = '\n'.join(export_vars_lines)
        template_name = 'devenv.fish.template'
        replacements = {
            'restore_vars_fish': restore_vars,
            'export_vars_fish': export_vars,
            'project_name': project_name,
            'builddir': str(builddir.resolve()),
        }

    elif shell_type == 'ps1':
        restore_vars_lines = []
        for var, _ in env_exports:
            old_var = f'_OLD_MESON_{var}'
            restore_vars_lines.extend([
                f'    if (Test-Path env:{old_var}) {{',
                f'        if ($env:{old_var} -eq "__NOT__SET__") {{',
                f'            Remove-Item env:{var} -ErrorAction SilentlyContinue',
                '        } else {',
                f'            $env:{var} = $env:{old_var}',
                '        }',
                f'        Remove-Item env:{old_var} -ErrorAction SilentlyContinue',
                '    }',
            ])
        restore_vars = '\n'.join(restore_vars_lines)

        export_vars_lines = []
        for var, value in env_exports:
            old_var = f'_OLD_MESON_{var}'
            # Escape backticks and quotes, but keep $VAR references intact
            safe_value = value.replace('`', '``').replace('"', '`"').replace('$', '`$')
            # Un-escape $VAR patterns and convert to $env:VAR for PowerShell
            import re
            safe_value = re.sub(r'`\$([A-Z_][A-Z0-9_]*)', r'$env:\1', safe_value)
            export_vars_lines.extend([
                f'if (Test-Path env:{var}) {{',
                f'    $env:{old_var} = $env:{var}',
                '} else {',
                f'    $env:{old_var} = "__NOT__SET__"',
                '}',
                f'$env:{var} = "{safe_value}"',
            ])
        export_vars = '\n'.join(export_vars_lines)
        template_name = 'devenv.ps1.template'
        replacements = {
            'restore_vars_ps1': restore_vars,
            'export_vars_ps1': export_vars,
            'project_name': project_name,
            'builddir': str(builddir.resolve()),
        }

    elif shell_type == 'nu':
        # Build up environment dictionaries to pass to load-env
        old_vars_merge_lines = []
        new_vars_dict_entries = []

        for var, value in env_exports:
            old_var = f'_OLD_MESON_{var}'
            safe_value = value.replace('\\', '\\\\').replace('"', '\\"')
            # Special handling for PATH: convert list to string with os.pathsep
            if var == 'PATH':
                old_vars_merge_lines.append(
                    f'    | merge (if "{var}" in $env {{ {{{old_var}: ($env.{var} | str join "{os.pathsep}")}} }} else {{ {{{old_var}: "__NOT__SET__"}} }})'
                )
            else:
                old_vars_merge_lines.append(
                    f'    | merge (if "{var}" in $env {{ {{{old_var}: $env.{var}}} }} else {{ {{{old_var}: "__NOT__SET__"}} }})'
                )
            new_vars_dict_entries.append(f'        {var}: "{safe_value}"')

        old_vars_merge = '\n'.join(old_vars_merge_lines)
        new_vars_dict = '\n'.join(new_vars_dict_entries)

        export_vars_parts = [
            '    # Save old Meson variables',
            '    let old_meson_vars = {}',
            old_vars_merge,
            '',
            '    # Set new Meson variables',
            '    let meson_vars = {',
            new_vars_dict,
            f'        MESON_DEVENV_ACTIVE: "{project_name}"',
            f'        MESON_DEVENV_BUILDDIR: "{str(builddir.resolve())}"',
            '    }',
        ]
        export_vars = '\n'.join(export_vars_parts)

        restore_vars_lines = []
        for var, _ in env_exports:
            old_var = f'_OLD_MESON_{var}'
            restore_vars_lines.extend([
                f'    if "{old_var}" in $env {{',
                f'        if $env.{old_var} == "__NOT__SET__" {{',
                f'            hide-env {var}',
                '        }} else {{',
                f'            $env.{var} = $env.{old_var}',
                '        }}',
                f'        hide-env {old_var}',
                '    }',
            ])
        # Also clean up MESON_DEVENV_ACTIVE and MESON_DEVENV_BUILDDIR
        restore_vars_lines.extend([
            '    if "MESON_DEVENV_ACTIVE" in $env {',
            '        hide-env MESON_DEVENV_ACTIVE',
            '    }',
            '    if "MESON_DEVENV_BUILDDIR" in $env {',
            '        hide-env MESON_DEVENV_BUILDDIR',
            '    }',
        ])
        restore_vars = '\n'.join(restore_vars_lines)

        template_name = 'devenv.nu.template'
        replacements = {
            'restore_vars_nu': restore_vars,
            'export_vars_nu': export_vars,
            'project_name': project_name,
            'builddir': str(builddir.resolve()),
        }
    else:
        raise MesonException(f'Unsupported shell type: {shell_type}')

    # Read and process template
    template_path = Path(__file__).parent / 'scripts' / 'templates' / 'devenv' / template_name
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    script_content = template.format(**replacements)

    # Write the script
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    os.chmod(output_path, 0o644)

def generate_devenv_scripts(b: build.Build, builddir: str) -> None:
    """Generate devenv activation scripts automatically during meson setup."""
    # Only generate scripts if the project uses meson.add_devenv()
    if not b.devenv:
        return

    project_name = b.project_name
    env, varnames = get_env(b, 'devenv')
    builddir_path = Path(builddir)

    shells = [('sh', 'devenv'), ('fish', 'devenv.fish'),
              ('ps1', 'devenv.ps1'), ('nu', 'devenv.nu')]

    for shell_type, filename in shells:
        try:
            script_path = builddir_path / filename
            generate_devenv_script(shell_type, env, varnames, project_name, script_path, builddir_path)
            mlog.log(f'Generated {shell_type} devenv script:', mlog.bold(str(script_path)))
        except Exception as e:
            mlog.warning(f'Failed to generate {filename}: {e}')

def run(options: argparse.Namespace) -> int:
    privatedir = Path(options.builddir) / 'meson-private'
    buildfile = privatedir / 'build.dat'
    if not buildfile.is_file():
        raise MesonException(f'Directory {options.builddir!r} does not seem to be a Meson build directory.')
    b = build.load(options.builddir)
    workdir = options.workdir or options.builddir

    need_vsenv = T.cast('bool', b.environment.coredata.optstore.get_value_for(OptionKey('vsenv')))
    setup_vsenv(need_vsenv) # Call it before get_env to get vsenv vars as well
    dump_fmt = options.dump_format if options.dump else None
    devenv, varnames = get_env(b, dump_fmt)
    if options.dump:
        if options.devcmd:
            raise MesonException('--dump option does not allow running other command.')
        if options.dump is True:
            dump(devenv, varnames, dump_fmt)
        else:
            with open(options.dump, "w", encoding='utf-8') as output:
                dump(devenv, varnames, dump_fmt, output)
        return 0

    if b.environment.need_exe_wrapper():
        m = 'An executable wrapper could be required'
        exe_wrapper = b.environment.get_exe_wrapper()
        if exe_wrapper:
            cmd = ' '.join(exe_wrapper.get_command())
            m += f': {cmd}'
        mlog.log(m)

    install_data = minstall.load_install_data(str(privatedir / 'install.dat'))
    write_gdb_script(privatedir, install_data, workdir)

    args = options.devcmd
    if not args:
        prompt_prefix = f'[{b.project_name}]'
        shell_env = os.environ.get("SHELL")
        # Prefer $SHELL in a MSYS2 bash despite it being Windows
        if shell_env and os.path.exists(shell_env):
            args = [shell_env]
        elif is_windows():
            shell = get_windows_shell()
            if not shell:
                mlog.warning('Failed to determine Windows shell, fallback to cmd.exe')
            if shell in POWERSHELL_EXES:
                args = [shell, '-NoLogo', '-NoExit']
                prompt = f'function global:prompt {{  "{prompt_prefix} PS " + $PWD + "> "}}'
                args += ['-Command', prompt]
            else:
                args = [os.environ.get("COMSPEC", r"C:\WINDOWS\system32\cmd.exe")]
                args += ['/k', f'prompt {prompt_prefix} $P$G']
        else:
            args = [os.environ.get("SHELL", os.path.realpath("/bin/sh"))]
        if "bash" in args[0]:
            # Let the GC remove the tmp file
            tmprc = tempfile.NamedTemporaryFile(mode='w')
            tmprc.write('[ -e ~/.bashrc ] && . ~/.bashrc\n')
            if not os.environ.get("MESON_DISABLE_PS1_OVERRIDE"):
                tmprc.write(f'export PS1="{prompt_prefix} $PS1"\n')
            for f in bash_completion_files(b, install_data):
                tmprc.write(f'. "{f}"\n')
            tmprc.flush()
            args.append("--rcfile")
            args.append(tmprc.name)
    else:
        # Try to resolve executable using devenv's PATH
        abs_path = shutil.which(args[0], path=devenv.get('PATH', None))
        args[0] = abs_path or args[0]

    try:
        if is_windows():
            # execvpe doesn't return exit code on Windows
            # see https://github.com/python/cpython/issues/63323
            result = subprocess.run(args, env=devenv, cwd=workdir)
            sys.exit(result.returncode)
        else:
            os.chdir(workdir)
            os.execvpe(args[0], args, env=devenv)
    except FileNotFoundError:
        raise MesonException(f'Command not found: {args[0]}')
    except OSError as e:
        raise MesonException(f'Command `{join_args(args)}` failed to execute: {e}')
