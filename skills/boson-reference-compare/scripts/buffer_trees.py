#!/usr/bin/env python3
"""Buffer trees of two or more netlists, side by side.

    buffer_trees.py --liberty a.lib boson=boson.v ref=reference.v \\
        [--def boson=boson.def --def ref=reference.def] [--top TOP] [--examples 5] \\
        [--out-md trees.md] [--out-json trees.json]

A tree is one driver (a logic cell, register or input port) through every
buffer and inverter it reaches to the final sinks (the first pins that are
not a buffer or inverter). Buffers and inverters are recognised by their
Liberty function, so a clock NAND2 is a sink, not an inverter. Nets on the
clock network are left out, so compare netlists before clock-tree synthesis
or read the data side only.

Per tree: sinks, levels (buffer/inverter stages to the deepest sink) and
buffer/inverter area. With a DEF per netlist (cell origins, um): the
Manhattan distance from the driver to its farthest sink, and the spacing,
the mean length of each edge that ends at a buffer (driver to first buffer,
buffer to buffer). Tables bin trees by that distance and by sink count.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cmp import BUFFERING, Graph, def_name, md_table, read_def_locations, read_liberty, read_netlist  # noqa: E402

DIST_BINS = ((0, 50, "<50"), (50, 100, "50-100"), (100, 200, "100-200"), (200, 400, "200-400"),
             (400, float("inf"), ">400"))
SINK_BINS = ((1, 1, "1"), (2, 3, "2-3"), (4, 15, "4-15"), (16, 63, "16-63"), (64, float("inf"), "64+"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="label=netlist.v")
    ap.add_argument("--liberty", action="append", required=True)
    ap.add_argument("--def", dest="defs", action="append", default=[], help="label=placed.def")
    ap.add_argument("--top")
    ap.add_argument("--examples", type=int, default=5, help="deepest trees listed per netlist")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    lib = read_liberty(a.liberty)
    defs = dict(d.split("=", 1) for d in a.defs)
    report = {}
    for label, path in (r.split("=", 1) for r in a.runs):
        g = Graph(read_netlist(path, a.top), lib)
        loc = read_def_locations(defs[label]) if label in defs else None
        trees = list(walk_trees(g, loc))
        report[label] = summarize(trees, loc is not None, a.examples)
        if loc is not None:
            missing = sum(1 for n in g.nl.inst_name if def_name(n) not in loc)
            report[label]["cells_without_location"] = missing
        print(f"{label}: {len(trees):,} trees", file=sys.stderr)
    md = to_md(report)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(report, indent=1))
    return 0


def walk_trees(g: Graph, loc):
    """One record per tree root: a net driven by something that is not a buffer or inverter."""
    names = g.nl.inst_name
    where = (lambda i: loc.get(def_name(names[i]))) if loc is not None else (lambda i: None)
    for net in set(g.loads) | g.output_port_nets:
        if net in g.clock_nets or net in (0, 1):     # 0 and 1 are the constant nets
            continue
        d = g.driver.get(net)
        if d is not None and g.category[d[0]] in BUFFERING:
            continue
        root = where(d[0]) if d is not None else None
        sinks, levels, buffers, area, edges, far = 0, 0, 0, 0.0, [], None
        work = [(net, 0, root)]
        seen = {net}
        while work:
            n, level, src = work.pop()
            if n in g.output_port_nets:
                sinks += 1
                levels = max(levels, level)
            for j, _ in g.loads.get(n, ()):
                pos = where(j)
                if g.category[j] in BUFFERING and len(g.outputs[j]) == 1 and g.outputs[j][0][1] not in seen:
                    buffers += 1
                    area += g.area[j]
                    if src is not None and pos is not None:
                        edges.append(abs(pos[0] - src[0]) + abs(pos[1] - src[1]))
                    out = g.outputs[j][0][1]
                    seen.add(out)
                    work.append((out, level + 1, pos))
                    continue
                sinks += 1
                levels = max(levels, level)
                if root is not None and pos is not None:
                    dist = abs(pos[0] - root[0]) + abs(pos[1] - root[1])
                    far = dist if far is None else max(far, dist)
        if sinks:
            yield {"net": g.nl.net_name[net], "sinks": sinks, "levels": levels, "buffers": buffers, "area": area,
                   "edges": edges, "far": far}


def _sink_bin(sinks):
    for lo, hi, label in SINK_BINS:
        if lo <= sinks <= hi:
            return label
    return SINK_BINS[-1][2]


def summarize(trees, placed: bool, n_examples: int) -> dict:
    by_sinks = {lb: _acc() for _, _, lb in SINK_BINS}
    by_dist = {lb: _acc() for _, _, lb in DIST_BINS}
    for t in trees:
        _add(by_sinks[_sink_bin(t["sinks"])], t)
        if placed and t["far"] is not None:
            _add(by_dist[_dist_bin(t["far"])], t)
    deepest = sorted(trees, key=lambda t: (-t["levels"], -t["buffers"]))[:n_examples]
    return {"trees": len(trees), "buffered": sum(1 for t in trees if t["buffers"]),
            "buffers": sum(t["buffers"] for t in trees), "buffer_area": sum(t["area"] for t in trees),
            "by_sinks": {k: _final(v) for k, v in by_sinks.items()},
            "by_distance": {k: _final(v) for k, v in by_dist.items()} if placed else None,
            "deepest": [{k: t[k] for k in ("net", "sinks", "levels", "buffers", "far")} for t in deepest]}


def _dist_bin(d):
    for lo, hi, label in DIST_BINS:
        if lo <= d < hi:
            return label
    return DIST_BINS[-1][2]


def _acc():
    return {"trees": 0, "buffered": 0, "levels": 0, "max_level": 0, "area": 0.0, "edge_sum": 0.0, "edges": 0}


def _add(acc, t):
    acc["trees"] += 1
    acc["buffered"] += bool(t["buffers"])
    acc["levels"] += t["levels"]
    acc["max_level"] = max(acc["max_level"], t["levels"])
    acc["area"] += t["area"]
    acc["edge_sum"] += sum(t["edges"])
    acc["edges"] += len(t["edges"])


def _final(acc):
    return {"trees": acc["trees"], "buffered": acc["buffered"], "buf_inv_area": acc["area"],
            "avg_level": acc["levels"] / acc["trees"] if acc["trees"] else None, "max_level": acc["max_level"],
            "spacing_um": acc["edge_sum"] / acc["edges"] if acc["edges"] else None}


def to_md(report: dict) -> str:
    labels = list(report)
    o = ["# Buffer trees", "",
         "Data nets only (clock network excluded). Levels = buffer/inverter stages to the deepest sink; "
         "spacing = mean length of the edges that end at a buffer or inverter (driver to first buffer, "
         "buffer to buffer), Manhattan between cell origins.", ""]
    o.append(md_table(["netlist", "trees", "buffered", "buffers + inverters", "their area (um2)"],
                      [[f"`{lb}`", r["trees"], r["buffered"], r["buffers"], r["buffer_area"]]
                       for lb, r in report.items()]))

    def side(key, field, bin_label, nd=2):
        vals = []
        for lb in labels:
            table = report[lb][key]
            v = table[bin_label][field] if table else None
            vals.append(v if v is None or isinstance(v, int) else round(v, nd))
        return vals

    if any(report[lb]["by_distance"] for lb in labels):
        o.append("## By driver -> farthest sink distance (um)")
        heads = ["distance"]
        for f in ("trees", "buffered", "avg lvl", "max lvl", "spacing um"):
            heads += [f"{f} `{lb}`" for lb in labels]
        rows = []
        for _, _, b in DIST_BINS:
            rows.append([b] + side("by_distance", "trees", b) + side("by_distance", "buffered", b)
                        + side("by_distance", "avg_level", b) + side("by_distance", "max_level", b)
                        + side("by_distance", "spacing_um", b, 1))
        o.append(md_table(heads, rows))
        for lb in labels:
            if report[lb].get("cells_without_location"):
                o.append(f"- `{lb}`: {report[lb]['cells_without_location']:,} cells had no DEF location "
                         "(left out of distances)")
    o.append("## By number of sinks")
    heads = ["sinks"]
    for f in ("trees", "buffered", "buf/inv area", "avg lvl", "max lvl"):
        heads += [f"{f} `{lb}`" for lb in labels]
    rows = []
    for _, _, b in SINK_BINS:
        rows.append([b] + side("by_sinks", "trees", b) + side("by_sinks", "buffered", b)
                    + side("by_sinks", "buf_inv_area", b, 1) + side("by_sinks", "avg_level", b)
                    + side("by_sinks", "max_level", b))
    o.append(md_table(heads, rows))
    o.append("## Deepest trees")
    for lb in labels:
        o.append(f"- `{lb}`: " + "; ".join(
            f"`{t['net']}` {t['levels']} levels, {t['buffers']} buf/inv, {t['sinks']} sinks"
            + (f", {t['far']:.0f} um" if t["far"] is not None else "") for t in report[lb]["deepest"]))
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
