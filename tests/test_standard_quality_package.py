"""표준 스킬의 단일 정본·이식성 공개 경계 회귀시험."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "skills/kicad-schematic-quality"


class StandardPackageTests(unittest.TestCase):
    def test_two_host_aliases_resolve_to_single_canonical_package(self):
        for host in (".claude", ".agents"):
            alias = ROOT / host / "skills/kicad-schematic-quality"
            self.assertTrue(alias.is_symlink(), str(alias))
            self.assertEqual(alias.resolve(strict=True), PACKAGE)
            self.assertFalse(Path(alias.readlink()).is_absolute())

    def test_markdown_links_stay_inside_portable_package(self):
        count = 0
        for path in PACKAGE.rglob("*.md"):
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
                if "://" in link or link.startswith("#"):
                    continue
                destination = (path.parent / link.split("#", 1)[0]).resolve()
                self.assertTrue(destination.is_relative_to(PACKAGE), f"{path}: {link}")
                self.assertTrue(destination.exists(), f"{path}: {link}")
                count += 1
        self.assertGreaterEqual(count, 14)

    def test_no_product_checkout_or_lab_path_in_portable_text(self):
        for path in PACKAGE.rglob("*"):
            if path.suffix not in (".md", ".py", ".json"):
                continue
            body = path.read_text()
            for forbidden in ("/home/hanol", "battery-module-cycler", "schematic_quality_lab", "LAB_ROOT"):
                self.assertNotIn(forbidden, body, str(path))

    def test_plan_example_json_is_parseable(self):
        data = json.loads((PACKAGE / "assets/plan-index.example.json").read_text())
        self.assertEqual(data["schema_version"], 1)
        self.assertIn(data["mode"], ("design", "rewrite", "change", "review"))
        self.assertIs(data["require_all_plans_before_write"], True)

    def test_all_clis_load_from_relocated_package_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="표준 패키지 ") as tmp:
            moved = Path(tmp) / "독립 root" / PACKAGE.name
            shutil.copytree(PACKAGE, moved, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for script in ("guarded_mcp.py", "verify_quality.py", "collect_evidence.py"):
                result = subprocess.run([sys.executable, "-B", str(moved / "scripts" / script), "--help"],
                                        cwd=tmp, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--", result.stdout)


if __name__ == "__main__":
    unittest.main()
