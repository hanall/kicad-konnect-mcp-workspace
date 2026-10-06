import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent


class RuntimeHomeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        self.launcher = self.root / "scripts/run-konnect.sh"
        shutil.copy2(ROOT / "scripts/run-konnect.sh", self.launcher)
        (self.root / "upstreams.lock.json").write_text(json.dumps({"components": {"kicad": {"tag": "10.0.6"}}}))
        binary = self.root / "upstream/konnect/target/release/konnect"
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "$HOME" "$XDG_CONFIG_HOME"\n')
        binary.chmod(0o755)

    def run_launcher(self, target=None):
        env = {key: value for key, value in os.environ.items() if key != "KONNECT_RUNTIME_HOME"}
        if target is not None:
            env["KONNECT_RUNTIME_HOME"] = str(target)
        return subprocess.run([str(self.launcher)], env=env, capture_output=True, text=True)

    def test_default_home_remains_project_isolated(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], str(self.root / ".runtime-home"))

    def test_explicit_artifact_home_is_used(self):
        target = self.root / ".artifacts/test/runtime-home"
        result = self.run_launcher(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(target), str(target / ".config")])
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.root / ".runtime-home").exists())

    def test_outside_home_is_rejected_without_creation(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "must-not-create"
            result = self.run_launcher(target)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists())

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            artifact = self.root / ".artifacts"
            artifact.mkdir()
            (artifact / "escape").symlink_to(outside, target_is_directory=True)
            target = artifact / "escape/runtime-home"
            result = self.run_launcher(target)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(outside) / "runtime-home").exists())
