#!/usr/bin/env python3
"""Group failing setup paths into families and say how much of each is buffering.

    path_families.py --liberty a.lib \\
        boson=boson_timing.json:boson.v ref=ref_paths.tsv:reference.v \\
        [--reference ref] [--depth N] [--top-families 15] [--out-md families.md] [--out-json families.json]

Each run is label=TIMING:NETLIST. TIMING is boson's
`report_timing -format json` output, or a `paths.tsv` written by the
boson-dc-datapath-compare collect/score scripts (worst path to every
endpoint). Time both netlists with the same boson session settings, the same
libraries and the same SDC, so both sides come from one timer.

A family is the startpoint and endpoint names with every number replaced by
`#` (`tile_3/u_alu/acc_reg[5]` -> `tile_#/u_alu/acc_reg[#]`); `--depth N`
keeps only the first N hierarchy levels of each, for coarser groups. Per
family, over the failing paths of each run:

- endpoints and TNS; the mean violation;
- logic stages (cells that are not buffers, inverters or registers) and
  buffer/inverter stages per path, and the delay of those buffer/inverter
  arcs (input pin to output pin) per path;
- closable: failing paths whose buffer/inverter delay is at least their
  violation. It is an upper bound on what better buffering could recover:
  some buffering is needed for load and distance.

The reference columns are over the same family's paths in the reference run,
failing or not, so a family that only fails in boson still gets a baseline.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cmp import BUFFERING, Graph, def_name, fmt_num, md_table, read_liberty, read_netlist  # noqa: E402

NUM = re.compile(r"\d+")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="label=timing.json|paths.tsv:netlist.v")
    ap.add_argument("--liberty", action="append", required=True)
    ap.add_argument("--reference", help="label used as the baseline (default: the last)")
    ap.add_argument("--top")
    ap.add_argument("--depth", type=int, help="hierarchy levels kept in family names")
    ap.add_argument("--top-families", type=int, default=15)
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    lib = read_liberty(a.liberty)
    runs = {}
    for spec in a.runs:
        label, _, rest = spec.partition("=")
        timing, _, netlist = rest.rpartition(":")
        if not (label and timing and netlist):
            ap.error(f"{spec}: expected label=TIMING:NETLIST")
        g = Graph(read_netlist(netlist, a.top), lib)
        paths = [annotate(p, g) for p in read_paths(Path(timing))]
        runs[label] = paths
        print(f"{label}: {len(paths):,} paths, {sum(p['slack'] < 0 for p in paths):,} failing", file=sys.stderr)
    reference = a.reference or list(runs)[-1]
    report = compare(runs, reference, a.depth)
    md = to_md(report, a.top_families)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(report, indent=1))
    return 0


# ---------------------------------------------------------------- reading

def read_paths(path: Path) -> list[dict]:
    """[{start, end, slack, points: [(pin, arrival)]}] from timing JSON or paths.tsv (ns)."""
    text = path.read_text()
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        out = []
        for p in data.get("paths", []):
            if p.get("path_type", "max") != "max" or p.get("slack_ns") is None:
                continue
            pts = [(q["point"], q["arrival_ns"]) for q in p.get("points", [])
                   if q.get("point") != q.get("net") and q.get("arrival_ns") is not None]
            out.append({"start": p["startpoint"], "end": p["endpoint"], "slack": p["slack_ns"], "points": pts})
        return out
    out = []
    for line in text.splitlines():
        cols = line.split("\t")
        if cols[0] == "P":
            out.append({"start": cols[1], "end": cols[2], "slack": float(cols[3]), "points": []})
        elif cols[0] == "" and out and len(cols) >= 3 and cols[2] not in ("", "INFINITY"):
            out[-1]["points"].append((cols[1], float(cols[2])))
    return out


def annotate(p: dict, g: Graph) -> dict:
    """Split a path into cell arcs (input pin -> output pin of one instance) and class each one."""
    index = g.__dict__.setdefault("_by_name", {def_name(n): i for i, n in enumerate(g.nl.inst_name)})
    logic = buffers = 0
    buffer_delay = 0.0
    prev = None
    for pin, arrival in p["points"]:
        inst = def_name(pin).rpartition("/")[0]
        if prev and prev[0] == inst and inst in index:
            cat = g.category[index[inst]]
            if cat in BUFFERING:
                buffers += 1
                buffer_delay += arrival - prev[1]
            elif cat not in ("sequential", "clock_gate", "macro"):
                logic += 1
        prev = (inst, arrival)
    return {"start": p["start"], "end": p["end"], "slack": p["slack"], "logic": logic, "buffers": buffers,
            "buffer_delay": buffer_delay}


# ---------------------------------------------------------------- families

def family_name(name: str, depth: int | None) -> str:
    name = def_name(name)
    if "/" in name:
        name = name.rpartition("/")[0] if re.search(r"/[A-Z][A-Z0-9]*N?$", name) else name
    parts = NUM.sub("#", name).split("/")
    if depth and len(parts) > depth:
        parts = parts[:depth] + ["..."]
    return "/".join(parts)


def compare(runs: dict, reference: str, depth) -> dict:
    fams = {lb: defaultdict(list) for lb in runs}
    for lb, paths in runs.items():
        for p in paths:
            fams[lb][f"{family_name(p['start'], depth)} -> {family_name(p['end'], depth)}"].append(p)
    out = {"reference": reference, "runs": {}}
    for lb, paths in runs.items():
        failing = [p for p in paths if p["slack"] < 0]
        sample = _stats(paths, all_paths=True) if lb == reference else _stats(failing)
        out["runs"][lb] = {"paths": len(paths), **sample, "families": {}}
        if lb == reference:
            continue
        for key, members in fams[lb].items():
            bad = [p for p in members if p["slack"] < 0]
            if not bad:
                continue
            ref_members = fams[reference].get(key, [])
            out["runs"][lb]["families"][key] = {"run": _stats(bad), "reference": _stats(ref_members, all_paths=True)}
    return out


def _stats(paths, all_paths=False) -> dict:
    failing = [p for p in paths if p["slack"] < 0]
    sample = paths if all_paths else failing
    mean = (lambda xs: statistics.fmean(xs) if xs else None)
    return {"failing": len(failing), "tns": sum(p["slack"] for p in failing),
            "wns": min((p["slack"] for p in failing), default=None),
            "mean_violation": mean([-p["slack"] for p in failing]),
            "paths_in_sample": len(sample),
            "logic_per_path": mean([p["logic"] for p in sample]),
            "buffers_per_path": mean([p["buffers"] for p in sample]),
            "buffer_delay_per_path": mean([p["buffer_delay"] for p in sample]),
            "closable": sum(1 for p in failing if p["buffer_delay"] >= -p["slack"])}


def to_md(report: dict, top: int) -> str:
    ref = report["reference"]
    o = ["# Failing-path families", "",
         f"Per-path columns are over failing paths, and over every path for the reference `{ref}`.", ""]
    o.append(md_table(["run", "paths", "failing", "TNS (ns)", "mean violation (ps)", "logic stages / path",
                       "buf/inv stages / path", "buf/inv delay / path (ps)", "closable by buffering"],
                      [[f"`{lb}`", r["paths"], r["failing"], f"{r['tns']:.3f}", _ps(r["mean_violation"]),
                        _f(r["logic_per_path"]), _f(r["buffers_per_path"]), _ps(r["buffer_delay_per_path"]),
                        r["closable"]] for lb, r in report["runs"].items()]))
    for lb, r in report["runs"].items():
        if lb == ref:
            continue
        o.append(f"## `{lb}` families, worst TNS first (reference `{ref}`)")
        rows = []
        for key, f in sorted(r["families"].items(), key=lambda kv: kv[1]["run"]["tns"])[:top]:
            a, b = f["run"], f["reference"]
            rows.append([f"`{key}`", f"{a['failing']:,} / {a['tns']:.3f}", _ps(a["mean_violation"]),
                         f"{_f(a['buffers_per_path'])} ({_ps(a['buffer_delay_per_path'])} ps)",
                         _f(a["logic_per_path"]), a["closable"],
                         f"{b['failing']:,} / {b['tns']:.3f}" if b["paths_in_sample"] else "no paths",
                         _f(b["buffers_per_path"]), _f(b["logic_per_path"])])
        o.append(md_table(["family", "failing / TNS ns", "mean viol ps", "buf/inv per path (delay)",
                           "logic per path", "closable", f"`{ref}` failing / TNS", f"`{ref}` buf/inv per path",
                           f"`{ref}` logic per path"], rows))
    return "\n".join(o) + "\n"


def _ps(v):
    return "–" if v is None else f"{1000 * v:.0f}"


def _f(v):
    return "–" if v is None else fmt_num(round(v, 1), 1)


if __name__ == "__main__":
    raise SystemExit(main())
