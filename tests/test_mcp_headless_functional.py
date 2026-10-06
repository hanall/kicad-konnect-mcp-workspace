#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/mcp-headless-functional.py"


def load_module():
    spec = importlib.util.spec_from_file_location("mcp_headless_functional", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HeadlessFunctionalContractTest(unittest.TestCase):
    def test_target_inventory_is_complete_and_exclusions_are_explicit(self) -> None:
        module = load_module()
        self.assertEqual(
            set(module.TARGET_TOOLSETS),
            {
                "sch_components",
                "sch_wiring",
                "sch_analysis",
                "sch_batch",
                "sch_bus",
                "sch_hierarchy",
                "library",
                "templates",
                "sch_export",
            },
        )
        expected = module.expected_tool_names()
        self.assertEqual(len(expected), 114)
        self.assertIn("move_connected", expected)
        self.assertIn("update_pcb_from_schematic", expected)
        self.assertEqual(
            module.EXCLUDED_TOOLS,
            {"update_pcb_from_schematic": "실행 중인 KiCad PCB IPC가 필요한 라이브 전용 도구"},
        )

    def test_passed_record_requires_independent_postconditions(self) -> None:
        module = load_module()
        base = {
            "schema_version": 1,
            "tool": "probe",
            "request": {},
            "response": {"result": {"isError": False}},
            "is_error": False,
            "postconditions": [],
            "verdict": "passed",
        }
        errors = module.validate_case_record(base)
        self.assertTrue(any("postcondition" in error for error in errors), errors)

        base["postconditions"] = [
            {"name": "readback", "expected": 1, "actual": 1, "passed": True}
        ]
        self.assertEqual(module.validate_case_record(base), [])

    def test_is_error_false_alone_cannot_turn_failure_into_pass(self) -> None:
        module = load_module()
        record = {
            "schema_version": 1,
            "tool": "probe",
            "request": {},
            "response": {"result": {"isError": False}},
            "is_error": False,
            "postconditions": [
                {"name": "readback", "expected": "present", "actual": "missing", "passed": False}
            ],
            "verdict": "passed",
        }
        errors = module.validate_case_record(record)
        self.assertTrue(any("실패한 postcondition" in error for error in errors), errors)

    def test_config_forces_stdio_headless_isolation(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory(prefix="headless-contract-") as temp_dir:
            temp = Path(temp_dir)
            config = temp / "konnect.toml"
            project = temp / "project"
            state = temp / "state"
            project.mkdir()
            state.mkdir()
            socket = "ipc:///tmp/konnect-contract-no-such.sock"
            module.write_runtime_config(config, project, socket)
            text = config.read_text(encoding="utf-8")
            self.assertIn('transport = "stdio"', text)
            self.assertIn(f"project_dir = {json.dumps(str(project.resolve()))}", text)
            self.assertIn(f"ipc_address = {json.dumps(socket)}", text)
            self.assertIn('kicad_binary = "/nonexistent/konnect-headless-kicad"', text)
            self.assertNotIn("DISPLAY", text)

    def test_fixture_digest_is_order_independent_and_detects_change(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory(prefix="headless-digest-") as temp_dir:
            temp = Path(temp_dir)
            a = temp / "a.txt"
            b = temp / "b.txt"
            a.write_text("a\n", encoding="utf-8")
            b.write_text("b\n", encoding="utf-8")
            first = module.filesystem_digest([a, b])
            self.assertEqual(first, module.filesystem_digest([b, a]))
            b.write_text("changed\n", encoding="utf-8")
            self.assertNotEqual(first, module.filesystem_digest([a, b]))

    def test_script_uses_only_safe_launcher(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('ROOT / "scripts/run-konnect.sh"', text)
        self.assertIn('env["KONNECT_RUNTIME_HOME"]', text)
        self.assertIn('env["KONNECT_STATE_DIR"]', text)
        self.assertNotIn('Popen([str(BINARY)', text)
        self.assertNotIn('subprocess.run([str(BINARY)', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
