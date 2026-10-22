"""배포 패키지 전체 bytes 결속과 실행 중 변경 거부 시험."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/kicad-schematic-quality/scripts/package_identity.py"


class PackageIdentityTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("quality_package_identity", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory(prefix="품질 패키지 identity ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "SKILL.md").write_text("원본 스킬\n")
        (self.root / "scripts").mkdir()
        (self.root / "scripts/tool.py").write_text("print(1)\n")

    def test_identity_is_relocatable_and_sorted(self):
        import shutil
        before = self.module.capture(self.root)
        second = self.root.parent / (self.root.name + "-copy")
        self.addCleanup(shutil.rmtree, second)
        shutil.copytree(self.root, second)
        self.assertEqual(before, self.module.capture(second))
        self.assertEqual([f["path"] for f in before["files"]], ["SKILL.md", "scripts/tool.py"])

    def test_change_and_new_file_are_rejected(self):
        before = self.module.capture(self.root)
        (self.root / "scripts/tool.py").write_text("print(2)\n")
        with self.assertRaisesRegex(ValueError, "변경"):
            self.module.assert_unchanged(before, self.root)
        before = self.module.capture(self.root)
        (self.root / "extra.md").write_text("새 파일\n")
        with self.assertRaisesRegex(ValueError, "변경"):
            self.module.assert_unchanged(before, self.root)

    def test_bytecode_is_not_distribution_source(self):
        before = self.module.capture(self.root)
        (self.root / "scripts/__pycache__").mkdir()
        (self.root / "scripts/__pycache__/tool.pyc").write_bytes(b"cache")
        self.assertEqual(before, self.module.capture(self.root))

    def test_symlink_file_and_directory_are_rejected(self):
        for target in ("SKILL.md", "scripts"):
            link = self.root / "unexpected-link"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.module.capture(self.root)
            link.unlink()

    def test_missing_entrypoint_is_rejected(self):
        (self.root / "SKILL.md").unlink()
        with self.assertRaisesRegex(ValueError, "SKILL.md"):
            self.module.capture(self.root)

    def test_corrupted_manifest_is_rejected(self):
        before = self.module.capture(self.root)
        before["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "변경"):
            self.module.assert_unchanged(before, self.root)

    def test_boolean_and_float_schema_cannot_alias_integer_identity(self):
        for invalid in (True, 1.0):
            with self.subTest(value=invalid):
                before = self.module.capture(self.root)
                before["schema_version"] = invalid
                with self.assertRaisesRegex(ValueError, "변경"):
                    self.module.assert_unchanged(before, self.root)

    def test_json_strict_equality_preserves_types_and_rejects_python_only_values(self):
        strict = self.module.strict_equal
        self.assertTrue(strict({"b": [1, False], "a": 0}, {"a": 0, "b": [1, False]}))
        self.assertFalse(strict({"rc": False}, {"rc": 0}))
        self.assertFalse(strict({"size": 1.0}, {"size": 1}))
        self.assertFalse(strict({"items": (1,)}, {"items": [1]}))
        self.assertFalse(strict({1: "x"}, {"1": "x"}))
        self.assertFalse(strict(float("nan"), float("nan")))


if __name__ == "__main__":
    unittest.main()
