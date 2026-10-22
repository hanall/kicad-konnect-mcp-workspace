from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = REPO / "skills" / "kicad-schematic-quality"
DEFAULT_MD = REPO / "docs" / "agents" / "20261012-040121_standard-quality-user-guide.md"
DEFAULT_HTML = REPO / "docs" / "보고서" / "20261012-040121_standard-quality.html"
MARKERS = {
    "install": "# standard-quality-safe-install",
    "alias": "# standard-quality-safe-alias-rollback",
    "package": "# standard-quality-safe-package-rollback",
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def package_identity(package: Path) -> dict:
    completed = subprocess.run(
        ["python3", "-B", str(package / "scripts" / "package_identity.py")],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    return json.loads(completed.stdout)


def markdown_blocks(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    chunks = text.split("```bash\n")[1:]
    blocks = [item.split("\n```", 1)[0] for item in chunks]
    return {
        name: next(item for item in blocks if marker in item)
        for name, marker in MARKERS.items()
    }


class _CodeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_code = False
        self.current: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "code":
            self.in_code = True
            self.current = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self.in_code:
            self.blocks.append("".join(self.current))
            self.in_code = False

    def handle_data(self, data: str) -> None:
        if self.in_code:
            self.current.append(data)


def html_blocks(path: Path) -> dict[str, str]:
    parser = _CodeParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return {
        name: next(item for item in parser.blocks if marker in item)
        for name, marker in MARKERS.items()
    }


class _DocsSafetyMixin:
    doc_kind: str

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standard-quality-docs-safety-")
        self.base = Path(self.temp.name)
        self.source_copy = self.base / "source-package"
        shutil.copytree(
            SOURCE_PACKAGE,
            self.source_copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        source_identity = package_identity(SOURCE_PACKAGE)
        copied_identity = package_identity(self.source_copy)
        self.assertEqual(canonical_json(source_identity), canonical_json(copied_identity))
        self.expected_sha = source_identity["sha256"]

        if self.doc_kind == "markdown":
            doc = Path(os.environ.get("STANDARD_QUALITY_MD_DOC", str(DEFAULT_MD)))
            self.blocks = markdown_blocks(doc)
        else:
            doc = Path(os.environ.get("STANDARD_QUALITY_HTML_DOC", str(DEFAULT_HTML)))
            self.blocks = html_blocks(doc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def new_case(self, name: str):
        case = self.base / name
        target = case / "target"
        receipt = case / "receipts" / "install.json"
        backup = case / "backups" / "kicad-schematic-quality"
        target.mkdir(parents=True)
        receipt.parent.mkdir()
        backup.parent.mkdir()
        return target, receipt, backup

    def environment(self, target: Path, receipt: Path, backup: Path) -> dict[str, str]:
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_PACKAGE": str(self.source_copy),
            "TARGET_ROOT": str(target),
            "EXPECTED_PACKAGE_SHA256": self.expected_sha,
            "INSTALL_RECEIPT": str(receipt),
            "ROLLBACK_BACKUP": str(backup),
        }

    def run_block(
        self, block: str, target: Path, receipt: Path, backup: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash"],
            input=block,
            text=True,
            capture_output=True,
            env=self.environment(target, receipt, backup),
        )

    def install(self, target: Path, receipt: Path, backup: Path) -> None:
        completed = self.run_block(self.blocks["install"], target, receipt, backup)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_normal_install_and_safe_rollback(self) -> None:
        target, receipt, backup = self.new_case("normal")
        self.install(target, receipt, backup)
        package = target / "skills" / "kicad-schematic-quality"
        self.assertTrue((package / "SKILL.md").is_file())
        self.assertEqual(
            os.readlink(target / ".claude/skills/kicad-schematic-quality"),
            "../../skills/kicad-schematic-quality",
        )
        self.assertEqual(
            os.readlink(target / ".agents/skills/kicad-schematic-quality"),
            "../../skills/kicad-schematic-quality",
        )
        expected = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(canonical_json(expected), canonical_json(package_identity(package)))

        alias = self.run_block(self.blocks["alias"], target, receipt, backup)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertFalse(os.path.lexists(target / ".claude/skills/kicad-schematic-quality"))
        self.assertFalse(os.path.lexists(target / ".agents/skills/kicad-schematic-quality"))

        moved = self.run_block(self.blocks["package"], target, receipt, backup)
        self.assertEqual(moved.returncode, 0, moved.stderr)
        self.assertFalse(os.path.lexists(package))
        self.assertTrue((backup / "SKILL.md").is_file())

    def test_existing_target_is_rejected_without_copy(self) -> None:
        target, receipt, backup = self.new_case("existing-target")
        existing = target / "skills" / "kicad-schematic-quality"
        existing.mkdir(parents=True)
        sentinel = existing / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        completed = self.run_block(self.blocks["install"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(
            {item.name for item in existing.iterdir()},
            {"sentinel"},
            "기존 target 검사 실패 뒤에는 어떤 source basename으로도 copy가 계속되면 안 됩니다",
        )
        self.assertFalse(receipt.exists())

    def test_dangling_alias_is_rejected(self) -> None:
        target, receipt, backup = self.new_case("dangling-link")
        link = target / ".claude" / "skills" / "kicad-schematic-quality"
        link.parent.mkdir(parents=True)
        link.symlink_to("../../skills/missing")
        completed = self.run_block(self.blocks["install"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(link.is_symlink())
        self.assertFalse(os.path.lexists(target / "skills/kicad-schematic-quality"))

    def test_different_alias_is_rejected_before_any_unlink(self) -> None:
        target, receipt, backup = self.new_case("different-alias")
        self.install(target, receipt, backup)
        good = target / ".claude" / "skills" / "kicad-schematic-quality"
        bad = target / ".agents" / "skills" / "kicad-schematic-quality"
        bad.unlink()
        bad.symlink_to("../../skills/other")
        completed = self.run_block(self.blocks["alias"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(good.is_symlink())
        self.assertEqual(os.readlink(good), "../../skills/kicad-schematic-quality")
        self.assertTrue(bad.is_symlink())
        self.assertEqual(os.readlink(bad), "../../skills/other")

    def test_missing_receipt_preserves_package(self) -> None:
        target, receipt, backup = self.new_case("missing-receipt")
        self.install(target, receipt, backup)
        package = target / "skills" / "kicad-schematic-quality"
        receipt.unlink()
        completed = self.run_block(self.blocks["package"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue((package / "SKILL.md").is_file())
        self.assertFalse(os.path.lexists(backup))

    def test_modified_package_preserves_original_location(self) -> None:
        target, receipt, backup = self.new_case("modified-package")
        self.install(target, receipt, backup)
        skill = target / "skills" / "kicad-schematic-quality" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\n수정 fixture\n", encoding="utf-8")
        completed = self.run_block(self.blocks["package"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(skill.is_file())
        self.assertFalse(os.path.lexists(backup))

    def test_existing_backup_is_not_overwritten(self) -> None:
        target, receipt, backup = self.new_case("existing-backup")
        self.install(target, receipt, backup)
        package = target / "skills" / "kicad-schematic-quality"
        backup.mkdir()
        sentinel = backup / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        completed = self.run_block(self.blocks["package"], target, receipt, backup)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue((package / "SKILL.md").is_file())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


class MarkdownDocsSafetyTests(_DocsSafetyMixin, unittest.TestCase):
    doc_kind = "markdown"


class HtmlDocsSafetyTests(_DocsSafetyMixin, unittest.TestCase):
    doc_kind = "html"


class DocsSafetyMutationTests(unittest.TestCase):
    def test_failure_without_errexit_would_continue_copy_and_current_block_refuses(self) -> None:
        original = markdown_blocks(DEFAULT_MD)["install"]
        mutated = original.replace("  set -eu", "  set +e", 1)
        mutated = mutated.replace(
            '  absent "$DEST" || fail \'canonical destination이 이미 있거나 dangling symlink입니다\'',
            '  test ! -e "$DEST"',
            1,
        )
        self.assertNotEqual(mutated, original)

        with tempfile.TemporaryDirectory(prefix="standard-quality-docs-mutation-") as raw:
            base = Path(raw)
            source = base / "source-package"
            shutil.copytree(
                SOURCE_PACKAGE,
                source,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            expected_sha = package_identity(source)["sha256"]

            def prepare(name: str):
                target = base / name / "target"
                receipt = base / name / "receipts/install.json"
                backup = base / name / "backups/kicad-schematic-quality"
                target.mkdir(parents=True)
                receipt.parent.mkdir()
                backup.parent.mkdir()
                existing = target / "skills/kicad-schematic-quality"
                existing.mkdir(parents=True)
                (existing / "sentinel").write_text("keep", encoding="utf-8")
                env = {
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "SOURCE_PACKAGE": str(source),
                    "TARGET_ROOT": str(target),
                    "EXPECTED_PACKAGE_SHA256": expected_sha,
                    "INSTALL_RECEIPT": str(receipt),
                    "ROLLBACK_BACKUP": str(backup),
                }
                return target, env

            red_target, red_env = prepare("red")
            red = subprocess.run(
                ["/bin/bash"], input=mutated, text=True, capture_output=True, env=red_env
            )
            self.assertNotEqual(red.returncode, 0)
            self.assertTrue(
                (red_target / "skills/kicad-schematic-quality/source-package/SKILL.md").is_file(),
                "errexit·즉시 fail을 제거한 변이는 실패 뒤에도 copy를 계속해야 RED가 재현됩니다",
            )

            green_target, green_env = prepare("green2")
            green = subprocess.run(
                ["/bin/bash"], input=original, text=True, capture_output=True, env=green_env
            )
            self.assertNotEqual(green.returncode, 0)
            self.assertFalse(
                (green_target / "skills/kicad-schematic-quality/kicad-schematic-quality").exists()
            )
            self.assertEqual(
                (green_target / "skills/kicad-schematic-quality/sentinel").read_text(encoding="utf-8"),
                "keep",
            )


if __name__ == "__main__":
    unittest.main()
