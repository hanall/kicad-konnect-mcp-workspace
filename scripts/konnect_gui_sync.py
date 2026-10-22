#!/usr/bin/env python3
# 용도: 열린 KiCad 회로도의 GUI 인계와 Konnect 파일 편집을 조율한다.
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time


EDIT_TOOLS = frozenset({
    "add_schematic_text", "add_schematic_component", "batch_place_components",
    "edit_schematic_component", "batch_edit_schematic_components",
    "move_schematic_component", "rotate_schematic_component",
    "delete_schematic_component", "add_wire", "batch_add_wire",
    "delete_schematic_wire", "add_schematic_net_label", "delete_schematic_net_label",
    "connect_pins", "batch_connect_pins", "connect_to_net", "batch_connect_to_net",
    "add_power_symbol", "add_junction", "add_no_connect", "delete_no_connect",
    "set_schematic_page", "reset_schematic_field_positions",
})


def result_body(result):
    if result.get("isError"):
        raise SyncError("upstream_error", "Konnect 도구가 변경을 거부했습니다.", result=result)
    blocks = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
    if len(blocks) != 1:
        raise SyncError("invalid_evidence", "Konnect 구조화 응답이 하나가 아닙니다.")
    try:
        body = json.loads(blocks[0])
    except (ValueError, TypeError) as error:
        raise SyncError("invalid_evidence", "Konnect 응답을 해석할 수 없습니다.") from error
    if not isinstance(body, dict) or "error" in body or body.get("success") is False:
        raise SyncError("upstream_error", "Konnect 응답 본문에 오류가 있습니다.", result=result)
    outcome = body.get("outcome")
    if body.get("errors") or body.get("failures") or (
        isinstance(outcome, dict) and outcome.get("status") != "complete"
    ):
        raise SyncError("upstream_partial", "Konnect 개별 항목 오류 또는 미완료 결과를 관측했습니다.", result=result)
    return body


