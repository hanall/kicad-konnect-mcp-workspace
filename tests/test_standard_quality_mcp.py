from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = Path(
    os.environ.get(
        "STANDARD_GUARDED_MCP_PATH",
        ROOT / "skills" / "kicad-schematic-quality" / "scripts" / "guarded_mcp.py",
    )
).resolve()
SPEC = importlib.util.spec_from_file_location("standard_guarded_mcp", ADAPTER_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
sys.path.insert(0, str(ADAPTER_PATH.parent))
try:
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)

AdapterError = MODULE.AdapterError
EvidenceWriter = MODULE.EvidenceWriter
ProjectPolicy = MODULE.ProjectPolicy
ProjectWriterLock = MODULE.ProjectWriterLock
StdioMcp = MODULE.StdioMcp
dispatch_prepared_requests = MODULE.dispatch_prepared_requests
response_quality_error = MODULE.response_quality_error
validate_evidence_dir = MODULE.validate_evidence_dir


def valid_plan() -> str:
    detail = "실제 ref.pin과 좌표, 읽기 방향, 근거를 기록한다. " * 30
    return "\n".join(
        [
            "# 페이지 사전 계획",
            "## 범위와 작성 방법",
            detail,
            "## 반드시 실선으로 닫을 로컬 망",
            detail,
            "## 페이지 포트 계약",
            detail,
            "## 공급과 반환 계약",
            detail,
            "## 완료 검증",
            detail,
        ]
    )


class WorkspaceFixture:
    def __init__(
        self,
        workspace: Path,
        *,
        project_at_root: bool = False,
        mode: str = "design",
        require_all: bool = True,
    ):
        self.workspace = workspace
        self.project = workspace if project_at_root else workspace / "제품 프로젝트 공백"
        (self.project / "plans").mkdir(parents=True, exist_ok=True)
        for name in ("00.md", "01.md", "common.md"):
            (self.project / "plans" / name).write_text(valid_plan(), encoding="utf-8")
        self.index = {
            "schema_version": 1,
            "mode": mode,
            "project_stem": "case",
            "plans": {
                "case.kicad_sch": "plans/00.md",
                "01_input.kicad_sch": "plans/01.md",
            },
            "common_plan": "plans/common.md",
            "require_all_plans_before_write": require_all,
            "allowed_files": [
                "case.kicad_pro",
                "case.kicad_pcb",
                "case.kicad_sch",
                "01_input.kicad_sch",
                "lib/Eval.kicad_sym",
                "sym-lib-table",
            ],
        }
        self.write_index()

    def write_index(self) -> None:
        (self.project / "plan-index.json").write_text(
            json.dumps(self.index, ensure_ascii=False), encoding="utf-8"
        )

    def policy(self) -> object:
        return ProjectPolicy(self.project, workspace_root=self.workspace)

    def mutation(self) -> dict[str, object]:
        return {
            "tool": "add_schematic_text",
            "arguments": {
                "schematic": "01_input.kicad_sch",
                "text": "모의 작성",
                "x": 10,
                "y": 10,
            },
        }


FAKE_SERVER = r'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

config_path = Path(sys.argv[sys.argv.index("--config") + 1]).resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))
trace = Path(config["trace"])

def send(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

def tool_result(body, failed=False):
    return {"isError": failed, "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    params = request.get("params", {})
    tool = params.get("name") if method == "tools/call" else None
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"method": method, "tool": tool}, ensure_ascii=False) + "\n")
    if "id" not in request:
        continue
    identifier = request["id"]
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": identifier, "result": {"serverInfo": {"name": "모의서버", "version": "1"}}})
        if config.get("exit_after_initialize"):
            raise SystemExit(9)
    elif method == "tools/list":
        if config.get("polluted_schema"):
            tools = [{"name": "server_stats"}]
        else:
            tools = [{"name": name, "inputSchema": {"type": "object"}} for name in config["tools"]]
        send({"jsonrpc": "2.0", "id": identifier, "result": {"tools": tools}})
    elif method == "tools/call" and tool == "get_installation_info":
        body = {
            "build": {"version": config["version"], "commit": config["commit"]},
            "configuration": {"selected_path": config.get("selected_path", str(config_path)), "source": "explicit_path"},
            "runtime": {"executable_path": config.get("executable_path", str(Path(sys.executable).resolve()))},
        }
        send({"jsonrpc": "2.0", "id": identifier, "result": tool_result(body)})
    elif method == "tools/call" and tool == "get_symbol_info":
        pins = config.get("symbol_pins", [])
        send({"jsonrpc": "2.0", "id": identifier, "result": tool_result({
            "lib_id": params.get("arguments", {}).get("lib_id"),
            "pin_count": len(pins),
            "pins": pins,
        })})
    elif method == "tools/call":
        failed = tool == config.get("fail_tool")
        body = config.get("tool_bodies", {}).get(tool, {"tool": tool})
        if tool in config.get("mutate_cad_tools", []):
            schematic = Path(params.get("arguments", {}).get("schematic", ""))
            if schematic.is_absolute():
                schematic.write_text("모의 MCP가 변경한 CAD\n", encoding="utf-8")
        package_target = config.get("mutate_package_on_tool", {}).get(tool)
        if package_target:
            Path(package_target).write_text("실행 중 패키지 변경\n", encoding="utf-8")
        send({"jsonrpc": "2.0", "id": identifier, "result": tool_result(body, failed)})
        if tool == config.get("mutate_config_on_tool"):
            config_path.write_text("{}", encoding="utf-8")
    else:
        send({"jsonrpc": "2.0", "id": identifier, "error": {"code": -1, "message": "지원하지 않는 모의 요청"}})
