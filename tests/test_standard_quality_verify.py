#!/usr/bin/env python3
"""표준 회로도 품질 검증기의 공개 CLI 계약 시험."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "skills/kicad-schematic-quality/scripts"))
import package_identity


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/kicad-schematic-quality/scripts/verify_quality.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_pdf(path: Path, text: str = "PASS", *, width_pt: float = 595.2756,
             height_pt: float = 841.8898) -> None:
    """추가 라이브러리 없이 Poppler가 읽는 한 쪽 PDF를 만든다."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 18 Tf 72 {height_pt - 72:.4f} Td ({safe}) Tj ET\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width_pt:.4f} {height_pt:.4f}] "
         "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>").encode("ascii"),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend((f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\n"
                 f"startxref\n{xref}\n%%EOF\n").encode("ascii"))
    path.write_bytes(data)


class Fixture:
    def __init__(self, base: Path) -> None:
        self.root = base / "임의 프로젝트 공간"
        self.root.mkdir()
        self.data = self.root / "data files"
        self.data.mkdir()
        self.source = self.data / "source.dat"
        self.oracle = self.data / "oracle.dat"
        self.source.write_text("source-v1\n", encoding="utf-8")
        self.oracle.write_text("oracle-v1\n", encoding="utf-8")
        self.plans = self.root / "plans"
        self.plans.mkdir()
        self.common_plan = self.plans / "common.md"
        self.page_plan = self.plans / "root.md"
        self.common_plan.write_text(
            "# 공통 계획\n\n## 범위\n" + "공통 범위와 권위를 고정한다. " * 30
            + "\n\n## 도구\n도구 identity를 확인한다.\n\n## 검증\n원 증거를 보존한다.\n",
            encoding="utf-8",
        )
        self.page_plan.write_text(
            "# fixture page 계획\n\n## 범위\n" + "후보 이전 독립 계획이다. " * 30
            + "\n\n## 실선\n모든 pin을 실선으로 연결한다.\n\n## 포트\n페이지 포트는 없다.\n"
            + "\n## 반환\n반환망을 별도로 확인한다.\n\n## 검증\n원 SHA와 결과를 대조한다.\n",
            encoding="utf-8",
        )
        self.plan_index = self.root / "plan-index.json"
        dump(self.plan_index, {
            "schema_version": 1,
            "mode": "design",
            "project_stem": "fixture",
            "common_plan": "plans/common.md",
            "plans": {"fixture.kicad_sch": "plans/root.md"},
            "allowed_files": ["fixture.kicad_pro", "fixture.kicad_sch"],
            "read_only_files": [],
            "read_only_library_refs": {},
            "require_all_plans_before_write": True,
        })
        self.netlist = self.data / "net list.xml"
        self.layout = self.data / "layout.json"
        self.erc = self.data / "erc.json"
        self.pdf = self.data / "schematic.pdf"
        self.semantic = self.data / "semantic.json"
        self.registry = self.data / "registry.json"
        self.runtime = self.data / "runtime.json"
        self.counter = 0
        self._write_valid()

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def _write_valid(self) -> None:
        self.netlist.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<export><design><source>data files/source.dat</source><tool>Eeschema fixture</tool></design>
