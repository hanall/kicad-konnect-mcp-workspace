#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


class ProjectContractTest(unittest.TestCase):
    def test_root_verifier(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify-project.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mcp_config_uses_safe_launcher(self) -> None:
        text = (ROOT / ".mcp.json").read_text(encoding="utf-8")
        self.assertIn("scripts/run-konnect.sh", text)
        self.assertNotIn("target/release/konnect\"", text)

    def test_runtime_home_is_ignored(self) -> None:
        ignored = subprocess.run(
            ["git", "check-ignore", ".runtime-home/probe"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(ignored.returncode, 0, ignored.stdout + ignored.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
