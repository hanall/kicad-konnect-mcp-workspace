import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("konnect_gui_sync", ROOT / "scripts/konnect_gui_sync.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(ROOT / "scripts"))
from konnect_gui_desktop import process_matches_schematic


class FakeDesktop:
    def __init__(self):
        self.events = []
        self.dirty = False
        self.identity = {"window_id": "0x123", "pid": 42, "start_time": "100", "display": ":199"}

    def observe(self, lane, schematic):
        return {**self.identity, "dirty": self.dirty, "title": "*시험" if self.dirty else "시험", "lane": lane}

    def close(self, observation, schematic):
        self.events.append("close")

    def reopen(self, observation, schematic):
        self.events.append("reopen")
        return {**self.identity, "window_id": "0x124", "dirty": False}

    def capture(self, lane):
        self.events.append("capture")
        return "시험.png"


class FakeMcp:
    def __init__(self, schematic):
        self.schematic = schematic
        self.events = []

    def call(self, name, arguments):
        self.events.append(name)
        if name == "get_sheet_hierarchy":
            value = {"file": str(self.schematic), "children": []}
        elif name == "add_schematic_text":
            self.schematic.write_bytes(self.schematic.read_bytes() + b"\nfixture-change")
            value = {"added": True}
        elif name == "get_schematic_layout":
            value = {"texts": [{"text": "시험"}]}
        else:
            raise AssertionError(name)
        return {"isError": False, "content": [{"type": "text", "text": json.dumps(value)}]}


class GuiSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schematic = self.root / "fixture.kicad_sch"
        # 이 단위시험의 바이트는 해시/인계 seam용이며 실제 회로도 파서 입력이 아니다.
        self.schematic.write_bytes(b"fixture-before")
        self.desktop = FakeDesktop()
        self.mcp = FakeMcp(self.schematic)
        self.controller = MODULE.SyncController(self.desktop, self.mcp, self.root / "evidence")
        self.arguments = {
            "schematic": str(self.schematic), "lane": "sync-test", "dry_run": True,
            "operations": [{"tool": "add_schematic_text", "arguments": {
                "schematic": str(self.schematic), "text": "시험", "x": 25.4, "y": 25.4,
            }}],
        }

    def test_clean_editor_handoff_applies_mcp_and_reopens_with_readback(self):
        plan = self.controller.run(self.arguments)
        self.assertEqual(self.desktop.events, [])
        self.assertEqual(self.schematic.read_bytes(), b"fixture-before")
        result = self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(result["outcome"], "applied_and_reopened")
        self.assertEqual(self.desktop.events, ["close", "reopen", "capture"])
        self.assertIn("get_schematic_layout", self.mcp.events)
        self.assertEqual(self.schematic.read_bytes(), b"fixture-before\nfixture-change")
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(receipt["outcome"], "applied_and_reopened")
        self.assertEqual(receipt["applied_count"], 1)
        self.assertTrue(result["needs_visual_confirmation"])

    def test_same_basename_in_different_directory_is_not_an_identity(self):
        self.assertTrue(process_matches_schematic(["/opt/bin/eeschema", str(self.schematic)], "/", self.schematic))
        self.assertTrue(process_matches_schematic(["/opt/bin/kicad", str(self.schematic.with_suffix('.kicad_pro'))], "/", self.schematic))
        self.assertFalse(process_matches_schematic(["/opt/bin/kicad", "/other/fixture.kicad_pro"], "/", self.schematic))
        self.assertFalse(process_matches_schematic(["/usr/bin/python3", str(self.schematic)], "/", self.schematic))

    def test_symlink_target_is_refused(self):
        link = self.root / "link.kicad_sch"
        link.symlink_to(self.schematic)
        with self.assertRaises(MODULE.SyncError):
            self.controller.run({**self.arguments, "schematic": str(link)})
        self.assertEqual(self.desktop.events, [])

    def test_dirty_editor_is_refused_without_save_or_close(self):
        self.desktop.dirty = True
        with self.assertRaises(MODULE.SyncError) as caught:
            self.controller.run(self.arguments)
        self.assertEqual(caught.exception.kind, "unsaved_changes")
        self.assertEqual(self.desktop.events, [])
        self.assertEqual(self.schematic.read_bytes(), b"fixture-before")

    def test_file_revision_drift_is_refused_before_close(self):
        plan = self.controller.run(self.arguments)
        self.schematic.write_bytes("외부 변경".encode())
        with self.assertRaises(MODULE.SyncError) as caught:
            self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(caught.exception.kind, "stale_revision")
        self.assertEqual(self.desktop.events, [])

    def test_pid_generation_drift_is_refused_before_close(self):
        plan = self.controller.run(self.arguments)
        self.desktop.identity["start_time"] = "101"
        with self.assertRaises(MODULE.SyncError):
            self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(self.desktop.events, [])

    def test_token_is_bound_to_operations_and_cannot_be_replayed(self):
        plan = self.controller.run(self.arguments)
        changed = json.loads(json.dumps(self.arguments))
        changed["operations"][0]["arguments"]["text"] = "변경됨"
        with self.assertRaises(MODULE.SyncError):
            self.controller.run({**changed, "dry_run": False, "expected_revision": plan["revision"]})
        with self.assertRaises(MODULE.SyncError):
            self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(self.desktop.events, [])

    def test_non_hierarchy_target_is_refused(self):
        another = self.root / "another.kicad_sch"
        another.write_bytes(b"unrelated")
        self.arguments["operations"][0]["arguments"]["schematic"] = str(another)
        with self.assertRaises(MODULE.SyncError):
            self.controller.run(self.arguments)
        self.assertEqual(self.desktop.events, [])

    def test_reopen_failure_does_not_rollback_or_claim_completion(self):
        plan = self.controller.run(self.arguments)

        def fail(*_):
            raise MODULE.SyncError("reopen_failed", "재열기 실패")

        self.desktop.reopen = fail
        result = self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(result["outcome"], "applied_but_reopen_failed")
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(self.schematic.read_bytes(), b"fixture-before\nfixture-change")
        self.assertEqual(Path(result["backups"][str(self.schematic)]).read_bytes(), b"fixture-before")

    def test_partial_failure_reopens_and_retains_applied_prefix(self):
        self.arguments["operations"] *= 2
        plan = self.controller.run(self.arguments)
        call = self.mcp.call
        writes = 0

        def failing_call(name, arguments):
            nonlocal writes
            if name == "add_schematic_text":
                writes += 1
                if writes == 2:
                    return {"isError": False, "content": [{"type": "text", "text": '{"error":"거부"}'}]}
            return call(name, arguments)

        self.mcp.call = failing_call
        result = self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(result["outcome"], "partial_or_uncertain")
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["pending_index"], 1)
        self.assertEqual(self.desktop.events, ["close", "reopen", "capture"])

    def test_dirty_change_after_dry_run_is_refused(self):
        plan = self.controller.run(self.arguments)
        self.desktop.dirty = True
        with self.assertRaises(MODULE.SyncError) as caught:
            self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(caught.exception.kind, "unsaved_changes")
        self.assertEqual(self.desktop.events, [])

    def test_transport_success_with_partial_batch_is_not_complete(self):
        self.arguments["operations"][0]["tool"] = "batch_edit_schematic_components"
        plan = self.controller.run(self.arguments)
        original = self.mcp.call

        def partial_call(name, arguments):
            if name == "batch_edit_schematic_components":
                self.schematic.write_bytes(b"fixture-partial")
                body = {"updated_count": 1, "errors": ["누락된 부품"], "outcome": {"status": "partial"}}
                return {"isError": False, "content": [{"type": "text", "text": json.dumps(body)}]}
            return original(name, arguments)

        self.mcp.call = partial_call
        result = self.controller.run({**self.arguments, "dry_run": False, "expected_revision": plan["revision"]})
        self.assertEqual(result["outcome"], "partial_or_uncertain")
        self.assertEqual(result["pending_index"], 0)
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(self.schematic.read_bytes(), b"fixture-partial")
        self.assertEqual(self.desktop.events, ["close", "reopen", "capture"])


if __name__ == "__main__":
    unittest.main()
