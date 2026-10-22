#!/usr/bin/env python3
# 용도: 검증된 Konnect STDIO에 선택적인 회로 시뮬레이션 MCP 도구 4개를 추가한다.
# 활성화: KONNECT_SIM=1 (scripts/run-konnect.sh가 이 중계를 실행한다).
# 회로도 쓰기는 고정된 upstream Konnect 도구(edit_schematic_component)만 수행한다.
import datetime
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_engines  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1"
MAX_TIMEOUT = 100  # GUI 동기화 중계의 upstream 응답 제한(120초) 안에서 끝나야 한다.
SIM_FIELDS = ("Sim.Device", "Sim.Type", "Sim.Params", "Sim.Pins", "Sim.Library", "Sim.Name", "Sim.Enable")

MEASUREMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "description": "결과 키. 식별자 형식"},
        "kind": {"type": "string", "enum": list(sim_engines.MEAS_KINDS),
                 "description": "FIND(at), MAX/MIN/AVG/RMS/PP/INTEG(from,to), WHEN(val,edge), TRIG_TARG(trig_val,targ_val,edge), AC_FIND_DB(at), AC_WHEN_DB(val dB,edge), DERIVED(formula)"},
        "signal": {"type": "string", "description": "예: v(out), i(V1), vdb(out)"},
        "at": {"type": "string"}, "from": {"type": "string"}, "to": {"type": "string"},
        "val": {"type": "number"}, "edge": {"type": "string", "default": "RISE=1"},
        "trig_val": {"type": "number"}, "targ_val": {"type": "number"},
        "formula": {"type": "string", "description": "DERIVED: 다른 측정 이름과 산술만 허용. 예 (12 - vds_on)/100"},
    },
    "required": ["name", "kind"],
}