def canonical_file(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise SyncError("invalid_argument", "회로도는 실제 파일의 절대경로여야 합니다.")
    path = Path(value)
    if path != path.resolve() or not path.is_file() or path.suffix != ".kicad_sch":
        raise SyncError("invalid_argument", "심볼릭 링크·없는 파일·회로도 이외 경로는 허용하지 않습니다.")
    return path


def digest_files(paths):
    result = {}
    for path in paths:
        path = canonical_file(str(path))
        data = path.read_bytes()
        if len(data) > 64 * 1024 * 1024:
            raise SyncError("invalid_argument", "회로도가 동기화 크기 상한을 초과했습니다.")
        result[str(path)] = hashlib.sha256(data).hexdigest()
    return result


def public_observation(observation):
    return {key: value for key, value in observation.items() if not key.startswith("_")}


def write_json(path, body):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class SyncError(RuntimeError):
    def __init__(self, kind, message, **evidence):
        super().__init__(message)
        self.kind = kind
        self.evidence = evidence


class SyncController:
    def __init__(self, desktop, upstream, evidence_root):
        self.desktop = desktop
        self.upstream = upstream
        self.evidence_root = Path(evidence_root)
        self.plans = {}

    def _validate(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) - {
            "schematic", "lane", "operations", "dry_run", "expected_revision"
        }:
            raise SyncError("invalid_argument", "알 수 없는 동기화 인자입니다.")
        if type(arguments.get("dry_run", True)) is not bool:
            raise SyncError("invalid_argument", "dry_run은 boolean이어야 합니다.")
        schematic = canonical_file(arguments.get("schematic"))
        lane = arguments.get("lane")
        if not isinstance(lane, str) or not lane or len(lane) > 80 or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in lane
        ):
            raise SyncError("invalid_argument", "명명된 ACUW 레인이 필요합니다.")
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
            raise SyncError("invalid_argument", "operations는 1~32개의 편집이어야 합니다.")
        hierarchy = result_body(self.upstream.call("get_sheet_hierarchy", {"schematic": str(schematic)}))
        files = {schematic}

        def visit(node, parent):
            if not isinstance(node, dict) or node.get("error"):
                raise SyncError("invalid_evidence", "회로도 계층을 확인할 수 없습니다.")
            children = node.get("children")
            if not isinstance(children, list):
                raise SyncError("invalid_evidence", "회로도 계층 응답에 children이 없습니다.")
            for child in children:
                name = child.get("file") if isinstance(child, dict) else None
                if not isinstance(name, str):
                    raise SyncError("invalid_evidence", "하위 회로도 경로가 없습니다.")
                path = parent.parent / name
                if not path.is_relative_to(schematic.parent):
                    raise SyncError("invalid_argument", "프로젝트 밖 하위 회로도는 지원하지 않습니다.")
                path = canonical_file(str(path))
                files.add(path)
                if len(files) > 256:
                    raise SyncError("invalid_argument", "회로도 계층이 너무 큽니다.")
                visit(child, path)

        if hierarchy.get("file") != str(schematic):
            raise SyncError("invalid_evidence", "계층 응답의 루트 회로도가 다릅니다.")
        visit(hierarchy, schematic)
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {"tool", "arguments"}:
                raise SyncError("invalid_argument", "각 편집은 tool과 arguments만 가져야 합니다.")
            if not isinstance(operation["tool"], str) or operation["tool"] not in EDIT_TOOLS or not isinstance(operation["arguments"], dict):
                raise SyncError("invalid_argument", "이 편집 도구는 안전 인계 범위에 없습니다.")
            target = canonical_file(operation["arguments"].get("schematic"))
            if target not in files:
                raise SyncError("invalid_argument", "편집 대상이 지정 루트의 회로도 계층에 없습니다.")
        return schematic, lane, copy.deepcopy(operations), sorted(files)

    def _observe(self, lane, schematic):
        observation = self.desktop.observe(lane, schematic)
        if observation.get("dirty") is not False:
            raise SyncError("unsaved_changes", "GUI에 미저장 변경이 있습니다. 먼저 사용자가 확인해 저장해야 합니다.",
                            editor=public_observation(observation))
        return observation

    def run(self, arguments):
        schematic, lane, operations, files = self._validate(arguments)
        observation = self._observe(lane, schematic)
        before = digest_files(files)
        binding = {"schematic": str(schematic), "lane": lane, "operations": operations,
                   "files": before, "editor": public_observation(observation)}
        now = time.monotonic()
        self.plans = {token: plan for token, plan in self.plans.items() if now - plan["created"] < 300}
        if arguments.get("dry_run", True):
            if len(self.plans) >= 16:
                self.plans.pop(next(iter(self.plans)))
            revision = secrets.token_hex(32)
            self.plans[revision] = {"binding": binding, "created": now}
            return {"outcome": "planned", "revision": revision, "expires_in_seconds": 300,
                    "editor": public_observation(observation), "files": before,
                    "operation_count": len(operations), "mutation": False,
                    "contract": "미저장 변경 거부 / 정상 종료 / MCP 편집 / 같은 레인 재열기"}
        revision = arguments.get("expected_revision")
        plan = self.plans.pop(revision, None) if isinstance(revision, str) else None
        if plan is None or plan["binding"] != binding:
            raise SyncError("stale_revision", "dry_run의 창·파일·편집 또는 유효 시간이 달라졌습니다. 쓰지 않았습니다.")
        self.evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.evidence_root.is_symlink() or self.evidence_root.stat().st_uid != os.getuid():
            raise SyncError("unsafe_evidence_path", "증거 디렉터리 소유권을 확인할 수 없습니다.")
        lock_path = self.evidence_root / (hashlib.sha256(str(schematic).encode()).hexdigest() + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SyncError("conflict", "다른 동기화가 이 회로도를 인계 중입니다.") from error
            if digest_files(files) != before or public_observation(self._observe(lane, schematic)) != binding["editor"]:
                raise SyncError("stale_revision", "인계 직전 창 또는 파일이 변경됐습니다.")
            return self._apply(schematic, lane, operations, files, observation, before, revision)
        finally:
            os.close(descriptor)

    def _apply(self, schematic, lane, operations, files, observation, before, revision):
        directory = self.evidence_root / revision
        directory.mkdir(mode=0o700)
        receipt_path = directory / "receipt.json"
        receipt = {"version": 1, "revision": revision, "schematic": str(schematic), "lane": lane,
                   "before": before, "outcome": "prepared", "applied_count": 0, "operations": [],
                   "operation_count": len(operations),
                   "applied_count_unit": "fully_completed_tool_calls",
                   "needs_visual_confirmation": True, "backups": {}}
        for index, path in enumerate(files):
            backup = directory / f"{index:03d}.snapshot"
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != before[str(path)]:
                raise SyncError("stale_revision", "백업 중 회로도가 바뀌었습니다.")
            with backup.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            receipt["backups"][str(path)] = str(backup)
        write_json(receipt_path, receipt)
        closed = False
        expected = before
        started = time.monotonic()
        try:
            if public_observation(self._observe(lane, schematic)) != public_observation(observation):
                raise SyncError("stale_revision", "정상 종료 직전에 GUI 정체가 바뀌었습니다.")
            self.desktop.close(observation, schematic)
            closed = True
            receipt["outcome"] = "editor_closed"
            write_json(receipt_path, receipt)
            if digest_files(files) != before:
                raise SyncError("stale_revision", "GUI 종료 중 회로도 파일이 바뀌어 편집을 중단했습니다.")
            for index, operation in enumerate(operations):
                if time.monotonic() - started > 60:
                    raise SyncError("sync_deadline", "인계 시간 예산을 초과해 남은 편집을 수행하지 않습니다.")
                if digest_files(files) != expected:
                    raise SyncError("stale_revision", "편집 사이에 외부 파일 변경을 관측했습니다.")
                receipt["outcome"] = "operation_pending"
                receipt["pending_index"] = index
                write_json(receipt_path, receipt)
                result = self.upstream.call(operation["tool"], operation["arguments"])
                receipt["operations"].append({"index": index, "tool": operation["tool"], "result": result})
                result_body(result)
                observed = digest_files(files)
                target = operation["arguments"]["schematic"]
                if any(observed[path] != expected[path] for path in observed if path != target):
                    raise SyncError("unexpected_write", "편집 대상 이외 회로도가 변경됐습니다.")
                receipt["applied_count"] += 1
                receipt.pop("pending_index", None)
                expected = observed
                receipt["after"] = observed
                write_json(receipt_path, receipt)
            receipt["readback"] = {}
            for path in sorted({operation["arguments"]["schematic"] for operation in operations}):
                receipt["readback"][path] = result_body(self.upstream.call("get_schematic_layout", {"schematic": path}))
            if digest_files(files) != expected:
                raise SyncError("stale_revision", "읽기 검증 중 파일이 바뀌었습니다.")
            receipt["outcome"] = "applied"
        except Exception as error:
            closed = closed or isinstance(error, SyncError) and bool(error.evidence.get("editor_closed"))
            receipt["outcome"] = "partial_or_uncertain" if "pending_index" in receipt or receipt["applied_count"] else "refused_before_mutation"
            receipt["error"] = {"kind": getattr(error, "kind", "sync_failed"), "message": str(error)}
            if isinstance(error, SyncError):
                receipt["error"]["evidence"] = error.evidence
        finally:
            try:
                receipt["after"] = digest_files(files)
            except Exception as error:
                receipt["after_read_error"] = str(error)
            if closed:
                try:
                    reopened = self.desktop.reopen(observation, schematic)
                    receipt["reopened_editor"] = public_observation(reopened)
                    receipt["screenshot"] = self.desktop.capture(lane)
                    if receipt["outcome"] == "applied":
                        if digest_files(files) != expected:
                            raise SyncError("stale_revision", "재열기 중 회로도 파일이 바뀌었습니다.")
                        receipt["outcome"] = "applied_and_reopened"
                except Exception as error:
                    receipt["reopen_error"] = {"kind": getattr(error, "kind", "reopen_failed"), "message": str(error)}
                    if receipt["outcome"] == "applied":
                        receipt["outcome"] = "applied_but_reopen_failed"
            receipt["receipt"] = str(receipt_path)
            write_json(receipt_path, receipt)
        return receipt
