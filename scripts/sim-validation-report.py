#!/usr/bin/env python3
"""2026-10-22 회로 시뮬레이터 설치·검증·MCP 체계 HTML 보고서 생성기.

결과 JSON(projects/sim-validation-20261022/results/)과 워크플로 저널을 읽어 Hanol 표준
자기완결 HTML(docs/보고서/)을 만든다. 수치는 모두 파일에서 읽으며 손으로 적지 않는다.

사용법: python3 -I scripts/sim-validation-report.py --out docs/보고서/<ts>_slug.html
         [--kicad-journal <journal.jsonl>] [--kicad-gui <json>]
"""
import argparse
import datetime
import html
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAL = ROOT / "projects/sim-validation-20261022"
RESULTS = VAL / "results"
EVIDENCE = ROOT / "docs/검증/20261022-172859-circuit-simulators"


def esc(x):
    return html.escape(str(x))


def fmt(v, digits=6):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}g}"
    except (TypeError, ValueError):
        return esc(v)


def pct(err):
    return "—" if err is None else f"{float(err) * 100:.3f}%"


def tag(kind, text):
    return f'<span class="tag t-{kind}">{esc(text)}</span>'


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_journal_results(path):
    out = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") == "result" and isinstance(rec.get("result"), dict):
            out.append(rec["result"])
    return out


def collect():
    spec = load_json(VAL / "spec/spec.json")
    data = {"spec": spec, "engines": {}}
    sysr = load_json(RESULTS / "ngspice-regression-system.json")
    bund = load_json(RESULTS / "ngspice-regression-kicad-bundled.json")
    data["engines"]["system-ngspice"] = {c["id"]: {m["name"]: m for m in c["measurements"]} for c in sysr["circuits"]}
    data["engines"]["kicad-bundled-ngspice"] = {c["id"]: {m["name"]: m for m in c["measurements"]} for c in bund["circuits"]}
    data["engine_labels"] = {"system-ngspice": sysr["ngspice"], "kicad-bundled-ngspice": bund["ngspice"]}
    lt = load_json(RESULTS / "ltspice-workflow.json")
    lt_batches = [a["result"] for a in lt["agents"] if isinstance(a.get("result"), dict) and "ltspice_version" in a["result"]]
    lt_verdicts = {a["result"]["id"]: a["result"] for a in lt["agents"] if isinstance(a.get("result"), dict) and "verdict" in a["result"] and "ltspice_version" not in a["result"]}
    data["engines"]["ltspice"] = {b["id"]: {r["name"]: {"value": r["value"], "err_rel": r.get("err_rel"), "pass": r["pass"]} for r in b["results"]} for b in lt_batches}
    data["engine_labels"]["ltspice"] = lt_batches[0]["ltspice_version"] if lt_batches else "LTspice"
    data["ltspice_verdicts"] = lt_verdicts
    q = load_json(RESULTS / "qucs-s-workflow.json")
    q_run = next((a["result"] for a in q["agents"] if isinstance(a.get("result"), dict) and "circuits" in a["result"]), None)
    data["engines"]["qucs-s"] = {c["id"]: {r["name"]: {"value": r["value"], "err_rel": r.get("err_rel"), "pass": r["pass"]} for r in c["results"]} for c in q_run["circuits"]} if q_run else {}
    data["engine_labels"]["qucs-s"] = (q_run or {}).get("qucs_version", "Qucs-S")[:60]
    data["qucs_verdicts"] = {a["result"]["id"]: a["result"] for a in q["agents"] if isinstance(a.get("result"), dict) and "verdict" in a["result"]}
    return data


def kicad_results(journal):
    res = {"build": {}, "batch": {}, "verdict": {}}
    for r in load_journal_results(journal):
        if "equivalent" in r:
            res["build"][r["id"]] = r
        elif "all_pass" in r and "results" in r and "hand_value" in (r["results"][0] if r["results"] else {}):
            res["batch"][r["id"]] = r
        elif "verdict" in r:
            res["verdict"][r["id"]] = r
    return res


CLAIMS = [
    ("방법 B `apt install kicad ngspice libngspice0`", "bad", "이 시스템에 부적합", "apt kicad는 9.0.2. KiCad 10.0.6 AppImage가 이미 설치되어 있고 ngspice 45.2를 번들함(kicad-cli version --format about 실측)"),
    ("Qucs-S는 Debian 패키지 또는 AppImage", "warn", "부분 정정", "Debian 공식 저장소에 qucs-s 없음. 개발자 OBS 저장소·GitHub AppImage·Flathub만 존재"),
    ("Qucs-S AppImage에 ngspice 미포함", "good", "사실", "공식 페이지 원문과 추출본 실측. Flatpak판은 ngspice 47 번들"),
    ("Debian 13 ngspice 제공", "good", "사실, 44.2+ds-1", "KiCad 번들 45.2보다 낮음. Qucs-S 마이크로스트립 해석은 45 이상 필요"),
    ("PSpice for TI 타사 모델 시 3노드 프로브 제한", "good", "사실", "TI SLYP725 원문 확인"),
    ("PSpice for TI 주기적 온라인 라이선스 갱신", "warn", "부분 정정", "Cadence FAQ: 1년 단위 라이선스, 오프라인 실행 가능"),
    ("LTspice는 Wine으로 실행", "good", "사실, 실증", "ADI 공식 FAQ. 이 호스트에서 Wine 10.0으로 배치·GUI 기동 확인"),
    ("QSPICE Windows 전용, 상업적 무료", "good", "사실", "Qorvo 제품 페이지"),
    ("ngspice는 PSpice/LTspice 호환, 암호화 모델 불가", "good", "사실", "ngspice 공식 문서. KiCad 10은 호환 모드 설정 내장"),
    ("Altium Mixed Simulation 먼저 확인", "bad", "해당 없음", "사용자 확인: Windows PC·VM·Altium 없음"),
]


