#!/usr/bin/env python3
"""실제 PCB 기능 검증 하네스의 실패 폐쇄 보조 계약."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/mcp-pcb-functional.py"


def load_subject():
    spec = importlib.util.spec_from_file_location("mcp_pcb_functional", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"검증기를 불러올 수 없습니다: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class McpPcbFunctionalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_subject()

    def test_target_toolsets_are_exact_and_nonempty(self) -> None:
        self.assertEqual(
            self.subject.TARGET_TOOLSETS,
            (
                "project",
                "editor_navigation",
                "pcb_board",
                "pcb_components",
                "pcb_routing",
                "placement",
                "pcb_export",
                "verification",
            ),
        )

    def test_safe_run_directory_rejects_escape_and_root_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child = root / "baseline"
            self.subject.assert_safe_run_directory(root, child)
            with self.assertRaises(self.subject.FunctionalError):
                self.subject.assert_safe_run_directory(root, root)
            with self.assertRaises(self.subject.FunctionalError):
                self.subject.assert_safe_run_directory(root, root.parent / "escape")

    def test_response_summary_separates_text_json_and_image_payload(self) -> None:
        result = {
            "isError": False,
            "content": [
                {"type": "text", "text": '{"count":2,"source":"ipc"}'},
                {"type": "image", "mimeType": "image/png", "data": "aGVsbG8="},
            ],
        }
        summary, parsed, images = self.subject.summarize_tool_result(result)
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(summary["content"][1]["decoded_bytes"], 5)
        self.assertEqual(len(summary["content"][1]["sha256"]), 64)
        self.assertEqual(images[0][1], b"hello")

    def test_coverage_fails_closed_on_missing_or_failed_tool(self) -> None:
        inventory = {
            "toolsets": {"pcb_board": ["a", "b"]},
        }
        ledger = [
            {"tool": "a", "classification": "passed"},
            {"tool": "b", "classification": "expected_limitation"},
        ]
        report = self.subject.coverage_report(inventory, ledger, ("pcb_board",))
        self.assertTrue(report["complete_invocation"])
        self.assertFalse(report["all_normal_behaviors_passed"])
        self.assertEqual(report["expected_limitations"], ["b"])

        report = self.subject.coverage_report(inventory, ledger[:1], ("pcb_board",))
        self.assertFalse(report["complete_invocation"])
        self.assertEqual(report["missing"], ["b"])

        ledger.append({"tool": "b", "classification": "failed"})
        report = self.subject.coverage_report(inventory, ledger, ("pcb_board",))
        self.assertEqual(report["failed"], ["b"])

    def test_pick_net_and_component_pad_pair_use_observed_data_only(self) -> None:
        nets = {"nets": [{"name": ""}, {"name": "GND"}, {"name": "VCC"}]}
        self.assertEqual(self.subject.pick_net_names(nets, 2), ["GND", "VCC"])
        pads = {
            "R1": [{"number": "1", "net_name": "GND"}],
            "R2": [{"number": "2", "net": "GND"}],
        }
        self.assertEqual(
            self.subject.pick_pad_pair(pads),
            ("GND", "R1", "1", "R2", "2"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