'''


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "임의 workspace 공백"
        self.workspace.mkdir()
        self.fixture = WorkspaceFixture(self.workspace)
        self.policy = self.fixture.policy()

    def tearDown(self):
        self.temp.cleanup()

    def test_project_may_equal_workspace_root(self):
        with tempfile.TemporaryDirectory() as raw:
            fixture = WorkspaceFixture(Path(raw), project_at_root=True)
            policy = fixture.policy()
            self.assertEqual(policy.project_dir, policy.workspace_root)

    def test_project_outside_workspace_is_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "plan-index.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "workspace-root 안"):
            ProjectPolicy(outside, workspace_root=self.workspace)

    def test_mode_is_required_and_review_is_read_only(self):
        del self.fixture.index["mode"]
        self.fixture.write_index()
        with self.assertRaisesRegex(AdapterError, "mode"):
            self.fixture.policy()
        self.fixture.index["mode"] = "review"
        self.fixture.write_index()
        review = self.fixture.policy()
        self.assertFalse(review.prepare_request("server_stats", {}).mutating)
        with self.assertRaisesRegex(AdapterError, "읽기 전용"):
            review.prepare_request(**self.fixture.mutation())
        preview = review.prepare_request(
            "annotate_schematic",
            {"schematic": "case.kicad_sch", "dry_run": True},
        )
        self.assertFalse(preview.mutating)
        with self.assertRaisesRegex(AdapterError, "읽기 전용"):
            review.prepare_request(
                "annotate_schematic",
                {"schematic": "case.kicad_sch", "dry_run": False},
            )

    def test_plan_schema_version_rejects_bool_and_float_aliases(self):
        for bad in (True, 1.0):
            with self.subTest(schema_version=bad):
                self.fixture.index["schema_version"] = bad
                self.fixture.write_index()
                with self.assertRaisesRegex(AdapterError, "schema_version"):
                    self.fixture.policy()

    def test_only_exact_known_dry_run_tools_become_read_only(self):
        for tool in (
            "annotate_schematic",
            "reset_schematic_field_positions",
            "update_symbols_from_library",
        ):
            with self.subTest(tool=tool):
                prepared = self.policy.prepare_request(
                    tool, {"schematic": "case.kicad_sch", "dry_run": True}
                )
                self.assertFalse(prepared.mutating)
        with self.assertRaisesRegex(AdapterError, "boolean"):
            self.policy.prepare_request(
                "annotate_schematic",
                {"schematic": "case.kicad_sch", "dry_run": "true"},
            )

    def test_all_plans_and_common_plan_are_required_before_prepare(self):
        self.fixture.index["allowed_files"].append("02_missing.kicad_sch")
        self.fixture.write_index()
        policy = self.fixture.policy()
        with self.assertRaisesRegex(AdapterError, "모든 회로도"):
            policy.prepare_request(**self.fixture.mutation())
        self.fixture.index["plans"]["02_missing.kicad_sch"] = "plans/01.md"
        del self.fixture.index["common_plan"]
        self.fixture.write_index()
        policy = self.fixture.policy()
        with self.assertRaisesRegex(AdapterError, "common_plan"):
            policy.prepare_request(**self.fixture.mutation())

    def test_require_all_flag_must_be_true_for_write(self):
        self.fixture.index["require_all_plans_before_write"] = False
        self.fixture.write_index()
        with self.assertRaisesRegex(AdapterError, "true"):
            self.fixture.policy().prepare_request(**self.fixture.mutation())

    def test_page_and_common_plan_changes_after_prepare_are_rejected(self):
        prepared = self.policy.prepare_request(**self.fixture.mutation())
        (self.fixture.project / "plans/01.md").write_text(valid_plan() + "\n변경", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "변경"):
            self.policy.mutation_intent(prepared)

        self.fixture = WorkspaceFixture(self.workspace / "둘째")
        self.policy = self.fixture.policy()
        prepared = self.policy.prepare_request(**self.fixture.mutation())
        (self.fixture.project / "plans/common.md").write_text(valid_plan() + "\n변경", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "common_plan"):
            self.policy.mutation_intent(prepared)

    def test_index_change_after_prepare_is_rejected(self):
        prepared = self.policy.prepare_request(**self.fixture.mutation())
        self.fixture.index["mode"] = "change"
        self.fixture.write_index()
        with self.assertRaisesRegex(AdapterError, "plan-index.json이 변경"):
            self.policy.mutation_intent(prepared)

    def test_unknown_tool_is_rejected_even_if_runtime_might_advertise_it(self):
        with self.assertRaisesRegex(AdapterError, "허용되지 않은"):
            self.policy.prepare_request("brand_new_safe_write", {"schematic": "case.kicad_sch"})

    def test_legacy_wiring_signatures_are_rejected_before_dispatch(self):
        cases = [
            (
                "connect_pins",
                {
                    "schematic": "01_input.kicad_sch",
                    "from_component": "R1",
                    "from_pin": "1",
                    "to_component": "U1",
                    "to_pin": "2",
                },
                "필수 문자열 누락",
            ),
            (
                "connect_to_net",
                {
                    "schematic": "01_input.kicad_sch",
                    "component_reference": "R1",
                    "pin_number": "1",
                    "net_name": "SIG",
                },
                "필수 문자열 누락",
            ),
            (
                "add_power_symbol",
                {
                    "schematic": "01_input.kicad_sch",
                    "component_reference": "U1",
                    "pin_number": "8",
                    "power_net": "VCC",
                },
                "숫자 x/y",
            ),
        ]
        for tool, arguments, message in cases:
            with self.subTest(tool=tool), self.assertRaisesRegex(AdapterError, message):
                self.policy.prepare_request(tool, arguments)

    def test_wireless_batch_default_and_child_erc_are_rejected(self):
        with self.assertRaisesRegex(AdapterError, "stub_length"):
            self.policy.prepare_request(
                "batch_connect_to_net",
                {
                    "schematic": "01_input.kicad_sch",
                    "pins": [{"reference": "U1", "pin_number": "1"}],
                    "net": "SIG",
                },
            )
        prepared = self.policy.prepare_request(
            "batch_connect_to_net",
            {
                "schematic": "01_input.kicad_sch",
                "pins": [{"reference": "U1", "pin_number": "1"}],
                "net": "SIG",
                "stub_length": 2.54,
            },
        )
        self.assertTrue(prepared.mutating)
        with self.assertRaisesRegex(AdapterError, "owning root"):
            self.policy.prepare_request("run_erc", {"schematic": "01_input.kicad_sch"})
        self.assertFalse(
            self.policy.prepare_request("run_erc", {"schematic": "case.kicad_sch"}).mutating
        )

    def test_named_phantom_and_pcb_save_tools_are_not_schematic_writes(self):
        for tool in ("audit_esd_protection", "save_project"):
            with self.subTest(tool=tool), self.assertRaisesRegex(AdapterError, "허용되지 않은"):
                self.policy.prepare_request(tool, {})

    def test_outside_path_and_allowed_symlink_are_rejected(self):
        with self.assertRaisesRegex(AdapterError, "프로젝트 밖"):
            self.policy.prepare_request(
                "create_schematic", {"path": str(self.workspace / "outside.kicad_sch")}
            )
        outside = Path(self.temp.name) / "outside.kicad_sch"
        outside.write_text("외부", encoding="utf-8")
        link = self.fixture.project / "escape.kicad_sch"
        link.symlink_to(outside)
        self.fixture.index["allowed_files"].append("escape.kicad_sch")
        self.fixture.index["plans"]["escape.kicad_sch"] = "plans/01.md"
        self.fixture.write_index()
        with self.assertRaisesRegex(AdapterError, "symlink"):
            self.fixture.policy()

    def test_run_design_review_board_must_be_allowed_project_board(self):
        outside = self.workspace / "outside-board.kicad_pcb"
        outside.write_text("(kicad_pcb)\n", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "프로젝트 밖|allowed_files"):
            self.policy.prepare_request(
                "run_design_review",
                {"schematic": "case.kicad_sch", "board": str(outside)},
            )
        prepared = self.policy.prepare_request(
            "run_design_review",
            {"schematic": "case.kicad_sch", "board": "case.kicad_pcb"},
        )
        self.assertEqual(
            prepared.arguments["board"], str(self.fixture.project / "case.kicad_pcb")
        )

    def test_power_flag_requires_machine_readable_plan_approval(self):
        with self.assertRaisesRegex(AdapterError, "PWR_FLAG"):
            self.policy.prepare_request(
                "add_power_symbol",
                {
                    "schematic": "01_input.kicad_sch",
                    "power_net": "PWR_FLAG",
                    "x": 10,
                    "y": 10,
                },
            )
        bypasses = [
            (
                "add_schematic_component",
                {
                    "schematic": "01_input.kicad_sch",
                    "lib_id": "power:PWR_FLAG",
                    "x": 10,
                    "y": 10,
                },
            ),
            (
                "batch_place_components",
                {
                    "schematic": "01_input.kicad_sch",
                    "components": [
                        {"lib_id": "power:PWR_FLAG", "x": 10, "y": 10}
                    ],
                },
            ),
            (
                "replace_component",
                {
                    "schematic": "01_input.kicad_sch",
                    "reference": "U1",
                    "new_lib_id": "power:PWR_FLAG",
                },
            ),
        ]
        for tool, arguments in bypasses:
            with self.subTest(tool=tool), self.assertRaisesRegex(AdapterError, "PWR_FLAG"):
                self.policy.prepare_request(tool, arguments)

    def test_read_only_file_is_exactly_enforced(self):
        self.fixture.index["read_only_files"] = ["01_input.kicad_sch"]
        self.fixture.write_index()
        policy = self.fixture.policy()
        self.assertFalse(
            policy.prepare_request(
                "get_schematic_component",
                {"schematic": "01_input.kicad_sch", "reference": "U1"},
            ).mutating
        )
        with self.assertRaisesRegex(AdapterError, "read_only_files"):
            policy.prepare_request(**self.fixture.mutation())

    def test_external_library_mapping_is_exact_and_global_is_forbidden(self):
        library = self.workspace / "설치 라이브러리" / "Device.kicad_sym"
        library.parent.mkdir()
        library.write_text("(kicad_symbol_lib)\n", encoding="utf-8")
        self.fixture.index["read_only_library_refs"] = {"Device": str(library)}
        self.fixture.write_index()
        policy = self.fixture.policy()
        prepared = policy.prepare_request(
            "register_symbol_library",
            {
                "library_path": str(library),
                "nickname": "Device",
                "scope": "project",
                "project": "case.kicad_pro",
            },
        )
        intent = policy.mutation_intent(prepared)
        self.assertEqual(intent["registered_read_only_library_ref"]["nickname"], "Device")
        alias = self.workspace / "library-alias.kicad_sym"
        alias.symlink_to(library)
        with self.assertRaisesRegex(AdapterError, "exact"):
            policy.prepare_request(
                "register_symbol_library",
                {
                    "library_path": str(alias),
                    "nickname": "Device",
                    "scope": "project",
                    "project": "case.kicad_pro",
                },
            )
        with self.assertRaisesRegex(AdapterError, "global"):
            policy.prepare_request(
                "register_symbol_library",
                {
                    "library_path": str(library),
                    "nickname": "Device",
                    "scope": "global",
                    "project": "case.kicad_pro",
                },
            )

    def test_symbol_unit_is_preserved_but_invalid_units_are_rejected(self):
        prepared = self.policy.prepare_request(
            "add_schematic_component",
            {"schematic": "01_input.kicad_sch", "lib_id": "Amplifier:OpAmp", "unit": 4},
        )
        self.assertEqual(prepared.arguments["unit"], 4)
        for bad in (0, -1, True, "2"):
            with self.subTest(unit=bad), self.assertRaisesRegex(AdapterError, "1 이상의 정수"):
                self.policy.prepare_request(
                    "batch_place_components",
                    {"schematic": "01_input.kicad_sch", "components": [{"unit": bad}]},
                )

    def test_editor_lock_is_not_deleted_or_bypassed(self):
        prepared = self.policy.prepare_request(**self.fixture.mutation())
        lock = self.fixture.project / "~case.kicad_sch.lck"
        lock.write_text("살아 있는 잠금", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "editor lock"):
            self.policy.mutation_intent(prepared)
        self.assertTrue(lock.exists())

    def test_evidence_must_be_new_inside_workspace_and_not_collide(self):
        good = self.workspace / "증거 새 폴더"
        self.assertEqual(validate_evidence_dir(good, self.policy), good.resolve())
        good.mkdir()
        with self.assertRaisesRegex(AdapterError, "존재하지 않는 새 경로"):
            validate_evidence_dir(good, self.policy)
        with self.assertRaisesRegex(AdapterError, "workspace-root 안"):
            validate_evidence_dir(Path(self.temp.name) / "밖 증거", self.policy)
        with self.assertRaisesRegex(AdapterError, "충돌"):
            validate_evidence_dir(
                self.fixture.project / "case.kicad_sch" / "증거", self.policy
            )
        evidence_link = self.workspace / "증거 symlink"
        evidence_link.symlink_to(self.workspace / "실제 새 증거", target_is_directory=True)
        with self.assertRaisesRegex(AdapterError, "symlink"):
            validate_evidence_dir(evidence_link, self.policy)

    def test_metadata_query_needs_no_plan_or_toolset_mapping(self):
        prepared = self.policy.prepare_request("server_stats", {})
        self.assertFalse(prepared.mutating)

    def test_portable_source_has_no_product_or_fixed_root_dependency(self):
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "/home/hanol",
            "battery-module-cycler",
            "hardware/schematic_quality_lab",
            "from scripts.schematic_quality_mcp",
            "import scripts.schematic_quality_mcp",
        ):
            self.assertNotIn(forbidden, source)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(
            imported - {"__future__", "package_identity"}, sys.stdlib_module_names
        )


class DispatchAndLockTests(unittest.TestCase):
    def test_mutation_ready_rejects_cad_change_after_intent(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            fixture = WorkspaceFixture(workspace)
            for name in ("case.kicad_sch", "01_input.kicad_sch"):
                (fixture.project / name).write_text(f"원본 {name}\n", encoding="utf-8")
            policy = fixture.policy()
            prepared = policy.prepare_request(**fixture.mutation())
            intent = policy.mutation_intent(prepared)
            (fixture.project / "01_input.kicad_sch").write_text(
                "intent 뒤 외부 변경\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(AdapterError, "CAD.*변경"):
                policy.assert_mutation_ready(prepared, intent)

    def test_mutation_false_green_shapes_and_unchanged_cad_are_rejected(self):
        bodies = [
            {"outcome": {"status": "partial"}, "failed_count": 1, "errors": ["실패"]},
            {"outcome": {"status": "failed"}},
            None,
            {"outcome": {"status": "complete"}, "applied_count": 0},
        ]
        for index, body in enumerate(bodies):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as raw:
                workspace = Path(raw)
                fixture = WorkspaceFixture(workspace)
                for name in ("case.kicad_sch", "01_input.kicad_sch"):
                    (fixture.project / name).write_text(f"원본 {name}\n", encoding="utf-8")
                policy = fixture.policy()
                prepared = policy.prepare_request(**fixture.mutation())

                def caller(tool, arguments, intent):
                    if index == 1:
                        Path(arguments["schematic"]).write_text(
                            "failed 응답 전 target 변경\n", encoding="utf-8"
                        )
                    content = [] if body is None else [
                        {"type": "text", "text": json.dumps(body, ensure_ascii=False)}
                    ]
                    return (
                        {"jsonrpc": "2.0", "id": 1, "result": {"isError": False, "content": content}},
                        1.0,
                        {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                    )

                with EvidenceWriter(workspace / "증거") as evidence:
                    records, failed = dispatch_prepared_requests(
                        policy, [prepared], caller, evidence
                    )
                self.assertTrue(failed)
                self.assertFalse(records[0]["ok"])

    def test_mutation_rejects_non_target_cad_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            fixture = WorkspaceFixture(workspace)
            for name in ("case.kicad_sch", "01_input.kicad_sch"):
                (fixture.project / name).write_text(f"원본 {name}\n", encoding="utf-8")
            policy = fixture.policy()
            prepared = policy.prepare_request(**fixture.mutation())

            def caller(tool, arguments, intent):
                (fixture.project / "case.kicad_sch").write_text(
                    "대상 밖 변경\n", encoding="utf-8"
                )
                return (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "isError": False,
                            "content": [{"type": "text", "text": '{"outcome":{"status":"complete"}}'}],
                        },
                    },
                    1.0,
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                )

            with EvidenceWriter(workspace / "증거") as evidence:
                records, failed = dispatch_prepared_requests(policy, [prepared], caller, evidence)
            self.assertTrue(failed)
            self.assertFalse(records[0]["ok"])

    def test_plan_snapshot_is_durable_before_mock_caller(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            fixture = WorkspaceFixture(workspace)
            policy = fixture.policy()
            request = policy.prepare_request(**fixture.mutation())
            evidence_dir = workspace / "증거"

            def caller(tool, arguments, intent):
                event = json.loads(
                    (evidence_dir / "mcp-journal.jsonl").read_text(encoding="utf-8").splitlines()[-1]
                )
                self.assertEqual(event["event"], "pre_dispatch")
                snapshots = [event["common_plan"]["snapshot_path"]]
                snapshots.extend(item["snapshot_path"] for item in event["plans"])
                for raw_snapshot in snapshots:
                    snapshot = Path(raw_snapshot)
                    self.assertEqual(snapshot.stem, hashlib.sha256(snapshot.read_bytes()).hexdigest())
                Path(arguments["schematic"]).write_text("모의 MCP 변경\n", encoding="utf-8")
                return (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "isError": False,
                            "content": [{"type": "text", "text": '{"outcome":{"status":"complete"}}'}],
                        },
                    },
                    1.0,
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                )

            with EvidenceWriter(evidence_dir) as evidence:
                records, failed = dispatch_prepared_requests(policy, [request], caller, evidence)
            self.assertFalse(failed)
            self.assertTrue(records[0]["ok"])

    def test_first_mock_mcp_error_stops_following_requests(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            fixture = WorkspaceFixture(workspace)
            policy = fixture.policy()
            requests = [
                policy.prepare_request("get_symbol_info", {"lib_id": item})
                for item in ("Device:R", "Device:C", "Device:L")
            ]
            calls = []

            def caller(tool, arguments, intent):
                calls.append(arguments["lib_id"])
                return (
                    {
                        "jsonrpc": "2.0",
                        "id": len(calls),
                        "result": {
                            "isError": len(calls) == 2,
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "lib_id": arguments["lib_id"],
                                            "pin_count": 1,
                                            "pins": [
                                                {
                                                    "number": "1",
                                                    "name": "P",
                                                    "type": "passive",
                                                    "unit": 1,
                                                }
                                            ],
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        },
                    },
                    1.0,
                    {"jsonrpc": "2.0", "id": len(calls), "method": "tools/call"},
                )

            with EvidenceWriter(workspace / "증거") as evidence:
                records, failed = dispatch_prepared_requests(policy, requests, caller, evidence)
            self.assertTrue(failed)
            self.assertEqual(calls, ["Device:R", "Device:C"])
            self.assertEqual(len(records), 2)

    def test_duplicate_writer_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            first = ProjectWriterLock(Path(raw))
            first.acquire()
            try:
                with self.assertRaisesRegex(AdapterError, "다른 작성자"):
                    ProjectWriterLock(Path(raw)).acquire()
            finally:
                first.release()

    def test_writer_lock_symlink_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / "project"
            project.mkdir()
            target = root / "outside.txt"
            target.write_text("보존", encoding="utf-8")
            (project / ".schematic-quality-mcp.lock").symlink_to(target)
            with self.assertRaisesRegex(AdapterError, "writer lock"):
                ProjectWriterLock(project).acquire()
            self.assertEqual(target.read_text(encoding="utf-8"), "보존")

    def test_stdio_close_broken_pipe_still_reaps_and_closes_resources(self):
        class BrokenStdin:
            closed = False
            close_attempted = False

            def close(self):
                self.close_attempted = True
                raise BrokenPipeError("조기 종료")

        class FinishedProcess:
            pid = os.getpid()

            def __init__(self):
                self.stdin = BrokenStdin()
                self.waited = False

            def wait(self, timeout):
                self.waited = True
                return 9

            def poll(self):
                return 9

        class Closable:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        transport = StdioMcp.__new__(StdioMcp)
        transport.process = FinishedProcess()
        transport.selector = Closable()
        transport.stderr_handle = Closable()
        self.assertEqual(transport.close(), 9)
        self.assertTrue(transport.process.stdin.close_attempted)
        self.assertTrue(transport.process.waited)
        self.assertTrue(transport.selector.closed)
        self.assertTrue(transport.stderr_handle.closed)


class SymbolResponseContractTests(unittest.TestCase):
    @staticmethod
    def response(body):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "isError": False,
                "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
            },
        }

    def test_actual_shape_without_unit_coverage_is_incomplete(self):
        body = {
            "lib_id": "Device:R",
            "pin_count": 2,
            "pins": [
                {"number": "1", "name": "", "type": "passive", "x": 0.0, "y": 3.81},
                {"number": "2", "name": "", "type": "passive", "x": 0.0, "y": -3.81},
            ],
        }
        error = response_quality_error(
            "get_symbol_info", self.response(body), {"lib_id": "Device:R"}
        )
        self.assertIn("unit", error)

    def test_count_identity_name_and_type_mismatches_are_rejected(self):
        base = {
            "lib_id": "Device:D",
            "pin_count": 2,
            "pins": [
                {"number": "1", "name": "K", "type": "passive", "x": -3.81, "y": 0.0},
                {"number": "2", "name": "A", "type": "passive", "x": 3.81, "y": 0.0},
            ],
        }
        variants = []
        changed = json.loads(json.dumps(base)); changed["pin_count"] = 3
        variants.append((changed, "pin_count"))
        changed = json.loads(json.dumps(base)); changed["lib_id"] = "Device:LED"
        variants.append((changed, "lib_id"))
        changed = json.loads(json.dumps(base)); del changed["pins"][0]["name"]
        variants.append((changed, "name"))
        changed = json.loads(json.dumps(base)); del changed["pins"][0]["type"]
        variants.append((changed, "type"))
        changed = json.loads(json.dumps(base))
        for pin in changed["pins"]:
            pin["unit"] = 1
        changed["pins"][0]["unit"] = 0
        variants.append((changed, "unit"))
        for body, expected in variants:
            with self.subTest(expected=expected):
                error = response_quality_error(
                    "get_symbol_info", self.response(body), {"lib_id": "Device:D"}
                )
                self.assertIn(expected, error)

        complete = json.loads(json.dumps(base))
        for pin in complete["pins"]:
            pin["unit"] = 1
        self.assertIsNone(
            response_quality_error(
                "get_symbol_info", self.response(complete), {"lib_id": "Device:D"}
            )
        )


class PublicCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.workspace = self.base / "임의 제품 workspace 공백"
        self.workspace.mkdir()
        self.fixture = WorkspaceFixture(self.workspace)
        self.backend = self.base / "backend 공백"
        self.backend.mkdir()
        self.launcher = self.backend / "정식 launcher.py"
        self.launcher.write_text(FAKE_SERVER, encoding="utf-8")
        self.launcher.chmod(0o755)
        self.trace = self.backend / "calls.jsonl"
        self.config = self.backend / "backend config.json"
        self.adapter_copy = self.base / "이동된 skill root" / "scripts" / "guarded_mcp.py"
        self.adapter_copy.parent.mkdir(parents=True)
        shutil.copy2(ADAPTER_PATH, self.adapter_copy)
        shutil.copy2(ADAPTER_PATH.parent / "package_identity.py", self.adapter_copy.parent)
        (self.adapter_copy.parents[1] / "SKILL.md").write_text(
            "# 이동 fixture skill\n", encoding="utf-8"
        )
        self.other_cwd = self.base / "호출자 다른 cwd"
        self.other_cwd.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **overrides) -> None:
        config = {
            "trace": str(self.trace),
            "version": "9.8.7",
            "commit": "commit-abc",
            "tools": [
                "get_installation_info",
                "load_toolset",
                "server_stats",
                "get_symbol_info",
                "add_schematic_text",
                "brand_new_safe_write",
            ],
            "mutate_cad_tools": ["add_schematic_text"],
        }
        config.update(overrides)
        self.config.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def invoke(self, request: dict[str, object], evidence_name: str, **config_overrides):
        self.write_config(**config_overrides)
        request_path = self.workspace / f"{evidence_name}-requests.jsonl"
        request_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
        evidence = self.workspace / evidence_name
        command = [
            sys.executable,
            str(self.adapter_copy),
            "--workspace-root",
            str(self.workspace),
            "--project-dir",
            str(self.fixture.project),
            "--launcher",
            str(self.launcher),
            "--config",
            str(self.config),
            "--server-cwd",
            str(self.backend),
            "--expected-version",
            "9.8.7",
            "--expected-commit",
            "commit-abc",
            "--requests",
            str(request_path),
            "--evidence-dir",
            str(evidence),
            "--timeout",
            "5",
        ]
        completed = subprocess.run(
            command,
            cwd=self.other_cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        return completed, evidence

    def trace_rows(self):
        if not self.trace.exists():
            return []
        return [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]

    def test_metadata_only_cli_is_portable_and_never_loads_empty_toolset(self):
        """이 시험은 이동된 어댑터와 모의 MCP이며 native 성공을 뜻하지 않는다."""
        completed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}}, "메타 증거"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        calls = self.trace_rows()
        self.assertEqual(sum(row.get("tool") == "load_toolset" for row in calls), 0)
        session = json.loads((evidence / "session-start.json").read_text(encoding="utf-8"))
        runtime = json.loads((evidence / "runtime-identity.json").read_text(encoding="utf-8"))
        self.assertRegex(session["backend_environment"]["launcher"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(session["backend_environment"]["config"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(session["backend_environment"]["environment_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(session["package_identity"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(runtime["matches_expected"])
        self.assertFalse((self.fixture.project / ".schematic-quality-mcp.lock").exists())

    def test_mock_mutation_uses_launcher_and_snapshots_all_plans(self):
        """MCP 왕복과 정책만 모의하며 KiCad native 저장 성공으로 승격하지 않는다."""
        completed, evidence = self.invoke(self.fixture.mutation(), "쓰기 모의 증거")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        calls = self.trace_rows()
        self.assertEqual(sum(row.get("tool") == "load_toolset" for row in calls), 1)
        self.assertEqual(sum(row.get("tool") == "add_schematic_text" for row in calls), 1)
        tool_order = [row.get("tool") for row in calls if row.get("tool")]
        self.assertLess(
            tool_order.index("get_installation_info"), tool_order.index("load_toolset")
        )
        self.assertLess(tool_order.index("load_toolset"), tool_order.index("add_schematic_text"))
        pre_dispatch = next(
            json.loads(line)
            for line in (evidence / "mcp-journal.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("event") == "pre_dispatch"
        )
        snapshots = [pre_dispatch["common_plan"]["snapshot_path"]]
        snapshots.extend(item["snapshot_path"] for item in pre_dispatch["plans"])
        self.assertEqual(len(snapshots), 3)
        self.assertTrue(all(Path(path).is_file() for path in snapshots))
        summary = json.loads((evidence / "session-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["session_rc"], 0)
        self.assertEqual(summary["server_exit_rc"], 0)

    def test_runtime_version_mismatch_refuses_mock_mutation(self):
        completed, evidence = self.invoke(
            self.fixture.mutation(), "버전 불일치 증거", version="0.0.0"
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("version/commit", completed.stderr)
        self.assertEqual(sum(row.get("tool") == "add_schematic_text" for row in self.trace_rows()), 0)
        runtime = json.loads((evidence / "runtime-identity.json").read_text(encoding="utf-8"))
        self.assertFalse(runtime["matches_expected"])

    def test_runtime_version_mismatch_refuses_read_evidence_too(self):
        completed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "읽기 version 불일치 증거",
            version="0.0.0",
        )
        self.assertNotEqual(completed.returncode, 0)
        runtime = json.loads((evidence / "runtime-identity.json").read_text(encoding="utf-8"))
        self.assertFalse(runtime["matches_expected"])

    def test_serving_config_and_process_binary_identity_mismatch_are_rejected(self):
        other_config = self.backend / "다른 config.json"
        other_config.write_text("{}", encoding="utf-8")
        config_mismatch, _ = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "config identity 불일치",
            selected_path=str(other_config),
        )
        self.assertNotEqual(config_mismatch.returncode, 0)
        self.assertIn("serving config", config_mismatch.stderr)

        binary_mismatch, _ = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "binary identity 불일치",
            executable_path="/bin/false",
        )
        self.assertNotEqual(binary_mismatch.returncode, 0)
        self.assertIn("실제 서버 /proc executable", binary_mismatch.stderr)

    def test_missing_config_and_failed_backend_cannot_pass(self):
        self.write_config()
        self.config.unlink()
        request = self.workspace / "missing-requests.jsonl"
        request.write_text('{"tool":"server_stats","arguments":{}}\n', encoding="utf-8")
        command = [
            sys.executable,
            str(self.adapter_copy),
            "--workspace-root", str(self.workspace),
            "--project-dir", str(self.fixture.project),
            "--launcher", str(self.launcher),
            "--config", str(self.config),
            "--server-cwd", str(self.backend),
            "--expected-version", "9.8.7",
            "--expected-commit", "commit-abc",
            "--requests", str(request),
            "--evidence-dir", str(self.workspace / "missing 증거"),
        ]
        missing = subprocess.run(command, cwd=self.other_cwd, text=True, capture_output=True, check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("config", missing.stderr)

        failed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "실패 backend 증거",
            exit_after_initialize=True,
        )
        self.assertNotEqual(failed.returncode, 0)
        summary = json.loads((evidence / "session-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["session_rc"], 1)

    def test_backend_identity_change_during_last_call_cannot_pass(self):
        completed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "backend 변경 증거",
            mutate_config_on_tool="server_stats",
        )
        self.assertNotEqual(completed.returncode, 0)
        summary = json.loads((evidence / "session-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["session_rc"], 1)
        self.assertIn("config identity", summary["backend_final_error"])

    def test_package_identity_change_during_last_call_cannot_pass(self):
        skill_entry = self.adapter_copy.parents[1] / "SKILL.md"
        completed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "package 변경 증거",
            mutate_package_on_tool={"server_stats": str(skill_entry)},
        )
        self.assertNotEqual(completed.returncode, 0)
        summary = json.loads((evidence / "session-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["session_rc"], 1)
        self.assertIn("패키지", summary["package_identity_error"])

    def test_polluted_runtime_tool_schema_is_rejected(self):
        completed, evidence = self.invoke(
            {"tool": "server_stats", "arguments": {}},
            "schema 오염 증거",
            polluted_schema=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("오염된 tool schema", completed.stderr)
        self.assertTrue((evidence / "runtime-tool-schemas.json").is_file())

    def test_symbol_success_with_zero_pins_is_not_green(self):
        completed, evidence = self.invoke(
            {"tool": "get_symbol_info", "arguments": {"lib_id": "Amplifier_Operational:LM358"}},
            "pin0 false green 증거",
            symbol_pins=[],
        )
        self.assertNotEqual(completed.returncode, 0)
        records = json.loads((evidence / "dispatch-records.json").read_text(encoding="utf-8"))
        self.assertFalse(records[0]["ok"])
        # initialize가 response-0001이므로 pin 응답의 quality 판정은 journal에서 찾는다.
        events = [json.loads(line) for line in (evidence / "mcp-journal.jsonl").read_text(encoding="utf-8").splitlines()]
        quality = next(item for item in events if item.get("event") == "rpc_exchange")
        self.assertIn("pin_count", quality["quality_contract_error"])

    def test_unknown_advertised_write_is_rejected_before_launch(self):
        completed, evidence = self.invoke(
            {"tool": "brand_new_safe_write", "arguments": {"schematic": "case.kicad_sch"}},
            "unknown write 증거",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("허용되지 않은 도구", completed.stderr)
        self.assertFalse(evidence.exists())
        self.assertEqual(self.trace_rows(), [])


if __name__ == "__main__":
    unittest.main()