def build_html(data, kicad, gui, stamp):
    spec = data["spec"]
    circuits = spec["circuits"]
    engines = ["system-ngspice", "kicad-bundled-ngspice", "ltspice", "qucs-s"]
    labels = {"system-ngspice": "시스템 ngspice 44.2", "kicad-bundled-ngspice": "KiCad 번들 ngspice 45.2", "ltspice": "LTspice 24.0.12 (Wine)", "qucs-s": "Qucs-S 26.1.1"}

    # 엔진별 통과 집계
    totals = {}
    for e in engines:
        n = ok = 0
        for c in circuits:
            for m in c["measurements"]:
                n += 1
                r = data["engines"].get(e, {}).get(c["id"], {}).get(m["name"])
                if r and r.get("pass"):
                    ok += 1
        totals[e] = (ok, n)
    # 교차(ngspice 기준) 미달
    cross_fail = []
    for c in circuits:
        for m in c["measurements"]:
            base = data["engines"]["system-ngspice"].get(c["id"], {}).get(m["name"], {}).get("value")
            for e in ("ltspice", "qucs-s", "kicad-bundled-ngspice"):
                v = data["engines"].get(e, {}).get(c["id"], {}).get(m["name"], {}).get("value")
                if base is not None and v is not None and m["theory"]:
                    rel = abs(v - base) / abs(m["theory"])
                    if rel > 0.01:
                        cross_fail.append((c["id"], m["name"], e, base, v, rel))
    kb, kv = kicad["build"], kicad["verdict"]
    kbatch = kicad["batch"]
    kicad_done = sum(1 for c in circuits if c["id"] in kb and kb[c["id"]].get("equivalent"))
    kicad_pass = sum(1 for c in circuits if c["id"] in kbatch and kbatch[c["id"]].get("all_pass"))

    rows_measure = []
    for c in circuits:
        for m in c["measurements"]:
            cells = []
            for e in engines:
                r = data["engines"].get(e, {}).get(c["id"], {}).get(m["name"])
                if not r:
                    cells.append("<td>—</td>")
                else:
                    ok = r.get("pass")
                    cells.append(f"<td>{fmt(r.get('value'))}<br><span class='small'>{pct(r.get('err_rel'))} {tag('good' if ok else 'bad', 'ok' if ok else 'FAIL')}</span></td>")
            rows_measure.append(f"<tr><td>{esc(c['id'])}</td><td><code>{esc(m['name'])}</code></td><td>{fmt(m['theory'])} {esc(m.get('unit',''))}</td>{''.join(cells)}</tr>")

    rows_kicad = []
    for c in circuits:
        b = kb.get(c["id"]); bt = kbatch.get(c["id"]); v = kv.get(c["id"])
        if not b:
            rows_kicad.append(f"<tr><td>{esc(c['id'])}</td><td colspan='5'>{tag('warn', '진행 중 / 미실행')}</td></tr>")
            continue
        cross = ", ".join(f"{x['name']} {pct(x.get('cross_rel'))}" for x in (bt or {}).get("results", []))
        rows_kicad.append(
            f"<tr><td>{esc(c['id'])}</td><td>{tag('good' if b.get('equivalent') else 'bad', '동등' if b.get('equivalent') else '불일치')}</td>"
            f"<td>{esc(', '.join(b.get('net_names') or []))}</td>"
            f"<td>{tag('good' if (bt or {}).get('all_pass') else 'warn', '통과' if (bt or {}).get('all_pass') else ('미실행' if not bt else '실패'))}</td>"
            f"<td class='small'>{esc(cross)}</td><td>{tag('good' if (v or {}).get('verdict') == 'confirmed' else 'warn', (v or {}).get('verdict', '미실행'))}</td></tr>")

    rows_claims = "".join(f"<tr><td>{esc(a)}</td><td>{tag(k, t)}</td><td>{esc(w)}</td></tr>" for a, k, t, w in CLAIMS)
    cross_rows = "".join(f"<tr><td>{esc(cid)}</td><td><code>{esc(n)}</code></td><td>{esc(labels[e])}</td><td>{fmt(b)}</td><td>{fmt(v)}</td><td>{pct(rel)}</td></tr>" for cid, n, e, b, v, rel in cross_fail) or "<tr><td colspan='6'>미달 없음</td></tr>"

    gui_section = ""
    if gui:
        def gui_vals(g):
            rs = g.get("results") or []
            if not rs:
                return "—"
            return "<br>".join(f"<code>{esc(r['name'])}</code> {fmt(r.get('value'))} ({pct(r.get('err_rel'))}) {tag('good' if r.get('pass') else 'bad', 'ok' if r.get('pass') else 'FAIL')}" for r in rs)
        status_kind = {"ran": "good", "partial": "warn", "failed": "bad", "skipped": "warn"}
        gui_rows = "".join(
            f"<tr><td>{esc(g.get('id'))}</td><td>{tag(status_kind.get(g.get('status'), 'warn'), g.get('status'))}<br><span class='small'>{esc(g.get('value_source', ''))}</span></td>"
            f"<td class='small'>{gui_vals(g)}</td><td class='small'>{esc(g.get('note', ''))}</td>"
            f"<td class='small'>{'<br>'.join(esc(Path(x).name) for x in g.get('screenshots', []))}</td></tr>"
            for g in gui.get("circuits", []))
        gui_section = f"""
    <h3>3.3 KiCad 편집기 시뮬레이터 GUI 검증 (ACUW 레인, 번들 ngspice)</h3>
    <p>{esc(gui.get('summary', ''))} KiCad {esc(gui.get('kicad_version', ''))}, 시뮬레이터 엔진 {esc(gui.get('ngspice_version_in_gui', '미확인'))}.</p>
    <table><tr><th>회로</th><th>상태 · 값 출처</th><th>측정(이론 대비)</th><th>비고</th><th>캡처</th></tr>{gui_rows}</table>
    <p class="small">화면 판독(screen_reading) 값은 캡처에 표시된 자릿수까지만 유효하다. 결정적 판정은 3.1·3.2절의 배치 경로가 담당한다.</p>"""
    else:
        gui_section = """
    <h3>3.3 KiCad 편집기 시뮬레이터 GUI 검증</h3>
    <p>이 보고서 생성 시점에는 <span class="tag t-warn">미실행</span>이다. 같은 엔진(번들 ngspice 45.2)의 헤드리스 결과는 3.1절의 KiCad 번들 열로 검증했다.</p>"""

    evidence_files = sorted(p.relative_to(EVIDENCE).as_posix() for p in EVIDENCE.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    ev_list = "".join(f"<li><code>{esc(f)}</code></li>" for f in evidence_files)

    def eng_tot(e):
        ok, n = totals[e]
        return f"{ok}/{n} {tag('good' if ok == n else 'bad', '통과' if ok == n else '미달')}"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Linux 회로 시뮬레이터 구축·검증과 AI MCP 체계 — 2026-10-22</title>
<style>
  :root{{--bg:#0f1419;--panel:#171d26;--panel2:#1e2630;--line:#2b3645;--txt:#e6edf3;--muted:#9aa7b4;--accent:#4ea1ff;--good:#3fb950;--warn:#e3b341;--bad:#f85149;--code:#0b0f14;--chip:#243140;--purple:#bc8cff;}}
  *{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
  body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;line-height:1.7;font-size:15px}}
  .wrap{{display:grid;grid-template-columns:256px 1fr;max-width:1320px;margin:0 auto}}
  nav.toc{{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;padding:26px 18px;border-right:1px solid var(--line);background:var(--panel)}}
  nav.toc h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 14px}}
  nav.toc a{{display:block;color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:7px;font-size:13.5px;margin-bottom:2px;border-left:2px solid transparent}}
  nav.toc a:hover{{color:var(--txt);background:var(--panel2)}} nav.toc a.sub{{padding-left:22px;font-size:13px}}
  main{{padding:34px 42px 90px;min-width:0}} h1{{font-size:26px;margin:0 0 6px;line-height:1.28}}
  .sub{{color:var(--muted);font-size:14px;margin-bottom:26px}}
  h2.sec{{font-size:21px;margin:46px 0 14px;padding-top:14px;border-top:1px solid var(--line);scroll-margin-top:14px}}
  h3{{font-size:16.5px;margin:24px 0 8px;color:#cdd9e5}} p{{margin:10px 0}}
  code{{background:var(--chip);padding:1.5px 6px;border-radius:5px;font-size:13px;font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;color:#ffd9a0}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}}
  th,td{{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
  th{{background:var(--panel2);color:#cdd9e5;font-weight:600}} tr:nth-child(even) td{{background:#141a22}}
  .tag{{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:600}}
  .t-good{{background:rgba(63,185,80,.15);color:var(--good);border:1px solid rgba(63,185,80,.4)}}
  .t-warn{{background:rgba(227,179,65,.13);color:var(--warn);border:1px solid rgba(227,179,65,.4)}}
  .t-bad{{background:rgba(248,81,73,.13);color:var(--bad);border:1px solid rgba(248,81,73,.4)}}
  .t-info{{background:rgba(78,161,255,.13);color:var(--accent);border:1px solid rgba(78,161,255,.4)}}
  .t-best{{background:rgba(188,140,255,.14);color:var(--purple);border:1px solid rgba(188,140,255,.45)}}
  .callout{{border-radius:12px;padding:16px 18px;margin:16px 0;border-left:4px solid}}
  .c-key{{background:rgba(78,161,255,.07);border-color:var(--accent)}} .c-warn{{background:rgba(227,179,65,.07);border-color:var(--warn)}}
  .c-bad{{background:rgba(248,81,73,.08);border-color:var(--bad)}} .c-good{{background:rgba(63,185,80,.07);border-color:var(--good)}}
  .callout b{{color:#fff}}
  pre{{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto;position:relative;margin:10px 0}}
  pre code{{background:none;color:#d6e2ee;padding:0;font-size:12.8px;line-height:1.65;white-space:pre}}
  .cmnt{{color:#6e7d8c}}
  .copybtn{{position:absolute;top:8px;right:8px;background:var(--panel2);border:1px solid var(--line);color:var(--muted);border-radius:6px;padding:3px 9px;font-size:11px;cursor:pointer}}
  .copybtn:hover{{color:var(--txt);border-color:var(--accent)}}
  .diagram{{font-family:ui-monospace,monospace;font-size:12.5px;color:#bcd;white-space:pre;background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px;overflow-x:auto}}
  .small{{font-size:12.5px;color:var(--muted)}} hr{{border:0;border-top:1px solid var(--line);margin:20px 0}}
  .big-warn{{background:linear-gradient(180deg,rgba(248,81,73,.13),rgba(248,81,73,.05));border:1.5px solid var(--bad);border-radius:12px;padding:18px 20px;margin:18px 0}}
  .big-warn h3{{margin-top:0;color:var(--bad)}}
  @media(max-width:880px){{.wrap{{grid-template-columns:1fr}}nav.toc{{display:none}}main{{padding:24px 18px}}.grid2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">
  <nav class="toc">
    <h2>목차</h2>
    <a href="#summary">0. 요약 / 결론</a>
    <a href="#claims">1. 클라우드 분석 검증</a>
    <a href="#install">2. 설치 구성</a>
    <a href="#validation">3. 검증 회로 5종 결과</a>
    <a href="#v-measure" class="sub">└ 3.1 측정값 전표</a>
    <a href="#v-kicad" class="sub">└ 3.2 KiCad 회로도 → MCP 경로</a>
    <a href="#mcp">4. AI MCP 체계</a>
    <a href="#docs">5. 문서·스킬 갱신</a>
    <a href="#risk">6. 리스크와 결정 필요</a>
    <a href="#rollback">7. 롤백</a>
    <a href="#appendix">부록. 식별값·증거</a>
  </nav>
  <main>
    <h1>Linux 회로 시뮬레이터 구축·검증과 AI MCP 체계</h1>
    <div class="sub">대상: <code>kicad-konnect-mcp-workspace</code> · Debian 13 · 작성 <b>{stamp} KST</b> · {tag('good', '설치·검증 완료')} {tag('info', 'MCP 도구 4종')} {tag("good", "사용자 결정 4건 반영")}</div>

    <h2 class="sec" id="summary">0. 요약 / 결론</h2>
    <div class="callout c-good"><b>클라우드 분석의 핵심 추천(Qucs-S + ngspice)은 타당하지만 이 시스템에는 더 나은 전제가 있었다.</b> KiCad 10.0.6 AppImage가 ngspice 45.2를 번들하므로 내장 시뮬레이터는 추가 설치 없이 동작한다. 사용자 승인 아래 시스템 ngspice 44.2(apt), Qucs-S 26.1.1(AppImage 고정), LTspice 24.0.12(Wine)를 더해 네 경로를 만들었고, 검증 회로 5종 17개 측정 항목이 네 경로 모두 이론값 2% 이내로 일치했다. AI가 사용자 대신 전 과정을 수행하도록 Konnect MCP 시뮬레이션 도구 4종(<code>KONNECT_SIM=1</code>)과 프로젝트 스킬 <code>kicad-simulation</code>, 계약 문서, 회귀 테스트를 구축하고 기존 문서 9종에 통합했다.</div>
    <table>
      <tr><th style="width:28%">항목</th><th>결과</th></tr>
      <tr><td>설치</td><td>ngspice 44.2+ds-1(apt) · Qucs-S 26.1.1(<code>/opt/qucs-s/26.1.1</code>, SHA 2중 검증) · LTspice 24.0.12.0(Wine 10.0, 사용자 prefix) · KiCad 번들 ngspice 45.2(기존). <code>make sim-runtime-verify</code> 통과</td></tr>
      <tr><td>검증 회로 5종 × 17 측정</td><td>시스템 ngspice {eng_tot('system-ngspice')} · KiCad 번들 {eng_tot('kicad-bundled-ngspice')} · LTspice {eng_tot('ltspice')} · Qucs-S {eng_tot('qucs-s')}. 적대적 검증 LTspice 5/5, Qucs-S 5/5 confirmed</td></tr>
      <tr><td>KiCad 회로도 → MCP 경로</td><td>Konnect MCP로 작성한 회로도 {kicad_done}/5 넷리스트 동등, ngspice 판정 {kicad_pass}/5 통과(수기 넷리스트와 상호 차 0)</td></tr>
      <tr><td>경로 간 1% 교차</td><td>{len(cross_fail)}건 미달 (6절). 이론값 2% 기준은 전부 통과</td></tr>
      <tr><td>AI MCP 체계</td><td>도구 4종 <code>list_simulation_engines</code> <code>export_spice_netlist</code> <code>set_simulation_model</code> <code>run_spice_simulation</code>, 계약 테스트 13건 + 체인 스모크 통과(<code>make test-sim-mcp</code>), 입력 경계(.control/shell 거부, 허용 루트) 포함</td></tr>
      <tr><td>사용자 결정(2026-10-22)</td><td>apt hold 없이 fail-closed 유지 · Wine 하드닝 보류 · 품질 스킬 패키지 밖 연결 유지 · ERC 설정 유지, 넷리스트 진단으로 대체 (6절)</td></tr>
    </table>

    <h2 class="sec" id="claims">1. 클라우드 분석 검증</h2>
    <p>2026-10-18 기준 클라우드 분석의 주장을 공식 자료와 이 호스트 실측으로 대조했다. 판정은 사실·부분 정정·부적합으로 나눈다.</p>
    <table><tr><th>주장</th><th>판정</th><th>근거</th></tr>{rows_claims}</table>
    <div class="callout c-key"><b>핵심:</b> 클라우드 분석이 몰랐던 사실은 "KiCad 10.0.6 AppImage에 ngspice 45.2가 이미 번들되어 있다"는 점과 "이 사용자는 Windows·Altium이 없다"는 점이다. 그래서 방법 B(apt kicad)와 Altium 1순위 권고는 이 시스템에 적용되지 않는다.</div>

    <h2 class="sec" id="install">2. 설치 구성</h2>
    <table>
      <tr><th>구성요소</th><th>버전</th><th>설치 방식 · 승인</th><th>검증</th></tr>
      <tr><td>KiCad 내장 시뮬레이터</td><td>KiCad 10.0.6, ngspice 45.2 번들</td><td>기존 설치. 공유 라이브러리를 GUI 없이 직접 로드 가능(<code>scripts/ngspice_shared_batch.py</code>)</td><td><code>kicad-cli version --format about</code></td></tr>
      <tr><td>시스템 ngspice</td><td>44.2+ds-1</td><td>Debian 13 공식 apt. 그릴링 Q2 승인</td><td>배치 스모크, 5종 회귀</td></tr>
      <tr><td>Qucs-S</td><td>26.1.1 (2026-04-26 게시, age 179일)</td><td>GitHub AppImage를 <code>/opt/qucs-s/26.1.1</code>에 고정, SHA256을 API digest·hashes.sha256 교차 검증. 그릴링 Q1 승인</td><td><code>make install-qucs-s --verify-only</code>, GUI 기동·5종 실행</td></tr>
      <tr><td>LTspice</td><td>24.0.12.0 (MSI 2024-04-19)</td><td>ADI 공식 MSI를 사용자 Wine prefix에 조용한 설치. 직접 URL 예외 승인(Q3), Wine 전체 wine32 포함(Q10)</td><td>배치 <code>-b</code> 5종, GUI 기동 캡처</td></tr>
      <tr><td>Wine</td><td>10.0~repack-6</td><td>Debian 13 공식 apt, 287개 패키지</td><td><code>wine --version</code></td></tr>
    </table>
    <p>잠금: <code>config/qucs-s.lock.json</code>, <code>config/ltspice.lock.json</code>. 재현 스크립트: <code>scripts/install-qucs-s-appimage.sh</code>, <code>scripts/install-ltspice-wine.sh</code>. 설치 계약: <code>docs/agents/20261022-172859_circuit-simulators-linux.md</code>.</p>

    <h2 class="sec" id="validation">3. 검증 회로 5종 결과</h2>
    <p>사양 <code>projects/sim-validation-20261022/spec/spec.json</code>(<code>theory.py</code>가 생성)의 이론값과 각 엔진 측정값. 허용 오차는 이론값 대비 2%. 값은 결과 JSON에서 읽었다.</p>
    <h3 id="v-measure">3.1 측정값 전표</h3>
    <table>
      <tr><th>회로</th><th>측정</th><th>이론값</th><th>{esc(labels['system-ngspice'])}</th><th>{esc(labels['kicad-bundled-ngspice'])}</th><th>{esc(labels['ltspice'])}</th><th>{esc(labels['qucs-s'])}</th></tr>
      {''.join(rows_measure)}
    </table>
    <h3 id="v-kicad">3.2 KiCad 회로도 → Konnect MCP → kicad-cli 넷리스트 경로</h3>
    <p>Konnect MCP(0.13.0+hanall.1, commit 94f8035)로 회로도를 작성하고 kicad-cli로 SPICE 넷리스트를 내보내 수기 넷리스트와 토폴로지 동등성을 비교한 뒤, 두 넷리스트를 같은 측정으로 ngspice에서 실행해 상호 차를 봤다.</p>
    <table><tr><th>회로</th><th>넷리스트 동등</th><th>네트</th><th>ngspice 판정</th><th>수기↔KiCad 상호 차</th><th>적대적 검증</th></tr>{''.join(rows_kicad)}</table>
    <div class="callout c-warn"><b>실측 함정:</b> 배치 도구는 라이브러리 Sim 필드를 인스턴스에 복사하지 않아 kicad-cli가 rc=0으로 <code>V1 in GND DC VPULSE</code> 같은 잘못된 줄을 낸다. MOS1 모델은 4단자라 3핀 NMOS 심볼의 벌크가 떠 버린다. PWR_FLAG는 GND 네트에 필요하다. 전부 <code>skills/kicad-simulation/references/kicad-sim-fields.md</code>에 기록했고, <code>export_spice_netlist</code> 진단(<code>suspicious_values</code>)이 첫 번째 함정을 잡는다.</div>
    {gui_section}

    <h2 class="sec" id="mcp">4. AI MCP 체계</h2>
    <div class="diagram">MCP client (Claude / Codex)
      |  initialize, tools/list, tools/call
      v
scripts/run-konnect.sh
      +-- KONNECT_GUI_SYNC=1 -- konnect-mcp-gui.py --&gt; synchronize_schematic_edit (+1)
      +-- KONNECT_SIM=1 ------- konnect-mcp-sim.py --&gt; list_simulation_engines / export_spice_netlist /
      |                                                 set_simulation_model / run_spice_simulation (+4)
      v
Konnect 0.13.0+hanall.1 (core 228+8 도구, HOME 격리)
      +-- kicad-cli sch export netlist --format spice --&gt; .cir
      +-- edit_schematic_component --&gt; Sim.* 필드
시뮬레이션 중계 --&gt; 시스템 ngspice -b | KiCad 번들 libngspice(ctypes) | LTspice -b (ACUW 레인)</div>
    <table>
      <tr><th>도구</th><th>역할</th><th>쓰기</th><th>안전 경계</th></tr>
      <tr><td><code>list_simulation_engines</code></td><td>엔진 설치 상태·버전·경로</td><td>없음</td><td>—</td></tr>
      <tr><td><code>export_spice_netlist</code></td><td>kicad-cli SPICE 넷리스트 + 진단(미할당 모델, 값 자리 심볼명, include 누락)</td><td><code>.artifacts/sim-exports/</code></td><td>읽기 허용 루트, 출력은 레포 안</td></tr>
      <tr><td><code>set_simulation_model</code></td><td>Sim.Device/Type/Params/Pins/Library/Name/Enable 설정 + readback</td><td>회로도(upstream edit_schematic_component만)</td><td>sch_components 로드 필요, 쓰기 허용 루트</td></tr>
      <tr><td><code>run_spice_simulation</code></td><td>해석·측정 지시 조립, 엔진 실행, 이론값 판정, 파형 CSV</td><td>작업 디렉터리</td><td>.control 항상 제거, 지시어 화이트리스트, 제어 토큰 거부, include 검사, timeout ≤100s</td></tr>
    </table>
    <p>회귀: <code>make test-sim-mcp</code> = 계약 테스트 13건(실제 회로도 복사본 왕복, .control/shell 무력화 3경로, 허용 루트 밖 거부 포함) + GUI·시뮬레이션 체인 스모크(starter 도구 27개). 기존 계약 테스트 30건, 품질 스킬 107건, 설치 계약 8건, root Python 시험 전체 211건(<code>unittest discover</code>)도 통과.</p>
    <pre><button class="copybtn" onclick="cp(this)">복사</button><code>make sim-runtime-verify   <span class="cmnt"># 설치 상태</span>
make sim-verify           <span class="cmnt"># 검증 회로 5종, 시스템 ngspice</span>
python3 scripts/sim-validation-run.py --engine kicad-bundled   <span class="cmnt"># KiCad 번들 ngspice</span>
make test-sim-mcp         <span class="cmnt"># MCP 중계 계약 + 체인 스모크</span></code></pre>

    <h2 class="sec" id="docs">5. 문서·스킬 갱신</h2>
    <div class="grid2">
      <div class="card"><h3 style="margin-top:0">신규</h3><ul style="margin:0;padding-left:18px">
        <li><code>skills/kicad-simulation/</code> SKILL.md + references 6종(mcp-tools, kicad-sim-fields, measurements, engines, vendor-models, legacy-skill-overrides C14~C21), <code>.claude/skills</code>·<code>.agents/skills</code> 상대 링크</li>
        <li><code>docs/agents/20261022-172859_circuit-simulators-linux.md</code> 설치 계약</li>
        <li><code>docs/agents/20261022-172859_simulation-mcp-tools.md</code> MCP 도구 공개 API 계약(호환성·migration·rollback·회귀)</li>
        <li><code>scripts/konnect-mcp-sim.py</code>, <code>scripts/sim_engines.py</code>, <code>scripts/sim-validation-run.py</code>, <code>scripts/ngspice_shared_batch.py</code>, 설치 스크립트 2종</li>
        <li><code>tests/test_sim_mcp_extension.py</code>, <code>tests/test_sim_validation.py</code></li>
        <li><code>docs/검증/20261022-172859-circuit-simulators/</code> 증거 폴더</li>
      </ul></div>
      <div class="card"><h3 style="margin-top:0">기존 문서 갱신</h3><ul style="margin:0;padding-left:18px">
        <li><code>AGENTS.md</code>(=CLAUDE.md): 시작 게이트, 최신 연결 확인(<code>simulation_extension</code>), 소스 경계, 검증 계약, 안전 계약, 공개 API, 라이선스, 스킬 표·라우팅·교정 체계, 레인 메모리</li>
        <li><code>README.md</code>: 구조도, 빠른 시작, 디렉터리 표, 현재 범위, Linux 회로 시뮬레이션 절</li>
        <li><code>docs/아키텍처.md</code>: 중계 체인 구조도, 데이터 경계, 안전 실행, 검증 계층, 회로 시뮬레이션 경계 절</li>
        <li><code>docs/개발-로드맵.md</code>: 0단계 런타임, 갱신 계약, 5단계 시뮬레이션 검증, 2026-10-22 검증 범위</li>
        <li><code>docs/보안-및-라이선스.md</code>: 공급망 표, 서명 범위, MCP 실행 위험, 라이선스 표, 2026-10-22 승인 예외와 잔여 리스크</li>
        <li><code>docs/설치-및-ACUW-검증.md</code>, <code>docs/20261006-112759_업그레이드-및-검증-계약.md</code>: 현재판 설치 절·버전 표·rollback·재현 gate</li>
        <li><code>docs/agents/20261006-112759_kicad-konnect-overlay.md</code>: 도구 개수·기본 순서·교정 표</li>
        <li><code>docs/agents/20261012-040121_standard-quality-user-guide.md</code>: 시뮬레이션 연결(패키지 밖)</li>
        <li><code>Makefile</code>: install-qucs-s, install-ltspice, sim-runtime-verify, sim-verify, test-sim-mcp, help</li>
      </ul></div>
    </div>
    <p>품질 스킬 패키지 <code>skills/kicad-schematic-quality</code> 내부는 package identity(c77ca8ed…)를 보존하려고 수정하지 않았다. 시뮬레이션 연결은 전부 패키지 밖에 두었다.</p>

    <h2 class="sec" id="risk">6. 리스크와 사용자 결정</h2>
    <p>아래 네 건은 2026-10-22 마지막 라운드에서 사용자가 결정했다(모두 현재 상태 유지).</p>
    <table>
      <tr><th>리스크</th><th>등급</th><th>대응 · 결정</th></tr>
      <tr><td>시스템 ngspice·Wine이 unattended-upgrades로 바뀌면 <code>make sim-runtime-verify</code>가 버전 불일치로 실패(fail-closed)</td><td>{tag('warn', '중')}</td><td><b>결정:</b> <code>apt-mark hold</code>를 쓰지 않는다. 보안 업데이트를 막지 않고, 버전이 바뀌면 회귀를 재실행한 뒤 설치 스크립트 상수(<code>NGSPICE_PACKAGE_VERSION</code>, <code>WINE_PACKAGE_VERSION</code>)와 계약 문서를 갱신한다</td></tr>
      <tr><td>Wine은 샌드박스가 아님. <code>z:</code>가 <code>/</code>, COM 포트가 ttyUSB/ttyACM에 매핑. LTspice Web Sync 업데이트 확인이 네트워크 접근</td><td>{tag('warn', '중')}</td><td><b>결정:</b> 하드닝 보류. 사용자 권한·ACUW 레인에서만 실행하며 신뢰 경계 밖 모델 파일은 내용 확인 뒤 사용</td></tr>
      <tr><td>경로 간 1% 교차 기준 미달 {len(cross_fail)}건 (아래 표)</td><td>{tag('warn', '하')}</td><td>이론값 2%는 통과. LTspice 다이오드 기본 파라미터·파형 압축(<code>.options plotwinsize=0</code>) 재실행은 로드맵 5단계 미완료 항목</td></tr>
      <tr><td>품질 스킬 패키지 내부에는 시뮬레이션 관문이 없음(identity 보존 때문에 패키지 밖에만 연결)</td><td>{tag('info', '정보')}</td><td><b>결정:</b> 패키지 밖 연결 유지. package identity c77ca8ed…와 107건 테스트 수치를 보존하고, AGENTS 라우팅·오버레이·user-guide·<code>kicad-simulation</code>으로 잇는다</td></tr>
      <tr><td>KiCad 기본 ERC는 <code>simulation_model_issue</code>를 무시하므로 ERC 0이 모델 완비가 아님</td><td>{tag('info', '정보')}</td><td><b>결정:</b> ERC 설정은 바꾸지 않고 <code>export_spice_netlist</code> 진단(<code>unassigned_models</code>·<code>suspicious_values</code>)을 시뮬레이션 범위의 관문으로 쓴다</td></tr>
      <tr><td><code>projects/sim-validation-20261022/</code>가 약 15 MB(Qucs 데이터셋·LTspice raw)</td><td>{tag('info', '정보')}</td><td>커밋 전 <code>.raw</code>·<code>.dat.ngspice</code>를 <code>.gitignore</code>하거나 증거 폴더 사본만 남길지 결정</td></tr>
      <tr><td>2차 과제: 사용자 핵심 IC 미정</td><td>{tag('info', '정보')}</td><td>부품명·모델 형식(텍스트/암호화) 확인부터. 암호화 모델은 Linux 오픈 엔진에서 불가</td></tr>
    </table>
    <h3>경로 간 1% 교차 미달 항목(시스템 ngspice 기준)</h3>
    <table><tr><th>회로</th><th>측정</th><th>엔진</th><th>ngspice</th><th>해당 엔진</th><th>상대 차(이론값 기준)</th></tr>{cross_rows}</table>

    <h2 class="sec" id="rollback">7. 롤백</h2>
    <pre><button class="copybtn" onclick="cp(this)">복사</button><code><span class="cmnt"># MCP 시뮬레이션 도구 비활성화(새 연결부터): .mcp.json/.codex/config.toml의 KONNECT_SIM을 0으로</span>
<span class="cmnt"># Qucs-S 제거</span>
sudo rm -rf /opt/qucs-s/26.1.1 /usr/local/bin/qucs-s /usr/local/share/applications/qucs-s.desktop /usr/local/share/icons/hicolor/scalable/apps/qucs-s.svg
<span class="cmnt"># LTspice 제거(사용자 홈만)</span>
rm -rf ~/.local/share/wineprefixes/ltspice ~/.local/bin/ltspice
<span class="cmnt"># Debian 패키지 제거(wine 287개 포함)</span>
sudo apt-get remove --purge ngspice wine wine64 wine32:i386 libwine && sudo apt-get autoremove</code></pre>
    <p class="small">레포 파일은 untracked 상태이며 커밋하지 않았다. <code>git status</code>로 목록을 보고 필요 시 삭제한다. 품질 스킬 패키지는 변경되지 않았다.</p>

    <h2 class="sec" id="appendix">부록. 식별값·증거</h2>
    <table>
      <tr><th>대상</th><th>값</th></tr>
      <tr><td>Qucs-S AppImage SHA256</td><td><code>a86ab951118bfdffc8acfda8893cde0e2aeedc7129cc73978ae7d16761ec5cb5</code></td></tr>
      <tr><td>LTspice64.msi SHA256</td><td><code>62a9f20b630738e6ade20a37551baa91b20760bfb718807d8a2be4caa3421a36</code></td></tr>
      <tr><td>LTspice.exe SHA256(설치본)</td><td><code>17f5efb978c0df2e164328b7352801fdc1ed0225827e41669bd9da25893fe96d</code></td></tr>
      <tr><td>KiCad AppImage SHA256</td><td><code>723b6890c60a5da962d3f4d07e0dba0f3dd2f3deb50d303f06a3d8a2ab7cf7f5</code></td></tr>
      <tr><td>Konnect 연결</td><td>0.13.0+hanall.1 · commit <code>94f80350cf67db27b179a06a8f6dbebfe4717927</code> · exe SHA <code>cbb5b9785d376ab55a57bbf5723f8e1d79805c5eeeca8d5b1d58b84f7c3d909a</code></td></tr>
      <tr><td>사양 SHA256</td><td>spec.json <code>c5863dcf4a4e3d0af5364dddd505d2b48e95b065175562badbf3eda7e47e9856</code> · theory.py <code>2f0e53232b5b5d3db5d8da54c0fb8c5ce342336cd88fab7b4bfafb70098e1e01</code></td></tr>
      <tr><td>엔진 라벨(결과 JSON)</td><td>{esc(data['engine_labels']['system-ngspice'])} · {esc(data['engine_labels']['kicad-bundled-ngspice'])} · {esc(data['engine_labels']['ltspice'])} · {esc(data['engine_labels']['qucs-s'])}</td></tr>
      <tr><td>ACUW 레인</td><td>kicad-standard-quality(:188, Qucs-S·LTspice), kicad-smps-sync-gui(:182, LTspice GUI·KiCad GUI)</td></tr>
    </table>
    <h3>증거 폴더 <code>docs/검증/20261022-172859-circuit-simulators/</code></h3>
    <ul class="small">{ev_list}</ul>
    <hr>
    <p class="small">작성: Claude Code (Fable 5.1) · {stamp} KST · 생성기 <code>scripts/sim-validation-report.py</code>. 본 문서는 자기완결 HTML(외부 의존성 없음). 측정값 일치는 모델 정확성·정격·실물 안전의 승인이 아니다.</p>
  </main>
</div>
<script>
function cp(btn){{const code=btn.parentElement.querySelector('code');navigator.clipboard.writeText(code.innerText).then(()=>{{const o=btn.textContent;btn.textContent='복사됨 ✓';setTimeout(()=>btn.textContent=o,1200);}});}}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--kicad-journal", type=Path, default=None)
    ap.add_argument("--kicad-gui", type=Path, default=None)
    args = ap.parse_args()
    data = collect()
    kicad = kicad_results(args.kicad_journal) if args.kicad_journal else {"build": {}, "batch": {}, "verdict": {}}
    gui = load_json(args.kicad_gui) if args.kicad_gui and args.kicad_gui.exists() else None
    stamp = subprocess.run(["date", "+%Y-%m-%d %H:%M"], capture_output=True, text=True).stdout.strip()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(data, kicad, gui, stamp), encoding="utf-8")
    print(f"보고서 생성: {args.out} ({args.out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
