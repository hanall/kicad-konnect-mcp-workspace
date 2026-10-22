#!/usr/bin/env python3
# 용도: 검증된 Konnect STDIO에 선택적인 GUI 안전 인계 MCP 도구를 추가한다.
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading

from konnect_gui_desktop import LinuxDesktop
from konnect_gui_sync import EDIT_TOOLS, SyncController, SyncError


ROOT = Path(__file__).resolve().parent.parent
VERSION = "1"
TOOL_NAME = "synchronize_schematic_edit"
TOOL = {
    "name": TOOL_NAME,
    "description": "Linux ACUW 공유 레인의 정확한 KiCad 루트 회로도 창을 안전하게 인계합니다. dry_run으로 파일·PID 세대·창·편집을 결속한 revision을 받은 뒤 같은 인자와 dry_run=false로 적용합니다. 미저장 변경·대화상자는 거부합니다. 정상 종료 후 기존 Konnect 도구로 편집하고 같은 레인에 다시 엽니다. 저장/폐기 강제 승인과 잠금 삭제는 하지 않습니다. 라이브 메모리 수정 API가 아니며 재열기 캡처를 시각 확인해야 합니다. get_sheet_hierarchy, get_schematic_layout과 사용할 편집 도구를 먼저 로드해야 합니다.",
    "inputSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "schematic": {"type": "string", "description": "현재 GUI에 보이는 루트 .kicad_sch 절대경로"},
            "lane": {"type": "string", "description": "실행 중인 명명된 ACUW visible-xvfb 레인"},
            "dry_run": {"type": "boolean", "default": True},
            "expected_revision": {"type": "string", "description": "동일 연결에서 5분 이내 받은 일회용 revision"},
            "operations": {"type": "array", "minItems": 1, "maxItems": 32, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"tool": {"type": "string", "enum": sorted(EDIT_TOOLS)},
                               "arguments": {"type": "object"}},
                "required": ["tool", "arguments"],
            }},
        },
        "required": ["schematic", "lane", "operations"],
    },
}


OUTPUT_LOCK = threading.Lock()


def emit(value):
    with OUTPUT_LOCK:
        print(json.dumps(value, ensure_ascii=False), flush=True)


def tool_result(body, error=False):
    return {"isError": error, "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


class Upstream:
    def __init__(self, arguments):
        environment = {**os.environ, "KONNECT_GUI_SYNC": "0"}
        self.process = subprocess.Popen(
            [str(ROOT / "scripts/run-konnect.sh"), *arguments], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
            text=True, bufsize=1, env=environment,
        )
        self.responses = queue.Queue()
        self.sequence = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if "id" in message:
                    self.responses.put(message)
                else:
                    emit(message)
        except Exception as error:
            self.responses.put({"reader_error": str(error)})
        finally:
            self.responses.put({"eof": True})

    def request(self, method, params):
        self.sequence += 1
        identifier = f"gui-proxy-{self.sequence}"
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        try:
            response = self.responses.get(timeout=120)
        except queue.Empty as error:
            # 불확실한 쓰기가 계속 실행되는 상태에서 GUI를 다시 열지 않는다.
            self.close()
            raise SyncError("upstream_timeout", "자기 Konnect 연결을 종료해 쓰기를 정지했습니다. 부분 적용 여부를 확인해야 합니다.") from error
        if response.get("id") != identifier:
            self.close()
            raise SyncError("upstream_protocol_error", "Konnect 응답 정체를 확인할 수 없습니다.")
        return response

    def call(self, name, arguments):
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise SyncError("upstream_rpc_error", "Konnect JSON-RPC 오류입니다.", response=response)
        return response["result"]

    def notify(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def main():
    upstream = Upstream(sys.argv[1:])
    controller = SyncController(LinuxDesktop(), upstream, ROOT / ".artifacts/gui-sync")
    stopping = False
    initialized = False

    def stop_owned_connection(_signum, _frame):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        upstream.close()
        raise SyncError("connection_stopped", "자기 Konnect 연결의 쓰기를 정지했습니다. 영수증으로 부분 적용 여부를 확인해야 합니다.")

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, stop_owned_connection)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("JSON-RPC 객체가 아닙니다.")
            except ValueError:
                emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON-RPC 요청을 해석할 수 없습니다."}})
                continue
            if "id" not in request:
                upstream.notify(request)
                if request.get("method") == "notifications/initialized":
                    initialized = True
                continue
            method = request.get("method")
            params = request.get("params", {})
            try:
                if method == "tools/call" and params.get("name") == TOOL_NAME:
                    if not initialized:
                        raise SyncError("not_initialized", "MCP 초기화 후 동기화를 요청해야 합니다.")
                    listed = upstream.request("tools/list", {})
                    available = {item["name"] for item in listed.get("result", {}).get("tools", [])}
                    arguments = params.get("arguments", {})
                    operations = arguments.get("operations", []) if isinstance(arguments, dict) else []
                    required = {"get_sheet_hierarchy", "get_schematic_layout"}
                    if isinstance(operations, list):
                        required |= {item["tool"] for item in operations if isinstance(item, dict) and isinstance(item.get("tool"), str)}
                    if not required <= available:
                        raise SyncError("toolset_not_loaded", "필요한 도구를 먼저 로드해야 합니다.", missing=sorted(required - available))
                    body = controller.run(params.get("arguments", {}))
                    response = {"result": tool_result(body, body["outcome"] not in {"planned", "applied_and_reopened"})}
                else:
                    response = upstream.request(method, params)
                    if method == "tools/list" and "result" in response:
                        response["result"]["tools"].append(TOOL)
                    if method == "tools/call" and params.get("name") == "get_installation_info" and "result" in response:
                        result = response["result"]
                        if not result.get("isError"):
                            body = json.loads(result["content"][0]["text"])
                            body["gui_sync_extension"] = {"version": VERSION, "path": str(Path(__file__).resolve()),
                                                          "upstream_pid": upstream.process.pid, "tool": TOOL_NAME,
                                                          "mode": "native_close_mcp_edit_reopen", "memory_ipc": False}
                            response["result"] = tool_result(body)
                response.update(jsonrpc="2.0", id=request["id"])
                emit(response)
            except SyncError as error:
                emit({"jsonrpc": "2.0", "id": request["id"], "result": tool_result(
                    {"error": {"kind": error.kind, "message": str(error), **error.evidence}}, True)})
            except Exception as error:
                emit({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32603, "message": f"GUI 동기화 중계 실패: {error}"}})
            if stopping:
                break
    finally:
        upstream.close()


if __name__ == "__main__":
    main()
