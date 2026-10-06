#!/usr/bin/env python3
"""격리된 실제 KiCad GUI/IPC에서 Konnect PCB 공개 기능을 전수 호출한다.

이 스크립트는 성공 transport를 기능 성공으로 승격하지 않는다. 각 호출의 원 요청,
응답, 경과 시간, binary/source identity, 후속 관측을 ledger에 남기며 지원 한계와
예기치 않은 실패를 별도 분류한다. 보호된 KiCad 파일은 Konnect 도구로만 변경하고,
공식 KiCad/Konnect fixture는 byte-for-byte 복제만 한다.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts/run-konnect.sh"
KONNECT_BINARY = ROOT / "upstream/konnect/target/release/konnect"
INVENTORY_DEFAULT = ROOT / ".artifacts/20261006-improvement/catalogue/inventory.json"
ARTIFACT_ROOT = ROOT / ".artifacts/20261006-improvement/pcb-functional"
ACUW_INSTANCE = Path("/home/hanol/ai-computer-use-workspace/scripts/instance.sh")
ACUW_CAPTURE = "capture.sh"
GUI_CONFIG_SOURCE = ROOT / ".artifacts/20261006-upgrade/gui-config"
VARIANTS_SOURCE = ROOT / "upstream/kicad/qa/data/eeschema/variants"
SPECCTRA_BOARD_SOURCE = (
    ROOT
    / "upstream/konnect/crates/konnect-core/tests/fixtures/"
    "specctra_two_resistors_locked.kicad_pcb"
)
SPECCTRA_SES_SOURCE = (
    ROOT
    / "upstream/konnect/crates/konnect-core/tests/fixtures/"
    "specctra_two_resistors_locked.freerouting-2.3.0.ses"
)
ROUTING_BOARD_SOURCE = (
    ROOT / "upstream/konnect/crates/konnect-ipc/tests/fixtures/live_ipc.kicad_pcb"
)
TARGET_TOOLSETS = (
    "project",
    "editor_navigation",
    "pcb_board",
    "pcb_components",
    "pcb_routing",
    "placement",
    "pcb_export",
    "verification",
)

MUTATING_TOOLS = {
    "create_project", "rename_project", "save_project",
    "add_board_outline", "add_board_text", "add_layer", "add_mounting_hole",
    "add_zone", "delete_graphics", "import_svg_logo", "set_active_layer",
    "set_board_size", "align_components", "delete_component",
    "duplicate_component", "edit_board_footprint_graphic", "edit_component",
    "flip_component", "move_component", "place_component",
    "place_component_array", "repair_corrupted_footprints", "rotate_component",
    "set_component_placements", "set_placed_footprint_models",
    "update_footprints_from_library", "add_copper_pour", "add_net", "add_via",
    "apply_specctra_ses", "assign_net_to_class", "create_netclass",
    "delete_trace", "modify_trace", "route_differential_pair",
    "route_pad_to_pad", "route_trace", "place_decoupling_caps",
    "plan_bga_fanout", "refine_placement_force_directed", "refill_zones",
    "copy_routing_pattern", "launch_kicad_ui", "set_design_rules",
    "set_layer_constraints", "set_predefined_sizes", "mutate_editor_selection",
}


def is_mutating_call(tool: str, arguments: dict[str, Any]) -> bool:
    if tool not in MUTATING_TOOLS:
        return False
    if arguments.get("dry_run") is True:
        return False
    if tool == "set_placed_footprint_models" and arguments.get("mode") == "inspect":
        return False
    if tool == "plan_bga_fanout" and arguments.get("apply") is not True:
        return False
    if tool in {"repair_corrupted_footprints", "update_footprints_from_library"} and arguments.get("dry_run", True):
        return False
    return True


class FunctionalError(RuntimeError):
    """검증을 계속하면 다른 레인이나 기능 판정을 오염시킬 때 발생한다."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    for path in sorted(files):
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            relative = path
        digest.update(str(relative).encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def assert_safe_run_directory(root: Path, run_dir: Path) -> None:
    root = root.resolve()
    run_dir = run_dir.resolve()
    if run_dir == root or root not in run_dir.parents:
        raise FunctionalError(f"run directory가 전용 artifact 하위가 아닙니다: {run_dir}")


def summarize_tool_result(
    result: dict[str, Any],
) -> tuple[dict[str, Any], Any, list[tuple[str, bytes]]]:
    """이미지는 원문 ledger를 비대하게 하지 않고 digest+별도 파일로 보존한다."""

    summary: dict[str, Any] = {
        key: value for key, value in result.items() if key != "content"
    }
    summary["content"] = []
    parsed: Any = None
    images: list[tuple[str, bytes]] = []
    for index, block in enumerate(result.get("content", [])):
        if not isinstance(block, dict):
            summary["content"].append(block)
            continue
        kind = block.get("type")
        if kind == "text":
            text = block.get("text", "")
            summary["content"].append({"type": "text", "text": text})
            if parsed is None and isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"text": text}
        elif kind == "image" and isinstance(block.get("data"), str):
            raw = base64.b64decode(block["data"], validate=True)
            mime = str(block.get("mimeType", "application/octet-stream"))
            summary["content"].append(
                {
                    "type": "image",
                    "mimeType": mime,
                    "decoded_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            images.append((mime, raw))
        else:
            summary["content"].append(block)
    return summary, parsed, images


def _net_name(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("name", "net_name", "net"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = value.get("name")
            if isinstance(nested, str) and nested:
                return nested
    return None


def pick_net_names(payload: Any, count: int = 2) -> list[str]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("nets", payload.get("networks", []))
    if isinstance(candidates, dict):
        candidates = [dict(value, name=key) if isinstance(value, dict) else {"name": key}
                      for key, value in candidates.items()]
    names: list[str] = []
    if isinstance(candidates, list):
        for item in candidates:
            name = item if isinstance(item, str) else _net_name(item)
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return names[:count]


def pick_pad_pair(
    pads_by_reference: dict[str, list[dict[str, Any]]]
) -> tuple[str, str, str, str, str] | None:
    observed: dict[str, list[tuple[str, str]]] = {}
    for reference, pads in pads_by_reference.items():
        for pad in pads:
            number = pad.get("number", pad.get("pad_number"))
            net = _net_name(pad)
            if isinstance(number, (str, int)) and net:
                observed.setdefault(net, []).append((reference, str(number)))
    for net, endpoints in observed.items():
        for first in endpoints:
            for second in endpoints:
                if first[0] != second[0]:
                    return net, first[0], first[1], second[0], second[1]
    return None


def coverage_report(
    inventory: dict[str, Any],
    ledger: list[dict[str, Any]],
    toolsets: Iterable[str] = TARGET_TOOLSETS,
) -> dict[str, Any]:
    expected = sorted(
        {
            tool
            for toolset in toolsets
            for tool in inventory.get("toolsets", {}).get(toolset, [])
        }
    )
    invoked = {row.get("tool") for row in ledger}
    by_tool: dict[str, list[str]] = {}
    for row in ledger:
        tool = row.get("tool")
        classification = row.get("classification")
        if isinstance(tool, str) and isinstance(classification, str):
            by_tool.setdefault(tool, []).append(classification)
    missing = sorted(set(expected) - invoked)
    passed = sorted(
        tool for tool in expected if "passed" in by_tool.get(tool, [])
    )
    limitations = sorted(
        tool
        for tool in expected
        if tool not in passed and "expected_limitation" in by_tool.get(tool, [])
    )
    failed = sorted(
        tool
        for tool in expected
        if tool not in passed
        and any(c in {"failed", "harness_error"} for c in by_tool.get(tool, []))
    )
    incomplete = sorted(set(expected) - set(passed) - set(limitations) - set(failed))
    return {
        "target_toolsets": list(toolsets),
        "expected_count": len(expected),
        "invoked_count": len(set(expected) & invoked),
        "passed_count": len(passed),
        "expected_limitation_count": len(limitations),
        "failed_count": len(failed),
        "missing": missing,
        "passed": passed,
        "expected_limitations": limitations,
        "failed": failed,
        "incomplete": incomplete,
        "complete_invocation": not missing,
        "all_normal_behaviors_passed": not missing and not limitations and not failed and not incomplete,
    }


class McpClient:
    def __init__(
        self,
        config: Path,
        env: dict[str, str],
        timeout: float,
        stderr_path: Path,
    ) -> None:
        self.timeout = timeout
        self.next_id = 1
        self.stderr_stream = stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(LAUNCHER), "--config", str(config)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_stream,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self.process.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], float]:
        request_id = self.next_id
        self.next_id += 1
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        started = time.monotonic()
        self.send(request)
        deadline = started + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise FunctionalError(f"Konnect 조기 종료: rc={self.process.returncode}")
            events = self.selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = self.process.stdout.readline()
            if not line:
                break
            response = json.loads(line)
            if response.get("id") == request_id:
                return response, time.monotonic() - started
        raise FunctionalError(f"MCP 응답 timeout: {method}")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.stderr_stream.close()


class FunctionalRun:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.output = args.output.resolve()
        self.requests = self.output / "responses"
        self.images = self.output / "images"
        self.exports = self.output / "exports"
        self.ledger: list[dict[str, Any]] = []
        self.sequence = 0
        self.client: McpClient | None = None
        self.inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        self.binary_sha256 = sha256_file(KONNECT_BINARY)
        self.source_commit = git_output("-C", "upstream/konnect", "rev-parse", "HEAD")
        self.source_worktree_sha256 = sha256_tree(
            [
                ROOT / "upstream/konnect/crates/konnect-core/src",
                ROOT / "upstream/konnect/crates/konnect/src",
                ROOT / "upstream/konnect/Cargo.toml",
                ROOT / "upstream/konnect/Cargo.lock",
            ]
        )
        self.toolset_by_tool = {
            tool: toolset
            for toolset, tools in self.inventory.get("toolsets", {}).items()
            for tool in tools
        }
        self.lane_env: dict[str, str] = {}
        self.project_dir = self.output / "fixture" / "variants"
        self.project = self.project_dir / "variants.kicad_pro"
        self.board = self.project_dir / "variants.kicad_pcb"
        self.schematic = self.project_dir / "variants.kicad_sch"
        self.tmpdir = Path(f"/tmp/konnect-pcb-tests-{os.getpid()}")
        self.socket_path = self.tmpdir / "kicad" / "api.sock"
        self.config = self.output / "konnect.toml"
        self.state_dir = self.output / "konnect-state"
        self.gui_pid: int | None = None
        self.spec_dir = self.output / "fixture" / "specctra_two_resistors_locked"
        self.spec_project = self.spec_dir / "specctra_two_resistors_locked.kicad_pro"
        self.spec_board = self.spec_dir / "specctra_two_resistors_locked.kicad_pcb"
        self.spec_schematic = self.spec_dir / "specctra_two_resistors_locked.kicad_sch"

    def prepare_output(self) -> None:
        source_files = list((ROOT / "upstream/konnect/crates/konnect-core/src").rglob("*.rs"))
        source_files.extend((ROOT / "upstream/konnect/crates/konnect/src").rglob("*.rs"))
        newest_source_mtime = max(path.stat().st_mtime_ns for path in source_files)
        binary_mtime = KONNECT_BINARY.stat().st_mtime_ns
        if binary_mtime < newest_source_mtime and not self.args.allow_stale_binary:
            raise FunctionalError(
                "release binary가 현재 Rust source보다 오래되었습니다. root 합성 build 뒤 재실행하거나 "
                "의도된 baseline에만 --allow-stale-binary를 명시하세요."
            )
        assert_safe_run_directory(ARTIFACT_ROOT, self.output)
        if self.output.exists():
            if not self.args.fresh:
                raise FunctionalError(f"출력 디렉터리가 이미 있습니다: {self.output}")
            shutil.rmtree(self.output)
        for path in (
            self.requests,
            self.images,
            self.exports,
            self.output / "gui-home",
            self.output / "gui-config",
            self.state_dir,
            self.output / "runtime-home",
        ):
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.chmod(0o700)
        if self.tmpdir.exists() or self.tmpdir.is_symlink():
            raise FunctionalError(f"전용 TMPDIR가 이미 존재합니다: {self.tmpdir}")
        self.tmpdir.mkdir(mode=0o700)
        self.tmpdir.chmod(0o700)
        if len(os.fsencode(str(self.socket_path))) >= 108:
            raise FunctionalError(f"Unix socket 경로가 sun_path 한계를 넘습니다: {self.socket_path}")
        if GUI_CONFIG_SOURCE.is_dir():
            shutil.copytree(
                GUI_CONFIG_SOURCE,
                self.output / "gui-config",
                dirs_exist_ok=True,
                copy_function=shutil.copy2,
            )
        self.project_dir.mkdir(parents=True, exist_ok=True)
        for suffix in ("kicad_pro", "kicad_sch", "kicad_pcb"):
            source = VARIANTS_SOURCE / f"variants.{suffix}"
            destination = self.project_dir / f"variants.{suffix}"
            shutil.copy2(source, destination)
            if sha256_file(source) != sha256_file(destination):
                raise FunctionalError(f"fixture 복제 digest 불일치: {source}")
        for name in (
            "pic_sockets.kicad_sch",
            "pic_programmer.kicad_sym",
            "fp-lib-table",
            "sym-lib-table",
        ):
            source = VARIANTS_SOURCE / name
            destination = self.project_dir / name
            shutil.copy2(source, destination)
            if sha256_file(source) != sha256_file(destination):
                raise FunctionalError(f"hierarchical fixture 복제 digest 불일치: {source}")
        logo = self.output / "fixture" / "konnect-logo.svg"
        logo.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10" '
            'viewBox="0 0 20 10"><path d="M1 5h18M10 1v8" '
            'stroke="black" fill="none"/></svg>\n',
            encoding="utf-8",
        )
        self.config.write_text(
            "\n".join(
                [
                    'transport = "stdio"',
                    'kicad_cli = "/usr/local/bin/kicad-cli"',
                    'kicad_binary = "/usr/local/bin/kicad"',
                    f'project_dir = "{self.output / "fixture"}"',
                    f'ipc_address = "ipc://{self.socket_path}"',
                    'http_address = "127.0.0.1:0"',
                    'log_level = "info"',
                    "eager_toolsets = true",
                    "auto_load_toolsets = false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _instance(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ACUW_INSTANCE_OWNER"] = self.args.owner
        return subprocess.run(
            ["bash", str(ACUW_INSTANCE), *arguments],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=check,
            timeout=60,
        )

    def open_lane(self) -> None:
        opened = self._instance("open", self.args.lane)
        (self.output / "lane-open.log").write_text(
            opened.stdout + opened.stderr, encoding="utf-8"
        )
        env_result = self._instance("env", self.args.lane)
        for line in env_result.stdout.splitlines():
            if not line.startswith("export "):
                continue
            key, raw = line[len("export ") :].split("=", 1)
            values = shlex.split(raw)
            self.lane_env[key] = values[0] if values else ""
        display = self.lane_env.get("ACUW_DISPLAY")
        if not display or display == ":171":
            raise FunctionalError(f"전용 lane DISPLAY 판정 실패: {display}")

    def server_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.lane_env)
        env.update(
            {
                "DISPLAY": self.lane_env["ACUW_DISPLAY"],
                "TMPDIR": str(self.tmpdir),
                "KICAD_API_SOCKET": f"ipc://{self.socket_path}",
                "KONNECT_STATE_DIR": str(self.state_dir),
                "KONNECT_RUNTIME_HOME": str(self.output / "runtime-home"),
            }
        )
        return env

    def start_client(self, label: str) -> None:
        if self.client is not None:
            self.client.close()
        self.client = McpClient(
            self.config,
            self.server_env(),
            self.args.timeout,
            self.output / f"server-{label}.stderr.log",
        )
        response, elapsed = self.client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-pcb-functional", "version": "1.0.0"},
            },
        )
        if "error" in response:
            raise FunctionalError(f"MCP initialize 실패: {response['error']}")
        self.client.send(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        (self.output / f"initialize-{label}.json").write_text(
            json.dumps(
                {"response": response, "elapsed_seconds": elapsed},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        note: str,
        postcondition: dict[str, Any] | list[dict[str, Any]] | None = None,
        expected_limitation: str | None = None,
    ) -> Any:
        if self.client is None:
            raise FunctionalError("MCP client가 시작되지 않았습니다")
        self.sequence += 1
        request = {"name": tool, "arguments": arguments}
        mutating = is_mutating_call(tool, arguments)
        classification = "failed"
        parsed: Any = None
        started_at_unix_ms = int(time.time() * 1000)
        fixture_before = self.fixture_sha256()
        try:
            response, elapsed = self.client.request("tools/call", request)
            if "error" in response:
                result_summary = {"jsonrpc_error": response["error"]}
                is_error = True
                images: list[tuple[str, bytes]] = []
            else:
                result = response.get("result", {})
                result_summary, parsed, images = summarize_tool_result(result)
                is_error = bool(result.get("isError"))
            if isinstance(postcondition, dict):
                postconditions = [
                    {
                        "name": str(postcondition.get("name", "caller_postcondition")),
                        "expected": postcondition.get("expected", True),
                        "actual": postcondition.get(
                            "actual", postcondition.get("passed", False)
                        ),
                        "passed": postcondition.get("passed") is True,
                        "independent": postcondition.get("independent", False),
                        **{
                            key: value
                            for key, value in postcondition.items()
                            if key
                            not in {"name", "expected", "actual", "passed", "independent"}
                        },
                    }
                ]
            elif isinstance(postcondition, list):
                postconditions = postcondition
            else:
                postconditions = []
            if not is_error and not postconditions:
                postconditions = [
                    {
                        "name": "response_decoded",
                        "expected": True,
                        "actual": parsed is not None or bool(result_summary.get("content")),
                        "passed": parsed is not None or bool(result_summary.get("content")),
                        "independent": not mutating,
                    }
                ]
            independent_pass = any(
                item.get("passed") is True and item.get("independent") is True
                for item in postconditions
            )
            all_postconditions_pass = bool(postconditions) and all(
                item.get("passed") is True for item in postconditions
            )
            if is_error and expected_limitation:
                classification = "expected_limitation"
            elif is_error:
                classification = "failed"
            elif not all_postconditions_pass:
                classification = "failed"
            elif mutating and not independent_pass:
                classification = "incomplete_evidence"
            else:
                classification = "passed"
            image_files = []
            for index, (mime, raw) in enumerate(images, 1):
                suffix = ".png" if mime == "image/png" else ".bin"
                path = self.images / f"{self.sequence:04d}-{tool}-{index}{suffix}"
                path.write_bytes(raw)
                image_files.append(str(path))
            body_error = parsed.get("error") if isinstance(parsed, dict) else None
            error_kind = body_error.get("kind") if isinstance(body_error, dict) else None
            response_source = parsed.get("source") if isinstance(parsed, dict) else None
            caveats: list[str] = []
            if mutating and not independent_pass and not is_error:
                caveats.append("독립 readback이 없어 mutation 정상 판정을 보류함")
            if expected_limitation:
                caveats.append(expected_limitation)
            record = {
                "schema_version": 1,
                "seq": self.sequence,
                "lane": self.args.lane,
                "toolset": self.toolset_by_tool.get(tool, "meta"),
                "tool": tool,
                "case_id": f"pcb-functional-{self.sequence:04d}-{tool}",
                "behavior": "mutation" if mutating else "observation",
                "request": request,
                "response": {"result": result_summary},
                "body": parsed,
                "is_error": is_error,
                "error_kind": error_kind,
                "started_at_unix_ms": started_at_unix_ms,
                "elapsed_ms": round(elapsed * 1000, 3),
                "process_rc": self.client.process.poll(),
                "tool": tool,
                "classification": classification,
                "expected_limitation": expected_limitation,
                "note": note,
                "postconditions": postconditions,
                "image_files": image_files,
                "binary_sha256": self.binary_sha256,
                "source_commit": self.source_commit,
                "source_worktree_sha256": self.source_worktree_sha256,
                "fixture_before_sha256": fixture_before,
                "fixture_after_sha256": self.fixture_sha256(),
                "source_authority": response_source or self.default_source_authority(tool),
                "external_conditions": {
                    "display": self.lane_env.get("ACUW_DISPLAY"),
                    "ipc_address": f"ipc://{self.socket_path}",
                    "socket_is_socket": self.socket_path.is_socket(),
                    "board": str(self.board),
                    "kicad_cli": "/usr/local/bin/kicad-cli",
                },
                "verdict": (
                    "PASS"
                    if classification == "passed"
                    else "EXPECTED_LIMITATION"
                    if classification == "expected_limitation"
                    else "INCOMPLETE"
                    if classification == "incomplete_evidence"
                    else "FAIL"
                ),
                "caveats": caveats,
            }
        except Exception as error:
            record = {
                "schema_version": 1,
                "seq": self.sequence,
                "lane": self.args.lane,
                "toolset": self.toolset_by_tool.get(tool, "meta"),
                "tool": tool,
                "case_id": f"pcb-functional-{self.sequence:04d}-{tool}",
                "behavior": "mutation" if mutating else "observation",
                "request": request,
                "response": None,
                "body": None,
                "is_error": True,
                "error_kind": "harness_error",
                "started_at_unix_ms": started_at_unix_ms,
                "elapsed_ms": None,
                "process_rc": self.client.process.poll(),
                "classification": "harness_error",
                "expected_limitation": expected_limitation,
                "note": note,
                "postconditions": [],
                "harness_error": f"{type(error).__name__}: {error}",
                "binary_sha256": self.binary_sha256,
                "source_commit": self.source_commit,
                "source_worktree_sha256": self.source_worktree_sha256,
                "fixture_before_sha256": fixture_before,
                "fixture_after_sha256": self.fixture_sha256(),
                "source_authority": self.default_source_authority(tool),
                "external_conditions": {
                    "display": self.lane_env.get("ACUW_DISPLAY"),
                    "ipc_address": f"ipc://{self.socket_path}",
                    "socket_is_socket": self.socket_path.is_socket(),
                    "board": str(self.board),
                },
                "verdict": "HARNESS_ERROR",
                "caveats": [f"{type(error).__name__}: {error}"],
            }
        self.ledger.append(record)
        response_path = self.requests / f"{self.sequence:04d}-{tool}.json"
        response_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.write_ledger()
        return parsed

    def fixture_sha256(self) -> dict[str, str | None]:
        return {
            "project": sha256_file(self.project) if self.project.is_file() else None,
            "schematic": sha256_file(self.schematic) if self.schematic.is_file() else None,
            "board": sha256_file(self.board) if self.board.is_file() else None,
        }

    def default_source_authority(self, tool: str) -> str:
        if tool in {"run_drc", "get_drc_violations", "snapshot_project"} or tool.startswith("export_"):
            return "kicad-cli"
        if tool in {
            "check_kicad_ui", "open_project", "save_project", "set_active_layer",
            "get_editor_state", "get_editor_selection", "mutate_editor_selection",
            "resolve_navigation_target", "resolve_cross_probe_target",
        }:
            return "live_ipc"
        if tool in MUTATING_TOOLS:
            return "live_ipc_or_saved_file_as_handler_reports"
        return "handler_observation"

    def attach_proof(self, tool: str, postconditions: list[dict[str, Any]]) -> None:
        """가장 최근 해당 tool 호출에 뒤따른 독립 증거를 결속한다."""
        row = next((item for item in reversed(self.ledger) if item.get("tool") == tool), None)
        if row is None:
            raise FunctionalError(f"proof를 결속할 호출이 없습니다: {tool}")
        row["postconditions"] = postconditions
        if row.get("is_error") is False and postconditions and all(
            item.get("passed") is True for item in postconditions
        ) and any(item.get("independent") is True for item in postconditions):
            row["classification"] = "passed"
            row["verdict"] = "PASS"
            row["caveats"] = [
                caveat
                for caveat in row.get("caveats", [])
                if "독립 readback" not in caveat
            ]
        else:
            row["classification"] = "failed"
            row["verdict"] = "FAIL"
        self.write_ledger()

    def write_ledger(self) -> None:
        path = self.output / "ledger.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for row in self.ledger:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def load_toolsets(self) -> None:
        for name in TARGET_TOOLSETS:
            self.call("load_toolset", {"name": name}, note=f"{name} 도구셋 로드")

    def launch_gui(self) -> None:
        gui_home = self.output / "gui-home"
        gui_config = self.output / "gui-config"
        command = [
            "run",
            self.args.lane,
            "--",
            "run-in-workspace.sh",
            "--json",
            "--env-mode",
            "host",
            "--dbus-mode",
            "private",
            "--cwd",
            str(self.project_dir),
            "--name",
            f"kicad-pcb-functional-{self.board.stem}",
            "--",
            "env",
            f"HOME={gui_home}",
            f"XDG_CONFIG_HOME={gui_config}",
            f"TMPDIR={self.tmpdir}",
            "LIBGL_ALWAYS_SOFTWARE=1",
            "GALLIUM_DRIVER=llvmpipe",
            "/usr/local/bin/pcbnew",
            str(self.board),
        ]
        launched = self._instance(*command, check=False)
        (self.output / f"gui-launch-{self.board.stem}.stdout.log").write_text(launched.stdout, encoding="utf-8")
        (self.output / f"gui-launch-{self.board.stem}.stderr.log").write_text(launched.stderr, encoding="utf-8")
        if launched.returncode != 0:
            raise FunctionalError(f"KiCad GUI launch 실패: rc={launched.returncode}")
        match = re.search(r'"pid":(\d+)', launched.stdout)
        if match:
            self.gui_pid = int(match.group(1))
        deadline = time.monotonic() + 120
        window_ready = False
        while time.monotonic() < deadline:
            window = subprocess.run(
                [
                    "xdotool", "search", "--onlyvisible", "--name", self.board.stem,
                ],
                text=True,
                capture_output=True,
                timeout=5,
                env={**os.environ, "DISPLAY": self.lane_env["ACUW_DISPLAY"]},
            )
            window_ready = window.returncode == 0 and bool(window.stdout.strip())
            if self.socket_path.is_socket() and window_ready:
                break
            time.sleep(0.25)
        if not self.socket_path.is_socket() or not window_ready:
            raise FunctionalError(
                f"전용 KiCad readiness 불충분: socket={self.socket_path.is_socket()} "
                f"window={window_ready}"
            )
        self.verify_gui_identity()
        capture = self._instance(
            "run",
            self.args.lane,
            "--",
            ACUW_CAPTURE,
            str(self.output / f"screen-before-{self.board.stem}.png"),
            check=False,
        )
        (self.output / "capture-before.log").write_text(
            capture.stdout + capture.stderr, encoding="utf-8"
        )

    def verify_gui_identity(self) -> None:
        display = self.lane_env["ACUW_DISPLAY"]
        tmpdir = str(self.tmpdir)
        candidates: list[dict[str, Any]] = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                environ = (proc / "environ").read_bytes().split(b"\0")
                values = {
                    item.split(b"=", 1)[0].decode(errors="replace"): item.split(b"=", 1)[1].decode(errors="replace")
                    for item in environ
                    if b"=" in item
                }
                cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except (OSError, IndexError):
                continue
            if values.get("DISPLAY") != display or values.get("TMPDIR") != tmpdir:
                continue
            if "pcbnew" not in cmdline and "kicad" not in cmdline.lower():
                continue
            candidates.append(
                {
                    "pid": int(proc.name),
                    "display": values.get("DISPLAY"),
                    "tmpdir": values.get("TMPDIR"),
                    "xdg_config_home": values.get("XDG_CONFIG_HOME"),
                    "cmdline": cmdline,
                    "board_in_argv": str(self.board) in cmdline,
                }
            )
        if not candidates or not any(item["board_in_argv"] for item in candidates):
            raise FunctionalError("실제 GUI process의 DISPLAY/TMPDIR/board argv 결속을 확인하지 못했습니다")
        title = subprocess.run(
            ["xdotool", "search", "--name", self.board.stem, "getwindowname", "%@"],
            text=True,
            capture_output=True,
            timeout=10,
            env={**os.environ, "DISPLAY": display},
        )
        identity = {
            "display": display,
            "socket": str(self.socket_path),
            "socket_is_socket": self.socket_path.is_socket(),
            "processes": candidates,
            "window_query_rc": title.returncode,
            "window_titles": title.stdout.splitlines(),
        }
        (self.output / f"gui-identity-{self.board.stem}.json").write_text(
            json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if title.returncode != 0 or not title.stdout.strip():
            raise FunctionalError("전용 GUI 창 제목을 독립 대조하지 못했습니다")

    def stop_gui(self) -> None:
        def process_running(pid: int) -> bool:
            try:
                fields = (Path("/proc") / str(pid) / "stat").read_text().split()
                return len(fields) > 2 and fields[2] != "Z"
            except (OSError, IndexError):
                return False

        owned: list[int] = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                environ = (proc / "environ").read_bytes().split(b"\0")
                values = {
                    item.split(b"=", 1)[0].decode(errors="replace"): item.split(b"=", 1)[1].decode(errors="replace")
                    for item in environ if b"=" in item
                }
                cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except (OSError, IndexError):
                continue
            if (
                values.get("TMPDIR") == str(self.tmpdir)
                and values.get("DISPLAY") == self.lane_env.get("ACUW_DISPLAY")
            ):
                owned.append(int(proc.name))
        pgids = set()
        if self.gui_pid is not None:
            pgids.add(self.gui_pid)
        for pid in owned:
            try:
                pgids.add(os.getpgid(pid))
            except ProcessLookupError:
                pass
        current_pgid = os.getpgrp()
        for pgid in pgids:
            if pgid == current_pgid:
                continue
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for pid in owned:
            try:
                if os.getpgid(pid) == current_pgid:
                    os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            alive = []
            for pid in owned:
                if process_running(pid):
                    alive.append(pid)
            if not alive:
                if self.socket_path.exists() or self.socket_path.is_symlink():
                    self.socket_path.unlink()
                self.gui_pid = None
                return
            time.sleep(0.2)
        for pid in alive:
            try:
                pgid = os.getpgid(pid)
                if pgid == current_pgid:
                    os.kill(pid, signal.SIGKILL)
                else:
                    os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        kill_deadline = time.monotonic() + 5
        while time.monotonic() < kill_deadline:
            remaining = []
            for pid in alive:
                if process_running(pid):
                    remaining.append(pid)
            if not remaining:
                if self.socket_path.exists() or self.socket_path.is_symlink():
                    self.socket_path.unlink()
                self.gui_pid = None
                return
            time.sleep(0.1)
        raise FunctionalError(f"전용 GUI process가 SIGKILL 뒤에도 종료되지 않았습니다: {remaining}")

    def pre_gui_calls(self) -> None:
        self.start_client("pre-gui")
        self.load_toolsets()
        created_dir = self.output / "fixture" / "created"
        created = self.call(
            "create_project",
            {"path": str(created_dir), "name": "created"},
            note="MCP 자체 project 생성",
        )
        created_ok = all((created_dir / f"created.{suffix}").is_file() for suffix in ("kicad_pro", "kicad_sch", "kicad_pcb"))
        if self.ledger and self.ledger[-1]["tool"] == "create_project":
            self.ledger[-1]["postconditions"] = [{
                "name": "project_files_created",
                "expected": True,
                "actual": created_ok,
                "passed": created_ok,
                "independent": True,
            }]
            self.ledger[-1]["classification"] = "passed" if created_ok else "failed"
            self.ledger[-1]["verdict"] = "PASS" if created_ok else "FAIL"
            self.write_ledger()
        renamed_project = created_dir / "created.kicad_pro"
        self.call(
            "rename_project",
            {"project": str(renamed_project), "new_name": "renamed", "dry_run": True},
            note="rename dry-run",
        )
        self.call(
            "rename_project",
            {"project": str(renamed_project), "new_name": "renamed", "dry_run": False},
            note="MCP rename apply와 파일 집합 readback",
        )
        renamed_ok = all(
            (created_dir / f"renamed.{suffix}").is_file()
            for suffix in ("kicad_pro", "kicad_sch", "kicad_pcb")
        )
        self.attach_proof("rename_project", [{
            "name": "renamed_file_set_exists",
            "expected": True,
            "actual": renamed_ok,
            "passed": renamed_ok,
            "independent": True,
            "project": str(created_dir / "renamed.kicad_pro"),
        }])
        self.call(
            "create_project",
            {"path": str(self.spec_dir), "name": "specctra_two_resistors_locked"},
            note="Specctra 정상행동용 별도 project 생성",
        )
        shutil.copy2(SPECCTRA_BOARD_SOURCE, self.spec_board)
        spec_copy_ok = sha256_file(SPECCTRA_BOARD_SOURCE) == sha256_file(self.spec_board)
        self.attach_proof("create_project", [{
            "name": "specctra_project_created_and_official_board_copied_exactly",
            "expected": True,
            "actual": spec_copy_ok,
            "passed": spec_copy_ok and self.spec_project.is_file() and self.spec_schematic.is_file(),
            "independent": True,
            "source_board_sha256": sha256_file(SPECCTRA_BOARD_SOURCE),
            "copied_board_sha256": sha256_file(self.spec_board),
        }])
        self.call("get_project_info", {"path": str(self.project)}, note="복제 fixture project metadata")
        pre_netlist = self.exports / "pre-gui.net"
        self.call(
            "export_netlist",
            {"board": str(self.board), "output": str(pre_netlist), "format": "kicad"},
            note="보호 파일을 직접 파싱하지 않고 netlist export",
        )
        net_names: list[str] = []
        if pre_netlist.is_file():
            source = pre_netlist.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r'\(name\s+"([^"]+)"\)', source):
                if match.group(1) not in net_names:
                    net_names.append(match.group(1))
        self.call(
            "create_netclass",
            {"board": str(self.board), "name": "KonnectFunctional", "trace_width": 0.3, "clearance": 0.22},
            note="GUI 비실행 상태 project netclass 쓰기",
        )
        self.call(
            "get_netclasses",
            {"board": str(self.board), "board_source": "saved"},
            note="netclass 저장본 readback",
        )
        netclasses_body = self.ledger[-1].get("body")
        netclass_text = json.dumps(netclasses_body, ensure_ascii=False)
        self.attach_proof("create_netclass", [{
            "name": "netclass_readback_contains_name",
            "expected": "KonnectFunctional",
            "actual": "KonnectFunctional" if "KonnectFunctional" in netclass_text else None,
            "passed": "KonnectFunctional" in netclass_text,
            "independent": True,
        }])
        self.call(
            "assign_net_to_class",
            {"board": str(self.board), "net_name": net_names[0] if net_names else "GND", "netclass": "KonnectFunctional"},
            note="GUI 비실행 상태 netclass pattern 쓰기",
            expected_limitation=None if net_names else "export된 named net이 없어 입력 fixture 한계",
        )
        self.call(
            "set_design_rules",
            {"board": str(self.board), "min_clearance": 0.2, "min_trace_width": 0.2, "min_via_size": 0.7, "min_via_drill": 0.35},
            note="GUI 비실행 상태 design rules 설정",
        )
        self.call(
            "set_layer_constraints",
            {"board": str(self.board), "layer": "F.Cu", "min_clearance": 0.2, "min_trace_width": 0.2},
            note="layer constraints 설정",
        )
        self.call(
            "set_predefined_sizes",
            {"board": str(self.board), "track_widths": [0.2, 0.3, 0.5], "via_dimensions": [{"diameter": 0.7, "drill": 0.35}]},
            note="router predefined size 설정",
        )
        sizes = self.call("get_predefined_sizes", {"board": str(self.board)}, note="predefined size readback")
        sizes_text = json.dumps(sizes, ensure_ascii=False)
        self.attach_proof("set_predefined_sizes", [{
            "name": "predefined_sizes_readback",
            "expected": [0.2, 0.3, 0.5],
            "actual": sizes,
            "passed": all(str(value) in sizes_text for value in (0.2, 0.3, 0.5)),
            "independent": True,
        }])
        rules = self.call("get_design_rules", {"board": str(self.board)}, note="design rules readback")
        rules_text = json.dumps(rules, ensure_ascii=False)
        self.attach_proof("set_design_rules", [{
            "name": "design_rules_readback",
            "expected": {"min_clearance": 0.2, "min_trace_width": 0.2},
            "actual": rules,
            "passed": "0.2" in rules_text,
            "independent": True,
        }])
        rules_file = self.board.with_suffix(".kicad_dru")
        self.attach_proof("set_layer_constraints", [{
            "name": "rules_file_created",
            "expected": True,
            "actual": rules_file.is_file(),
            "passed": rules_file.is_file(),
            "independent": True,
            "sha256": sha256_file(rules_file) if rules_file.is_file() else None,
        }])
        layer_board = created_dir / "renamed.kicad_pcb"
        self.call(
            "add_layer",
            {"board": str(layer_board), "layer_name": "In1.Cu", "layer_type": "signal"},
            note="별도 disposable fixture에서 inner copper layer 추가",
        )
        layers_after = self.call(
            "get_layer_list",
            {"board": str(layer_board), "board_source": "saved"},
            note="add_layer 저장본 readback",
        )
        layers_text = json.dumps(layers_after, ensure_ascii=False)
        layer_cli = subprocess.run(
            [
                "/usr/local/bin/kicad-cli", "pcb", "drc", "--exit-code-violations",
                "--output", str(self.exports / "add-layer-validation.rpt"), str(layer_board),
            ],
            text=True,
            capture_output=True,
            timeout=60,
        )
        layer_valid = layer_cli.returncode in {0, 5}
        self.attach_proof("add_layer", [{
            "name": "saved_layer_readback_and_kicad_cli_parse",
            "expected": {"layer": "In1.Cu", "kicad_cli_parse": True},
            "actual": {
                "layer_observed": "In1.Cu" in layers_text,
                "kicad_cli_rc": layer_cli.returncode,
                "stderr": layer_cli.stderr[-2000:],
            },
            "passed": "In1.Cu" in layers_text and layer_valid,
            "independent": True,
        }])
        self.call(
            "add_net",
            {"board": str(self.board), "net_name": "KONNECT_TEST_NET"},
            note="board 세대별 add_net 정상 또는 명시적 지원 한계 확인",
        )
        netclasses_after = self.call(
            "get_netclasses",
            {"board": str(self.board), "board_source": "saved"},
            note="netclass assignment와 add_net 저장본 재조회",
        )
        after_text = json.dumps(netclasses_after, ensure_ascii=False)
        self.attach_proof("assign_net_to_class", [{
            "name": "assigned_pattern_readback",
            "expected": {"net": net_names[0] if net_names else "GND", "class": "KonnectFunctional"},
            "actual": netclasses_after,
            "passed": "KonnectFunctional" in after_text and (net_names[0] if net_names else "GND") in after_text,
            "independent": True,
        }])
        add_net_row = next(item for item in reversed(self.ledger) if item.get("tool") == "add_net")
        if add_net_row.get("is_error") is False:
            self.attach_proof("add_net", [{
                "name": "saved_board_net_readback",
                "expected": "KONNECT_TEST_NET",
                "actual": "KONNECT_TEST_NET" if "KONNECT_TEST_NET" in after_text else None,
                "passed": "KONNECT_TEST_NET" in after_text,
                "independent": True,
            }])
        else:
            add_net_row["classification"] = "expected_limitation"
            add_net_row["verdict"] = "EXPECTED_LIMITATION"
            add_net_row["caveats"] = ["board 세대가 top-level net table을 지원하지 않음"]
            self.write_ledger()
        # Typed IPC가 표현할 수 없는 stock point/pad metadata는 guard를
        # 완화하지 않고 closed-board raw library path로 먼저 배치한다.
        for footprint, reference, x, y, note in [
            (
                "TerminalBlock_Philmore:TerminalBlock_Philmore_TB132_1x02_P5.00mm_Horizontal",
                "KPOLY1", 190, 90, "polygon graphic fixture closed-board placement",
            ),
            ("Package_DIP:DIP-8_W7.62mm", "KU1", 150, 90, "point-bearing DIP closed-board placement"),
            (
                "Package_BGA:BGA-100_11.0x11.0mm_Layout10x10_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD",
                "KUBGA1", 170, 90, "pad-property BGA closed-board placement",
            ),
        ]:
            self.call(
                "place_component",
                {"board": str(self.board), "footprint": footprint, "reference": reference, "x": x, "y": y},
                note=note,
            )
        closed_drc = subprocess.run(
            ["/usr/local/bin/kicad-cli", "pcb", "drc", "--output", str(self.exports / "closed-placement.drc"), str(self.board)],
            text=True,
            capture_output=True,
            timeout=120,
        )
        if closed_drc.returncode != 0:
            raise FunctionalError(f"closed stock placement 뒤 KiCad CLI parse 실패: {closed_drc.stderr[-2000:]}")

        routing_dir = self.output / "fixture" / "copy-routing"
        routing_dir.mkdir(parents=True, exist_ok=True)
        routing_board = routing_dir / "routing.kicad_pcb"
        shutil.copy2(ROUTING_BOARD_SOURCE, routing_board)
        routing_before = sha256_file(routing_board)
        copied = self.call(
            "copy_routing_pattern",
            {
                "board": str(routing_board),
                "src_x1": 70.0, "src_y1": 70.0, "src_x2": 130.0, "src_y2": 90.0,
                "dest_x": 70.0, "dest_y": 100.0, "net_map": {},
            },
            note="closed KiCad10 tab-indented routing fixture copy",
        )
        routing_after = sha256_file(routing_board)
        routing_cli = subprocess.run(
            ["/usr/local/bin/kicad-cli", "pcb", "drc", "--output", str(self.exports / "copy-routing.drc"), str(routing_board)],
            text=True,
            capture_output=True,
            timeout=120,
        )
        copied_count = (copied or {}).get("copied", 0) if isinstance(copied, dict) else 0
        self.attach_proof("copy_routing_pattern", [{
            "name": "positive_copy_and_native_cli_load",
            "expected": {"copied": ">0", "cli_rc": 0},
            "actual": {"copied": copied_count, "cli_rc": routing_cli.returncode},
            "passed": copied_count > 0 and routing_before != routing_after and routing_cli.returncode == 0,
            "independent": True,
            "before_sha256": routing_before,
            "after_sha256": routing_after,
        }])
        assert self.client is not None
        self.client.close()
        self.client = None

    def _post_file(self, path: Path) -> dict[str, Any]:
        return {
            "passed": path.is_file() and path.stat().st_size > 0,
            "path": str(path),
            "bytes": path.stat().st_size if path.is_file() else 0,
            "sha256": sha256_file(path) if path.is_file() else None,
        }

    def live_calls(self) -> None:
        self.start_client("live")
        self.load_toolsets()
        opened = self.call("open_project", {"path": str(self.project)}, note="요청 board가 전용 IPC에서 열린 상태 결속")
        self.call("check_kicad_ui", {"timeout_seconds": 5}, note="전용 IPC health")
        self.call("save_project", {}, note="live board 저장")
        self.call("get_project_info", {"path": str(self.project)}, note="saved project metadata")
        self.call(
            "open_schematic_viewer",
            {"schematic": str(self.schematic)},
            note="별도 schematic viewer 실행 표면 확인",
            expected_limitation="release bundle에 schematic-viewer binary가 없으면 명시적 지원 한계",
        )
        board_info = self.call("get_board_info", {"board": str(self.board)}, note="live board inventory")
        self.call("get_layer_list", {"board": str(self.board), "board_source": "live"}, note="live layer source 강제")
        self.call("get_board_extents", {"board": str(self.board)}, note="live board geometry extents")
        self.call("get_board_stackup", {"board": str(self.board)}, note="saved stackup readback")
        components = self.call("get_component_list", {"board": str(self.board)}, note="live component list")
        refs = [item.get("reference") for item in (components or {}).get("components", []) if isinstance(item, dict) and item.get("reference")]
        for reference in ("KPOLY1", "KU1", "KUBGA1"):
            row = next(
                (
                    item for item in reversed(self.ledger)
                    if item.get("tool") == "place_component"
                    and item.get("request", {}).get("arguments", {}).get("reference") == reference
                ),
                None,
            )
            if row is not None:
                observed = reference in refs
                row["postconditions"] = [{
                    "name": "closed_placement_live_reopen_readback",
                    "expected": reference,
                    "actual": reference if observed else None,
                    "passed": observed,
                    "independent": True,
                }]
                row["classification"] = "passed" if observed else "failed"
                row["verdict"] = "PASS" if observed else "FAIL"
                row["caveats"] = [] if observed else ["closed placement가 live reopen inventory에 없음"]
        self.write_ledger()
        base_ref = refs[0] if refs else "R1"
        self.call("find_component", {"board": str(self.board), "reference": base_ref}, note="component identity lookup")
        self.call("get_component_pads", {"board": str(self.board), "reference": base_ref}, note="component pads readback")
        self.call("list_board_footprint_graphics", {"board": str(self.board), "reference": base_ref}, note="footprint graphic inventory")

        self.call(
            "place_component",
            {"board": str(self.board), "footprint": "Resistor_SMD:R_0603_1608Metric", "reference": "KF1", "x": 120, "y": 80, "rotation": 0},
            note="live IPC footprint 생성",
        )
        placed = self.call("find_component", {"board": str(self.board), "reference": "KF1"}, note="place_component readback")
        self.attach_proof("place_component", [{
            "name": "placed_component_readback",
            "expected": {"reference": "KF1", "x": 120, "y": 80},
            "actual": placed,
            "passed": isinstance(placed, dict) and placed.get("reference") == "KF1" and abs(float(placed.get("x", 0)) - 120) < 0.001,
            "independent": True,
        }])
        self.call("get_component_pads", {"board": str(self.board), "reference": "KF1"}, note="placed footprint pads")
        self.call("get_pad_position", {"board": str(self.board), "reference": "KF1", "pad_number": "1"}, note="placed pad geometry readback")
        self.call(
            "place_component",
            {"board": str(self.board), "footprint": "Symbol:CE-Logo_11.2x8mm_SilkScreen", "reference": "KLOGO2", "x": 205, "y": 90},
            note="stock unlocked-property typed mapping live placement",
        )
        logo = self.call("find_component", {"board": str(self.board), "reference": "KLOGO2"}, note="stock logo typed placement readback")
        self.attach_proof("place_component", [{
            "name": "stock_unlocked_property_live_readback", "expected": "KLOGO2", "actual": logo,
            "passed": isinstance(logo, dict) and logo.get("reference") == "KLOGO2", "independent": True,
        }])
        self.call(
            "duplicate_component",
            {"board": str(self.board), "reference": "KF1", "new_reference": "KF2", "x": 126, "y": 82},
            note="front-side footprint duplicate",
        )
        duplicate = self.call("find_component", {"board": str(self.board), "reference": "KF2"}, note="duplicate_component readback")
        self.attach_proof("duplicate_component", [{
            "name": "duplicate_reference_readback",
            "expected": "KF2",
            "actual": duplicate,
            "passed": isinstance(duplicate, dict) and duplicate.get("reference") == "KF2",
            "independent": True,
        }])
        self.call("delete_component", {"board": str(self.board), "reference": "KF2"}, note="duplicate 삭제")
        deleted_probe = self.call(
            "find_component",
            {"board": str(self.board), "reference": "KF2"},
            note="delete_component absence readback",
            expected_limitation="삭제 후 not-found는 기대 postcondition",
        )
        deleted_absent = "not found" in json.dumps(deleted_probe, ensure_ascii=False).lower()
        self.attach_proof("delete_component", [{
            "name": "deleted_component_absent",
            "expected": "not_found",
            "actual": deleted_probe,
            "passed": deleted_absent,
            "independent": True,
        }])
        self.call("move_component", {"board": str(self.board), "reference": "KF1", "x": 122, "y": 82}, note="live move")
        moved = self.call("find_component", {"board": str(self.board), "reference": "KF1"}, note="move_component geometry readback")
        self.attach_proof("move_component", [{
            "name": "moved_coordinates_readback", "expected": [122, 82], "actual": moved,
            "passed": isinstance(moved, dict) and abs(float(moved.get("x", 0)) - 122) < 0.001 and abs(float(moved.get("y", 0)) - 82) < 0.001,
            "independent": True,
        }])
        self.call("rotate_component", {"board": str(self.board), "reference": "KF1", "rotation": 90}, note="live rotate")
        rotated = self.call("find_component", {"board": str(self.board), "reference": "KF1"}, note="rotate_component readback")
        self.attach_proof("rotate_component", [{
            "name": "rotation_readback", "expected": 90, "actual": (rotated or {}).get("rotation") if isinstance(rotated, dict) else None,
            "passed": isinstance(rotated, dict) and abs(float(rotated.get("rotation", 0)) - 90) < 0.001,
            "independent": True,
        }])
        self.call("edit_component", {"board": str(self.board), "reference": "KF1", "value": "4.7k"}, note="live value edit")
        edited = self.call("find_component", {"board": str(self.board), "reference": "KF1"}, note="edit_component value readback")
        self.attach_proof("edit_component", [{
            "name": "component_value_readback", "expected": "4.7k", "actual": (edited or {}).get("value") if isinstance(edited, dict) else None,
            "passed": isinstance(edited, dict) and edited.get("value") == "4.7k", "independent": True,
        }])
        self.call("flip_component", {"board": str(self.board), "reference": "KF1", "layer": "B.Cu"}, note="live flip")
        flipped = self.call("find_component", {"board": str(self.board), "reference": "KF1"}, note="flip_component layer readback")
        self.attach_proof("flip_component", [{
            "name": "component_layer_readback", "expected": "B.Cu", "actual": (flipped or {}).get("layer") if isinstance(flipped, dict) else None,
            "passed": isinstance(flipped, dict) and flipped.get("layer") == "B.Cu", "independent": True,
        }])
        self.call(
            "place_component_array",
            {"board": str(self.board), "footprint": "Capacitor_SMD:C_0603_1608Metric", "ref_prefix": "KC", "ref_start": 101, "start_x": 130, "start_y": 85, "count_x": 2, "count_y": 2, "spacing_x": 3, "spacing_y": 3},
            note="2x2 live placement array",
        )
        self.call("align_components", {"board": str(self.board), "references": ["KC101", "KC102"], "axis": "y", "value": 88}, note="array 정렬")
        self.call(
            "set_component_placements",
            {"board": str(self.board), "placements": [{"reference": "KC101", "x": 130, "y": 90, "rotation": 0}, {"reference": "KC102", "x": 134, "y": 90, "rotation": 180}]},
            note="batch absolute placement",
        )
        placed_components = self.call("get_component_list", {"board": str(self.board)}, note="array/alignment/batch placement readback")
        placed_map = {
            item.get("reference"): item
            for item in (placed_components or {}).get("components", [])
            if isinstance(item, dict) and item.get("reference")
        }
        array_ok = all(reference in placed_map for reference in ("KC101", "KC102", "KC103", "KC104"))
        self.attach_proof("place_component_array", [{
            "name": "array_references_readback", "expected": ["KC101", "KC102", "KC103", "KC104"],
            "actual": [reference for reference in ("KC101", "KC102", "KC103", "KC104") if reference in placed_map],
            "passed": array_ok, "independent": True,
        }])
        align_ok = all(abs(float(placed_map.get(reference, {}).get("y", 0)) - 90) < 0.001 for reference in ("KC101", "KC102"))
        self.attach_proof("align_components", [{
            "name": "aligned_components_retained_in_batch_result", "expected": ["KC101", "KC102"],
            "actual": [placed_map.get("KC101"), placed_map.get("KC102")],
            "passed": align_ok, "independent": True,
            "caveat": "후속 absolute batch placement가 y=90으로 이동했으므로 존재와 공통 y를 검증",
        }])
        batch_ok = (
            abs(float(placed_map.get("KC101", {}).get("x", 0)) - 130) < 0.001
            and abs(float(placed_map.get("KC102", {}).get("x", 0)) - 134) < 0.001
            and abs(float(placed_map.get("KC102", {}).get("rotation", 0)) - 180) < 0.001
        )
        self.attach_proof("set_component_placements", [{
            "name": "batch_placement_readback", "expected": {"KC101": [130, 90, 0], "KC102": [134, 90, 180]},
            "actual": {"KC101": placed_map.get("KC101"), "KC102": placed_map.get("KC102")},
            "passed": batch_ok, "independent": True,
        }])
        self.call("repair_corrupted_footprints", {"board": str(self.board), "dry_run": True}, note="healthy board repair dry-run")
        self.call("update_footprints_from_library", {"board": str(self.board), "references": ["KF1"], "dry_run": True}, note="library refresh dry-run")
        models = self.call("set_placed_footprint_models", {"board": str(self.board), "reference": "KF1", "mode": "inspect"}, note="placed 3D model inspect")

        graphics = self.call("list_board_footprint_graphics", {"board": str(self.board), "reference": "KPOLY1"}, note="graphic edit polygon 후보 조회")
        graphic_items = (graphics or {}).get("graphics", (graphics or {}).get("items", []))
        poly = next((item for item in graphic_items if isinstance(item, dict) and item.get("uuid") and str(item.get("type", item.get("kind", ""))).lower() in {"poly", "polygon"}), None)
        self.call(
            "edit_board_footprint_graphic",
            {"board": str(self.board), "reference": "KPOLY1", "uuid": poly.get("uuid") if poly else "00000000-0000-0000-0000-000000000000", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]},
            note="관측된 footprint polygon 편집",
            expected_limitation=None if poly else "fixture에 편집 가능한 footprint polygon이 없음",
        )
        edited_graphics = self.call("list_board_footprint_graphics", {"board": str(self.board), "reference": "KPOLY1"}, note="footprint polygon edit readback")
        edited_text = json.dumps(edited_graphics, ensure_ascii=False)
        self.attach_proof("edit_board_footprint_graphic", [{
            "name": "edited_polygon_uuid_readback", "expected": poly.get("uuid") if poly else None, "actual": edited_graphics,
            "passed": bool(poly) and str(poly.get("uuid")) in edited_text, "independent": True,
        }])

        self.call("add_board_text", {"board": str(self.board), "text": "KONNECT FUNCTIONAL", "x": 120, "y": 75, "layer": "Dwgs.User", "size": 1.2}, note="live board text 생성")
        self.call("add_mounting_hole", {"board": str(self.board), "x": 240, "y": 150, "reference": "KH1", "drill_diameter": 3.2}, note="mounting-hole footprint 생성")
        hole = self.call("find_component", {"board": str(self.board), "reference": "KH1"}, note="mounting hole readback")
        self.attach_proof("add_mounting_hole", [{
            "name": "mounting_hole_reference_readback", "expected": "KH1", "actual": hole,
            "passed": isinstance(hole, dict) and hole.get("reference") == "KH1", "independent": True,
        }])
        active_layer_board_before = sha256_file(self.board)
        active_change = self.call(
            "set_active_layer",
            {"board": str(self.board), "layer": "B.Cu"},
            note="typed IPC active layer B.Cu 변경 및 readback",
        )
        active_restore = self.call(
            "set_active_layer",
            {"board": str(self.board), "layer": "F.Cu"},
            note="typed IPC active layer F.Cu 복원 및 readback",
        )
        active_layer_board_after = sha256_file(self.board)
        active_layer_round_trip = (
            isinstance(active_change, dict)
            and active_change.get("active_layer") == "B.Cu"
            and active_change.get("readback") == "exact_match"
            and isinstance(active_restore, dict)
            and active_restore.get("previous_layer") == "B.Cu"
            and active_restore.get("active_layer") == "F.Cu"
            and active_restore.get("readback") == "exact_match"
        )
        self.attach_proof("set_active_layer", [{
            "name": "active_layer_round_trip_and_board_file_invariance",
            "expected": {
                "first_active": "B.Cu",
                "restore_previous": "B.Cu",
                "final_active": "F.Cu",
                "board_sha_unchanged": True,
            },
            "actual": {
                "first": active_change,
                "restore": active_restore,
                "board_sha256_before": active_layer_board_before,
                "board_sha256_after": active_layer_board_after,
            },
            "passed": (
                active_layer_round_trip
                and active_layer_board_before == active_layer_board_after
            ),
            "independent": True,
        }])
        nets = self.call("get_nets_list", {"board": str(self.board)}, note="live net inventory")
        net_names = pick_net_names(nets, 2)
        nets_text = json.dumps(nets, ensure_ascii=False)
        add_net_rows = [item for item in self.ledger if item.get("tool") == "add_net"]
        if add_net_rows and add_net_rows[-1].get("is_error") is False:
            self.attach_proof("add_net", [{
                "name": "live_net_inventory_contains_created_net",
                "expected": "KONNECT_TEST_NET",
                "actual": "KONNECT_TEST_NET" if "KONNECT_TEST_NET" in nets_text else None,
                "passed": "KONNECT_TEST_NET" in nets_text,
                "independent": True,
            }])
        net1 = net_names[0] if net_names else "GND"
        net2 = net_names[1] if len(net_names) > 1 else net1
        self.call("route_trace", {"board": str(self.board), "net_name": net1, "layer": "F.Cu", "x1": 110, "y1": 70, "x2": 115, "y2": 70, "width": 0.25}, note="live trace 생성")
        traces = self.call("query_traces", {"board": str(self.board), "net_name": net1, "layer": "F.Cu"}, note="trace readback")
        trace_items = (traces or {}).get("traces", (traces or {}).get("items", []))
        selected_trace = next(
            (
                item for item in trace_items
                if isinstance(item, dict) and item.get("uuid")
                and abs(float(item.get("x1", -1)) - 110) < 0.001
                and abs(float(item.get("y1", -1)) - 70) < 0.001
                and abs(float(item.get("x2", -1)) - 115) < 0.001
                and abs(float(item.get("y2", -1)) - 70) < 0.001
            ),
            None,
        )
        self.attach_proof("route_trace", [{
            "name": "trace_geometry_readback", "expected": [110, 70, 115, 70], "actual": selected_trace,
            "passed": selected_trace is not None, "independent": True,
        }])
        self.call("add_via", {"board": str(self.board), "net_name": net1, "x": 115, "y": 70, "drill": 0.4, "pad_size": 0.8}, note="live via 생성")
        self.call("route_differential_pair", {"board": str(self.board), "net_pos": net1, "net_neg": net2, "x1": 110, "y1": 72, "x2": 118, "y2": 72, "width": 0.15, "gap": 0.15, "layer": "F.Cu"}, note="differential pair 생성", expected_limitation=None if len(net_names) > 1 else "fixture에 서로 다른 두 net이 없음")
        diff_pos = self.call("query_traces", {"board": str(self.board), "net_name": net1, "layer": "F.Cu"}, note="differential positive trace readback")
        diff_neg = self.call("query_traces", {"board": str(self.board), "net_name": net2, "layer": "F.Cu"}, note="differential negative trace readback")
        diff_text = json.dumps([diff_pos, diff_neg], ensure_ascii=False)
        self.attach_proof("route_differential_pair", [{
            "name": "both_differential_nets_readback", "expected": [net1, net2], "actual": [diff_pos, diff_neg],
            "passed": net1 in diff_text and net2 in diff_text and '"width": 0.15' in diff_text,
            "independent": True,
        }])
        if selected_trace:
            self.call("modify_trace", {"board": str(self.board), "uuid": selected_trace["uuid"], "net_name": net1, "layer": "F.Cu", "x1": 110, "y1": 70, "x2": 116, "y2": 70, "width": 0.3}, note="관측 trace 수정")
            after = self.call("query_traces", {"board": str(self.board), "net_name": net1}, note="modify trace readback")
            items = (after or {}).get("traces", (after or {}).get("items", []))
            delete_item = next(
                (
                    item for item in items
                    if isinstance(item, dict) and item.get("uuid")
                    and abs(float(item.get("x1", -1)) - 110) < 0.001
                    and abs(float(item.get("x2", -1)) - 116) < 0.001
                    and abs(float(item.get("width", -1)) - 0.3) < 0.001
                ),
                None,
            )
            self.attach_proof("modify_trace", [{
                "name": "modified_trace_readback", "expected": {"x2": 116, "width": 0.3}, "actual": delete_item,
                "passed": delete_item is not None, "independent": True,
            }])
            self.call("delete_trace", {"board": str(self.board), "uuid": delete_item.get("uuid") if delete_item else selected_trace["uuid"]}, note="관측 trace 삭제와 handler postcondition")
            deleted_traces = self.call("query_traces", {"board": str(self.board), "net_name": net1}, note="delete_trace absence 재조회")
            deleted_items = (deleted_traces or {}).get("traces", (deleted_traces or {}).get("items", []))
            deleted_uuid = delete_item.get("uuid") if delete_item else selected_trace["uuid"]
            absent = not any(isinstance(item, dict) and item.get("uuid") == deleted_uuid for item in deleted_items)
            self.attach_proof("delete_trace", [{
                "name": "deleted_trace_absent", "expected": True, "actual": absent,
                "passed": absent, "independent": True,
            }])
        else:
            for name in ("modify_trace", "delete_trace"):
                args = {"board": str(self.board), "uuid": "00000000-0000-0000-0000-000000000000"}
                if name == "modify_trace":
                    args.update({"net_name": net1, "layer": "F.Cu", "x1": 0, "y1": 0, "x2": 1, "y2": 1})
                self.call(name, args, note="trace readback 부재", expected_limitation="fixture에서 생성 trace UUID를 관측하지 못함")

        pads_by_ref: dict[str, list[dict[str, Any]]] = {}
        for ref in refs[:16]:
            result = self.call("get_component_pads", {"board": str(self.board), "reference": ref}, note="pad-to-pad endpoint 탐색")
            items = (result or {}).get("pads", [])
            if isinstance(items, list):
                pads_by_ref[ref] = items
        pair = pick_pad_pair(pads_by_ref)
        self.call(
            "route_pad_to_pad",
            {"board": str(self.board), "net_name": pair[0] if pair else net1, "ref1": pair[1] if pair else base_ref, "pad1": pair[2] if pair else "1", "ref2": pair[3] if pair else "KF1", "pad2": pair[4] if pair else "1", "layer": "F.Cu", "width": 0.25},
            note="동일 net의 관측 pad endpoints routing",
            expected_limitation=None if pair else "fixture에서 동일 net의 서로 다른 footprint pad pair를 찾지 못함",
        )
        routed_pair = self.call("query_traces", {"board": str(self.board), "net_name": pair[0] if pair else net1}, note="pad-to-pad route readback")
        pair_count = (routed_pair or {}).get("count", 0) if isinstance(routed_pair, dict) else 0
        self.attach_proof("route_pad_to_pad", [{
            "name": "pad_route_segments_observed", "expected": ">=1", "actual": pair_count,
            "passed": isinstance(pair_count, int) and pair_count >= 1, "independent": True,
        }])
        self.call("save_project", {}, note="routing과 후속 zone 작업의 persisted snapshot 동기화")

        zone_points = [{"x": 105, "y": 65}, {"x": 125, "y": 65}, {"x": 125, "y": 78}, {"x": 105, "y": 78}]
        for name in ("add_zone", "add_copper_pour"):
            self.call(name, {"board": str(self.board), "net_name": net1, "layer": "B.Cu", "points": zone_points, "name": f"{name}-functional", "clearance": 0.25}, note=f"{name} live/fallback source 검증", expected_limitation=None if net_names else "fixture named net 없음")
        self.call("refill_zones", {"board": str(self.board)}, note="live zone refill")

        self.call("set_board_size", {"board": str(self.board), "width": 300, "height": 200, "origin_x": 0, "origin_y": 0}, note="plain rectangular outline 교체")
        self.call("save_project", {}, note="set_board_size saved-file planner 동기화")
        resized = self.call("get_board_extents", {"board": str(self.board)}, note="set_board_size geometry readback")
        self.attach_proof("set_board_size", [{
            "name": "rectangular_extent_readback", "expected": {"width": 300, "height": 200}, "actual": resized,
            "passed": isinstance(resized, dict) and abs(float(resized.get("width", 0)) - 300) < 0.1 and abs(float(resized.get("height", 0)) - 200) < 0.1,
            "independent": True,
        }])

        self.call("score_placement", {"board": str(self.board)}, note="placement quality score")
        self.call("auto_place_from_schematic", {"board": str(self.board), "dry_run": True, "margin_mm": 2.0}, note="auto placement bounded dry-run")
        self.call("refine_placement_force_directed", {"board": str(self.board), "dry_run": True, "references": ["KF1", "KC101", "KC102"], "iterations": 20, "max_displacement_mm": 20}, note="force-directed bounded dry-run")
        self.call("save_project", {}, note="placement planners의 saved-file source 동기화")
        self.call("place_decoupling_caps", {"board": str(self.board), "ic_reference": "KU1", "capacitor_references": ["KC101", "KC102"], "dry_run": True, "side": "right"}, note="explicit cap placement plan")
        self.call("plan_bga_fanout", {"board": str(self.board), "reference": "KUBGA1", "strategy": "dogbone", "apply": False}, note="BGA fanout dry-run")

        editor = self.call("get_editor_state", {}, note="live editor/project identity")
        pcb_state = None
        pcb_document = None
        if isinstance(editor, dict):
            candidates = editor.get("editors", editor.get("states", []))
            if isinstance(candidates, list):
                pcb_state = next((item for item in candidates if isinstance(item, dict) and item.get("editor") == "pcb"), None)
                if isinstance(pcb_state, dict):
                    documents = pcb_state.get("documents", [])
                    if isinstance(documents, list):
                        pcb_document = next(
                            (
                                item
                                for item in documents
                                if isinstance(item, dict)
                                and item.get("document_path") == str(self.board)
                            ),
                            documents[0] if documents else None,
                        )
            if pcb_state is None and editor.get("pcb") and isinstance(editor["pcb"], dict):
                pcb_state = editor["pcb"]
                pcb_document = pcb_state
        project_identity = (pcb_document or {}).get("project", {}) if isinstance(pcb_document, dict) else {}
        identity = {
            "editor": "pcb",
            "project_name": project_identity.get("name", self.project.stem),
            "project_path": project_identity.get("path", str(self.project_dir)),
            "document_path": (pcb_document or {}).get("document_path", str(self.board)),
        }
        selection = self.call("get_editor_selection", identity, note="PCB editor selection readback", expected_limitation=None if pcb_document else "editor_state 응답에서 PCB document identity를 추출하지 못함")
        target = self.call("resolve_navigation_target", {**identity, "human_reference": base_ref}, note="reference를 stable KIID로 resolve", expected_limitation=None if pcb_document else "editor identity 추출 실패")
        target_kiid = ""
        if isinstance(target, dict):
            target_kiid = str(
                target.get("target", {}).get("object", {}).get(
                    "kiid", target.get("object_kiid", target.get("kiid", ""))
                )
            )
        self.call("mutate_editor_selection", {**identity, "operation": "clear", "object_kiids": []}, note="selection clear")
        self.call("mutate_editor_selection", {**identity, "operation": "add", "object_kiids": [target_kiid] if target_kiid else []}, note="resolved KIID selection add", expected_limitation=None if target_kiid else "navigation target KIID를 얻지 못함")
        selection_after = self.call("get_editor_selection", identity, note="selection mutation readback")
        selection_text = json.dumps(selection_after, ensure_ascii=False)
        self.attach_proof("mutate_editor_selection", [{
            "name": "selected_kiid_readback", "expected": target_kiid, "actual": selection_after,
            "passed": bool(target_kiid) and target_kiid in selection_text, "independent": True,
        }])
        schematic_head = self.schematic.read_text(encoding="utf-8", errors="replace")[:4096]
        root_match = re.search(r'\(uuid\s+"([0-9a-fA-F-]{36})"\)', schematic_head)
        root_kiid = root_match.group(1) if root_match else ""
        cross_args = {
            "source_editor": "pcb",
            "project_name": identity["project_name"],
            "project_path": identity["project_path"],
            "schematic_document_path": str(self.schematic),
            "pcb_document_path": str(self.board),
            "schematic_sheet_instance_path": [root_kiid] if root_kiid else [],
            "source_object_kiid": target_kiid or "00000000-0000-0000-0000-000000000000",
        }
        self.call(
            "resolve_cross_probe_target",
            cross_args,
            note="PCB footprint와 paired official schematic cross-probe",
            expected_limitation=(
                "KiCad PCB endpoint가 destination schematic editor document를 관측하지 못해 "
                "양쪽 live context 증거를 동시에 충족할 수 없음"
            ),
        )

        self.call("get_board_2d_view", {"board": str(self.board), "width": 1000, "height": 700}, note="live board renderer image digest")
        self.call("check_clearance", {"board": str(self.board), "ref1": "KF1", "ref2": "KC101", "mode": "anchor"}, note="placement clearance geometry")
        self.export_calls()

        self.call("add_board_outline", {"board": str(self.board), "x1": 260, "y1": 40, "x2": 280, "y2": 60, "corner_radius": 2}, note="rounded Edge.Cuts 생성")
        outline_probe = self.call("delete_graphics", {"board": str(self.board), "layer": "Edge.Cuts", "types": ["arc"], "dry_run": True}, note="rounded outline arc readback")
        outline_count = (outline_probe or {}).get("count", 0) if isinstance(outline_probe, dict) else 0
        self.attach_proof("add_board_outline", [{
            "name": "rounded_outline_arcs_observed", "expected": 4, "actual": outline_count,
            "passed": isinstance(outline_count, int) and outline_count >= 4, "independent": True,
        }])
        self.call("get_board_extents", {"board": str(self.board)}, note="outline mutation geometry readback")
        self.call("import_svg_logo", {"board": str(self.board), "svg": str(self.output / "fixture/konnect-logo.svg"), "width_mm": 20, "x": 10, "y": 10, "layer": "Dwgs.User"}, note="SVG graphic import")
        graphics_probe = self.call("delete_graphics", {"board": str(self.board), "layer": "Dwgs.User", "types": ["text", "line", "poly"], "dry_run": True}, note="graphic deletion dry-run")
        graphics_text = json.dumps(graphics_probe, ensure_ascii=False)
        self.attach_proof("add_board_text", [{
            "name": "board_text_observed", "expected": "text", "actual": graphics_probe,
            "passed": '"type": "text"' in graphics_text, "independent": True,
        }])
        self.attach_proof("import_svg_logo", [{
            "name": "imported_polygon_observed", "expected": "poly", "actual": graphics_probe,
            "passed": '"type": "poly"' in graphics_text, "independent": True,
        }])
        self.call("delete_graphics", {"board": str(self.board), "layer": "Dwgs.User", "types": ["text", "line", "poly"], "dry_run": False}, note="graphic deletion apply")
        graphics_after = self.call("delete_graphics", {"board": str(self.board), "layer": "Dwgs.User", "types": ["text", "line", "poly"], "dry_run": True}, note="graphic deletion absence readback")
        after_count = (graphics_after or {}).get("count", -1) if isinstance(graphics_after, dict) else -1
        self.attach_proof("delete_graphics", [{
            "name": "deleted_graphics_absent", "expected": 0, "actual": after_count,
            "passed": after_count == 0, "independent": True,
        }])
        self.call("save_project", {}, note="최종 live state 저장")
        self.call("launch_kicad_ui", {"project": str(self.project), "wait_ready": True, "timeout_seconds": 10}, note="전용 DISPLAY에서 UI launch/idempotent readiness")
        ui_after_launch = self.call("check_kicad_ui", {"timeout_seconds": 5}, note="launch_kicad_ui 후 IPC readiness 재검증")
        self.attach_proof("launch_kicad_ui", [{
            "name": "post_launch_ipc_ready", "expected": True, "actual": ui_after_launch,
            "passed": isinstance(ui_after_launch, dict) and ui_after_launch.get("running") is True and ui_after_launch.get("ipc_responsive") is True,
            "independent": True,
        }])

        capture = self._instance("run", self.args.lane, "--", ACUW_CAPTURE, str(self.output / "screen-after.png"), check=False)
        (self.output / "capture-after.log").write_text(capture.stdout + capture.stderr, encoding="utf-8")

    def export_calls(self) -> None:
        exports = self.exports
        cases: list[tuple[str, dict[str, Any], Path, str | None]] = [
            ("export_bom", {"schematic": str(self.schematic), "output": str(exports / "bom.csv"), "format": "csv"}, exports / "bom.csv", None),
            ("export_gencad", {"board": str(self.board), "output": str(exports / "board.cad")}, exports / "board.cad", None),
            ("export_ipc2581", {"board": str(self.board), "output": str(exports / "board.xml"), "units": "mm"}, exports / "board.xml", None),
            ("export_netlist", {"board": str(self.board), "output": str(exports / "board.d356"), "format": "ipc"}, exports / "board.d356", None),
            ("export_odb", {"board": str(self.board), "output": str(exports / "board.zip"), "compression": "zip", "units": "mm"}, exports / "board.zip", None),
            ("export_pdf", {"board": str(self.board), "output": str(exports / "board.pdf"), "layers": ["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"]}, exports / "board.pdf", None),
            ("export_position_file", {"board": str(self.board), "output": str(exports / "positions.csv"), "format": "csv", "side": "both", "units": "mm"}, exports / "positions.csv", None),
            ("export_svg", {"board": str(self.board), "output": str(exports / "board.svg"), "layers": ["F.Cu", "F.SilkS", "Edge.Cuts"]}, exports / "board.svg", None),
            ("export_3d", {"board": str(self.board), "output": str(exports / "board.step"), "format": "step", "include_unspecified": True}, exports / "board.step", "fixture library/3D model 누락 시 KiCad CLI가 정직하게 거부"),
        ]
        dxf_dir = exports / "dxf"
        gerber_dir = exports / "gerber"
        self.call("export_dxf", {"board": str(self.board), "output_dir": str(dxf_dir), "layers": ["Edge.Cuts", "F.Cu"]}, note="DXF export")
        self.attach_proof("export_dxf", [{"name": "dxf_files_exist", "expected": True, "actual": dxf_dir.is_dir() and any(dxf_dir.iterdir()), "passed": dxf_dir.is_dir() and any(dxf_dir.iterdir()), "independent": True}])
        self.call("export_gerber", {"board": str(self.board), "output_dir": str(gerber_dir), "layers": ["F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"], "drill_file": True}, note="Gerber+drill export")
        self.attach_proof("export_gerber", [{"name": "gerber_files_exist", "expected": True, "actual": gerber_dir.is_dir() and any(gerber_dir.iterdir()), "passed": gerber_dir.is_dir() and any(gerber_dir.iterdir()), "independent": True}])
        for tool, arguments, output, limitation in cases:
            self.call(tool, arguments, note=f"실제 KiCad CLI {tool}", expected_limitation=limitation)
            if self.ledger[-1]["classification"] == "passed":
                post = self._post_file(output)
                self.attach_proof(tool, [{
                    "name": "export_file_exists",
                    "expected": True,
                    "actual": post["passed"],
                    "passed": post["passed"],
                    "independent": True,
                    "path": post["path"],
                    "bytes": post["bytes"],
                    "sha256": post["sha256"],
                }])

        drc_path = exports / "drc.json"
        drc = self.call("get_drc_violations", {"board": str(self.board), "output": str(drc_path), "severity": "warning", "sync_live_board": True, "refill_zones": True}, note="save/refill ordered DRC evidence")
        drc_execution_ok = isinstance(drc, dict) and drc.get("live_board_synced") is True and drc.get("zones_refilled") is True
        for tool in ("add_zone", "add_copper_pour", "refill_zones"):
            self.attach_proof(tool, [{
                "name": "persisted_zone_refill_and_cli_drc", "expected": True, "actual": drc,
                "passed": drc_execution_ok, "independent": True,
                "caveat": "zone identity is bound by each mutation response; this proves persisted refill and independent CLI consumption",
            }])
        run_drc = self.call("run_drc", {"board": str(self.board), "output": str(exports / "run-drc.json"), "severity": "warning", "limit": 200, "sync_live_board": True, "refill_zones": False}, note="verification DRC 실행; violations는 실행 실패와 분리")
        save_proved = isinstance(run_drc, dict) and run_drc.get("live_board_synced") is True
        self.attach_proof("save_project", [{
            "name": "saved_snapshot_consumed_by_cli_drc", "expected": True, "actual": run_drc,
            "passed": save_proved, "independent": True,
        }])
        snapshots = exports / "snapshots"
        self.call("snapshot_project", {"schematic": str(self.schematic), "pcb": str(self.board), "output_dir": str(snapshots), "label": "functional"}, note="schematic+PCB PDF snapshot")

    def specctra_calls(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        self.stop_gui()
        main_paths = (self.project_dir, self.project, self.board, self.schematic)
        self.project_dir = self.spec_dir
        self.project = self.spec_project
        self.board = self.spec_board
        self.schematic = self.spec_schematic
        self.launch_gui()
        self.start_client("specctra")
        self.load_toolsets()
        self.call("open_project", {"path": str(self.project)}, note="Specctra exact fixture live binding")

        spec_exports = self.exports / "specctra"
        spec_exports.mkdir(parents=True, exist_ok=True)
        dsn = spec_exports / "specctra_two_resistors_locked.dsn"
        manifest = spec_exports / "specctra_two_resistors_locked.dsn.konnect.json"
        self.call(
            "export_specctra_dsn",
            {
                "board": str(self.board),
                "output": str(dsn),
                "manifest_output_path": str(manifest),
                "native_bridge_mode": "disable",
            },
            note="exact live fixture Rust-only Specctra DSN+manifest export",
        )
        export_ok = dsn.is_file() and manifest.is_file()
        self.attach_proof("export_specctra_dsn", [{
            "name": "dsn_manifest_pair_exists", "expected": True, "actual": export_ok,
            "passed": export_ok, "independent": True,
            "dsn_sha256": sha256_file(dsn) if dsn.is_file() else None,
            "manifest_sha256": sha256_file(manifest) if manifest.is_file() else None,
        }])
        ses = spec_exports / "specctra_two_resistors_locked.ses"
        ses_source = SPECCTRA_SES_SOURCE.read_text(encoding="utf-8")
        native_component = '''(component "Resistor_SMD:R_0402"
      (place R1 1000000 -500000 front 0)
      (place R2 1100000 -500000 front 0)
    )'''
        rust_components = '''(component konnect_image_R1
      (place R1 1000000 -500000 front 0)
    )
    (component konnect_image_R2
      (place R2 1100000 -500000 front 0)
    )'''
        if native_component not in ses_source:
            raise FunctionalError("paired SES component block가 기대한 native fixture와 다릅니다")
        ses_source = ses_source.replace(native_component, rust_components, 1)
        ses_source = ses_source.replace('"Via[0-1]_600:300_um"', "konnect_via_0001")
        ses.write_text(ses_source, encoding="utf-8")
        self.call(
            "plan_specctra_ses_import",
            {"board": str(self.board), "ses_path": str(ses), "manifest_path": str(manifest)},
            note="revision-bound matching Freerouting SES strict dry-run",
        )
        source_before = sha256_file(self.board)
        candidate = spec_exports / "specctra-candidate.kicad_pcb"
        self.call(
            "apply_specctra_ses",
            {
                "board": str(self.board),
                "ses_path": str(ses),
                "manifest_path": str(manifest),
                "candidate_output_path": str(candidate),
            },
            note="non-destructive SES apply, IPC readback, DRC, candidate publication",
        )
        source_after = sha256_file(self.board)
        apply_ok = candidate.is_file() and source_before == source_after
        self.attach_proof("apply_specctra_ses", [{
            "name": "candidate_exists_and_source_preserved", "expected": True, "actual": apply_ok,
            "passed": apply_ok, "independent": True,
            "candidate_sha256": sha256_file(candidate) if candidate.is_file() else None,
            "source_before_sha256": source_before,
            "source_after_sha256": source_after,
        }])
        self.stop_gui()
        self.project_dir, self.project, self.board, self.schematic = main_paths

    def finish(self) -> int:
        if self.client is not None:
            self.client.close()
            self.client = None
        report = coverage_report(self.inventory, self.ledger)
        expected = sorted({tool for toolset in TARGET_TOOLSETS for tool in self.inventory.get("toolsets", {}).get(toolset, [])})
        observed = [row.get("tool") for row in self.ledger if row.get("tool") in expected]
        duplicates = sorted({tool for tool in observed if observed.count(tool) > 1})
        extra = sorted(set(observed) - set(expected))
        ledger_sha256 = sha256_file(self.output / "ledger.jsonl")
        report.update(
            {
                "schema_version": 1,
                "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source_commit": self.source_commit,
                "binary_sha256": self.binary_sha256,
                "lane": self.args.lane,
                "display": self.lane_env.get("ACUW_DISPLAY"),
                "ipc_address": f"ipc://{self.socket_path}",
                "board": str(self.board),
                "ledger": str(self.output / "ledger.jsonl"),
                "manifest": {
                    "expected": expected,
                    "observed": sorted(set(observed)),
                    "missing": sorted(set(expected) - set(observed)),
                    "extra": extra,
                    "duplicates": duplicates,
                    "per_tool_cases": {
                        tool: [row["case_id"] for row in self.ledger if row.get("tool") == tool]
                        for tool in expected
                    },
                    "ledger_sha256": ledger_sha256,
                },
            }
        )
        (self.output / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["complete_invocation"] and not report["failed"] else 1

    def run(self) -> int:
        self.prepare_output()
        self.open_lane()
        self.pre_gui_calls()
        self.launch_gui()
        self.live_calls()
        self.specctra_calls()
        return self.finish()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="격리된 실제 KiCad GUI/IPC PCB 공개기능 전수 검증")
    parser.add_argument("--output", type=Path, default=ARTIFACT_ROOT / "baseline")
    parser.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    parser.add_argument("--lane", default="kicad-mcp-pcb-tests")
    parser.add_argument("--owner", default="codex-pcb-functional")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--allow-stale-binary", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    return FunctionalRun(args).run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FunctionalError, AssertionError, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"PCB 기능 검증 실패: {error}", file=sys.stderr)
        raise SystemExit(1)
