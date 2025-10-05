project('other_project', 'c')

meson.add_devenv({'OTHER_PROJECT_VAR': 'other_value'})

# Add a custom target that verifies we're in the MAIN devenv (not this one's)
# when building from the main devenv
check_in_main_devenv = custom_target(
  'check_in_main_devenv',
  output: 'main_devenv_check.txt',
  command: [
    find_program('python3'),
    '-c',
    '''import os, sys
# When building this "other" project from within the "main" project's devenv,
# the main devenv should STAY ACTIVE (not be restored, not switched to this one's)
main_devenv_builddir = os.environ.get("MESON_DEVENV_BUILDDIR", "")
current_builddir = os.getcwd()

# Check we're NOT building in the same builddir as the active devenv
if main_devenv_builddir == "":
    print("ERROR: No MESON_DEVENV_BUILDDIR set - not in any devenv!", file=sys.stderr)
    sys.exit(1)
elif main_devenv_builddir in current_builddir or current_builddir in main_devenv_builddir:
    # We're building in the same builddir as the devenv - environment should have been restored
    print(f"ERROR: Building in same directory as devenv ({main_devenv_builddir})", file=sys.stderr)
    print(f"       Current builddir: {current_builddir}", file=sys.stderr)
    print("       Environment should have been restored!", file=sys.stderr)
    sys.exit(1)
else:
    # Different builddir - devenv should stay active
    with open(sys.argv[1], "w") as f:
        f.write(f"SUCCESS: In main devenv ({main_devenv_builddir}) while building other project ({current_builddir})\\n")
''',
    '@OUTPUT@'
  ],
  build_by_default: true
)
