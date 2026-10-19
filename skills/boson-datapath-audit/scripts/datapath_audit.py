#!/usr/bin/env python3
"""Audit the arithmetic on a design's critical paths: which architecture boson
chose for each adder/subtractor/comparator, how many mapped cells it puts on
each critical path, and which logic-optimization passes rewrote those cells.

Inputs come from scripts/collect.tcl (a `compile -provenance` session):

    datapath_audit.py <audit_dir> [--min-paths 1] [--json out.json]

A block whose mapped cells per path exceed its architecture's depth, with most
of those cells rewritten by a pass like `dc2 -l`, is a block the rewrite
re-serialized after the datapath selector chose a log-depth form.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

ARITH = ("Add", "Sub", "Lt", "Gt", "Le", "Ge", "AddCarry", "AddTree", "Neg", "Inc", "Dec", "Cmp", "Mul")
LOG_DEPTH = ("HanCarlson", "KoggeStone", "Sklansky", "BrentKung", "Prefix", "Sparse", "CarrySelect", "Ladner")


def block_key(b: dict) -> tuple:
    o = next((x for x in b.get("origins") or [] if isinstance(x, dict) and x.get("file")), {})
    loc = f"{Path(o.get('file', '?')).name}:{o.get('line', '?')}"
    return (loc, b.get("op", "?"), b.get("width") or 0, b.get("lowering") or "-")


def ideal_cells(op: str, width: int, lowering: str) -> int | None:
    """Rough mapped-cell depth of a clean structure: prefix levels + generate + sum.
    Comparators report their 1-bit result width, not the operand width: no estimate."""
    if op in ("Lt", "Gt", "Le", "Ge", "Cmp") or not any(t in lowering for t in LOG_DEPTH):
        return None
    return math.ceil(math.log2(max(width, 2))) + 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audit_dir", type=Path)
    ap.add_argument("--min-paths", type=int, default=1)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    prov = {c["cell"]: c for c in json.loads((a.audit_dir / "prov_paths.json").read_text())}
    tj = json.loads((a.audit_dir / "timing.json").read_text())
    if tj.get("schema_version") != 1 or not tj.get("timing_complete"):
        print(f"timing.json unusable: schema {tj.get('schema_version')}, complete={tj.get('timing_complete')}", file=sys.stderr)
        return 1

    per_path = collections.defaultdict(list)       # block -> [(mapped cells, rewritten-by-pass counts, slack)]
    for p in tj["paths"]:
        if p.get("slack_ns") is None:
            continue
        seen, cells = set(), collections.defaultdict(list)
        for pt in p["points"]:
            name = pt["point"].rsplit("/", 1)[0]
            if name in seen or name not in prov:
                continue
            seen.add(name)
            c = prov[name]
            if c.get("mapped_in") != "technology mapping":   # repair buffers/clones are not the structure
                continue
            for b in c.get("blocks") or []:
                if b.get("op", "").startswith(ARITH):
                    cells[block_key(b)].append(c)
        for k, cs in cells.items():
            passes = collections.Counter()
            for c in cs:
                for x in {str(x).split(" ")[0] for x in c.get("aig_passes") or []}:
                    passes[x] += 1
            per_path[k].append((len(cs), passes, p["slack_ns"]))

    rows = []
    for (loc, op, w, low), v in per_path.items():
        if len(v) < a.min_paths:
            continue
        n = [x for x, _, _ in v]
        tot = sum(n)
        passes = collections.Counter()
        for _, ps, _ in v:
            passes.update(ps)
        ideal = ideal_cells(op, w, low)
        mean = tot / len(v)
        rows.append({
            "rtl": loc, "op": op, "width": w, "architecture": low, "paths": len(v),
            "worst_slack_ps": round(min(s for _, _, s in v) * 1000, 1),
            "cells_per_path_max": max(n), "cells_per_path_mean": round(mean, 1),
            "ideal_cells": ideal,
            "rewritten_share": {k: round(c / tot, 2) for k, c in passes.most_common() if k not in ("&nf",)},
            "deeper_than_architecture": ideal is not None and mean > 1.5 * ideal,
        })
    rows.sort(key=lambda r: (r["worst_slack_ps"], -r["paths"]))

    print(f"{'rtl':34s} {'op':8s} {'w':>3s} {'architecture':28s} {'paths':>5s} {'slack':>7s} "
          f"{'cells/path':>10s} {'ideal':>5s}  rewritten by")
    for r in rows:
        rw = " ".join(f"{k} {int(v * 100)}%" for k, v in r["rewritten_share"].items()) or "-"
        flag = "  <-- deeper than its architecture" if r["deeper_than_architecture"] else ""
        print(f"{r['rtl'][-34:]:34s} {r['op']:8s} {r['width']:3d} {r['architecture'][:28]:28s} {r['paths']:5d} "
              f"{r['worst_slack_ps']:7.1f} {r['cells_per_path_max']:4d}/{r['cells_per_path_mean']:5.1f} "
              f"{r['ideal_cells'] if r['ideal_cells'] else '-':>5}  {rw}{flag}")
    if not rows:
        print("no arithmetic blocks on the sampled paths (was the design compiled with -provenance?)")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
