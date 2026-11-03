#!/usr/bin/env python3
"""Area by mapping category for two or more netlists of the same RTL and library.

    cell_mix.py --liberty a.lib [--liberty b.lib ...] boson=boson.v ref=reference.v \\
        [--reference ref] [--top TOP] [--out-md mix.md] [--out-json mix.json]

Every cell is classed by its Liberty function (see _cmp.CATEGORIES), never by
its name: a clock NAND2 counts as a NAND2, a sum-only and a carry-only cell
count as the two halves of a full adder. Reports, per netlist:

- standard-cell area and cells per category, the delta against the reference
  netlist, and each category's share of the total area gap;
- the cell functions that differ most within each category;
- full-adder accounting: library full / half adders against bits built from a
  separate sum cell and carry cell on the same three inputs;
- cells with two inputs tied to one net, and what function that leaves
  (e.g. an AND-OR-invert gate wired as an XNOR);
- clock-class cells (by name) on data nets, by the function they compute;
- area by threshold-voltage flavour, and cells marked dont_use.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cmp import (BUFFERING, CATEGORIES, PATTERNS, CATEGORY_NOTES, Graph, clock_class, fmt_num, md_table,  # noqa: E402
                  parse_cell, read_liberty, read_netlist, tied_function, vt_of)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="label=netlist.v, two or more")
    ap.add_argument("--liberty", action="append", required=True, help="every Liberty file both tools read")
    ap.add_argument("--reference", help="label the others are compared against (default: the last)")
    ap.add_argument("--top", help="top module (default: the uninstantiated one)")
    ap.add_argument("--functions", type=int, default=8, help="cell functions listed per category")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    runs = [r.split("=", 1) for r in a.runs]
    if any(len(r) != 2 for r in runs) or len(runs) < 2:
        ap.error("give two or more label=netlist.v")
    lib = read_liberty(a.liberty)
    if not lib:
        ap.error("no cells read from the Liberty files")
    reference = a.reference or runs[-1][0]
    if reference not in dict(runs):
        ap.error(f"--reference {reference} is not one of the labels")
    report = {"reference": reference, "runs": {}}
    for label, path in runs:
        g = Graph(read_netlist(path, a.top), lib)
        report["runs"][label] = summarize(g)
        print(f"{label}: {len(g.nl):,} cells read from {path}", file=sys.stderr)
    add_gap(report)
    md = to_md(report, a.functions)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(report, indent=1))
    return 0


def summarize(g: Graph) -> dict:
    nl = g.nl
    cells, area = Counter(), Counter()
    fn_cells, fn_area = defaultdict(Counter), defaultdict(Counter)
    vt_area = Counter()
    dont_use = Counter()
    for i, t in enumerate(nl.inst_type):
        cat = g.category[i]
        cells[cat] += 1
        area[cat] += g.area[i]
        fn = parse_cell(t)["function"]
        fn_cells[cat][fn] += 1
        fn_area[cat][fn] += g.area[i]
        if cat != "macro":
            vt_area[vt_of(t) or "unmarked"] += g.area[i]
        if t in g.lib and g.lib[t].dont_use:
            dont_use[t] += 1
    std = sum(v for k, v in area.items() if k != "macro")
    return {
        "cells": sum(v for k, v in cells.items() if k != "macro"), "std_area": std, "macro_area": area["macro"],
        "unknown_types": sorted(g.unknown_types)[:20],
        "by_category": {c: {"cells": cells[c], "area": area[c]} for c in CATEGORIES if cells[c]},
        "functions": {c: {f: {"cells": fn_cells[c][f], "area": fn_area[c][f]} for f in fn_cells[c]}
                      for c in fn_cells},
        "adders": adder_accounting(g),
        "tied_inputs": tied_inputs(g),
        "clock_class_on_data": clock_class_on_data(g),
        "vt_area": dict(vt_area.most_common()),
        "dont_use_used": dict(dont_use.most_common(20)),
    }


def adder_accounting(g: Graph) -> dict:
    """Library adder cells against full-adder bits built from separate sum and carry cells."""
    by_inputs = defaultdict(lambda: {"adder_sum": 0, "adder_carry": 0})
    counts = Counter()
    for i, cat in enumerate(g.category):
        if cat in ("full_adder", "half_adder", "adder_sum", "adder_carry"):
            counts[cat] += 1
        if cat in ("adder_sum", "adder_carry"):
            nets = frozenset(n for _, n in g.inputs[i])
            if len(nets) == 3:
                by_inputs[nets][cat] += 1
    pairs = sum(min(v["adder_sum"], v["adder_carry"]) for v in by_inputs.values())
    return {"full_adder_cells": counts["full_adder"], "half_adder_cells": counts["half_adder"],
            "sum_cells": counts["adder_sum"], "carry_cells": counts["adder_carry"],
            "split_full_adder_bits": pairs}


def tied_inputs(g: Graph) -> dict:
    """Cells with two or more inputs on one net, keyed 'category -> function after tying'."""
    out = Counter()
    examples = {}
    for i, row in enumerate(g.inputs):
        if len(row) < 2 or g.category[i] in ("sequential", "clock_gate", "macro"):
            continue
        groups = defaultdict(list)
        for pin, net in row:
            groups[net].append(pin)
        ties = [p for p in groups.values() if len(p) > 1]
        if not ties:
            continue
        cell = g.lib.get(g.nl.inst_type[i])
        after = tied_function(cell, ties) if cell else None
        key = f"{g.category[i]} -> {after or '?'}"
        out[key] += 1
        examples.setdefault(key, parse_cell(g.nl.inst_type[i])["function"])
    return {k: {"cells": v, "example_function": examples[k]} for k, v in out.most_common()}


def clock_class_on_data(g: Graph) -> dict:
    """Cells named as clock cells whose outputs are not on a clock network, by function category."""
    out = defaultdict(lambda: {"cells": 0, "area": 0.0})
    on_clock = 0
    for i, t in enumerate(g.nl.inst_type):
        if not clock_class(t):
            continue
        if any(n in g.clock_nets for _, n in g.outputs[i]):
            on_clock += 1
            continue
        out[g.category[i]]["cells"] += 1
        out[g.category[i]]["area"] += g.area[i]
    return {"on_clock_network": on_clock, "on_data_by_category": dict(out),
            "clock_network_traced": bool(g.clock_nets)}


def add_gap(report: dict) -> None:
    ref = report["runs"][report["reference"]]
    for label, r in report["runs"].items():
        if label == report["reference"]:
            continue
        gap = r["std_area"] - ref["std_area"]
        r["gap"] = {"std_area": gap, "ratio": r["std_area"] / ref["std_area"] if ref["std_area"] else None,
                    "by_category": {}}
        for c in CATEGORIES:
            mine = r["by_category"].get(c, {"area": 0.0, "cells": 0})
            theirs = ref["by_category"].get(c, {"area": 0.0, "cells": 0})
            delta = mine["area"] - theirs["area"]
            if not (mine["cells"] or theirs["cells"]):
                continue
            r["gap"]["by_category"][c] = {"delta_area": delta, "delta_cells": mine["cells"] - theirs["cells"],
                                          "share": delta / gap if gap else None}
        r["gap"]["by_pattern"] = {}
        for pattern, members in PATTERNS.items():
            delta = sum(r["gap"]["by_category"].get(c, {}).get("delta_area", 0.0) for c in members)
            r["gap"]["by_pattern"][pattern] = {"delta_area": delta, "share": delta / gap if gap else None}


def to_md(report: dict, n_functions: int) -> str:
    ref_label = report["reference"]
    ref = report["runs"][ref_label]
    labels = list(report["runs"])
    o = ["# Cell mix by mapping category", ""]
    o.append(f"Reference: `{ref_label}`. Categories come from each cell's Liberty function, not its name.")
    o.append("")
    o.append(md_table(["netlist", "std cells", "std area (um2)", "vs reference", "macro area (um2)"],
                      [[f"`{lb}`", r["cells"], r["std_area"],
                        f"{100 * (r['gap']['ratio'] - 1):+.1f}%" if r.get("gap") and r["gap"]["ratio"] else "–",
                        r["macro_area"]] for lb, r in report["runs"].items()]))
    for label in labels:
        r = report["runs"][label]
        if "gap" not in r:
            continue
        o.append(f"## `{label}` against `{ref_label}`: where the {fmt_num(r['gap']['std_area'])} um2 goes")
        o.append(md_table(["mapping pattern", "categories", "delta area", "share of gap"],
                          [[p, ", ".join(PATTERNS[p]), d["delta_area"],
                            f"{100 * d['share']:+.0f}%" if d["share"] is not None else "–"]
                           for p, d in sorted(r["gap"]["by_pattern"].items(), key=lambda kv: -abs(kv[1]["delta_area"]))]))
        rows = []
        for c, d in sorted(r["gap"]["by_category"].items(), key=lambda kv: -abs(kv[1]["delta_area"])):
            mine = r["by_category"].get(c, {"cells": 0, "area": 0.0})
            theirs = ref["by_category"].get(c, {"cells": 0, "area": 0.0})
            rows.append([c, mine["cells"], theirs["cells"], mine["area"], theirs["area"], d["delta_area"],
                         f"{100 * d['share']:+.0f}%" if d["share"] is not None else "–"])
        o.append(md_table(["category", f"cells {label}", f"cells {ref_label}", f"area {label}",
                           f"area {ref_label}", "delta area", "share of gap"], rows))
        o.append("Largest function differences inside the categories that carry the gap:")
        o.append("")
        for c, _ in sorted(r["gap"]["by_category"].items(), key=lambda kv: -abs(kv[1]["delta_area"]))[:5]:
            mine = r["functions"].get(c, {})
            theirs = ref["functions"].get(c, {})
            diffs = sorted(set(mine) | set(theirs), key=lambda f: -abs(mine.get(f, {}).get("area", 0.0)
                                                                       - theirs.get(f, {}).get("area", 0.0)))
            o.append(f"- **{c}** ({CATEGORY_NOTES[c]}): " + ", ".join(
                f"`{f}` {mine.get(f, {}).get('cells', 0):,} vs {theirs.get(f, {}).get('cells', 0):,}"
                for f in diffs[:n_functions]))
        o.append("")
    o.append("## Adders")
    o.append(md_table(["netlist", "full-adder cells", "half-adder cells", "bits from separate sum + carry cells",
                       "sum-only cells", "carry-only cells"],
                      [[f"`{lb}`", r["adders"]["full_adder_cells"], r["adders"]["half_adder_cells"],
                        r["adders"]["split_full_adder_bits"], r["adders"]["sum_cells"], r["adders"]["carry_cells"]]
                       for lb, r in report["runs"].items()]))
    o.append("## Cells with inputs tied together")
    o.append("A gate with two inputs on one net computes a different function; `complex -> xor_xnor` is an "
             "AND-OR-invert gate wired as an XNOR, one cell for an equality bit.")
    o.append("")
    keys = sorted({k for r in report["runs"].values() for k in r["tied_inputs"]})
    o.append(md_table(["category -> function after tying"] + [f"`{lb}`" for lb in labels],
                      [[k] + [report["runs"][lb]["tied_inputs"].get(k, {}).get("cells", 0) for lb in labels]
                       for k in keys]))
    o.append("## Clock-class cells on data nets")
    o.append("Cells named as clock cells whose outputs reach no clock pin, by what they compute. A clock NAND2 "
             "here is data logic, not an inverter.")
    o.append("")
    cats = sorted({c for r in report["runs"].values() for c in r["clock_class_on_data"]["on_data_by_category"]})
    o.append(md_table(["function category"] + [f"`{lb}` cells / area" for lb in labels],
                      [[c] + [f"{d.get('cells', 0):,} / {fmt_num(d.get('area', 0.0))}"
                              for lb in labels
                              for d in [report["runs"][lb]["clock_class_on_data"]["on_data_by_category"].get(c, {})]]
                       for c in cats]))
    o.append("## Threshold-voltage mix by area")
    vts = sorted({v for r in report["runs"].values() for v in r["vt_area"]})
    o.append(md_table(["vt"] + [f"`{lb}`" for lb in labels],
                      [[v] + [f"{100 * report['runs'][lb]['vt_area'].get(v, 0.0) / max(report['runs'][lb]['std_area'], 1e-9):.1f}%"
                              for lb in labels] for v in vts]))
    for lb, r in report["runs"].items():
        if r["dont_use_used"]:
            o.append(f"- `{lb}` uses dont_use cells: {r['dont_use_used']}")
        if r["unknown_types"]:
            o.append(f"- `{lb}`: cell types missing from the Liberty files (counted as macro): {r['unknown_types']}")
        buf = sum(r["by_category"].get(c, {}).get("area", 0.0) for c in BUFFERING)
        o.append(f"- `{lb}`: buffers + inverters {fmt_num(buf)} um2 "
                 f"({100 * buf / max(r['std_area'], 1e-9):.1f}% of std area)")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
