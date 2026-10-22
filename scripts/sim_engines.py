#!/usr/bin/env python3
"""회로 시뮬레이션 엔진 공용 계층.

Konnect STDIO 중계(scripts/konnect-mcp-sim.py)와 CLI가 함께 쓴다.
- 엔진 탐지: 시스템 ngspice(apt), KiCad 10 AppImage 번들 libngspice, LTspice(Wine), Qucs-S(AppImage)
- 측정 정의 → 엔진별 .meas 문법 생성, 결과 로그 파싱
- 넷리스트 진단(모델 미할당, .include 누락, 지시어, 접지)
- 실행(ngspice 배치, 번들 공유 라이브러리, LTspice 배치 in ACUW 레인)

회로 파일(.kicad_*)은 읽지도 쓰지도 않는다. 넷리스트(.cir)와 로그만 다룬다.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KICAD_CLI_CANDIDATES = ("/usr/local/bin/kicad-cli", "kicad-cli")
KICAD_APPIMAGE = Path("/opt/kicad/10.0.6/kicad-10.0.6-x86_64.AppImage")
BUNDLED_LIB_CANDIDATES = (
    ROOT / ".artifacts/kicad-10.0.6-install/libraries/AppDir/shared/lib/libngspice.so.0.0.14",
    ROOT / ".artifacts/kicad-bundled-ngspice/squashfs-root/shared/lib/libngspice.so.0.0.14",
)
LTSPICE_WRAPPER = Path.home() / ".local/bin/ltspice"
LTSPICE_PREFIX = Path.home() / ".local/share/wineprefixes/ltspice"
QUCS_MANIFEST = Path("/opt/qucs-s/26.1.1/INSTALL-MANIFEST.json")
ACUW_INSTANCE = Path("/home/hanol/ai-computer-use-workspace/scripts/instance.sh")
SHARED_BATCH = ROOT / "scripts/ngspice_shared_batch.py"

ENGINES = ("system-ngspice", "kicad-bundled-ngspice", "ltspice")
# 입력 경계: 읽기(회로도·넷리스트·include)와 쓰기(작업 디렉터리·출력)의 허용 루트.
# KONNECT_SIM_ALLOWED_ROOTS(콜론 구분)로 추가한다. /tmp는 심볼릭 링크 경합을 피하려고 기본에서 뺀다.
LIBRARY_READ_ROOTS = (Path("/opt/kicad"), Path("/usr/share"), Path("/usr/lib"), Path("/usr/local/share"))
ALLOWED_DIRECTIVE_PREFIXES = (
    ".model", ".include", ".inc", ".lib", ".param", ".option", ".options", ".ic", ".nodeset", ".temp",
    ".global", ".func", ".subckt", ".ends", ".tran", ".ac", ".dc", ".op", ".noise", ".pz", ".sens", ".tf",
    ".save", ".meas", ".measure", ".four", ".probe", ".print", ".plot", ".width", ".title",
)
FORBIDDEN_TOKENS = re.compile(r"(?i)(^|\s)(\.control|\.endc|shell|source|cd|write|wrdata|wrs2p|edisplay|echo|set|unset|load|rusage|quit|exit|aspice|jobs|rspice|getcwd|mdump|mrdump|codemodel|setcs|setscale|setplot|destroy|remcirc|reset|snload|snsave|dowhile|repeat|while|foreach|goto|label)(\s|$)")
NGBEHAVIOR = ("none", "ltpsa", "psa", "lta", "hsa", "ps", "lt", "ki")
MEAS_KINDS = ("FIND", "MAX", "MIN", "AVG", "RMS", "PP", "INTEG", "WHEN", "TRIG_TARG",
              "AC_FIND_DB", "AC_WHEN_DB", "DERIVED")

NGSPICE_MEAS_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+0-9.][-+0-9.eE]*)")
LTSPICE_MEAS_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(?::\s*[^=\n]*?=|=)\s*([-+0-9.][-+0-9.eE]*)")
LTSPICE_DB_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*[^=\n]*=\s*\(\s*([-+0-9.][-+0-9.eE]*)dB")
UNASSIGNED_MODEL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s+__\1\b", re.MULTILINE)
INCLUDE_LINE = re.compile(r"^\s*\.(?:include|inc|lib)\s+\"?([^\"\s]+)\"?", re.IGNORECASE | re.MULTILINE)
DIRECTIVE_LINE = re.compile(r"^\s*\.(tran|ac|dc|op|noise|pz|sens|tf|sp|fft|meas(?:ure)?|save|control|endc|end|option|options|temp|ic|nodeset|param)\b",
                            re.IGNORECASE)


# ---------------------------------------------------------------- 엔진 탐지

def _run(cmd, timeout=30, cwd=None, env=None):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)


def _dpkg_version(package):
    rc, out, _ = _run(["dpkg-query", "-W", "-f=${Version}", package])
    return out.strip() if rc == 0 else None


def _ngspice_version_line(text):
    for line in text.splitlines():
        if "ngspice-" in line:
            return line.strip("* ").strip()
    return None


def locate_kicad_cli():
    for candidate in KICAD_CLI_CANDIDATES:
        path = shutil.which(candidate) if "/" not in candidate else (candidate if os.access(candidate, os.X_OK) else None)
        if path:
            return path
    return None


def locate_bundled_libngspice(extract=False):
    for candidate in BUNDLED_LIB_CANDIDATES:
        if candidate.exists():
            return candidate
    if extract and KICAD_APPIMAGE.exists():
        out = ROOT / ".artifacts/kicad-bundled-ngspice"
        out.mkdir(parents=True, exist_ok=True)
        _run([str(KICAD_APPIMAGE), "--appimage-extract", "shared/lib/libngspice.so*"], timeout=120, cwd=out)
        found = sorted(out.glob("squashfs-root/shared/lib/libngspice.so.0.0.*"))
        if found:
            return found[-1]
    return None


_BUNDLED_VERSION_CACHE = {}


def bundled_version(libpath):
    key = str(libpath)
    if key not in _BUNDLED_VERSION_CACHE:
        rc, out, err = _run(["python3", "-I", str(SHARED_BATCH), key, "/nonexistent.cir"], timeout=60)
        _BUNDLED_VERSION_CACHE[key] = _ngspice_version_line(out) or None
    return _BUNDLED_VERSION_CACHE[key]


def detect_engines(probe_bundled_version=True):
    engines = {}
    ngspice = shutil.which("ngspice")
    version = None
    if ngspice:
        _, out, _ = _run([ngspice, "--version"])
        version = _ngspice_version_line(out)
    engines["system-ngspice"] = {
        "available": bool(ngspice), "path": ngspice, "version": version,
        "package": _dpkg_version("ngspice"), "headless": True,
        "verify": "make sim-runtime-verify",
    }
    lib = locate_bundled_libngspice()
    engines["kicad-bundled-ngspice"] = {
        "available": lib is not None, "path": str(lib) if lib else None,
        "version": bundled_version(lib) if (lib and probe_bundled_version) else None,
        "headless": True, "source": "KiCad 10.0.6 AppImage shared/lib/libngspice",
        "note": "KiCad 회로도 편집기 내장 시뮬레이터와 같은 엔진. 코드모델(.cm)은 로드하지 않으므로 XSPICE 소자는 시스템 ngspice를 쓴다.",
    }
    lt_manifest = LTSPICE_PREFIX / "INSTALL-MANIFEST.json"
    lt_version = None
    if lt_manifest.exists():
        try:
            lt_version = json.loads(lt_manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            lt_version = None
    engines["ltspice"] = {
        "available": LTSPICE_WRAPPER.exists() and lt_manifest.exists() and shutil.which("wine") is not None,
        "path": str(LTSPICE_WRAPPER), "version": lt_version, "headless": False,
        "requires": "ACUW 레인(DISPLAY). run_spice_simulation의 lane 인자",
        "wine": _dpkg_version("wine"),
    }
    q_version = None
    if QUCS_MANIFEST.exists():
        try:
            q_version = json.loads(QUCS_MANIFEST.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            q_version = None
    engines["qucs-s"] = {
        "available": QUCS_MANIFEST.exists() and os.access("/usr/local/bin/qucs-s", os.X_OK),
        "path": "/usr/local/bin/qucs-s", "version": q_version, "headless": False,
        "note": "GUI 전용(회로도 .sch 필요). 이 도구로 실행하지 않는다. 사용법은 skills/kicad-simulation/references/engines.md",
        "engine": engines["system-ngspice"]["version"],
    }
    kicad_cli = locate_kicad_cli()
    engines["kicad-cli"] = {"available": kicad_cli is not None, "path": kicad_cli}
    return engines


# ---------------------------------------------------------------- 측정 정의

@dataclass
class Measurement:
    name: str
    kind: str
    signal: str = ""
    at: str | None = None
    from_: str | None = None
    to: str | None = None
    val: float | None = None
    edge: str = "RISE=1"
    trig_val: float | None = None
    targ_val: float | None = None
    formula: str | None = None

    @classmethod
    def from_dict(cls, raw):
        kind = str(raw.get("kind", "")).upper()
        if kind not in MEAS_KINDS:
            raise ValueError(f"지원하지 않는 측정 kind: {kind}")
        name = str(raw.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"측정 이름이 식별자가 아닙니다: {name!r}")
        return cls(
            name=name, kind=kind, signal=str(raw.get("signal", "")),
            at=_opt_str(raw.get("at")), from_=_opt_str(raw.get("from")), to=_opt_str(raw.get("to")),
            val=_opt_float(raw.get("val")), edge=str(raw.get("edge", "RISE=1")),
            trig_val=_opt_float(raw.get("trig_val")), targ_val=_opt_float(raw.get("targ_val")),
            formula=_opt_str(raw.get("formula")),
        )

    @property
    def analysis(self):
        return "ac" if self.kind.startswith("AC_") else "tran"

    def ngspice(self):
        k, n, s = self.kind, self.name, self.signal
        if k == "DERIVED":
            return None
        if k == "FIND":
            return f".meas tran {n} FIND {s} AT={self.at}"
        if k in ("MAX", "MIN", "AVG", "RMS", "PP", "INTEG"):
            return f".meas tran {n} {k} {s} FROM={self.from_} TO={self.to}"
        if k == "WHEN":
            return f".meas tran {n} WHEN {s}={_num(self.val)} {self.edge}"
        if k == "TRIG_TARG":
            return (f".meas tran {n} TRIG {s} VAL={_num(self.trig_val)} {self.edge} "
                    f"TARG {s} VAL={_num(self.targ_val)} {self.edge}")
        if k == "AC_FIND_DB":
            return f".meas ac {n} FIND {_vdb(s)} AT={self.at}"
        if k == "AC_WHEN_DB":
            return f".meas ac {n} WHEN {_vdb(s)}={_num(self.val)} {self.edge}"
        raise ValueError(k)

    def ltspice(self):
        k, n, s = self.kind, self.name, self.signal
        if k == "DERIVED":
            return None
        if k == "FIND":
            return f".meas tran {n} FIND {s} AT {self.at}"
        if k in ("MAX", "MIN", "AVG", "RMS", "PP", "INTEG"):
            return f".meas tran {n} {k} {s} FROM {self.from_} TO {self.to}"
        if k == "WHEN":
            return f".meas tran {n} WHEN {s}={_num(self.val)} {self.edge}"
        if k == "TRIG_TARG":
            return (f".meas tran {n} TRIG {s} VAL={_num(self.trig_val)} {self.edge} "
                    f"TARG {s} VAL={_num(self.targ_val)} {self.edge}")
        if k == "AC_FIND_DB":
            return f".meas ac {n} FIND {_strip_vdb(s)} AT {self.at}"
        if k == "AC_WHEN_DB":
            # LTspice는 복소수 크기를 선형값으로 비교한다. dB 기준을 선형 크기로 바꾼다.
            linear = 10 ** (float(self.val) / 20.0)
            return f".meas ac {n} WHEN mag({_strip_vdb(s)})={linear:.9g} {self.edge}"
        raise ValueError(k)


def _opt_str(value):
    return None if value is None else str(value)


def _opt_float(value):
    return None if value is None else float(value)


def _num(value):
    return f"{float(value):.12g}"


def _vdb(signal):
    s = signal.strip()
    if s.lower().startswith("vdb("):
        return s
    inner = s[2:-1] if s.lower().startswith("v(") and s.endswith(")") else s
    return f"vdb({inner})"


def _strip_vdb(signal):
    s = signal.strip()
    if s.lower().startswith("vdb("):
        return f"V({s[4:-1]})"
    return s


# ---------------------------------------------------------------- 안전한 식 평가

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
          "min": min, "max": max}


def safe_eval(expression, variables):
    tree = ast.parse(expression, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables and variables[node.id] is not None:
                return float(variables[node.id])
            raise ValueError(f"미정의 변수: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return float(_FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise ValueError(f"허용되지 않는 식 요소: {ast.dump(node)[:40]}")

    return ev(tree)


# ---------------------------------------------------------------- 넷리스트

def netlist_diagnostics(text, base_dir=None):
    unassigned = sorted({m.group(1) for m in UNASSIGNED_MODEL.finditer(text)})
    includes = []
    for m in INCLUDE_LINE.finditer(text):
        raw = m.group(1)
        expanded = os.path.expandvars(raw)
        path = Path(expanded)
        if not path.is_absolute() and base_dir:
            path = Path(base_dir) / path
        includes.append({"path": raw, "resolved": str(path), "exists": path.exists()})
    directives = [line.strip() for line in text.splitlines() if DIRECTIVE_LINE.match(line)]
    nodes = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("*", ".", "+")):
            continue
        parts = s.split()
        if parts[0][0].upper() in "RCLVIDMQJBEFGHKXSTW" and len(parts) >= 3:
            nodes.update(parts[1:3])
    has_ground = any(n.lower() in ("0", "gnd") for n in nodes)
    # 배치된 Simulation_SPICE 심볼에 Sim 필드가 복사되지 않으면 값 자리에 심볼 이름이 들어간다(예: "V1 in GND DC VPULSE").
    suspicious = []
    for line in text.splitlines():
        m = re.match(r"^\s*([VI][A-Za-z0-9_]*)\s+\S+\s+\S+\s+(?:DC\s+)?([A-Za-z][A-Za-z0-9_]*)\s*$", line.strip())
        if m and m.group(2).upper() in ("VPULSE", "VSIN", "VDC", "VEXP", "VPWL", "IPULSE", "ISIN", "IDC", "VAM", "VSFFM", "VTRNOISE", "VTRRANDOM"):
            suspicious.append({"line": line.strip(), "reason": f"{m.group(1)}의 값 자리에 심볼 이름 {m.group(2)}가 있다. Sim.Device/Sim.Type/Sim.Params 미지정"})
    return {
        "unassigned_models": unassigned,
        "suspicious_values": suspicious,
        "includes": includes,
        "missing_includes": [i["path"] for i in includes if not i["exists"]],
        "directives": directives,
        "has_ground": has_ground,
        "element_count": sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("*", ".", "+"))),
    }


def export_spice_netlist(schematic, output, kicad_cli=None, timeout=120):
    kicad_cli = kicad_cli or locate_kicad_cli()
    if not kicad_cli:
        raise RuntimeError("kicad-cli를 찾을 수 없습니다.")
    schematic = Path(schematic)
    if not schematic.is_file() or schematic.suffix != ".kicad_sch":
        raise RuntimeError(f"회로도 파일이 아닙니다: {schematic}")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    rc, out, err = _run([kicad_cli, "sch", "export", "netlist", "--format", "spice", "-o", str(output), str(schematic)],
                        timeout=timeout)
    if rc != 0 or not output.exists():
        raise RuntimeError(f"kicad-cli 넷리스트 내보내기 실패 rc={rc}: {(out + err).strip()[:400]}")
    text = output.read_text(encoding="utf-8", errors="replace")
    diag = netlist_diagnostics(text, base_dir=output.parent)
    return {"kicad_cli": kicad_cli, "schematic": str(schematic), "netlist_path": str(output),
            "netlist_text": text, "diagnostics": diag, "duration_s": round(time.monotonic() - started, 3),
            "stderr": err.strip()[:400]}


def allowed_roots(kind="read"):
    """kind='read': 회로도·넷리스트·include. kind='write': 작업 디렉터리·출력."""
    roots = [ROOT]
    extra = os.environ.get("KONNECT_SIM_ALLOWED_ROOTS", "")
    roots += [Path(p) for p in extra.split(":") if p]
    if kind == "read":
        roots += [Path.home(), *LIBRARY_READ_ROOTS]
    return [r.resolve() for r in roots if r.exists()]


def path_allowed(path, kind="read"):
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots(kind))


def strip_control_blocks(text):
    """`.control … .endc` 블록을 항상 제거한다(배치 모드가 shell 등 임의 명령을 실행하므로)."""
    kept, in_control = [], False
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith(".control"):
            in_control = True
            continue
        if s.startswith(".endc"):
            in_control = False
            continue
        if not in_control:
            kept.append(line)
    return "\n".join(kept)


def strip_directives(text):
    kept = []
    for line in strip_control_blocks(text).splitlines():
        s = line.strip().lower()
        if re.match(r"^\.(tran|ac|dc|op|noise|pz|sens|tf|sp|fft|meas|measure|save|end)\b", s):
            continue
        kept.append(line)
    return "\n".join(kept)


def sanitize_directives(directives):
    """호출자가 준 지시어 줄을 화이트리스트로 검사한다. 위반 줄은 ValueError."""
    clean = []
    for raw in directives or []:
        if not isinstance(raw, str):
            raise ValueError("지시어는 문자열이어야 합니다.")
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if "\n" in raw or "\r" in raw:
            raise ValueError("지시어 한 항목에 줄바꿈을 넣을 수 없습니다.")
        low = line.lower()
        if low.startswith("."):
            if not any(low.startswith(p + " ") or low == p for p in ALLOWED_DIRECTIVE_PREFIXES):
                raise ValueError(f"허용되지 않는 지시어: {line[:60]}")
        if FORBIDDEN_TOKENS.search(line) and not low.startswith((".model", ".subckt", ".param", ".func")):
            raise ValueError(f"제어 명령으로 해석될 수 있는 토큰이 있습니다: {line[:60]}")
        clean.append(line)
    return clean


def check_include_files(text, base_dir=None):
    """넷리스트의 .include/.lib 대상이 허용 루트 안에 있고 .control 블록이 없는지 확인한다."""
    problems = []
    for item in netlist_diagnostics(text, base_dir=base_dir)["includes"]:
        path = Path(item["resolved"])
        if "$" in item["path"] and not path.exists():
            continue  # 변수 경로는 엔진이 해석한다. 존재 여부는 diagnostics가 보고한다.
        if not path_allowed(path, "read"):
            problems.append(f"include 경로가 허용 루트 밖입니다: {item['path']}")
            continue
        if path.exists():
            try:
                head = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r"(?im)^\s*\.control\b", head):
                problems.append(f"include 파일에 .control 블록이 있습니다: {item['path']}")
    return problems


def compose_netlist(base_text, analysis, measurements, directives, save_signals, engine, strip_existing=True):
    body = strip_directives(base_text) if strip_existing else strip_control_blocks(base_text).rstrip()
    lines = [body.rstrip("\n")]
    if analysis:
        args_text = str(analysis.get("args", "")).strip()
        if "\n" in args_text or FORBIDDEN_TOKENS.search(args_text):
            raise ValueError("analysis.args 형식이 아닙니다.")
        lines.append(f".{analysis['type']} {args_text}".rstrip())
    lines.extend(sanitize_directives(directives))
    if engine == "ltspice":
        for m in measurements:
            d = m.ltspice()
            if d:
                lines.append(d)
    else:
        if any(m.kind.startswith("AC_") for m in measurements):
            lines.append(".save all")
        for m in measurements:
            d = m.ngspice()
            if d:
                lines.append(d)
        if save_signals:
            for s in save_signals:
                if not re.fullmatch(r"[A-Za-z_@#][A-Za-z0-9_@#.:]*\([A-Za-z0-9_\-+./:]+\)|[A-Za-z_][A-Za-z0-9_]*", s):
                    raise ValueError(f"저장할 신호명 형식이 아닙니다: {s[:40]}")
            lines.append(".control")
            lines.append("run")
            lines.append("wrdata waves.csv " + " ".join(save_signals))
            lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 실행

def parse_ngspice_log(text):
    values, warnings, errors = {}, [], []
    for line in text.splitlines():
        m = NGSPICE_MEAS_LINE.match(line)
        if m:
            try:
                values[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
        low = line.lower()
        if "error" in low and "bug-report" not in low:
            errors.append(line.strip())
        elif "warning" in low:
            warnings.append(line.strip())
    return values, warnings[:50], errors[:50]


def parse_ltspice_log(text):
    values, warnings, errors = {}, [], []
    for line in text.splitlines():
        m = LTSPICE_DB_LINE.match(line) or LTSPICE_MEAS_LINE.match(line)
        if m:
            try:
                values[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
        low = line.lower()
        if low.startswith("error") or "fatal" in low or "singular" in low:
            errors.append(line.strip())
        elif "warning" in low:
            warnings.append(line.strip())
    return values, warnings[:50], errors[:50]


def read_wrdata(path, signals):
    """ngspice wrdata 출력(각 벡터마다 x y 열 쌍)을 신호별 요약으로 읽는다."""
    summary = {}
    try:
        rows = [list(map(float, line.split())) for line in Path(path).read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return summary
    for index, signal in enumerate(signals):
        col = 2 * index + 1
        ys = [r[col] for r in rows if len(r) > col]
        if ys:
            summary[signal] = {"points": len(ys), "min": min(ys), "max": max(ys), "final": ys[-1]}
    return summary


def run_engine(engine, netlist_path, work_dir, timeout=60, ngbehavior="none", lane=None):
    netlist_path = Path(netlist_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    spiceinit = work_dir / ".spiceinit"
    if engine in ("system-ngspice", "kicad-bundled-ngspice"):
        if ngbehavior and ngbehavior != "none":
            spiceinit.write_text(f"set ngbehavior={ngbehavior}\n", encoding="utf-8")
        elif spiceinit.exists():
            spiceinit.unlink()
    log_path = work_dir / (netlist_path.stem + ".log")
    started = time.monotonic()
    if engine == "system-ngspice":
        ngspice = shutil.which("ngspice")
        if not ngspice:
            raise RuntimeError("시스템 ngspice가 없습니다.")
        rc, out, err = _run([ngspice, "-b", "-o", str(log_path), str(netlist_path)], timeout=timeout, cwd=work_dir)
        text = (log_path.read_text(errors="replace") if log_path.exists() else "") + "\n" + out + err
        values, warnings, errors = parse_ngspice_log(text)
    elif engine == "kicad-bundled-ngspice":
        lib = locate_bundled_libngspice(extract=True)
        if not lib:
            raise RuntimeError("KiCad 번들 libngspice를 찾을 수 없습니다.")
        rc, out, err = _run(["python3", "-I", str(SHARED_BATCH), str(lib), str(netlist_path)], timeout=timeout, cwd=work_dir)
        log_path.write_text(out + err, encoding="utf-8")
        values, warnings, errors = parse_ngspice_log(out + err)
    elif engine == "ltspice":
        if not lane:
            raise RuntimeError("ltspice 엔진은 ACUW 레인 이름(lane)이 필요합니다.")
        if not ACUW_INSTANCE.exists():
            raise RuntimeError("ACUW instance.sh가 없습니다.")
        env = {**os.environ, "ACUW_LANE_MEMORY_MAX": os.environ.get("ACUW_LANE_MEMORY_MAX", "16G")}
        cmd = ["bash", str(ACUW_INSTANCE), "run", lane, "--", "run-in-workspace.sh", "--wait", "--host-home",
               "--cwd", str(work_dir), "--name", f"ltspice-{netlist_path.stem}", "--",
               str(LTSPICE_WRAPPER), "-b", netlist_path.name]
        rc, out, err = _run(cmd, timeout=timeout, cwd=work_dir, env=env)
        lt_log = work_dir / (netlist_path.stem + ".log")
        text = lt_log.read_text(errors="replace") if lt_log.exists() else ""
        values, warnings, errors = parse_ltspice_log(text)
        if not text:
            errors.append("LTspice 로그가 생성되지 않았습니다: " + (out + err).strip()[-300:])
    else:
        raise RuntimeError(f"지원하지 않는 엔진: {engine}")
    return {"returncode": rc, "log_path": str(log_path), "measurements": values,
            "warnings": warnings, "errors": errors, "duration_s": round(time.monotonic() - started, 3)}


def evaluate_expectations(measurements, derived, expectations):
    values = dict(measurements)
    for m in derived:
        try:
            values[m.name.lower()] = safe_eval(m.formula, {k.lower(): v for k, v in values.items()})
        except (ValueError, ZeroDivisionError, SyntaxError) as error:
            values[m.name.lower()] = None
            values.setdefault("_errors", []).append(f"{m.name}: {error}")
    rows = []
    for e in expectations or []:
        name = str(e.get("name", "")).lower()
        theory = float(e["theory"])
        value = values.get(name)
        row = {"name": name, "theory": theory, "value": value}
        if value is None:
            row.update(pass_=False, note="측정값 없음")
        elif "tol_abs" in e:
            err = abs(value - theory)
            row.update(err_abs=err, tol_abs=float(e["tol_abs"]), pass_=err <= float(e["tol_abs"]))
        else:
            tol = float(e.get("tol_rel", 0.02))
            err = abs(value - theory) / abs(theory) if theory else abs(value - theory)
            row.update(err_rel=err, tol_rel=tol, pass_=err <= tol)
        rows.append({("pass" if k == "pass_" else k): v for k, v in row.items()})
    errors = values.pop("_errors", [])
    return values, rows, errors
