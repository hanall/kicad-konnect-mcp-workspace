#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile
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

    def test_github_actions_are_not_configured(self) -> None:
        workflows = ROOT / ".github/workflows"
        configured = [] if not workflows.exists() else list(workflows.glob("*.y*ml"))
        self.assertEqual(configured, [], "과금 방침상 GitHub Actions workflow를 두지 않습니다.")

    def test_runtime_paths_are_checkout_relative(self) -> None:
        config = (ROOT / "config/konnect.toml").read_text(encoding="utf-8")
        mcp = (ROOT / ".mcp.json").read_text(encoding="utf-8")
        launcher = (ROOT / "scripts/run-konnect.sh").read_text(encoding="utf-8")

        self.assertIn('project_dir = "projects"', config)
        self.assertNotIn("/home/hanol", config)
        self.assertNotIn("/home/hanol", mcp)
        self.assertIn('"command": "scripts/run-konnect.sh"', mcp)
        self.assertIn('"config/konnect.toml"', mcp)
        self.assertIn('cd "$ROOT"', launcher)

    def test_konnect_development_fork_is_declared(self) -> None:
        lock = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))
        konnect = lock["components"]["konnect"]
        self.assertEqual(konnect["origin"], "https://github.com/hanall/Konnect.git")
        self.assertEqual(konnect["upstream_origin"], "https://github.com/mixelpixx/Konnect.git")
        self.assertEqual(konnect["upstream_tag"], "v0.2.2")
        self.assertEqual(konnect["development_branch"], "hanol-dev/v0.2.2")

    def test_locked_tag_fetch_restores_a_missing_tag(self) -> None:
        script = ROOT / "scripts/fetch-locked-tag.py"
        with tempfile.TemporaryDirectory(prefix="locked-tag-test-") as temp_dir:
            temp = Path(temp_dir)
            source = temp / "source"
            remote = temp / "remote.git"
            workspace = temp / "workspace"
            component = workspace / "upstream/konnect"

            subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "config", "user.name", "Contract Test"],
                check=True,
            )
            (source / "fixture.txt").write_text("locked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "fixture.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(source), "tag", "v1.2.3"], check=True)
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD", "--tags"], check=True, capture_output=True)

            component.parent.mkdir(parents=True)
            subprocess.run(
                ["git", "clone", "--no-tags", str(remote), str(component)],
                check=True,
                capture_output=True,
            )
            lock = {
                "schema_version": 2,
                "components": {
                    "konnect": {
                        "origin": str(remote),
                        "upstream_origin": str(remote),
                        "upstream_tag": "v1.2.3",
                        "upstream_commit": commit,
                        "commit": commit,
                        "source_path": "upstream/konnect",
                    }
                },
            }
            lock_file = workspace / "upstreams.lock.json"
            lock_file.write_text(json.dumps(lock), encoding="utf-8")
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(component), "tag", "--points-at", "HEAD"],
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip(),
                "",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "konnect",
                    "--root",
                    str(workspace),
                    "--lock-file",
                    str(lock_file),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(component), "tag", "--points-at", "HEAD"],
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip(),
                "v1.2.3",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
