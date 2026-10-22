#!/usr/bin/env python3
"""Qucs-S dataset measurement and pass/fail judgement for sim-validation-20261022.

Reads the spec (spec/spec.json), parses Qucs-S datasets written after an
ngspice run (``<id>.dat.ngspice``: ``<indep time N>`` / ``<dep tran.v(out) time>``
blocks, complex AC values as ``+re+jim``), evaluates every spec measurement by
kind and writes one JSON result per circuit plus a summary.

Standard library only. Run with ``python3 -I``.

Usage:
  python3 -I measure_qucs_dataset.py --spec SPEC --root QUCS_S_DIR [--dataset-suffix .dat.ngspice]
         [--alt-suffix SUFFIX] [--out SUMMARY.json]
"""
from __future__ import annotations

import argparse
import ast
import bisect
import json
import math
import os
import re
import sys

SPICE_SCALE = {
    "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "mil": 25.4e-6,
    "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
}
NUM_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z]*)\s*$")
CPLX_RE = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([+-])j((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)$")


def spice_num(text: str) -> float:
    m = NUM_RE.match(str(text))
    if not m:
        raise ValueError(f"not a SPICE number: {text!r}")
    value = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return value
    for key in ("meg", "mil"):
        if suffix.startswith(key):
            return value * SPICE_SCALE[key]
    if suffix[0] in SPICE_SCALE:
        return value * SPICE_SCALE[suffix[0]]
    return value  # unit letters only (e.g. "s", "Hz")


def parse_value(token: str):
    token = token.strip()
    m = CPLX_RE.match(token)
    if m:
        im = float(m.group(3))
        if m.group(2) == "-":
            im = -im
        return complex(float(m.group(1)), im)
    return float(token)


def parse_dataset(path: str):
    """Return (header, {name: {kind, deps, values}})."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    header = lines[0].strip() if lines else ""
    variables: dict[str, dict] = {}
    cur = None
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("<indep ") or line.startswith("<dep "):
            parts = line[1:-1].split()
            if parts[0] == "indep":
                cur = {"kind": "indep", "name": parts[1], "n": int(parts[2]), "deps": [], "values": []}
            else:
                cur = {"kind": "dep", "name": parts[1], "deps": parts[2:], "values": []}
            continue
        if line in ("</indep>", "</dep>"):
            if cur is not None:
                variables[cur["name"]] = cur
            cur = None
            continue
        if cur is not None:
            cur["values"].append(parse_value(line))
    return header, variables


def interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    j = bisect.bisect_left(xs, x)
    if xs[j] == x:
        return ys[j]
    x0, x1, y0, y1 = xs[j - 1], xs[j], ys[j - 1], ys[j]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def crossing(xs, ys, val, edge="RISE", nth=1):
    count = 0
    for k in range(1, len(xs)):
        y0, y1 = ys[k - 1], ys[k]
        hit = (y0 < val <= y1) if edge == "RISE" else (y0 > val >= y1)
        if hit:
            count += 1
            if count == nth:
                if y1 == y0:
                    return xs[k]
                return xs[k - 1] + (val - y0) * (xs[k] - xs[k - 1]) / (y1 - y0)
    return None


def window_points(xs, ys, a, b):
    pts = [(a, interp(xs, ys, a))]
    pts += [(x, y) for x, y in zip(xs, ys) if a < x < b]
    pts.append((b, interp(xs, ys, b)))
    return pts


def parse_edge(edge: str):
    kind, _, n = (edge or "RISE=1").partition("=")
    return kind.strip().upper(), int(n or 1)


ALLOWED_AST = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)


def eval_formula(formula: str, names: dict):
    tree = ast.parse(formula, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_AST):
            raise ValueError(f"formula node not allowed: {type(node).__name__}")
    return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, dict(names))


def signal_arrays(variables, signal: str, analysis: str):
    """Map spec signal names to dataset vectors. Returns (x, y, var_name)."""
    sig = signal.strip()
    if analysis == "ac":
        node = re.match(r"^v(?:db)?\((.+)\)$", sig, re.I)
        name = f"ac.v({node.group(1)})"
    else:
        name = f"tran.{sig}"
    if name not in variables:
        raise KeyError(f"dataset has no {name}; have {sorted(variables)}")
    var = variables[name]
    indep = var["deps"][0]
    xs = [float(v.real if isinstance(v, complex) else v) for v in variables[indep]["values"]]
    ys = var["values"]
    if len(xs) != len(ys):
        raise ValueError(f"{name}: {len(ys)} values vs {len(xs)} {indep} points")
    return xs, ys, name


def measure(meas: dict, variables: dict, done: dict):
    kind = meas["kind"]
    if kind == "DERIVED":
        return eval_formula(meas["formula"], done), "formula " + meas["formula"]
    if kind.startswith("AC_"):
        xs, ys, name = signal_arrays(variables, meas["signal"], "ac")
        db = [20.0 * math.log10(abs(v)) for v in ys]
        lf = [math.log10(f) for f in xs]
        if kind == "AC_FIND_DB":
            f = spice_num(meas["at"])
            return interp(lf, db, math.log10(f)), f"{name} 20*log10|V| at {f:g} Hz (log-f interpolation)"
        if kind == "AC_WHEN_DB":
            edge, nth = parse_edge(meas.get("edge", "FALL=1"))
            x = crossing(lf, db, float(meas["val"]), edge, nth)
            return (None if x is None else 10.0 ** x), f"{name} dB {edge}={nth} crossing of {meas['val']} (log-f interpolation)"
        raise ValueError(kind)
    xs, ys, name = signal_arrays(variables, meas["signal"], "tran")
    ys = [float(v.real if isinstance(v, complex) else v) for v in ys]
    if kind == "FIND":
        t = spice_num(meas["at"])
        return interp(xs, ys, t), f"{name} at {t:g} s (linear interpolation)"
    if kind == "MAX":
        a, b = spice_num(meas["from"]), spice_num(meas["to"])
        return max(y for _, y in window_points(xs, ys, a, b)), f"{name} max over [{a:g}, {b:g}] s"
    if kind == "INTEG":
        a, b = spice_num(meas["from"]), spice_num(meas["to"])
        pts = window_points(xs, ys, a, b)
        total = sum((x1 - x0) * (y0 + y1) / 2.0 for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
        return total, f"{name} trapezoidal integral over [{a:g}, {b:g}] s"
    if kind == "WHEN":
        edge, nth = parse_edge(meas.get("edge"))
        return crossing(xs, ys, float(meas["val"]), edge, nth), f"{name} {edge}={nth} crossing of {meas['val']}"
    if kind == "TRIG_TARG":
        edge, nth = parse_edge(meas.get("edge"))
        t1 = crossing(xs, ys, float(meas["trig_val"]), edge, nth)
        t2 = crossing(xs, ys, float(meas["targ_val"]), edge, nth)
        val = None if (t1 is None or t2 is None) else t2 - t1
        return val, f"{name} {edge}={nth}: t({meas['targ_val']}) - t({meas['trig_val']}) = {t2!r} - {t1!r}"
    raise ValueError(f"unknown kind {kind}")


def judge(meas: dict, value):
    theory = float(meas["theory"])
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, False
    err_rel = abs(value - theory) / abs(theory) if theory != 0 else None
    if "tol_abs" in meas:
        ok = abs(value - theory) <= float(meas["tol_abs"])
    else:
        ok = err_rel is not None and err_rel <= float(meas["tol_rel"])
    return err_rel, bool(ok)


def evaluate(circuit: dict, dataset: str):
    header, variables = parse_dataset(dataset)
    done: dict[str, float] = {}
    results = []
    for meas in circuit["measurements"]:
        try:
            value, how = measure(meas, variables, done)
        except Exception as exc:  # recorded, not raised
            value, how = None, f"ERROR {type(exc).__name__}: {exc}"
        if value is not None:
            done[meas["name"]] = value
        err_rel, ok = judge(meas, value)
        tol = f"tol_abs={meas['tol_abs']}" if "tol_abs" in meas else f"tol_rel={meas['tol_rel']}"
        results.append({
            "name": meas["name"], "kind": meas["kind"], "theory": meas["theory"], "value": value,
            "unit": meas.get("unit", ""), "err_rel": err_rel, "pass": ok,
            "note": f"{how}; {tol}",
        })
    npts = {name: len(v["values"]) for name, v in variables.items() if v["kind"] == "indep"}
    return {
        "id": circuit["id"], "dataset_path": os.path.abspath(dataset), "dataset_header": header,
        "dataset_vectors": sorted(variables), "independent_points": npts,
        "results": results, "all_pass": all(r["pass"] for r in results),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", required=True)
    ap.add_argument("--root", required=True, help="qucs-s output directory containing <id>/ folders")
    ap.add_argument("--dataset-suffix", default=".dat.ngspice")
    ap.add_argument("--alt-suffix", default="", help="optional second dataset per circuit (e.g. CLI --run) to compare")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    summary = {"spec": os.path.abspath(args.spec), "circuits": []}
    for circuit in spec["circuits"]:
        cid = circuit["id"]
        ds = os.path.join(args.root, cid, cid + args.dataset_suffix)
        if not os.path.exists(ds):
            entry = {"id": cid, "dataset_path": os.path.abspath(ds), "results": [], "all_pass": False,
                     "error": "dataset missing"}
        else:
            entry = evaluate(circuit, ds)
            if args.alt_suffix:
                alt = os.path.join(args.root, cid, "cli-run", cid + args.alt_suffix)
                if os.path.exists(alt):
                    alt_entry = evaluate(circuit, alt)
                    diffs = []
                    for a, b in zip(entry["results"], alt_entry["results"]):
                        if a["value"] is None or b["value"] is None:
                            diffs.append(None)
                        else:
                            ref = abs(a["value"]) or 1.0
                            diffs.append(abs(a["value"] - b["value"]) / ref)
                    entry["alt_dataset"] = {"path": os.path.abspath(alt), "all_pass": alt_entry["all_pass"],
                                            "values": [r["value"] for r in alt_entry["results"]],
                                            "max_rel_diff_vs_gui": max((d for d in diffs if d is not None), default=None)}
        with open(os.path.join(args.root, cid, "measurements.json"), "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2, ensure_ascii=False)
        summary["circuits"].append(entry)
        status = "PASS" if entry.get("all_pass") else "FAIL"
        print(f"[{status}] {cid}")
        for r in entry.get("results", []):
            v = "None" if r["value"] is None else f"{r['value']:.10g}"
            e = "None" if r["err_rel"] is None else f"{r['err_rel']:.3e}"
            print(f"    {r['name']:<16} value={v:<16} theory={r['theory']:<22.10g} err_rel={e:<10} pass={r['pass']}")
        if "alt_dataset" in entry:
            print(f"    alt(CLI --run) all_pass={entry['alt_dataset']['all_pass']} max_rel_diff_vs_gui={entry['alt_dataset']['max_rel_diff_vs_gui']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
