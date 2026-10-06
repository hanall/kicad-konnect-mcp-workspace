#!/usr/bin/env python3
"""config/meta/project/service 기능 runner의 실패 폐쇄 계약 테스트."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/mcp-service-functional.py"


def load_subject():
    spec = importlib.util.spec_from_file_location("mcp_service_functional", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"runner를 불러올 수 없습니다: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class McpServiceFunctionalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_subject()

    def inventory(self) -> dict:
        toolsets = {
            "project": [
                "create_project",
                "get_project_info",
                "open_project",
                "save_project",
                "snapshot_project",
                "rename_project",
                "open_schematic_viewer",
            ],
            "config": [
                "load_user_config",
                "save_user_config",
                "load_project_config",
                "save_project_config",
                "get_effective_config",
                "add_design_rule",
                "list_design_rules",
            ],
            "design_review": ["audit_connections"],
            "manufacturing": [
                "export_manufacturing_package",
                "validate_for_manufacturing",
                "estimate_cost",
            ],
            "integration": [
                "download_jlcpcb_database",
                "route_specctra_dsn",
                "check_freerouting",
                "search_jlcpcb_parts",
            ],
        }
        domain = [
            {"name": name, "description": "", "inputSchema": {"type": "object"}}
            for members in toolsets.values()
            for name in members
        ]
        meta = [
            {"name": name, "description": "", "inputSchema": {"type": "object"}}
            for name in self.subject.META_TOOLS
        ]
        return {"toolsets": toolsets, "tools": domain, "meta_tools": meta}

    def test_plan_covers_each_owned_domain_and_meta_tool_exactly_once(self) -> None:
        inventory = self.inventory()
        plan = self.subject.build_plan(inventory)
        expected = {
            name
            for toolset in self.subject.OWNED_TOOLSETS
            for name in inventory["toolsets"].get(toolset, [])
        } | set(self.subject.META_TOOLS)

        self.subject.validate_plan(inventory, plan)
        self.assertEqual({case["tool"] for case in plan}, expected)
        self.assertEqual(len(plan), len(expected))

    def test_plan_defers_only_explicit_gui_network_or_missing_service_cases(self) -> None:
        by_tool = {case["tool"]: case for case in self.subject.build_plan(self.inventory())}
        self.assertEqual(by_tool["open_schematic_viewer"]["planned_verdict"], "deferred_gui")
        self.assertEqual(by_tool["download_jlcpcb_database"]["planned_verdict"], "deferred_network")
        self.assertEqual(by_tool["route_specctra_dsn"]["planned_verdict"], "execute_no_egress_autoroute")
        self.assertEqual(by_tool["save_user_config"]["planned_verdict"], "execute_local")
        self.assertEqual(by_tool["estimate_cost"]["planned_verdict"], "execute_local")
        self.assertEqual(by_tool["reload_server"]["planned_verdict"], "execute_disposable_handoff")

    def test_plan_verification_fails_when_one_public_tool_is_removed(self) -> None:
        inventory = self.inventory()
        plan = self.subject.build_plan(inventory)
        with self.assertRaises(self.subject.FunctionalError):
            self.subject.validate_plan(inventory, plan[:-1])

    def test_executable_case_argument_check_fails_on_new_unplanned_required_field(self) -> None:
        inventory = self.inventory()
        estimate = next(item for item in inventory["tools"] if item["name"] == "estimate_cost")
        estimate["inputSchema"]["required"] = ["board", "new_required_field"]
        plan = self.subject.build_plan(inventory)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                key: root / key
                for key in (
                    "projects",
                    "snapshots",
                    "review_schematic",
                    "board",
                    "schematic",
                    "package",
                    "enrich",
                    "work",
                    "freerouting_jar",
                    "freerouting_dsn",
                    "freerouting_ses",
                )
            }
            with self.assertRaises(self.subject.FunctionalError):
                self.subject.validate_case_arguments(inventory, plan, paths)

    def test_manufacturing_package_requires_every_advertised_file_to_exist_and_be_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "package"
            output.mkdir()
            generated = output / "board-F_Cu.gbr"
            generated.write_text("G04 fixture*\nM02*\n", encoding="utf-8")
            response = {
                "complete": True,
                "files": [generated.name],
                "warnings": [],
            }
            passed = self.subject.evaluate_postconditions(
                "export_manufacturing_package",
                response,
                {"output_dir": str(output)},
            )
            self.assertTrue(all(item["passed"] for item in passed))

            generated.write_bytes(b"")
            failed = self.subject.evaluate_postconditions(
                "export_manufacturing_package",
                response,
                {"output_dir": str(output)},
            )
            self.assertFalse(all(item["passed"] for item in failed))

    def test_record_schema_names_identity_response_and_postconditions(self) -> None:
        record = self.subject.make_record(
            seq=1,
            lane="services",
            toolset="manufacturing",
            tool="estimate_cost",
            case_id="estimate-local-fixture",
            behavior="success",
            request={"name": "estimate_cost", "arguments": {"board": "fixture"}},
            response={"isError": False},
            body={"cost_estimate": {"total_estimate": "$2.00"}},
            elapsed_ms=3.2,
            binary_sha256="a" * 64,
            source_commit="b" * 40,
            source_worktree_sha256="c" * 64,
            fixture_before_sha256="d" * 64,
            fixture_after_sha256="d" * 64,
            postconditions=[{"name": "total", "expected": "present", "actual": "$2.00", "passed": True}],
            source_authority="saved_file",
            external_conditions=[],
            verdict="passed",
            caveats=[],
        )
        for field in self.subject.RECORD_FIELDS:
            self.assertIn(field, record)
        self.assertEqual(record["schema_version"], 1)

    def test_tool_response_parser_decodes_json_text_and_preserves_plain_text(self) -> None:
        result, body = self.subject.parse_tool_response(
            {"result": {"isError": False, "content": [{"type": "text", "text": '{"ok":true}'}]}}
        )
        self.assertFalse(result["isError"])
        self.assertEqual(body, {"ok": True})
        _, plain = self.subject.parse_tool_response(
            {"result": {"isError": False, "content": [{"type": "text", "text": "loaded"}]}}
        )
        self.assertEqual(plain, "loaded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