TOOLS = [
    {
        "name": "list_simulation_engines",
        "description": "이 호스트에서 AI가 쓸 수 있는 회로 시뮬레이션 엔진과 설치 상태를 반환합니다: 시스템 ngspice(Debian apt), KiCad 10 AppImage 번들 ngspice(회로도 편집기 내장 엔진과 동일, GUI 없이 공유 라이브러리로 실행), LTspice(Wine, ACUW 레인 필요), Qucs-S(GUI 전용), kicad-cli. 버전·경로·헤드리스 여부·검증 명령을 포함합니다. 시뮬레이션 작업 전에 먼저 호출합니다.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "probe_bundled_version": {"type": "boolean", "default": True, "description": "번들 libngspice를 로드해 실제 버전을 읽을지(약 1초)"},
        }},
    },
    {
        "name": "export_spice_netlist",
        "description": "KiCad 회로도(.kicad_sch)에서 kicad-cli로 SPICE 넷리스트를 내보내고 진단합니다: Sim 모델이 없는 심볼(unassigned_models), .include 경로 존재 여부, 포함된 지시어, 접지 노드 존재. 회로 파일은 읽기만 합니다. 시뮬레이션 전에 모델 누락을 먼저 고치는 데 씁니다.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "schematic": {"type": "string", "description": "루트 .kicad_sch 절대경로"},
            "output": {"type": "string", "description": "출력 .cir 경로. 생략하면 <프로젝트>/.konnect-sim/<stem>.cir"},
        }, "required": ["schematic"]},
    },
    {
        "name": "set_simulation_model",
        "description": "회로도 심볼에 KiCad 10 시뮬레이션 모델 필드(Sim.Device, Sim.Type, Sim.Params, Sim.Pins, Sim.Library, Sim.Name, Sim.Enable)를 upstream edit_schematic_component로 설정합니다. 필드 이름·문법 실수를 막는 편의 도구이며 쓰기는 고정된 Konnect 도구가 수행합니다. sch_components toolset이 로드되어 있어야 합니다. 예: NMOS level 1은 device=NMOS, type=MOS1, params='vto=2 kp=0.5 w=100u l=100u'; 서브서킷은 device=SUBCKT, library=<.sp 절대경로>, name=<subckt>, pins='1=in+ 2=in- ...'.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "schematic": {"type": "string"},
            "reference": {"type": "string", "description": "예: M1"},
            "device": {"type": "string", "description": "Sim.Device: R, C, L, D, NPN, PNP, NMOS, PMOS, V, I, SUBCKT, SPICE 등"},
            "type": {"type": "string", "description": "Sim.Type: 예 MOS1, VDMOS, PULSE, SIN, DC"},
            "params": {"type": "string", "description": "Sim.Params: 'key=value' 공백 구분"},
            "pins": {"type": "string", "description": "Sim.Pins: '1=D 2=G 3=S' 심볼 핀 번호→모델 핀"},
            "library": {"type": "string", "description": "Sim.Library: .lib/.sp 절대경로(상대경로·변수는 kicad-cli 해석이 다를 수 있음)"},
            "name": {"type": "string", "description": "Sim.Name: 라이브러리 안 모델/서브서킷 이름"},
            "enable": {"type": "boolean", "description": "Sim.Enable"},
            "clear": {"type": "array", "items": {"type": "string", "enum": list(SIM_FIELDS)}, "description": "빈 문자열로 지울 필드"},
        }, "required": ["schematic", "reference"]},
    },
    {
        "name": "run_spice_simulation",
        "description": "SPICE 넷리스트(또는 회로도→넷리스트)를 선택한 엔진으로 배치 실행하고 측정값·판정을 반환합니다. 엔진: system-ngspice, kicad-bundled-ngspice(KiCad 내장 45.2와 동일), ltspice(lane 필요). analysis로 .tran/.ac 지시어를 만들고 measurements로 엔진별 .meas 문법을 자동 생성하며 expectations로 이론값 대비 허용 오차 판정을 합니다. 기존 지시어는 기본적으로 제거해 호출 인자만 적용합니다. save_signals는 ngspice에서 파형 CSV를 남깁니다. 제조사 PSpice/LTspice 모델은 ngbehavior=ltpsa 등 호환 모드를 지정합니다. 결과는 isError=false여도 all_pass·errors를 확인해야 합니다.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "netlist": {"type": "string", "description": "입력 .cir 절대경로(netlist 또는 schematic 중 하나)"},
            "schematic": {"type": "string", "description": "루트 .kicad_sch 절대경로. 지정 시 먼저 넷리스트를 내보낸다"},
            "engine": {"type": "string", "enum": list(sim_engines.ENGINES), "default": "system-ngspice"},
            "analysis": {"type": "object", "additionalProperties": False, "properties": {
                "type": {"type": "string", "enum": ["tran", "ac", "dc", "op"]},
                "args": {"type": "string", "description": "예 tran: '1u 5m', ac: 'dec 100 1 10meg', dc: 'V1 0 5 0.1'"},
            }, "required": ["type"]},
            "directives": {"type": "array", "items": {"type": "string"}, "description": "그대로 추가할 SPICE 줄(.model/.include/.option/.ic 등)"},
            "measurements": {"type": "array", "items": MEASUREMENT_SCHEMA},
            "expectations": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
                "name": {"type": "string"}, "theory": {"type": "number"},
                "tol_rel": {"type": "number", "default": 0.02}, "tol_abs": {"type": "number"},
            }, "required": ["name", "theory"]}},
            "save_signals": {"type": "array", "items": {"type": "string"}, "description": "ngspice wrdata로 CSV 저장할 신호 (예 v(out))"},
            "ngbehavior": {"type": "string", "enum": list(sim_engines.NGBEHAVIOR), "default": "none", "description": "ngspice 호환 모드. 제조사 PSpice/LTspice 모델은 ltpsa"},
            "lane": {"type": "string", "description": "ltspice 엔진용 ACUW 레인 이름"},
            "work_dir": {"type": "string", "description": "작업 디렉터리. 생략하면 <ROOT>/.artifacts/sim-runs/<시각>-<stem>/"},
            "strip_existing_directives": {"type": "boolean", "default": True},
            "timeout_seconds": {"type": "integer", "default": 60, "minimum": 5, "maximum": MAX_TIMEOUT},
        }},
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}
OUTPUT_LOCK = threading.Lock()


class SimError(Exception):
    def __init__(self, kind, message, **evidence):
        super().__init__(message)
        self.kind = kind
        self.evidence = evidence


def emit(value):
    with OUTPUT_LOCK:
        print(json.dumps(value, ensure_ascii=False), flush=True)