<components><comp ref="R1"><value>1k</value><libsource lib="Device" part="R"/>
<property name="Sheetfile" value="source.dat"/><sheetpath names="/"/></comp></components>
<nets><net name="/NET"><node ref="R1" pin="1" pintype="passive"/>
<node ref="R1" pin="2" pintype="passive"/></net></nets></export>
""",
            encoding="utf-8",
        )
        pin1 = {"number": "1", "x": 10.0, "y": 10.0, "unit": 1,
                "length_mm": 2.54, "orientation_degrees": 0.0, "name": "1"}
        pin2 = {"number": "2", "x": 20.0, "y": 10.0, "unit": 1,
                "length_mm": 2.54, "orientation_degrees": 180.0, "name": "2"}
        layout = {
            "schema_version": 1,
            "files": {self.rel(self.source): digest(self.source)},
            "sheets": {
                "root": {
                    "layout": {
                        "component_count": 1,
                        "components": [{"reference": "R1", "unit": 1, "lib_id": "Device:R"}],
                        "bounds_resolved": 1,
                        "bounds_unresolved": [],
                        "wire_count": 1,
                        "wires": [{"uuid": "w1", "x1": 10.0, "y1": 10.0,
                                   "x2": 20.0, "y2": 10.0}],
                        "label_count": 0,
                        "labels": [],
                    },
                    "pins": {
                        "components": [{
                            "reference": "R1", "unit_count": 1,
                            "units": [{"unit": 1, "pins": [pin1, pin2]}],
                            "pins": [pin1, pin2],
                        }]
                    },
                    "junctions": [],
                    "texts": [],
                    "orphans": {"orphan_count": 0, "orphans": []},
                    "shorts": {"short_count": 0, "shorts": []},
                }
            },
        }
        dump(self.layout, layout)
        dump(self.erc, {
            "sheets": [{"path": "/", "violations": []}],
            "included_severities": ["error", "warning", "exclusion"],
            "ignored_checks": [],
        })
        make_pdf(self.pdf)
        semantic = {
            "schema_version": 2,
            "contract_kind": "schematic-quality-semantic",
            "profile_id": "fixture",
            "semantic_sources": {self.rel(self.oracle): digest(self.oracle)},
            "components": {"R1": {"value": "1k", "footprint": "", "lib_id": "Device:R"}},
            "component_sheets": {"R1": "root"},
            "functional_units": {"R1": [1]},
            "nets": {"NET": ["R1.1", "R1.2"]},
            "pin_types": {"R1.1": "passive", "R1.2": "passive"},
            "pin_units": {"R1.1": 1, "R1.2": 1},
            "net_name_policy": {"mode": "exact_after_root_local_slash"},
            "sheet_sources": {"root": self.rel(self.source)},
            "required_source_files": [self.rel(self.source)],
            "xml_component_sheet_policy": {
                "root": {"sheetfile": "source.dat", "sheetpath_names": "/"}
            },
            "layout_component_policy": {
                "functional_inventory": "exact_by_component_sheets", "auxiliary_rules": []
            },
            "wire_coverage": {
                "groups": [{"sheet": "root", "net": "NET", "pins": ["R1.1", "R1.2"]}],
                "exceptions": [],
            },
            "ports": {"status": "checked", "items": []},
            "duplicate_pin_exceptions": [],
            "erc": {
                "sheet_paths": ["/"], "errors": 0, "warnings": 0, "exclusions": 0,
                "warning_allowlist": [], "exclusion_allowlist": [],
                "policy": {
                    "included_severities": ["error", "warning", "exclusion"],
                    "ignored_checks": [],
                },
            },
            "pdf": {
                "page_count": 1,
                "page_size_mm": [210.0, 297.0],
                "page_size_tolerance_mm": 0.3,
                "required_text": {"1": ["PASS"]},
                "text_bounds_mm": [0.0, 0.0, 210.0, 297.0],
                "missing_glyph_markers": ["�"],
            },
            "layout": {"bounds_unresolved": 0, "orphan_count": 0, "short_count": 0},
            "required_companions": {},
            "scope_limits": {"visual_review": "not_checked"},
        }
        dump(self.semantic, semantic)
        dump(self.registry, {
            "schema_version": 1,
            "trust_boundary": "시험이 사전 고정한 registry SHA",
            "profiles": {
                "fixture": {"semantic_contract": self.rel(self.semantic),
                            "sha256": digest(self.semantic)}
            },
        })
        self.refresh_runtime()

    def refresh_runtime(self, *, source_files: dict[str, str] | None = None) -> None:
        layout = json.loads(self.layout.read_text(encoding="utf-8"))
        runtime = {
            "schema_version": 2,
            "contract_kind": "schematic-quality-runtime",
            "sealed": True,
            "profile_id": "fixture",
            "candidate": {
                "inputs_sha256": {
                    "netlist": digest(self.netlist), "layout": digest(self.layout),
                    "erc": digest(self.erc), "pdf": digest(self.pdf),
                },
                "source_files": source_files if source_files is not None else layout["files"],
            },
            "companion_receipts": {},
            "producer_plan_binding": {
                "schema_version": 1,
                "plan_index": {"path": "plan-index.json", "sha256": digest(self.plan_index),
                               "size": self.plan_index.stat().st_size},
                "mode": "design",
                "project_stem": "fixture",
                "require_all_plans_before_write": True,
                "allowed_files": ["fixture.kicad_pro", "fixture.kicad_sch"],
                "read_only_files": [],
                "plans": [{"schematic": "fixture.kicad_sch", "path": "plans/root.md",
                           "sha256": digest(self.page_plan), "size": self.page_plan.stat().st_size}],
                "common_plan": {"path": "plans/common.md", "sha256": digest(self.common_plan),
                                "size": self.common_plan.stat().st_size},
            },
            "producer_package_identity": package_identity.capture(
                ROOT / "skills/kicad-schematic-quality"),
        }
        dump(self.runtime, runtime)

    def run(self, *, cwd: Path | None = None, extra: list[str] | None = None,
            absolute_inputs: bool = False,
            registry_sha256: str | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
        self.counter += 1
        report = self.root / f"reports/run {self.counter}.json"
        values = {
            "registry": self.registry,
            "contract": self.runtime,
            "netlist": self.netlist,
            "layout": self.layout,
            "erc": self.erc,
            "pdf": self.pdf,
            "report": report,
        }
        def value(path: Path) -> str:
            return str(path if absolute_inputs else path.relative_to(self.root))
        command = [
            sys.executable, str(SCRIPT),
            "--project-root", str(self.root),
            "--registry", value(self.registry),
            "--registry-sha256", registry_sha256 or digest(self.registry),
            "--contract", value(self.runtime),
            "--netlist", value(self.netlist),
            "--layout", value(self.layout),
            "--erc", value(self.erc),
            "--pdf", value(self.pdf),
            "--report", value(report),
            "--pdf-text-tool", "/usr/bin/pdftotext",
        ]
        if extra:
            command.extend(extra)
        actual_cwd = cwd or self.root
        completed = subprocess.run(command, cwd=actual_cwd, text=True, capture_output=True)
        payload = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        return completed, payload


class PublicVerifyCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="표준-품질-")
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_rejected(self, fragment: str, **kwargs) -> dict:
        completed, report = self.fixture.run(**kwargs)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report.get("status"), "FAIL", completed.stdout + completed.stderr)
        self.assertIn(fragment, "\n".join(report.get("errors", [])))
        return report

    def test_passes_from_other_cwd_with_spaces_and_reports_scope(self) -> None:
        other = Path(self.temp.name) / "전혀 다른 cwd"
        other.mkdir()
        completed, report = self.fixture.run(cwd=other)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["layout"]["wire_coverage"], "complete_exact_once")
        self.assertEqual(report["pdf"]["text_matching"], "exact_normalized_word_or_line")
        self.assertEqual(report["scope"]["visual_review"], "not_checked")
        self.assertEqual(report["scope"]["glyph_completeness"], "not_checked")
        self.assertEqual(report["scope"]["schematic_position_as_pcb_distance"],
                         "not_checked_not_equivalent")
        self.assertFalse(report["erc"]["all_erc_checks_claimed"])
        self.assertIn("not independently checked", report["erc"]["source_class"])
        self.assertIn("-bbox-layout", report["pdf_tool"]["argv"])

    def test_absolute_inputs_inside_root_are_accepted(self) -> None:
        completed, report = self.fixture.run(absolute_inputs=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "PASS")

    def test_registry_hash_and_source_staleness_are_rejected(self) -> None:
        self.fixture.source.write_text("source-v2\n", encoding="utf-8")
        self.assert_rejected("stale CAD hash")

    def test_wrong_schema_hash_and_field_type_are_rejected(self) -> None:
        with self.subTest(case="runtime-schema"):
            runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
            runtime["schema_version"] = 1
            dump(self.fixture.runtime, runtime)
            self.assert_rejected("runtime schema_version")
            self.fixture.refresh_runtime()
        with self.subTest(case="registry-hash"):
            self.assert_rejected("registry SHA256 불일치", registry_sha256="0" * 64)
        with self.subTest(case="runtime-input-hash"):
            runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
            runtime["candidate"]["inputs_sha256"]["erc"] = "0" * 64
            dump(self.fixture.runtime, runtime)
            self.assert_rejected("runtime-CLI 입력 SHA 불일치")
            self.fixture.refresh_runtime()
        with self.subTest(case="layout-field-type"):
            layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))
            layout["sheets"]["root"]["layout"]["wire_count"] = "1"
            dump(self.fixture.layout, layout)
            self.fixture.refresh_runtime()
            self.assert_rejected("count 타입/범위")

    def test_semantic_scope_cannot_expand_verifier_reserved_scope(self) -> None:
        semantic = json.loads(self.fixture.semantic.read_text(encoding="utf-8"))
        semantic["scope_limits"] = {
            "visual_review": "checked",
            "glyph_completeness": "checked",
            "all_pages_manual_review": "checked",
            "pcb_manufacturing_energization_physical_safety": "checked",
        }
        dump(self.fixture.semantic, semantic)
        registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
        registry["profiles"]["fixture"]["sha256"] = digest(self.fixture.semantic)
        dump(self.fixture.registry, registry)
        completed, report = self.fixture.run(registry_sha256=digest(self.fixture.registry))
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("예약 scope", "\n".join(report["errors"]))
        self.assertEqual(report["scope"]["visual_review"], "not_checked")
        self.assertEqual(report["scope"]["glyph_completeness"], "not_checked")
        self.assertEqual(report["scope"]["all_pages_manual_review"], "not_checked")
        self.assertEqual(report["scope"]["pcb_manufacturing_energization_physical_safety"],
                         "not_checked")

    def test_runtime_requires_exact_package_and_project_policy_plan_binding(self) -> None:
        for field in ("producer_package_identity", "producer_plan_binding"):
            with self.subTest(missing=field):
                runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
                del runtime[field]
                dump(self.fixture.runtime, runtime)
                self.assert_rejected("runtime envelope 필드")
                self.fixture.refresh_runtime()
        with self.subTest(case="package-mismatch"):
            runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
            runtime["producer_package_identity"]["sha256"] = "0" * 64
            dump(self.fixture.runtime, runtime)
            self.assert_rejected("producer package identity")
            self.fixture.refresh_runtime()
        with self.subTest(case="plan-source-drift"):
            self.fixture.page_plan.write_text(
                self.fixture.page_plan.read_text(encoding="utf-8") + "\n변경\n",
                encoding="utf-8",
            )
            self.assert_rejected("producer_plan_binding")

    def test_schema_versions_and_package_numbers_require_exact_json_integer_types(self) -> None:
        for value in (True, 1.0):
            with self.subTest(field="registry.schema_version", value=value):
                registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
                registry["schema_version"] = value
                dump(self.fixture.registry, registry)
                self.assert_rejected("registry schema_version", registry_sha256=digest(self.fixture.registry))
                self.fixture._write_valid()
        with self.subTest(field="semantic.schema_version", value=2.0):
            semantic = json.loads(self.fixture.semantic.read_text(encoding="utf-8"))
            semantic["schema_version"] = 2.0
            dump(self.fixture.semantic, semantic)
            registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
            registry["profiles"]["fixture"]["sha256"] = digest(self.fixture.semantic)
            dump(self.fixture.registry, registry)
            self.assert_rejected("semantic schema_version", registry_sha256=digest(self.fixture.registry))
            self.fixture._write_valid()
        with self.subTest(field="runtime.schema_version", value=2.0):
            runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
            runtime["schema_version"] = 2.0
            dump(self.fixture.runtime, runtime)
            self.assert_rejected("runtime schema_version")
            self.fixture._write_valid()
        for value in (True, 1.0):
            with self.subTest(field="layout.schema_version", value=value):
                layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))
                layout["schema_version"] = value
                dump(self.fixture.layout, layout)
                self.fixture.refresh_runtime()
                self.assert_rejected("layout schema_version")
                self.fixture._write_valid()
        for value in (True, 1.0):
            with self.subTest(field="producer_plan_binding.schema_version", value=value):
                runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
                runtime["producer_plan_binding"]["schema_version"] = value
                dump(self.fixture.runtime, runtime)
                self.assert_rejected("producer_plan_binding schema_version")
                self.fixture._write_valid()
        with self.subTest(field="producer_package_identity.files[0].size", value="float-equivalent"):
            runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
            runtime["producer_package_identity"]["files"][0]["size"] = float(
                runtime["producer_package_identity"]["files"][0]["size"])
            dump(self.fixture.runtime, runtime)
            self.assert_rejected("producer package identity")

    def test_companion_schema_and_original_rc_reject_bool_equivalence(self) -> None:
        for case, schema_version, rc, fragment in [
            ("schema-bool", True, 0, "companion receipt schema_version"),
            ("rc-bool", 1, False, "companion 원 rc 타입/실패"),
        ]:
            with self.subTest(case=case):
                self.fixture._write_valid()
                verifier_path = self.fixture.data / f"{case}-verifier.dat"
                log_path = self.fixture.data / f"{case}.log"
                result_path = self.fixture.data / f"{case}-result.json"
                verifier_path.write_text("verifier\n", encoding="utf-8")
                log_path.write_text("log\n", encoding="utf-8")
                result_path.write_text('{"status":"PASS"}\n', encoding="utf-8")
                spec = {
                    "argv": ["python3", verifier_path.name],
                    "verifier": {"path": self.fixture.rel(verifier_path),
                                 "sha256": digest(verifier_path)},
                    "input_paths": [self.fixture.rel(self.fixture.oracle)],
                    "log_path": self.fixture.rel(log_path),
                    "report_path": self.fixture.rel(result_path),
                }
                semantic = json.loads(self.fixture.semantic.read_text(encoding="utf-8"))
                semantic["required_companions"] = {"logic": spec}
                dump(self.fixture.semantic, semantic)
                registry = json.loads(self.fixture.registry.read_text(encoding="utf-8"))
                registry["profiles"]["fixture"]["sha256"] = digest(self.fixture.semantic)
                dump(self.fixture.registry, registry)
                receipt = {
                    "schema_version": schema_version, "name": "logic", "rc": rc,
                    "argv": spec["argv"], "verifier": spec["verifier"],
                    "inputs": {self.fixture.rel(self.fixture.oracle): digest(self.fixture.oracle)},
                    "current_cad_source_files": {
                        self.fixture.rel(self.fixture.source): digest(self.fixture.source)},
                    "log": {"path": spec["log_path"], "sha256": digest(log_path)},
                    "report": {"path": spec["report_path"], "sha256": digest(result_path)},
                }
                receipt_path = self.fixture.data / f"{case}-receipt.json"
                dump(receipt_path, receipt)
                self.fixture.refresh_runtime()
                runtime = json.loads(self.fixture.runtime.read_text(encoding="utf-8"))
                runtime["companion_receipts"] = {
                    "logic": {"path": self.fixture.rel(receipt_path),
                              "sha256": digest(receipt_path)}}
                dump(self.fixture.runtime, runtime)
                self.assert_rejected(fragment, registry_sha256=digest(self.fixture.registry))

    def test_missing_wire_with_consistent_count_is_rejected(self) -> None:
        layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))
        layout["sheets"]["root"]["layout"]["wires"] = []
        layout["sheets"]["root"]["layout"]["wire_count"] = 0
        dump(self.fixture.layout, layout)
        self.fixture.refresh_runtime()
        self.assert_rejected("실선 그룹 분리")

    def test_xml_source_and_success_with_zero_pins_are_rejected(self) -> None:
        with self.subTest(case="xml-source-missing"):
            raw = self.fixture.netlist.read_text(encoding="utf-8")
            raw = raw.replace(
                "<design><source>data files/source.dat</source><tool>Eeschema fixture</tool></design>\n",
                "",
            )
            self.fixture.netlist.write_text(raw, encoding="utf-8")
            self.fixture.refresh_runtime()
            self.assert_rejected("XML design/source 누락")
        self.fixture._write_valid()
        with self.subTest(case="mcp-pin-zero"):
            layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))
            component = layout["sheets"]["root"]["pins"]["components"][0]
            component["pins"] = []
            component["units"][0]["pins"] = []
            dump(self.fixture.layout, layout)
            self.fixture.refresh_runtime()
            self.assert_rejected("pin 0개")

    def test_layout_split_endpoint_is_rejected(self) -> None:
        layout = json.loads(self.fixture.layout.read_text(encoding="utf-8"))
        layout["sheets"]["root"]["layout"]["wires"][0]["x2"] = 19.0
        dump(self.fixture.layout, layout)
        self.fixture.refresh_runtime()
        self.assert_rejected("실선 그룹 분리")

    def test_erc_ignore_policy_cannot_be_silently_added(self) -> None:
        erc = json.loads(self.fixture.erc.read_text(encoding="utf-8"))
        erc["ignored_checks"] = [{"key": "pin_not_connected", "value": True}]
        dump(self.fixture.erc, erc)
        self.fixture.refresh_runtime()
        self.assert_rejected("ERC 비활성")

    def test_json_duplicate_nonfinite_and_null_are_rejected(self) -> None:
        cases = {
            "duplicate": '{"schema_version":2,"schema_version":2}',
            "nonfinite": '{"schema_version":NaN}',
            "null": '{"schema_version":null}',
        }
        for name, raw in cases.items():
            with self.subTest(case=name):
                self.fixture.runtime.write_text(raw, encoding="utf-8")
                report = self.assert_rejected("JSON")
                self.assertIn(name, report["errors"][0] if name != "nonfinite" else name,
                              msg=report["errors"][0])
                self.fixture.refresh_runtime()

    def test_nonfinite_layout_number_is_rejected_without_zero_synthesis(self) -> None:
        raw = self.fixture.layout.read_text(encoding="utf-8").replace('"x2": 20.0', '"x2": Infinity')
        self.fixture.layout.write_text(raw, encoding="utf-8")
        self.fixture.refresh_runtime()
        self.assert_rejected("JSON nonfinite")

    def test_registry_and_input_symlinks_are_rejected(self) -> None:
        real = self.fixture.registry.with_name("registry-real.json")
        self.fixture.registry.rename(real)
        self.fixture.registry.symlink_to(real.name)
        self.assert_rejected("symbolic link")

    def test_pdf_required_text_and_page_size_fail_closed(self) -> None:
        make_pdf(self.fixture.pdf, "MISSING", width_pt=400.0, height_pt=400.0)
        self.fixture.refresh_runtime()
        self.assert_rejected("PDF page size")

    def test_bad_pdf_tool_is_unknown_and_failure(self) -> None:
        missing = self.fixture.root / "missing-pdftotext"
        self.assert_rejected("PDF text tool", extra=["--pdf-text-tool", str(missing)])

    def test_relative_project_root_is_rejected_before_verification(self) -> None:
        report = self.fixture.root / "relative-root-report.json"
        command = [sys.executable, str(SCRIPT), "--project-root", ".", "--registry", "x",
                   "--registry-sha256", "0" * 64, "--contract", "x", "--netlist", "x",
                   "--layout", "x", "--erc", "x", "--pdf", "x", "--report", str(report)]
        completed = subprocess.run(command, cwd=self.fixture.root, text=True, capture_output=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("absolute", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
