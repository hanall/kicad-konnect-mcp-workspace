#!/usr/bin/env python3
"""Check that each Qucs-S generated ngspice netlist carries the same circuit as spec netlist_body.

For every circuit: writes <id>/<id>.cir (spec netlist_body + analysis directives, the
reference SPICE netlist) and compares element-by-element with the Qucs-S GUI netlist
(<id>.gui-netlist.cir) plus any .INCLUDEd local library. Comparison is token based:
whitespace and case are normalised, two-terminal passive elements (R, C, L) compare
their node pair as an unordered set, and Qucs-S instance prefixes (XX1 for X1) are
reported as a naming difference, not a circuit difference. Standard library only.

Usage: python3 -I check_netlist_equivalence.py --spec SPEC --root QUCS_S_DIR [--out JSON]
"""
import argparse, json, os, re, sys


def directive_lines(analysis):
    out = []
    if analysis.get("type") == "tran":
        out.append(f".tran {analysis['tstep']} {analysis['tstop']}")
    if "ac" in analysis:
        out.append(f".ac {analysis['ac']}")
    return out


def norm_elements(lines):
    """Return {name: canonical token tuple} for element and .model lines."""
    elems = {}
    in_sub = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        if low.startswith((".control", ".endc", ".end", ".include", ".tran", ".ac", "tran ", "ac ", "write ", "destroy", "reset", "exit", "let ")):
            continue
        line = re.sub(r"\s*=\s*", "=", line)
        toks = line.lower().split()
        if toks[0] == ".subckt":
            in_sub += 1
            key = "subckt:" + toks[1]
            elems[key] = tuple(toks)
            continue
        if toks[0] == ".ends":
            in_sub -= 1
            continue
        if toks[0] == ".model":
            elems["model:" + toks[1]] = tuple(toks)
            continue
        name = toks[0]
        if in_sub:
            name = "sub:" + name
        bare = toks[0]
        if bare[0] in "rcl" and len(toks) >= 4:
            toks = [toks[0], *sorted(toks[1:3]), *toks[3:]]
        elems[name] = tuple(toks[1:])
    return elems


def included_files(lines, base):
    files = []
    for raw in lines:
        m = re.match(r'^\s*\.include\s+"?([^"]+)"?\s*$', raw, re.I)
        if m:
            path = m.group(1)
            if "/.mount_" in path:  # AppImage-internal helper (ngspice_mathfunc.inc)
                continue
            files.append(path if os.path.isabs(path) else os.path.join(base, path))
    return files


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    spec = json.load(open(a.spec, encoding="utf-8"))
    report = []
    for c in spec["circuits"]:
        cid = c["id"]
        d = os.path.join(a.root, cid)
        ref_lines = list(c["netlist_body"]) + directive_lines(c["analysis"]) + [".end"]
        with open(os.path.join(d, cid + ".cir"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(ref_lines) + "\n")
        qnet = os.path.join(d, cid + ".gui-netlist.cir")
        qlines = open(qnet, encoding="utf-8").read().splitlines()
        for inc in included_files(qlines, d):
            qlines += open(inc, encoding="utf-8").read().splitlines()
        ref = norm_elements(ref_lines)
        got = norm_elements(qlines)
        renamed = {}
        for k in list(got):
            if k.startswith("xx") and k[1:] in ref and k[1:] not in got:
                renamed[k[1:]] = k
                got[k[1:]] = got.pop(k)
        missing = sorted(set(ref) - set(got))
        extra = sorted(set(got) - set(ref))
        mismatch = {k: {"spec": " ".join(ref[k]), "qucs": " ".join(got[k])}
                    for k in sorted(set(ref) & set(got)) if ref[k] != got[k]}
        ok = not missing and not extra and not mismatch
        report.append({"id": cid, "reference_cir": os.path.join(d, cid + ".cir"), "qucs_netlist": qnet,
                       "equivalent": ok, "elements_compared": len(ref), "missing": missing, "extra": extra,
                       "mismatch": mismatch, "renamed_instances": renamed})
        print(f"[{'EQUIV' if ok else 'DIFF '}] {cid}: {len(ref)} elements; renamed={renamed} missing={missing} extra={extra} mismatch={mismatch}")
    if a.out:
        json.dump(report, open(a.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return 0 if all(r["equivalent"] for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
