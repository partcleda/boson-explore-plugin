#!/usr/bin/env python3
"""Audit the arithmetic on a design's critical paths: which architecture boson
chose for each adder/subtractor/comparator, how many mapped cells it puts on
each critical path, and which logic-optimization passes rewrote those cells.

Inputs come from scripts/collect.tcl (a `compile -provenance` session):

    datapath_audit.py <audit_dir> [--min-paths 1] [--json out.json]

Attribution ranks hypotheses, not causes: verify connectivity and use a controlled
pass ablation or stage snapshots before claiming a rewrite serialized a block.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
from pathlib import Path

ARITH = ("Add", "Sub", "Lt", "Gt", "Le", "Ge", "AddCarry", "AddTree", "Neg", "Inc", "Dec", "Cmp", "Mul")
# registers, buffers and inverters on a path are not the structure's depth
NOT_LOGIC = re.compile(r"^(S?E?DF|LH|LN|INV|BUF|CKBD|CKND\d|CKN\D)", re.I)
LOG_DEPTH = ("HanCarlson", "KoggeStone", "Sklansky", "BrentKung", "Prefix", "Sparse", "CarrySelect", "Ladner")


def block_key(b: dict) -> tuple:
    origins = tuple(sorted({(o.get("file", ""), o.get("line", 0),
                            o.get("col", 0), o.get("instance", ""))
                           for o in b.get("origins") or [] if isinstance(o, dict)}))
    return (b.get("block"), b.get("dp_node"), origins, b.get("op", "?"),
            b.get("width") or 0, b.get("lowering") or "-")


def path_cells(path: dict) -> list[str]:
    return list(dict.fromkeys(pt["point"].rsplit("/", 1)[0]
                             for pt in path["points"]
                             if "/" in pt["point"] and pt.get("increment_ns") is not None))


def audit(provenance, timing, min_paths=1, all_blocks=False):
    if not isinstance(provenance, list) or not provenance:
        raise ValueError("prov_paths.json must be a nonempty cell-story array; a summary or restored session is insufficient")
    if any(not isinstance(c, dict) or not isinstance(c.get("cell"), str) for c in provenance):
        raise ValueError("invalid cell story in prov_paths.json")
    prov = {c["cell"]: c for c in provenance}
    if len(prov) != len(provenance):
        raise ValueError("duplicate cell names in prov_paths.json")
    if not isinstance(timing, dict):
        raise ValueError("timing.json must be an object")
    if timing.get("schema_version") != 1 or timing.get("timing_complete") is not True:
        raise ValueError("timing.json requires schema_version 1 and complete timing")
    if not timing.get("paths"):
        raise ValueError("empty timing path sample")
    coverage = {"warnings": timing.get("warnings"), "message": timing.get("message"), "paths": []}
    per_path = collections.defaultdict(list)
    for index, path in enumerate(timing["paths"], 1):
        names = path_cells(path)
        matched = [prov[n] for n in names if n in prov]
        mapped = [c for c in matched if c.get("mapped_in") == "technology mapping"]
        coverage["paths"].append({
            "path": index, "startpoint": path["startpoint"], "endpoint": path["endpoint"],
            "slack_ns": path.get("slack_ns"), "unconstrained": path.get("unconstrained"),
            "cell_candidates": len(names),
            "matched_cells": len(matched), "missing_cells": [n for n in names if n not in prov],
            "technology_mapped_cells": len(mapped),
            "arithmetic_attributed_cells": sum(any(b.get("op", "").startswith(ARITH)
                                                     for b in c.get("blocks") or []) for c in mapped),
            "without_blocks": [c["cell"] for c in matched if not c.get("blocks")],
            "other_stages": dict(collections.Counter(c.get("mapped_in") or "unknown"
                                for c in matched if c.get("mapped_in") != "technology mapping")),
        })
        if path.get("slack_ns") is None or path.get("unconstrained"):
            continue
        cells = collections.defaultdict(dict)
        exact_cells = collections.defaultdict(set)
        for cell in mapped:
            if NOT_LOGIC.match(cell.get("lib_cell") or ""):
                continue
            for block in cell.get("blocks") or []:
                if all_blocks or block.get("op", "").startswith(ARITH):
                    cells[block_key(block)][cell["cell"]] = cell
                    if (block.get("exact") or 0) > 0:
                        exact_cells[block_key(block)].add(cell["cell"])
        for key, by_name in cells.items():
            passes = collections.Counter()
            for cell in by_name.values():
                passes.update({str(x).split(" ")[0] for x in cell.get("aig_passes") or []})
            # a cell that also implements another block is logic merged across the
            # boundary; only cells of this block alone measure its own depth
            own = sum(len(c.get("blocks") or []) == 1 for c in by_name.values())
            per_path[key].append((len(by_name), passes, path["slack_ns"], own, len(exact_cells[key])))
    if not any(p["matched_cells"] for p in coverage["paths"]):
        raise ValueError("no path cells match provenance; check session identity and collection")
    if not any(p.get("slack_ns") is not None and not p.get("unconstrained") for p in timing["paths"]):
        raise ValueError("no constrained paths with usable slack")
    rows = []
    for (block, dp_node, origins, op, width, lowering), samples in per_path.items():
        if len(samples) < min_paths:
            continue
        counts = [n for n, _, _, _, _ in samples]
        owns = [o for _, _, _, o, _ in samples]
        exacts = [e for _, _, _, _, e in samples]
        total = sum(counts)
        passes = collections.Counter()
        for _, ps, _, _, _ in samples:
            passes.update(ps)
        ideal = ideal_cells(op, width, lowering)
        mean = total / len(samples)
        source = next((o for o in origins if o[0]), ("?", 0, 0, ""))
        rows.append({
            "block": block, "dp_node": dp_node,
            "origins": [dict(zip(("file", "line", "col", "instance"), o)) for o in origins],
            "rtl": f"{source[0]}:{source[1]}", "instance": source[3],
            "op": op, "width": width, "architecture": lowering, "paths": len(samples),
            "worst_slack_ps": round(min(s for _, _, s, _, _ in samples) * 1000, 1),
            "cells_per_path_max": max(counts), "cells_per_path_mean": round(mean, 1),
            "own_cells_per_path_max": max(owns), "own_cells_per_path_mean": round(sum(owns) / len(owns), 1),
            "exact_cells_per_path_max": max(exacts), "exact_cells_per_path_mean": round(sum(exacts) / len(exacts), 1),
            "ideal_cells": ideal,
            "rewritten_share": {k: round(c / total, 2) for k, c in passes.most_common() if k != "&nf"},
            "deeper_than_architecture": ideal is not None and mean > 1.5 * ideal,
            # deeper only through labels the engine inferred from neighbouring logic
            "deeper_only_by_inference": ideal is not None and mean > 1.5 * ideal
                                        and sum(exacts) / len(exacts) <= 1.5 * ideal,
        })
    rows.sort(key=lambda r: (r["worst_slack_ps"], -r["cells_per_path_max"], str(r["block"])))
    return rows, coverage


def dominant(cell: dict) -> tuple[str, bool]:
    """The block a cell most belongs to: an exact match first, then the largest share.
    Returns its label and whether the attribution is exact."""
    blocks = cell.get("blocks") or []
    if not blocks:
        return (f"[{cell.get('mapped_in') or 'no provenance'}]", False)
    b = max(blocks, key=lambda b: ((b.get("exact") or 0) > 0, b.get("exact") or 0, b.get("share") or 0))
    o = next((o for o in b.get("origins") or [] if isinstance(o, dict) and o.get("file")), {})
    where = f"{o.get('file', '?').rsplit('/', 1)[-1]}:{o.get('line', 0)}" if o else "?:0"
    label = f"{where} {b.get('op', '?')}{b.get('width') or ''}"
    if b.get("lowering"):
        label += f" ({b['lowering']})"
    return (label, (b.get("exact") or 0) > 0)


def stages(provenance, timing, count=1):
    """Per-stage view of the `count` worst paths: each cell's arrival and delay (its input
    net plus the cell), the block it most belongs to, and the path folded into segments of
    consecutive cells with that block, so the delay each RTL structure costs reads off directly."""
    prov = {c["cell"]: c for c in provenance}
    out = []
    for path in timing["paths"][:count]:
        rows = []
        for pt in path["points"]:
            if "/" not in pt["point"] or pt.get("increment_ns") is None:
                continue
            cell = pt["point"].rsplit("/", 1)[0]
            if rows and rows[-1]["cell"] == cell:
                rows[-1]["incr_ps"] += pt["increment_ns"] * 1000
                rows[-1]["arrival_ps"] = pt["arrival_ns"] * 1000
                continue
            story = prov.get(cell)
            label, exact = dominant(story) if story else ("[missing from provenance]", False)
            rows.append({"cell": cell, "lib_cell": (story or {}).get("lib_cell") or "",
                         "incr_ps": pt["increment_ns"] * 1000, "arrival_ps": pt["arrival_ns"] * 1000,
                         "block": label, "exact": exact})
        segments = []
        for r in rows:
            if segments and segments[-1]["block"] == r["block"]:
                seg = segments[-1]
                seg["cells"] += 1
                seg["ps"] += r["incr_ps"]
                seg["exact_cells"] += r["exact"]
                seg["end_ps"] = r["arrival_ps"]
            else:
                segments.append({"block": r["block"], "cells": 1, "ps": r["incr_ps"],
                                 "exact_cells": int(r["exact"]), "end_ps": r["arrival_ps"]})
        out.append({"startpoint": path["startpoint"], "endpoint": path["endpoint"],
                    "slack_ns": path.get("slack_ns"), "stages": rows, "segments": segments})
    return out


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
    ap.add_argument("--coverage-json", type=Path, help="write per-path coverage, omissions and timing notices")
    ap.add_argument("--all-blocks", action="store_true", help="include mux, priority, Boolean and other non-arithmetic blocks")
    ap.add_argument("--stages", type=int, default=0, metavar="N",
                    help="also print the N worst paths stage by stage, folded into per-block segments")
    a = ap.parse_args()

    try:
        rows, coverage = audit(json.loads((a.audit_dir / "prov_paths.json").read_text()),
                               json.loads((a.audit_dir / "timing.json").read_text()),
                               a.min_paths, a.all_blocks)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"audit unusable: {error}", file=sys.stderr)
        return 1
    for p in coverage["paths"]:
        print(f"path {p['path']}: provenance {p['matched_cells']}/{p['cell_candidates']} cells, "
              f"arithmetic attribution {p['arithmetic_attributed_cells']}/{p['technology_mapped_cells']} mapped, "
              f"other stages {p['other_stages']}, missing {len(p['missing_cells'])}")
    if coverage["warnings"] or coverage["message"]:
        print(f"timing notices: {coverage['warnings']} {coverage['message'] or ''}")
    print("Attribution is shared and may be inferred; verify connectivity before assigning cause.")
    if a.coverage_json:
        a.coverage_json.write_text(json.dumps(coverage, indent=2))

    print(f"{'block':>7s} {'instance':30s} {'rtl':34s} {'op':8s} {'w':>3s} {'architecture':28s} {'paths':>5s} {'slack':>7s} "
          f"{'cells/path':>10s} {'own':>4s} {'exact':>5s} {'ideal':>5s}  rewritten by")
    for r in rows:
        rw = " ".join(f"{k} {int(v * 100)}%" for k, v in r["rewritten_share"].items()) or "-"
        flag = ("  <-- deeper only through inferred labels; check connectivity" if r["deeper_only_by_inference"]
                else "  <-- investigate depth/attribution" if r["deeper_than_architecture"] else "")
        print(f"{str(r['block']):>7s} {r['instance'][-30:]:30s} {r['rtl'][-34:]:34s} {r['op']:8s} {r['width']:3d} {r['architecture'][:28]:28s} {r['paths']:5d} "
              f"{r['worst_slack_ps']:7.1f} {r['cells_per_path_max']:4d}/{r['cells_per_path_mean']:5.1f} {r['own_cells_per_path_max']:4d} {r['exact_cells_per_path_max']:5d} "
              f"{r['ideal_cells'] if r['ideal_cells'] else '-':>5}  {rw}{flag}")
    if not rows:
        print("no matching blocks on constrained paths; inspect coverage and use --all-blocks for control logic")
    if a.stages:
        prov = json.loads((a.audit_dir / "prov_paths.json").read_text())
        timing = json.loads((a.audit_dir / "timing.json").read_text())
        for p in stages(prov, timing, a.stages):
            print(f"\n{p['startpoint']} -> {p['endpoint']}  slack {p['slack_ns'] * 1000:.1f} ps")
            print(f"  {'arrival':>8s} {'incr':>6s}  {'lib cell':26s} block (~ inferred from neighbouring logic)")
            for r in p["stages"]:
                print(f"  {r['arrival_ps']:8.1f} {r['incr_ps']:6.1f}  {r['lib_cell'][:26]:26s} {'' if r['exact'] else '~'}{r['block']}")
            print(f"  {'end':>8s} {'ps':>6s}  {'cells':>5s} {'exact':>5s}  segment")
            for g in p["segments"]:
                print(f"  {g['end_ps']:8.1f} {g['ps']:6.1f}  {g['cells']:5d} {g['exact_cells']:5d}  {g['block']}")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
