import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent


class UpgradeGitlinkTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("verifier", ROOT / "scripts/verify-project.py")
        self.verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verifier)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "component"
        self.repo.mkdir()
        for path in (self.root, self.repo):
            self.git(path, "init", "-b", "main")
            self.git(path, "config", "user.email", "test@example.invalid")
            self.git(path, "config", "user.name", "회귀검증")
        self.old = self.commit_component("old")
        self.git(self.root, "add", "--", "component")
        self.git(self.root, "commit", "-m", "초기 고정")
        self.new = self.commit_component("new")

    def git(self, cwd, *args):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()

    def commit_component(self, content):
        (self.repo / "fixture").write_text(content)
        self.git(self.repo, "add", "--", "fixture")
        self.git(self.repo, "commit", "-m", "검증 fixture")
        return self.git(self.repo, "rev-parse", "HEAD")

    def verify(self, commit=None):
        self.verifier.verify_gitlink(self.root, "component", commit or self.new, initialized=True)

    def test_unstaged_upgrade_preserves_index(self):
        before = self.git(self.root, "ls-files", "--stage", "--", "component")
        self.verify()
        self.assertEqual(self.git(self.root, "ls-files", "--stage", "--", "component"), before)

    def test_staged_upgrade(self):
        self.git(self.root, "add", "--", "component")
        self.verify()

    def test_wrong_checkout_rejected(self):
        with self.assertRaises(AssertionError):
            self.verify(self.old)

    def test_unrelated_staged_commit_rejected(self):
        third = self.commit_component("third")
        self.git(self.root, "add", "--", "component")
        self.git(self.repo, "switch", "--detach", self.new)
        self.assertNotEqual(third, self.new)
        with self.assertRaises(AssertionError):
            self.verify()

    def test_dirty_checkout_rejected(self):
        (self.repo / "fixture").write_text("오염")
        with self.assertRaises(AssertionError):
            self.verify()

    def test_uninitialized_index_must_match_lock(self):
        with self.assertRaises(AssertionError):
            self.verifier.verify_gitlink(self.root, "component", self.new, initialized=False)