def tool_result(body, error=False):
    return {"isError": error, "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


class Upstream:
    def __init__(self, arguments):
        environment = {**os.environ, "KONNECT_SIM": "0"}
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
        identifier = f"sim-proxy-{self.sequence}"
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        try:
            response = self.responses.get(timeout=120)
        except queue.Empty as error:
            self.close()
            raise SimError("upstream_timeout", "Konnect 응답이 없어 자기 연결을 종료했습니다.") from error
        if response.get("id") != identifier:
            self.close()
            raise SimError("upstream_protocol_error", "Konnect 응답 정체를 확인할 수 없습니다.")
        return response

    def call(self, name, arguments):
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise SimError("upstream_rpc_error", "Konnect JSON-RPC 오류입니다.", response=response)
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


def _require_abs_file(path, suffix, label):
    if not isinstance(path, str) or not path:
        raise SimError("invalid_argument", f"{label} 경로가 필요합니다.")
    p = Path(path)
    if not p.is_absolute():
        raise SimError("invalid_argument", f"{label}은 절대경로여야 합니다.", path=path)
    if suffix and p.suffix != suffix:
        raise SimError("invalid_argument", f"{label}은 {suffix} 파일이어야 합니다.", path=path)
    if not sim_engines.path_allowed(p, "read"):
        raise SimError("invalid_argument", f"{label} 경로가 읽기 허용 루트 밖입니다(KONNECT_SIM_ALLOWED_ROOTS로 추가).", path=path)
    if not p.is_file():
        raise SimError("not_found", f"{label}이 없습니다.", path=path)
    return p


def _require_write_dir(path, label):
    p = Path(path)
    if not p.is_absolute():
        raise SimError("invalid_argument", f"{label}은 절대경로여야 합니다.", path=str(path))
    if not sim_engines.path_allowed(p.parent if p.suffix else p, "write"):
        raise SimError("invalid_argument", f"{label} 경로가 쓰기 허용 루트 밖입니다(레포 안 또는 KONNECT_SIM_ALLOWED_ROOTS).", path=str(path))
    return p


def handle_list_engines(arguments):
    return {"engines": sim_engines.detect_engines(bool(arguments.get("probe_bundled_version", True))),
            "extension_version": VERSION}


def handle_export(arguments):
    schematic = _require_abs_file(arguments.get("schematic"), ".kicad_sch", "schematic")
    output = arguments.get("output")
    if output:
        output = _require_write_dir(output, "output")
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output = ROOT / ".artifacts/sim-exports" / f"{stamp}-{schematic.stem}.cir"
    try:
        result = sim_engines.export_spice_netlist(schematic, output)
    except RuntimeError as error:
        raise SimError("export_failed", str(error))
    result["include_problems"] = sim_engines.check_include_files(result["netlist_text"], base_dir=output.parent)
    return result


def handle_set_model(upstream, arguments):
    schematic = _require_abs_file(arguments.get("schematic"), ".kicad_sch", "schematic")
    reference = arguments.get("reference")
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z#]+[0-9]+[A-Za-z0-9_]*", reference):
        raise SimError("invalid_argument", "reference 형식이 아닙니다.", reference=reference)
    listed = upstream.request("tools/list", {})
    available = {item["name"] for item in listed.get("result", {}).get("tools", [])}
    if "edit_schematic_component" not in available:
        raise SimError("toolset_not_loaded", "sch_components toolset을 먼저 load_toolset으로 로드해야 합니다.",
                       missing=["edit_schematic_component"])
    fields = {}
    mapping = {"device": "Sim.Device", "type": "Sim.Type", "params": "Sim.Params", "pins": "Sim.Pins",
               "library": "Sim.Library", "name": "Sim.Name"}
    for key, field in mapping.items():
        if key in arguments and arguments[key] is not None:
            value = str(arguments[key])
            if "\n" in value:
                raise SimError("invalid_argument", f"{field} 값에 줄바꿈을 넣을 수 없습니다.")
            fields[field] = value
    if "enable" in arguments and arguments["enable"] is not None:
        fields["Sim.Enable"] = "1" if arguments["enable"] else "0"
    for name in arguments.get("clear", []) or []:
        fields[name] = ""
    if not fields:
        raise SimError("invalid_argument", "설정할 Sim 필드가 없습니다.")
    if fields.get("Sim.Library"):
        lib = Path(os.path.expandvars(fields["Sim.Library"]))
        if "$" not in fields["Sim.Library"] and not lib.is_file():
            raise SimError("not_found", "Sim.Library 파일이 없습니다.", path=fields["Sim.Library"])
    if not sim_engines.path_allowed(schematic.parent, "write"):
        raise SimError("invalid_argument", "회로도가 쓰기 허용 루트 밖입니다(KONNECT_SIM_ALLOWED_ROOTS로 추가).", path=str(schematic))
    result = upstream.call("edit_schematic_component", {"schematic": str(schematic), "reference": reference, "fields": fields})
    body = {"schematic": str(schematic), "reference": reference, "fields_applied": fields, "upstream": result}
    if result.get("isError"):
        raise SimError("upstream_tool_error", "edit_schematic_component가 실패했습니다.", **body)
    # readback: 저장된 파일에서 필드를 다시 읽어 적용값과 대조한다.
    readback = upstream.call("get_schematic_component", {"schematic": str(schematic), "reference": reference})
    body["readback"] = readback
    try:
        comp = json.loads(readback["content"][0]["text"])
        props = comp.get("properties") or comp.get("fields") or {}
        if isinstance(props, list):
            props = {p.get("name"): p.get("value") for p in props if isinstance(p, dict)}
        mismatched = {k: props.get(k) for k, v in fields.items() if str(props.get(k, "")) != v}
        body["readback_fields"] = {k: props.get(k) for k in fields}
        body["readback_matches"] = not mismatched
        if mismatched:
            body["readback_mismatch"] = mismatched
    except (KeyError, ValueError, TypeError, AttributeError):
        body["readback_matches"] = None
    return body


def handle_run(arguments):
    engine = arguments.get("engine", "system-ngspice")
    if engine not in sim_engines.ENGINES:
        raise SimError("invalid_argument", "지원하지 않는 엔진입니다.", engine=engine)
    timeout = int(arguments.get("timeout_seconds", 60))
    timeout = max(5, min(MAX_TIMEOUT, timeout))
    netlist = arguments.get("netlist")
    schematic = arguments.get("schematic")
    if bool(netlist) == bool(schematic):
        raise SimError("invalid_argument", "netlist 또는 schematic 중 하나만 지정합니다.")
    measurements = [sim_engines.Measurement.from_dict(m) for m in arguments.get("measurements", []) or []]
    analysis = arguments.get("analysis")
    if analysis and measurements:
        for m in measurements:
            if m.kind != "DERIVED" and m.analysis != analysis["type"] and analysis["type"] in ("tran", "ac"):
                raise SimError("invalid_argument", f"측정 {m.name}({m.kind})은 {analysis['type']} 해석과 맞지 않습니다.")
    if not analysis and any(m.kind != "DERIVED" for m in measurements) and arguments.get("strip_existing_directives", True):
        raise SimError("invalid_argument", "analysis가 없고 기존 지시어도 제거하면 실행할 해석이 없습니다.")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if schematic:
        sch = _require_abs_file(schematic, ".kicad_sch", "schematic")
        stem = sch.stem
    else:
        src = _require_abs_file(netlist, "", "netlist")
        stem = src.stem
    work_dir = arguments.get("work_dir")
    work_dir = _require_write_dir(work_dir, "work_dir") if work_dir else ROOT / ".artifacts/sim-runs" / f"{stamp}-{stem}"
    work_dir.mkdir(parents=True, exist_ok=True)
    export = None
    if schematic:
        try:
            export = sim_engines.export_spice_netlist(sch, work_dir / f"{stem}.kicad.cir")
        except RuntimeError as error:
            raise SimError("export_failed", str(error))
        base_text = export["netlist_text"]
    else:
        base_text = src.read_text(encoding="utf-8", errors="replace")
    save_signals = arguments.get("save_signals") or []
    if engine == "ltspice" and save_signals:
        save_signals = []
    try:
        composed = sim_engines.compose_netlist(base_text, analysis, measurements, arguments.get("directives") or [],
                                               save_signals, engine, bool(arguments.get("strip_existing_directives", True)))
    except ValueError as error:
        raise SimError("invalid_argument", str(error))
    include_problems = sim_engines.check_include_files(composed, base_dir=work_dir)
    if include_problems:
        raise SimError("invalid_argument", "넷리스트 include 검사 실패", problems=include_problems)
    run_path = work_dir / f"{stem}.{engine}.cir"
    run_path.write_text(composed, encoding="utf-8")
    diagnostics = sim_engines.netlist_diagnostics(composed, base_dir=work_dir)
    try:
        run = sim_engines.run_engine(engine, run_path, work_dir, timeout=timeout,
                                     ngbehavior=arguments.get("ngbehavior", "none"), lane=arguments.get("lane"))
    except RuntimeError as error:
        raise SimError("engine_failed", str(error), work_dir=str(work_dir), netlist_path=str(run_path))
    derived = [m for m in measurements if m.kind == "DERIVED"]
    values, rows, derive_errors = sim_engines.evaluate_expectations(run["measurements"], derived, arguments.get("expectations"))
    requested = [m.name.lower() for m in measurements]
    missing = [n for n in requested if values.get(n) is None]
    waveforms = {}
    if save_signals and (work_dir / "waves.csv").exists():
        waveforms = sim_engines.read_wrdata(work_dir / "waves.csv", save_signals)
        for s in waveforms:
            waveforms[s]["csv"] = str(work_dir / "waves.csv")
    engines = sim_engines.detect_engines(probe_bundled_version=(engine == "kicad-bundled-ngspice"))
    body = {
        "engine": {"name": engine, **{k: engines[engine].get(k) for k in ("version", "path")}},
        "work_dir": str(work_dir), "netlist_path": str(run_path), "log_path": run["log_path"],
        "returncode": run["returncode"], "duration_s": run["duration_s"],
        "measurements": {k: v for k, v in values.items()},
        "missing_measurements": missing,
        "expectations": rows, "all_pass": bool(rows) and all(r["pass"] for r in rows),
        "waveforms": waveforms, "diagnostics": diagnostics,
        "warnings": run["warnings"], "errors": run["errors"] + derive_errors,
        "export": {k: export[k] for k in ("netlist_path", "diagnostics")} if export else None,
        "note": "all_pass는 expectations가 있을 때만 의미가 있다. 측정값 일치는 모델 정확성이나 실물 안전을 보장하지 않는다.",
    }
    return body


def main():
    upstream = Upstream(sys.argv[1:])
    stopping = False
    initialized = False

    def stop_owned_connection(_signum, _frame):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        upstream.close()
        raise SimError("connection_stopped", "자기 Konnect 연결을 정지했습니다.")

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
                if method == "tools/call" and params.get("name") in TOOL_NAMES:
                    if not initialized:
                        raise SimError("not_initialized", "MCP 초기화 후 호출해야 합니다.")
                    name = params["name"]
                    arguments = params.get("arguments", {}) or {}
                    if not isinstance(arguments, dict):
                        raise SimError("invalid_argument", "arguments는 객체여야 합니다.")
                    if name == "list_simulation_engines":
                        body = handle_list_engines(arguments)
                    elif name == "export_spice_netlist":
                        body = handle_export(arguments)
                    elif name == "set_simulation_model":
                        body = handle_set_model(upstream, arguments)
                    else:
                        body = handle_run(arguments)
                    response = {"result": tool_result(body, False)}
                else:
                    response = upstream.request(method, params)
                    if method == "tools/list" and "result" in response:
                        response["result"]["tools"].extend(TOOLS)
                    if method == "tools/call" and params.get("name") == "get_installation_info" and "result" in response:
                        result = response["result"]
                        if not result.get("isError"):
                            body = json.loads(result["content"][0]["text"])
                            body["simulation_extension"] = {
                                "version": VERSION, "path": str(Path(__file__).resolve()),
                                "upstream_pid": upstream.process.pid, "tools": sorted(TOOL_NAMES),
                                "engines": sim_engines.detect_engines(probe_bundled_version=False),
                            }
                            response["result"] = tool_result(body)
                response.update(jsonrpc="2.0", id=request["id"])
                emit(response)
            except SimError as error:
                emit({"jsonrpc": "2.0", "id": request["id"], "result": tool_result(
                    {"error": {"kind": error.kind, "message": str(error), **error.evidence}}, True)})
            except Exception as error:
                emit({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32603, "message": f"시뮬레이션 중계 실패: {error}"}})
            if stopping:
                break
    finally:
        upstream.close()


if __name__ == "__main__":
    main()
