#!/usr/bin/env python3
"""What the XOR/XNOR cells of a netlist are for, and the logic cone of one output.

    logic_patterns.py xor  --liberty a.lib netlist.v [--top TOP] [--examples 5] [--out-json xor.json]
    logic_patterns.py cone --liberty a.lib netlist.v --net NAME | --pin INST/PIN [--out-json cone.json]

`xor` classes every 2-input XOR/XNOR cell by the logic around it:

- adder: shares both inputs with a carry cell (AND/NAND/majority/half adder),
  or feeds or is fed by another XOR or a sum cell (a sum or parity chain);
- compare: its output, directly or through one inverter, feeds a gate that
  reduces two or more XOR outputs (an a == b bit feeding an AND/NOR tree);
- conditional invert: one of its inputs drives four or more XORs (a shared
  control that inverts a word, the shape of a 2:1 mux of x and !x);
- other.

`cone` lists the combinational cells in the transitive fanin of one net, up
to registers, ports and macros. A cell is *exclusive* when everything it
drives stays inside the cone, *shared* when it also drives logic outside it.
Count exclusive cells when comparing how two tools built one function: shared
cells (an inverted register bit that many cones use) are not that function's
cost.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cmp import CATEGORIES, fmt_num, load, md_table, parse_cell  # noqa: E402

CARRY = {"simple", "adder_carry", "half_adder", "full_adder"}
SUM = {"xor_xnor", "adder_sum", "full_adder", "half_adder"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("xor", "cone"):
        p = sub.add_parser(name)
        p.add_argument("netlist")
        p.add_argument("--liberty", action="append", required=True)
        p.add_argument("--top")
        p.add_argument("--out-json")
        if name == "xor":
            p.add_argument("--examples", type=int, default=5)
            p.add_argument("--control-fanout", type=int, default=4,
                           help="XORs one input must drive to count as a conditional invert")
        else:
            p.add_argument("--net")
            p.add_argument("--pin", help="inst/pin; its net is used")
    a = ap.parse_args(argv)
    g = load(a.netlist, a.liberty, a.top)
    if a.cmd == "xor":
        d = xor_usage(g, a.control_fanout, a.examples)
        print(xor_md(d))
    else:
        net = find_net(g, a.net, a.pin)
        d = cone(g, net)
        print(cone_md(d))
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(d, indent=1))
    return 0


# ---------------------------------------------------------------- xor

def xor_usage(g, control_fanout: int, n_examples: int) -> dict:
    xors = [i for i, c in enumerate(g.category) if c == "xor_xnor" and len(g.inputs[i]) == 2]
    xor_set = set(xors)
    by_inputs = defaultdict(list)
    for i, row in enumerate(g.inputs):
        if g.category[i] in CARRY:
            by_inputs[frozenset(n for _, n in row)].append(i)
    xors_on_net = Counter(n for i in xors for _, n in g.inputs[i])
    counts, area, examples = Counter(), Counter(), defaultdict(list)
    for i in xors:
        cls = _xor_class(g, i, xor_set, by_inputs, xors_on_net, control_fanout)
        counts[cls] += 1
        area[cls] += g.area[i]
        if len(examples[cls]) < n_examples:
            examples[cls].append(g.nl.inst_name[i])
    total = sum(counts.values())
    return {"xor_cells": total, "xor_area": sum(area.values()),
            "classes": {c: {"cells": counts[c], "area": area[c], "share": counts[c] / total if total else None,
                            "examples": examples[c]} for c in ("adder", "compare", "conditional invert", "other")}}


def _xor_class(g, i, xor_set, by_inputs, xors_on_net, control_fanout) -> str:
    ins = frozenset(n for _, n in g.inputs[i])
    if any(j != i for j in by_inputs.get(ins, ())):
        return "adder"
    out_loads = [j for _, n in g.outputs[i] for j, _ in g.loads.get(n, ())]
    fed_by = [g.driver[n][0] for n in ins if n in g.driver]
    if any(g.category[j] in SUM and j != i and (j in xor_set or g.category[j] != "xor_xnor") for j in out_loads) \
            or any(g.category[j] in ("adder_sum", "full_adder", "half_adder") for j in fed_by):
        return "adder"
    for j in _through_inverter(g, out_loads):
        if g.category[j] in ("simple", "complex") and _xor_fed_inputs(g, j, xor_set) >= 2:
            return "compare"
    if any(xors_on_net[n] >= control_fanout for n in ins):
        return "conditional invert"
    return "other"


def _through_inverter(g, cells):
    for j in cells:
        if g.category[j] == "inverter":
            for _, n in g.outputs[j]:
                for k, _ in g.loads.get(n, ()):
                    yield k
        else:
            yield j


def _xor_fed_inputs(g, j, xor_set) -> int:
    count = 0
    for _, n in g.inputs[j]:
        d = g.driver.get(n)
        if d is None:
            continue
        k = d[0]
        if k not in xor_set and g.category[k] == "inverter":
            src = g.driver.get(g.inputs[k][0][1]) if g.inputs[k] else None
            k = src[0] if src else k
        count += k in xor_set
    return count


def xor_md(d: dict) -> str:
    o = ["# XOR/XNOR usage", "",
         f"{d['xor_cells']:,} two-input XOR/XNOR cells, {fmt_num(d['xor_area'])} um2.", ""]
    o.append(md_table(["used as", "cells", "share", "area (um2)", "examples"],
                      [[c, v["cells"], f"{100 * v['share']:.0f}%" if v["share"] is not None else "–", v["area"],
                        ", ".join(f"`{x}`" for x in v["examples"][:3])] for c, v in d["classes"].items()]))
    return "\n".join(o)


# ---------------------------------------------------------------- cone

def find_net(g, net_name, pin):
    if pin:
        inst, _, p = pin.rpartition("/")
        idx = {n: i for i, n in enumerate(g.nl.inst_name)}.get(inst)
        if idx is None:
            sys.exit(f"instance {inst} not found")
        for q, n in g.nl.pins[idx]:
            if q == p:
                return n
        sys.exit(f"pin {p} not found on {inst}")
    for n, name in enumerate(g.nl.net_name):
        if name == net_name:
            return n
    sys.exit(f"net {net_name} not found (nets merged through assigns or ports keep their highest-level name)")


def cone(g, root: int) -> dict:
    cells, frontier, work, seen = [], Counter(), [root], {root}
    while work:
        n = work.pop()
        d = g.driver.get(n)
        if d is None:
            frontier["port or undriven"] += 1
            continue
        i = d[0]
        if g.category[i] in ("sequential", "macro", "clock_gate"):
            frontier[g.category[i]] += 1
            continue
        cells.append(i)
        for _, m in g.inputs[i]:
            if m not in seen:
                seen.add(m)
                work.append(m)
    inside = set(cells)
    rows = []
    for i in cells:
        shared = any(j not in inside for _, n in g.outputs[i] if n != root for j, _ in g.loads.get(n, ()))
        rows.append({"cell": g.nl.inst_name[i], "type": g.nl.inst_type[i], "category": g.category[i],
                     "function": parse_cell(g.nl.inst_type[i])["function"], "area": g.area[i], "shared": shared})
    excl = [r for r in rows if not r["shared"]]
    return {"net": g.nl.net_name[root], "cells": len(rows), "exclusive": len(excl), "shared": len(rows) - len(excl),
            "exclusive_area": sum(r["area"] for r in excl),
            "exclusive_by_function": dict(Counter(r["function"] for r in excl).most_common()),
            "shared_by_function": dict(Counter(r["function"] for r in rows if r["shared"]).most_common()),
            "exclusive_by_category": {c: n for c, n in Counter(r["category"] for r in excl).items()
                                      if c in CATEGORIES},
            "inputs": dict(frontier), "rows": rows}


def cone_md(d: dict) -> str:
    o = [f"# Fanin cone of `{d['net']}`", "",
         f"- {d['cells']} combinational cells: {d['exclusive']} exclusive ({fmt_num(d['exclusive_area'])} um2), "
         f"{d['shared']} shared with logic outside the cone",
         f"- cone inputs: {d['inputs']}",
         f"- exclusive by function: {d['exclusive_by_function']}",
         f"- shared by function: {d['shared_by_function']}", ""]
    o.append(md_table(["cell", "type", "category", "area", "shared"],
                      [[f"`{r['cell']}`", r["type"], r["category"], r["area"], "yes" if r["shared"] else ""]
                       for r in d["rows"]]))
    return "\n".join(o)


if __name__ == "__main__":
    raise SystemExit(main())
