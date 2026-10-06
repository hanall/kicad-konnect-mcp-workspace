#!/usr/bin/env python3
"""MCP 공개 도구 카탈로그 검증기의 실패 폐쇄 계약 테스트."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/mcp-catalogue-coverage.py"


def load_subject():
    spec = importlib.util.spec_from_file_location("mcp_catalogue_coverage", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"검증기를 불러올 수 없습니다: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class McpCatalogueCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_subject()

    def inventory(self) -> dict:
        return {
            "schema_version": 1,
            "source": {"commit": "abc123", "binary_sha256": "f" * 64},
            "toolsets": {
                "project": ["read_item"],
                "pcb_board": ["write_item"],
            },
            "tools": [
                {
                    "name": "read_item",
                    "description": "Read a saved item.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "write_item",
                    "description": "Write an item to the live board via IPC.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            ],
            "meta_tools": [],
        }

    def test_inventory_rejects_duplicate_or_unowned_domain_tools(self) -> None:
        inventory = self.inventory()
        inventory["tools"].append(dict(inventory["tools"][0]))
        with self.assertRaises(self.subject.CoverageError):
            self.subject.validate_inventory(inventory)

        inventory = self.inventory()
        inventory["toolsets"]["project"] = []
        with self.assertRaises(self.subject.CoverageError):
            self.subject.validate_inventory(inventory)

    def test_refusal_plan_omits_each_required_field_without_reaching_handler(self) -> None:
        tool = self.inventory()["tools"][0]
        tool["inputSchema"]["properties"]["name"] = {"type": "string"}
        tool["inputSchema"]["required"] = ["path", "name"]

        probes = self.subject.plan_refusal_probes(tool)

        self.assertEqual([probe["field"] for probe in probes], ["path", "name"])
        self.assertNotIn("path", probes[0]["arguments"])
        self.assertIn("name", probes[0]["arguments"])
        self.assertNotIn("name", probes[1]["arguments"])
        self.assertIn("path", probes[1]["arguments"])
        self.assertTrue(all(probe["expected_kind"] == "invalid_argument" for probe in probes))

    def test_no_required_probe_requires_a_closed_top_level_record(self) -> None:
        tool = self.inventory()["tools"][1]
        probes = self.subject.plan_refusal_probes(tool)
        self.assertEqual(probes[0]["probe_kind"], "unknown_property")
        self.assertIn("__konnect_catalogue_probe__", probes[0]["arguments"])

        tool["inputSchema"]["additionalProperties"] = True
        with self.assertRaises(self.subject.CoverageError):
            self.subject.plan_refusal_probes(tool)

    def test_wrong_type_planner_handles_anyof_and_exposes_untyped_required_gap(self) -> None:
        tool = self.inventory()["tools"][0]
        tool["inputSchema"]["properties"]["path"] = {
            "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
        }
        probe = self.subject.plan_wrong_type_probes(tool)[0]
        self.assertNotEqual(probe.get("status"), "not_plannable")
        self.assertIsInstance(probe["arguments"]["path"], dict)

        tool["inputSchema"]["properties"]["path"] = {"description": "arbitrary value"}
        probe = self.subject.plan_wrong_type_probes(tool)[0]
        self.assertEqual(probe["status"], "not_applicable")
        self.assertIn("모든 non-null JSON", probe["reason"])

    def test_matrix_has_one_row_per_domain_tool_and_names_evidence_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            (source_root / "tools").mkdir()
            (source_root / "tools/read.rs").write_text(
                """
                pub fn tools() { tool!(\"read_item\", \"read\", json!({}), handle_read_item); }
                #[test]
                fn read_item_returns_saved_value() { let _ = handle_read_item; }
                """,
                encoding="utf-8",
            )
            rows = self.subject.build_matrix(self.inventory(), source_root)

        self.assertEqual({row["tool"] for row in rows}, {"read_item", "write_item"})
        read = next(row for row in rows if row["tool"] == "read_item")
        write = next(row for row in rows if row["tool"] == "write_item")
        self.assertEqual(read["normal_behavior"]["status"], "static_candidate_only")
        self.assertEqual(write["normal_behavior"]["status"], "missing")
        self.assertIn("ipc", write["external_requirements"])
        self.assertEqual(write["write_readback"]["status"], "missing")

        inventory = self.inventory()
        inventory["tools"][0]["inputSchema"]["properties"]["path"] = {
            "description": "임의 JSON"
        }
        row = next(
            row
            for row in self.subject.build_matrix(inventory, Path("/does/not/exist"))
            if row["tool"] == "read_item"
        )
        self.assertEqual(row["any_value_contract"]["status"], "intentional_any_non_null_json")

    def test_matrix_verification_fails_closed_on_removed_tool_or_unpassed_probe(self) -> None:
        inventory = self.inventory()
        rows = self.subject.build_matrix(inventory, Path("/does/not/exist"))
        for row in rows:
            row["refusal_validation"] = {"status": "passed", "probes": 1}

        self.subject.verify_matrix(inventory, rows, require_refusal_pass=True)

        with self.assertRaises(self.subject.CoverageError):
            self.subject.verify_matrix(inventory, rows[:-1], require_refusal_pass=True)

        rows[0]["refusal_validation"] = {"status": "not_run", "probes": 0}
        with self.assertRaises(self.subject.CoverageError):
            self.subject.verify_matrix(inventory, rows, require_refusal_pass=True)

    def test_report_marks_catalogue_incomplete_when_behavior_evidence_is_missing(self) -> None:
        rows = self.subject.build_matrix(self.inventory(), Path("/does/not/exist"))
        report = self.subject.summarize(rows)
        self.assertFalse(report["all_features_integrity_claim_supported"])
        self.assertEqual(report["gaps"]["normal_behavior"], len(rows))
        self.assertGreater(report["gaps"]["write_readback"], 0)

    def test_functional_evidence_only_promotes_passed_postconditioned_cases(self) -> None:
        rows = self.subject.build_matrix(self.inventory(), Path("/does/not/exist"))
        evidence = [
            {
                "tool": "read_item",
                "case_id": "read-ok",
                "verdict": "passed",
                "source_authority": "saved_file",
                "postconditions": [
                    {"name": "independent_readback", "passed": True}
                ],
                "binary_sha256": "f" * 64,
            },
            {
                "tool": "write_item",
                "case_id": "write-refused",
                "verdict": "environment_refusal_observed",
                "source_authority": "dummy_ipc",
                "postconditions": [],
                "binary_sha256": "f" * 64,
            },
        ]
        self.subject.merge_functional_evidence(
            rows,
            evidence,
            "evidence.jsonl",
            expected_binary_sha256="f" * 64,
        )
        read = next(row for row in rows if row["tool"] == "read_item")
        write = next(row for row in rows if row["tool"] == "write_item")
        self.assertEqual(read["normal_behavior"]["status"], "passed")
        self.assertNotEqual(write["normal_behavior"]["status"], "passed")

    def test_functional_evidence_rejects_missing_or_stale_success_binary(self) -> None:
        for binary_sha256 in (None, "a" * 64):
            with self.subTest(binary_sha256=binary_sha256):
                rows = self.subject.build_matrix(
                    self.inventory(), Path("/does/not/exist")
                )
                record = {
                    "tool": "read_item",
                    "case_id": "read-ok",
                    "verdict": "passed",
                    "source_authority": "saved_file",
                    "postconditions": [
                        {"name": "independent_readback", "passed": True}
                    ],
                }
                if binary_sha256 is not None:
                    record["binary_sha256"] = binary_sha256

                with self.assertRaises(self.subject.CoverageError):
                    self.subject.merge_functional_evidence(
                        rows,
                        [record],
                        "evidence.jsonl",
                        expected_binary_sha256="f" * 64,
                    )

    def test_changed_fixture_without_readback_does_not_prove_write_readback(self) -> None:
        rows = self.subject.build_matrix(self.inventory(), Path("/does/not/exist"))
        evidence = [
            {
                "tool": "write_item",
                "case_id": "write-without-readback",
                "verdict": "passed",
                "source_authority": "live_ipc",
                "postconditions": [{"name": "write_completed", "passed": True}],
                "binary_sha256": "f" * 64,
                "fixture_before_sha256": "a" * 64,
                "fixture_after_sha256": "b" * 64,
            }
        ]

        self.subject.merge_functional_evidence(
            rows,
            evidence,
            "evidence.jsonl",
            expected_binary_sha256="f" * 64,
        )

        write = next(row for row in rows if row["tool"] == "write_item")
        self.assertEqual(write["normal_behavior"]["status"], "passed")
        self.assertEqual(write["write_readback"]["status"], "missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
