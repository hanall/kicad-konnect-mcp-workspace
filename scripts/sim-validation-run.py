#!/usr/bin/env python3
"""검증 회로 사양(spec.json)을 시스템 ngspice 배치로 실행해 이론값과 대조하는 결정적 회귀.

사용법:
  python3 scripts/sim-validation-run.py [--spec PATH] [--out DIR] [--ngspice BIN] [--json RESULT]

종료 코드: 0 모든 항목 통과, 1 하나라도 실패, 2 실행 오류.
회로 파일(.kicad_*)은 건드리지 않는다. 순수 SPICE 넷리스트(.cir)만 생성한다.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "projects/sim-validation-20261022/spec/spec.json"
DEFAULT_OUT = ROOT / "projects/sim-validation-20261022/ngspice-regression"
MEAS_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+0-9.eE]+)")


def meas_directive(analysis_type, m):
    kind = m["kind"]
    name = m["name"]
    sig = m.get("signal", "")
    if kind == "FIND":
        return f".meas {analysis_type} {name} FIND {sig} AT={m['at']}"
    if kind == "MAX":
        return f".meas {analysis_type} {name} MAX {sig} FROM={m['from']} TO={m['to']}"
    if kind == "INTEG":
        return f".meas {analysis_type} {name} INTEG {sig} FROM={m['from']} TO={m['to']}"
    if kind == "WHEN":
        return f".meas {analysis_type} {name} WHEN {sig}={m['val']} {m['edge']}"
    if kind == "TRIG_TARG":
        return (f".meas {analysis_type} {name} TRIG {sig} VAL={m['trig_val']} {m['edge']} "
                f"TARG {sig} VAL={m['targ_val']} {m['edge']}")
    if kind == "AC_FIND_DB":
        return f".meas ac {name} FIND {sig} AT={m['at']}"
    if kind == "AC_WHEN_DB":
        return f".meas ac {name} WHEN {sig}={m['val']:.6g} {m['edge']}"
    return None


def build_netlists(circuit):
    """(파일명, 본문) 목록. tran과 ac는 별도 파일로 분리한다."""
    body = list(circuit["netlist_body"])
    an = circuit["analysis"]
    files = []
    tran_meas = [meas_directive("tran", m) for m in circuit["measurements"]
                 if m["kind"] in ("FIND", "MAX", "INTEG", "WHEN", "TRIG_TARG")]
    tran = body + [f".tran {an['tstep']} {an['tstop']}"] + tran_meas + [".end"]
    files.append(("tran.cir", "\n".join(tran) + "\n"))
    ac_meas = [meas_directive("ac", m) for m in circuit["measurements"]
               if m["kind"] in ("AC_FIND_DB", "AC_WHEN_DB")]
    if ac_meas and an.get("ac"):
        # 배치 모드는 .meas가 참조하는 벡터만 저장하는데 vdb(out)를 벡터명으로 읽지 못해
        # "no data saved" 로 해석을 건너뛴다. 전체 저장을 명시한다.
        ac = body + [".save all", f".ac {an['ac']}"] + ac_meas + [".end"]
        files.append(("ac.cir", "\n".join(ac) + "\n"))
    return files


def parse_meas(text, values):
    for line in text.splitlines():
        mo = MEAS_LINE.match(line)
        if mo:
            try:
                values[mo.group(1).lower()] = float(mo.group(2))
            except ValueError:
                pass


def run_ngspice(ngspice, workdir, cir_name):
    log_name = cir_name.replace(".cir", ".log")
    proc = subprocess.run(
        [ngspice, "-b", "-o", log_name, cir_name],
        cwd=workdir, capture_output=True, text=True, timeout=600,
    )
    values = {}
    parse_meas(proc.stdout, values)
    if (workdir / log_name).exists():
        parse_meas((workdir / log_name).read_text(errors="replace"), values)
    return proc.returncode, values, proc.stdout + proc.stderr


def run_shared(libpath, workdir, cir_name):
    """KiCad 번들 libngspice(공유 라이브러리)로 실행한다."""
    helper = Path(__file__).resolve().parent / "ngspice_shared_batch.py"
    log_name = cir_name.replace(".cir", ".log")
    proc = subprocess.run(
        [sys.executable, "-I", str(helper), str(Path(libpath).resolve()), str((workdir / cir_name).resolve())],
        cwd=workdir, capture_output=True, text=True, timeout=600,
    )
    (workdir / log_name).write_text(proc.stdout + proc.stderr, encoding="utf-8")
    values = {}
    parse_meas(proc.stdout, values)
    return proc.returncode, values, proc.stdout + proc.stderr


def locate_kicad_libngspice(explicit):
    """KiCad 10 AppImage에 번들된 libngspice를 찾거나 AppImage에서 추출한다."""
    if explicit:
        return Path(explicit)
    candidates = [
        ROOT / ".artifacts/kicad-10.0.6-install/libraries/AppDir/shared/lib/libngspice.so.0.0.14",
        ROOT / ".artifacts/kicad-bundled-ngspice/squashfs-root/shared/lib/libngspice.so.0.0.14",
    ]
    for c in candidates:
        if c.exists():
            return c
    appimage = Path("/opt/kicad/10.0.6/kicad-10.0.6-x86_64.AppImage")
    if not appimage.exists():
        return None
    out = ROOT / ".artifacts/kicad-bundled-ngspice"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(appimage), "--appimage-extract", "shared/lib/libngspice.so*"],
                   cwd=out, check=True, capture_output=True)
    found = sorted(out.glob("squashfs-root/shared/lib/libngspice.so.0.0.*"))
    return found[-1] if found else None


def evaluate(circuit, measured):
    rows = []
    for m in circuit["measurements"]:
        name = m["name"]
        theory = m["theory"]
        if m["kind"] == "DERIVED":
            env = {k: v for k, v in measured.items()}
            try:
                value = eval(m["formula"], {"__builtins__": {}}, env)  # noqa: S307 - 사양 내부 식
            except Exception:
                value = None
        else:
            value = measured.get(name.lower())
        if value is None:
            rows.append({"name": name, "theory": theory, "value": None, "err_rel": None, "pass": False,
                         "unit": m.get("unit", "")})
            continue
        if "tol_abs" in m:
            err = abs(value - theory)
            ok = err <= m["tol_abs"]
            rows.append({"name": name, "theory": theory, "value": value, "err_abs": err, "pass": ok,
                         "unit": m.get("unit", "")})
        else:
            err = abs(value - theory) / abs(theory)
            ok = err <= m["tol_rel"]
            rows.append({"name": name, "theory": theory, "value": value, "err_rel": err, "pass": ok,
                         "unit": m.get("unit", "")})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--out", type=Path, default=None,
                    help="작업 디렉터리. 기본값은 엔진별로 분리된 projects/sim-validation-20261022/ngspice-regression[-kicad-bundled]/")
    ap.add_argument("--ngspice", default=shutil.which("ngspice") or "ngspice")
    ap.add_argument("--engine", choices=["system", "kicad-bundled"], default="system",
                    help="system: /usr/bin/ngspice 배치, kicad-bundled: KiCad 10 AppImage의 libngspice 공유 라이브러리")
    ap.add_argument("--kicad-libngspice", default=None, help="kicad-bundled 엔진의 libngspice 경로 지정")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    if args.out is None:
        args.out = DEFAULT_OUT if args.engine == "system" else DEFAULT_OUT.with_name(DEFAULT_OUT.name + "-kicad-bundled")

    if args.engine == "system":
        if not shutil.which(args.ngspice):
            print(f"ngspice를 찾을 수 없습니다: {args.ngspice}", file=sys.stderr)
            return 2
        version = subprocess.run([args.ngspice, "--version"], capture_output=True, text=True).stdout.splitlines()
        version_line = next((l for l in version if "ngspice-" in l), "unknown")
        engine_label = f"system {args.ngspice}: {version_line.strip('* ').strip()}"
        runner = lambda workdir, cir: run_ngspice(args.ngspice, workdir, cir)  # noqa: E731
    else:
        libpath = locate_kicad_libngspice(args.kicad_libngspice)
        if not libpath or not libpath.exists():
            print("KiCad 번들 libngspice를 찾을 수 없습니다.", file=sys.stderr)
            return 2
        probe = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve().parent / "ngspice_shared_batch.py"),
             str(libpath), str(DEFAULT_SPEC)],  # 넷리스트가 아니므로 source는 실패하지만 version은 출력된다
            capture_output=True, text=True, timeout=120,
        )
        version_line = next((l for l in probe.stdout.splitlines() if "ngspice-" in l and "shared" in l), "unknown")
        engine_label = f"kicad-bundled {libpath}: {version_line.strip('* ').strip()}"
        runner = lambda workdir, cir: run_shared(libpath, workdir, cir)  # noqa: E731

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    report = {"engine": args.engine, "ngspice": engine_label, "spec": str(args.spec), "circuits": []}
    all_ok = True
    for circuit in spec["circuits"]:
        workdir = args.out / circuit["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        measured = {}
        logs = []
        for cir_name, text in build_netlists(circuit):
            (workdir / cir_name).write_text(text, encoding="utf-8")
            rc, values, output = runner(workdir, cir_name)
            logs.append({"file": cir_name, "returncode": rc})
            measured.update(values)
        rows = evaluate(circuit, measured)
        ok = all(r["pass"] for r in rows)
        all_ok = all_ok and ok
        report["circuits"].append({"id": circuit["id"], "title": circuit["title"], "pass": ok,
                                   "runs": logs, "measurements": rows})
        print(f"[{'PASS' if ok else 'FAIL'}] {circuit['id']} {circuit['title']}")
        for r in rows:
            if r["value"] is None:
                print(f"    {r['name']:>16s}: 측정 실패 (이론 {r['theory']:.6g} {r['unit']})")
            else:
                err = r.get("err_rel")
                err_txt = f"{err*100:.3f}%" if err is not None else f"abs {r.get('err_abs'):.4g}"
                print(f"    {r['name']:>16s}: {r['value']:.6g} vs {r['theory']:.6g} {r['unit']}  err={err_txt}  {'ok' if r['pass'] else 'FAIL'}")
    report["all_pass"] = all_ok
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ngspice: {report['ngspice']}  전체: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
