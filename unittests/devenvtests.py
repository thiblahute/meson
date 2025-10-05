#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 The Meson development team

"""Comprehensive tests for Meson development environment sourceable scripts across different shells."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List


class DevenvShellTests(unittest.TestCase):
    """Test Meson development environment scripts for various shells."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment by building the devenv test case."""
        cls.project_root = Path(__file__).parent.parent
        cls.unit_test_dir = cls.project_root / 'test cases' / 'unit'
        cls.testdir = cls.unit_test_dir / '90 devenv'

        # Create a temporary build directory
        cls.builddir = Path(tempfile.mkdtemp(prefix='meson-devenv-test-'))

        # Setup the test project
        meson_cmd = [
            'python3',
            str(cls.project_root / 'meson.py'),
            'setup',
            str(cls.builddir),
            str(cls.testdir)
        ]
        result = subprocess.run(meson_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to setup test project:\n{result.stderr}")

        # Devenv scripts are now automatically generated during meson setup
        # Verify they exist
        for script_name in ['devenv', 'devenv.fish', 'devenv.ps1', 'devenv.nu']:
            script_path = cls.builddir / script_name
            if not script_path.exists():
                raise RuntimeError(f"Expected devenv script not found: {script_path}")

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary build directory."""
        if hasattr(cls, 'builddir') and cls.builddir.exists():
            shutil.rmtree(cls.builddir)

    def _check_shell_available(self, shell_name):
        """Check if a shell is available on the system."""
        return shutil.which(shell_name) is not None

    def _run_shell_script(self, shell, args, script_content):
        """Run a script in a shell."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(script_content)
            f.flush()
            temp_script = f.name

        try:
            result = subprocess.run(
                [shell] + args + [temp_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result
        finally:
            os.unlink(temp_script)

    def test_bash_devenv_basic(self):
        """Test bash devenv script basic functionality."""
        if not self._check_shell_available('bash'):
            self.skipTest("bash not available")

        script = f"""
source {self.builddir}/devenv
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV not set"
    exit 1
fi
if [ "$MESON_PROJECT_NAME" != "devenv" ]; then
    echo "ERROR: MESON_PROJECT_NAME not set correctly"
    exit 1
fi
if [ -z "$_OLD_MESON_PATH" ]; then
    echo "ERROR: _OLD_MESON_PATH not set"
    exit 1
fi
echo "SUCCESS"
"""
        result = self._run_shell_script('bash', [], script)
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)

    def test_fish_devenv_basic(self):
        """Test fish devenv script basic functionality."""
        if not self._check_shell_available('fish'):
            self.skipTest("fish not available")

        script = f"""
source {self.builddir}/devenv.fish
if test "$MESON_DEVENV" != "1"
    echo "ERROR: MESON_DEVENV not set"
    exit 1
end
if test "$MESON_PROJECT_NAME" != "devenv"
    echo "ERROR: MESON_PROJECT_NAME not set correctly"
    exit 1
end
if not set -q _OLD_MESON_PATH
    echo "ERROR: _OLD_MESON_PATH not set"
    exit 1
end
echo "SUCCESS"
"""
        result = self._run_shell_script('fish', [], script)
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)

    def test_bash_devenvexit(self):
        """Test bash devenvexit functionality."""
        if not self._check_shell_available('bash'):
            self.skipTest("bash not available")

        script = f"""
source {self.builddir}/devenv
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV not set after source"
    exit 1
fi
devenvexit
if [ "$MESON_DEVENV" = "1" ]; then
    echo "ERROR: MESON_DEVENV still set after devenvexit"
    exit 1
fi
if [ -n "$_OLD_MESON_PATH" ]; then
    echo "ERROR: _OLD_MESON_PATH still set after devenvexit"
    exit 1
fi
echo "SUCCESS"
"""
        result = self._run_shell_script('bash', [], script)
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)

    def test_fish_devenvexit(self):
        """Test fish devenvexit functionality."""
        if not self._check_shell_available('fish'):
            self.skipTest("fish not available")

        script = f"""
source {self.builddir}/devenv.fish
if test "$MESON_DEVENV" != "1"
    echo "ERROR: MESON_DEVENV not set after source"
    exit 1
end
devenvexit
if test "$MESON_DEVENV" = "1"
    echo "ERROR: MESON_DEVENV still set after devenvexit"
    exit 1
end
if set -q _OLD_MESON_PATH
    echo "ERROR: _OLD_MESON_PATH still set after devenvexit"
    exit 1
end
echo "SUCCESS"
"""
        result = self._run_shell_script('fish', [], script)
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)

    def test_bash_double_source(self):
        """Test that sourcing devenv twice errors out."""
        if not self._check_shell_available('bash'):
            self.skipTest("bash not available")

        script = f"""
source {self.builddir}/devenv
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV not set"
    exit 1
fi
source {self.builddir}/devenv
echo "ERROR: Second source should have failed"
exit 1
"""
        result = self._run_shell_script('bash', [], script)
        self.assertNotEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("Already in Meson devenv", result.stderr)

    def test_fish_double_source(self):
        """Test that sourcing devenv twice errors out."""
        if not self._check_shell_available('fish'):
            self.skipTest("fish not available")

        script = f"""
source {self.builddir}/devenv.fish
if test "$MESON_DEVENV" != "1"
    echo "ERROR: MESON_DEVENV not set"
    exit 1
end
source {self.builddir}/devenv.fish
echo "ERROR: Second source should have failed"
exit 1
"""
        result = self._run_shell_script('fish', [], script)
        self.assertNotEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("Already in Meson devenv", result.stderr)

    def test_bash_meson_compile_restores_env(self):
        """Test that meson compile restores environment when run from devenv."""
        if not self._check_shell_available('bash'):
            self.skipTest("bash not available")

        import sys
        python_exe = sys.executable
        meson_exe = str(self.project_root / 'meson.py')
        script = f"""
source {self.builddir}/devenv
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV not set"
    exit 1
fi
# The build includes a custom target that checks environment was restored
{python_exe} {meson_exe} compile -C {self.builddir}
if [ $? -ne 0 ]; then
    echo "ERROR: meson compile failed"
    exit 1
fi
echo "SUCCESS"
"""
        result = self._run_shell_script('bash', [], script)
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)

    def test_scripts_auto_generated_during_setup(self):
        """Test that devenv scripts are automatically generated during meson setup."""
        import tempfile
        import shutil

        # Create a new temporary build directory
        test_builddir = Path(tempfile.mkdtemp(prefix='meson-devenv-autogen-test-'))

        try:
            # Run meson setup
            meson_cmd = [
                'python3',
                str(self.project_root / 'meson.py'),
                'setup',
                str(test_builddir),
                str(self.testdir)
            ]
            result = subprocess.run(meson_cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"meson setup failed:\n{result.stderr}")

            # Verify all devenv scripts were automatically generated
            for script_name in ['devenv', 'devenv.fish', 'devenv.ps1', 'devenv.nu']:
                script_path = test_builddir / script_name
                self.assertTrue(script_path.exists(), f'{script_name} was not automatically generated during setup')

                # Verify the script contains expected content
                content = script_path.read_text(encoding='utf-8')
                self.assertIn('MESON_DEVENV', content)
                self.assertIn('devenvexit', content)

            # Verify message was printed during setup
            self.assertIn('Generated', result.stdout)

        finally:
            # Clean up
            shutil.rmtree(test_builddir, ignore_errors=True)

    def test_bash_cross_project_keeps_devenv(self):
        """Test that devenv stays active when working on a different project."""
        if not self._check_shell_available('bash'):
            self.skipTest("bash not available")

        import tempfile
        import shutil

        # Use the other_project test case
        other_project = self.testdir / 'other_project'
        other_builddir = Path(tempfile.mkdtemp(prefix='meson-other-build-'))

        try:
            # Setup the other project
            setup_cmd = ['python3', str(self.project_root / 'meson.py'), 'setup', str(other_builddir), str(other_project)]
            result = subprocess.run(setup_cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"Setup of other project failed:\n{result.stderr}")

            # Test script: source main devenv, then compile other project
            # The custom target in other_project will verify we're in the main devenv
            script = f"""
source {self.builddir}/devenv
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV not set after sourcing"
    exit 1
fi

# Compile the OTHER project - devenv should stay active (not restored)
# The build will fail if we're not in the main devenv
python3 {self.project_root / 'meson.py'} compile -C {other_builddir}
if [ $? -ne 0 ]; then
    echo "ERROR: Build failed - check that main devenv stayed active"
    exit 1
fi

# Double-check that devenv is STILL active after the build
if [ "$MESON_DEVENV" != "1" ]; then
    echo "ERROR: MESON_DEVENV was incorrectly restored for different project"
    exit 1
fi

echo "SUCCESS"
"""
            result = self._run_shell_script('bash', [], script)
            self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)

        finally:
            shutil.rmtree(other_builddir, ignore_errors=True)

    def test_fish_cross_project_keeps_devenv(self):
        """Test that devenv stays active when working on a different project (fish)."""
        if not self._check_shell_available('fish'):
            self.skipTest("fish not available")

        import tempfile
        import shutil

        # Use the other_project test case
        other_project = self.testdir / 'other_project'
        other_builddir = Path(tempfile.mkdtemp(prefix='meson-other-build-'))

        try:
            # Setup the other project
            setup_cmd = ['python3', str(self.project_root / 'meson.py'), 'setup', str(other_builddir), str(other_project)]
            result = subprocess.run(setup_cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"Setup of other project failed:\n{result.stderr}")

            # Test script: source main devenv, then compile other project
            # The custom target in other_project will verify we're in the main devenv
            script = f"""
source {self.builddir}/devenv.fish
if test "$MESON_DEVENV" != "1"
    echo "ERROR: MESON_DEVENV not set after sourcing"
    exit 1
end

# Compile the OTHER project - devenv should stay active (not restored)
# The build will fail if we're not in the main devenv
python3 {self.project_root / 'meson.py'} compile -C {other_builddir}
if test $status -ne 0
    echo "ERROR: Build failed - check that main devenv stayed active"
    exit 1
end

# Double-check that devenv is STILL active after the build
if test "$MESON_DEVENV" != "1"
    echo "ERROR: MESON_DEVENV was incorrectly restored for different project"
    exit 1
end

echo "SUCCESS"
"""
            result = self._run_shell_script('fish', [], script)
            self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)

        finally:
            shutil.rmtree(other_builddir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main()
