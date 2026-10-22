#!/usr/bin/env python3
"""표준 증거 수집기의 공개 CLI 계약 시험."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_standard_quality_verify import Fixture, digest, dump


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/kicad-schematic-quality/scripts/collect_evidence.py"


class PublicCollectCliTests(unittest.TestCase):
    def test_help_exposes_portable_inputs(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for flag in ["--project-root", "--root-schematic", "--registry",
                     "--registry-sha256", "--profile-id", "--output-dir",
                     "--kicad-cli", "--pdf-text-tool", "--launcher", "--config",
                     "--server-cwd", "--expected-version", "--expected-commit"]:
            self.assertIn(flag, completed.stdout)


class CollectorFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="표준-수집-")
        self.base = Path(self.temp.name)
        self.fixture = Fixture(self.base)
        self.fixture.source.write_text(
            '(kicad_sch (junction (at 15 10)) '
            '(text "NOTE" (at 15 7 0) (uuid "text-1")))\n', encoding="utf-8")
        self.package_root = self.base / "portable package"
        self.package = self.package_root / "scripts"
        self.package.mkdir(parents=True)
        shutil.copy2(ROOT / "skills/kicad-schematic-quality/SKILL.md",
                     self.package_root / "SKILL.md")
        shutil.copy2(SCRIPT, self.package / "collect_evidence.py")
        shutil.copy2(ROOT / "skills/kicad-schematic-quality/scripts/verify_quality.py",
                     self.package / "verify_quality.py")
        shutil.copy2(ROOT / "skills/kicad-schematic-quality/scripts/package_identity.py",
                     self.package / "package_identity.py")
        shutil.copy2(ROOT / "skills/kicad-schematic-quality/scripts/guarded_mcp.py",
                     self.package / "guarded_policy.py")
        self.tools = self.fixture.root / "fake tools"
        self.tools.mkdir()
        shutil.copy2(self.fixture.netlist, self.tools / "template.xml")
        erc = json.loads(self.fixture.erc.read_text(encoding="utf-8"))
        erc["source"] = str(self.fixture.source)
        dump(self.fixture.erc, erc)
        shutil.copy2(self.fixture.erc, self.tools / "template-erc.json")
        shutil.copy2(self.fixture.pdf, self.tools / "template.pdf")
        source_layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))["sheets"]["root"]
        dump(self.tools / "mcp-payloads.json", {
            "get_schematic_layout": source_layout["layout"],
            "batch_get_schematic_pin_locations": source_layout["pins"],
            "find_orphan_items": source_layout["orphans"],
            "find_shorted_nets": source_layout["shorts"],
        })
        self._write_fake_kicad()
        self._write_fake_guarded()
        self.launcher = self.tools / "launcher.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.launcher.chmod(0o755)
        self.config = self.tools / "config.toml"
        self.config.write_text("[server]\n", encoding="utf-8")
        self.other_cwd = self.base / "다른 cwd"
        self.other_cwd.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fake_kicad(self) -> None:
        path = self.tools / "kicad cli"
        path.write_text(
            """#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import sys

here = Path(__file__).resolve().parent
with (here / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if (here / "fail-netlist").exists() and "netlist" in args:
    raise SystemExit(9)
output = Path(args[args.index("-o") + 1])
if "netlist" in args:
    shutil.copyfile(here / "template.xml", output)
elif "pdf" in args:
    shutil.copyfile(here / "template.pdf", output)
elif "erc" in args:
    shutil.copyfile(here / "template-erc.json", output)
else:
    raise SystemExit(8)
marker = here / "mutate-source"
if marker.exists():
    Path(marker.read_text(encoding="utf-8").strip()).write_text("changed\\n", encoding="utf-8")
for marker_name in ["mutate-plan", "mutate-package"]:
    target_marker = here / marker_name
    if target_marker.exists():
        target = Path(target_marker.read_text(encoding="utf-8").strip())
        target.write_text(target.read_text(encoding="utf-8") + "\\nchanged\\n", encoding="utf-8")
if "erc" in args and (here / "erc-five").exists():
    raise SystemExit(5)
""",
            encoding="utf-8",
        )
        path.chmod(0o755)
        self.kicad = path

    def _write_fake_guarded(self) -> None:
        path = self.package / "guarded_mcp.py"
        path.write_text(
            """#!/usr/bin/env python3
from guarded_policy import AdapterError, ProjectPolicy
if __name__ == "__main__":
    from fake_guarded_runner import main
    raise SystemExit(main())
""",
            encoding="utf-8",
        )
        path.chmod(0o755)
        runner = self.package / "fake_guarded_runner.py"
        runner.write_text(
            """import argparse
import json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    for name in ["workspace-root", "project-dir", "launcher", "config", "server-cwd",
                 "expected-version", "expected-commit", "requests", "evidence-dir"]:
        ap.add_argument("--" + name, required=True)
    args = ap.parse_args()
    project = Path(args.project_dir)
    (project / "guarded-argv.json").write_text(json.dumps(vars(args), indent=2) + "\\n")
    rows = [json.loads(line) for line in Path(args.requests).read_text().splitlines() if line]
    payloads = json.loads((project / "fake tools/mcp-payloads.json").read_text())
    evidence = Path(args.evidence_dir)
    (evidence / "responses").mkdir(parents=True)
    (evidence / "responses/response-0000.json").write_text(json.dumps({
        "event": "internal_rpc", "request": {"method": "initialize"},
        "response": {"result": {"serverInfo": {"name": "fake"}}}, "optional": None,
    }) + "\\n")
    limit = len(rows) - 1 if (project / "fake tools/missing-response").exists() else len(rows)
    for number, row in enumerate(rows[:limit], 1):
        payload = payloads[row["tool"]]
        document = {
            "event": "rpc_exchange",
            "request": {"params": {"name": row["tool"], "arguments": row["arguments"]}},
            "response": {"result": {"isError": False,
                                  "content": [{"type": "text", "text": json.dumps(payload)}]}},
            "logical_rc": (False if (project / "fake tools/logical-rc-false").exists() else 0),
        }
        (evidence / "responses" / f"response-{number:04d}.json").write_text(
            json.dumps(document) + "\\n")
    (evidence / "session-summary.json").write_text(json.dumps({"session_rc": 0}) + "\\n")
    return 0
""",
            encoding="utf-8",
        )

    def command(self, *, output: str = "evidence/final run",
                companion: str | None = None) -> list[str]:
        command = [
            sys.executable, str(self.package / "collect_evidence.py"),
            "--project-root", str(self.fixture.root),
            "--root-schematic", self.fixture.rel(self.fixture.source),
            "--registry", self.fixture.rel(self.fixture.registry),
            "--registry-sha256", digest(self.fixture.registry),
            "--profile-id", "fixture",
            "--output-dir", output,
            "--kicad-cli", str(self.kicad),
            "--pdf-text-tool", "/usr/bin/pdftotext",
            "--launcher", str(self.launcher),
            "--config", str(self.config),
            "--server-cwd", str(self.tools),
            "--expected-version", "fixture-version",
            "--expected-commit", "1" * 40,
        ]
        if companion is not None:
            command.extend(["--companion-receipts", companion])
        return command

    def run_cli(self, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.command(**kwargs), cwd=self.other_cwd,
                              text=True, capture_output=True)

    @property
    def output(self) -> Path:
        return self.fixture.root / "evidence/final run"

    def test_collects_native_and_four_mcp_queries_then_verifies(self) -> None:
        before = digest(self.fixture.source)
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(digest(self.fixture.source), before)
        report = json.loads((self.output / "static-report.json").read_text())
        self.assertEqual(report["status"], "PASS")
        runtime = json.loads((self.output / "runtime.json").read_text())
        self.assertEqual(runtime["companion_receipts"], {})
        self.assertEqual(runtime["producer_package_identity"]["sha256"],
                         report["package_identity"]["start"]["sha256"])
        self.assertEqual(runtime["producer_plan_binding"]["plan_index"]["path"],
                         "plan-index.json")
        requests = [json.loads(line) for line in
                    (self.output / "mcp-requests.jsonl").read_text().splitlines()]
        self.assertEqual(len(requests), 4)
        self.assertEqual({row["tool"] for row in requests}, {
            "get_schematic_layout", "batch_get_schematic_pin_locations",
            "find_orphan_items", "find_shorted_nets",
        })
        guarded = json.loads((self.fixture.root / "guarded-argv.json").read_text())
        self.assertEqual(guarded["workspace_root"], str(self.fixture.root))
        self.assertEqual(guarded["project_dir"], str(self.fixture.root))
        commands = json.loads((self.output / "commands.json").read_text())
        self.assertTrue(commands["source_files_before_after_equal"])
        self.assertTrue(commands["package_identity"]["unchanged"])
        self.assertEqual(commands["plan_binding"], runtime["producer_plan_binding"])
        self.assertEqual(commands["scope"]["gui_roundtrip_receipt"],
                         "not_checked_not_synthesized")
        self.assertIn("pdftoppm", commands["scope"]["pdf_page_png"])

    def test_erc_rc_five_is_preserved_and_content_verifier_decides(self) -> None:
        (self.tools / "erc-five").write_text("1\n")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        commands = json.loads((self.output / "commands.json").read_text())["commands"]
        erc = next(row for row in commands if row["phase"] == "native-erc")
        self.assertEqual(erc["rc"], 5)
        self.assertEqual(json.loads((self.output / "static-report.json").read_text())["status"],
                         "PASS")

    def test_output_collision_refuses_before_native_command(self) -> None:
        self.output.mkdir(parents=True)
        sentinel = self.output / "sentinel"
        sentinel.write_text("keep\n")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("새 경로", completed.stdout)
        self.assertFalse((self.tools / "calls.jsonl").exists())
        self.assertEqual(sentinel.read_text(), "keep\n")

    def test_invalid_plan_index_is_rejected_before_output_and_native_command(self) -> None:
        output = "evidence/invalid plan"
        (self.fixture.root / "plan-index.json").write_text("{}\n", encoding="utf-8")
        completed = self.run_cli(output=output)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn("plan-index", completed.stdout + completed.stderr)
        self.assertFalse((self.fixture.root / output).exists())
        self.assertFalse((self.tools / "calls.jsonl").exists())

    def test_active_editor_lock_refuses_before_output_and_commands(self) -> None:
        lock = self.fixture.root / "~case.kicad_sch.lck"
        lock.write_text("lock\n")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("active editor lock", completed.stdout)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.tools / "calls.jsonl").exists())

    def test_source_change_during_native_collection_is_failed_not_synthesized(self) -> None:
        (self.tools / "mutate-source").write_text(str(self.fixture.source), encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertEqual(failure["phase"], "native-netlist")
        self.assertIn("required_source_files 변경", failure["error"])
        self.assertNotEqual(json.loads(self.fixture.layout.read_text())["files"][self.fixture.rel(
            self.fixture.source)], digest(self.fixture.source))

    def test_plan_source_change_during_collection_is_rejected(self) -> None:
        (self.tools / "mutate-plan").write_text(str(self.fixture.page_plan), encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertEqual(failure["phase"], "native-netlist")
        self.assertIn("plan", failure["error"])

    def test_package_change_during_collection_is_rejected(self) -> None:
        target = self.package_root / "SKILL.md"
        (self.tools / "mutate-package").write_text(str(target), encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertIn("패키지", failure["error"])

    def test_native_failure_preserves_original_rc(self) -> None:
        (self.tools / "fail-netlist").write_text("1\n")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertEqual(failure["commands"][0]["rc"], 9)
        self.assertIn("원 rc 실패", failure["error"])

    def test_native_artifact_missing_owning_source_is_rejected(self) -> None:
        template = self.tools / "template.xml"
        raw = template.read_text(encoding="utf-8").replace(
            "<design><source>data files/source.dat</source><tool>Eeschema fixture</tool></design>\n",
            "",
        )
        template.write_text(raw, encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertEqual(failure["phase"], "native-netlist")
        self.assertIn("source identity 누락", failure["error"])

    def test_missing_mcp_response_is_unknown_failure(self) -> None:
        (self.tools / "missing-response").write_text("1\n")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertIn("response 개수 불일치", failure["error"])
        self.assertFalse((self.output / "runtime.json").exists())

    def test_mcp_logical_rc_false_is_not_integer_zero(self) -> None:
        (self.tools / "logical-rc-false").write_text("1\n", encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        failure = json.loads((self.output / "collection-failure.json").read_text())
        self.assertIn("logical rc 타입/실패", failure["error"])

    def test_registry_schema_bool_is_rejected_before_native_collection(self) -> None:
        registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
        registry["schema_version"] = True
        dump(self.fixture.registry, registry)
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn("registry schema_version", completed.stdout + completed.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.tools / "calls.jsonl").exists())

    def test_companion_receipts_must_be_mapping_before_collection(self) -> None:
        completed = self.run_cli(companion="[]")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("JSON mapping", completed.stdout)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.tools / "calls.jsonl").exists())

    def test_generic_companion_receipt_mapping_is_bound_by_verifier(self) -> None:
        companion_verifier = self.fixture.data / "companion-verifier.dat"
        companion_log = self.fixture.data / "companion.log"
        companion_report = self.fixture.data / "companion-report.json"
        companion_verifier.write_text("verifier-v1\n", encoding="utf-8")
        companion_log.write_text("PASS\n", encoding="utf-8")
        companion_report.write_text('{"status":"PASS"}\n', encoding="utf-8")
        semantic = json.loads(self.fixture.semantic.read_text(encoding="utf-8"))
        spec = {
            "argv": ["python3", "companion-verifier.dat"],
            "verifier": {"path": self.fixture.rel(companion_verifier),
                         "sha256": digest(companion_verifier)},
            "input_paths": [self.fixture.rel(self.fixture.oracle)],
            "log_path": self.fixture.rel(companion_log),
            "report_path": self.fixture.rel(companion_report),
        }
        semantic["required_companions"] = {"logic": spec}
        dump(self.fixture.semantic, semantic)
        registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
        registry["profiles"]["fixture"]["sha256"] = digest(self.fixture.semantic)
        dump(self.fixture.registry, registry)
        receipt = {
            "schema_version": 1,
            "name": "logic",
            "rc": 0,
            "argv": spec["argv"],
            "verifier": spec["verifier"],
            "inputs": {self.fixture.rel(self.fixture.oracle): digest(self.fixture.oracle)},
            "current_cad_source_files": {
                self.fixture.rel(self.fixture.source): digest(self.fixture.source)
            },
            "log": {"path": spec["log_path"], "sha256": digest(companion_log)},
            "report": {"path": spec["report_path"], "sha256": digest(companion_report)},
        }
        receipt_path = self.fixture.data / "logic-receipt.json"
        dump(receipt_path, receipt)
        mapping = json.dumps({
            "logic": {"path": self.fixture.rel(receipt_path), "sha256": digest(receipt_path)}
        })
        completed = self.run_cli(companion=mapping)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads((self.output / "static-report.json").read_text())
        self.assertEqual(report["companions"], {"status": "checked", "checked": ["logic"]})

    def test_registry_symlink_is_rejected_before_collection(self) -> None:
        real = self.fixture.registry.with_name("registry-real.json")
        self.fixture.registry.rename(real)
        self.fixture.registry.symlink_to(real.name)
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("symbolic link", completed.stdout)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
