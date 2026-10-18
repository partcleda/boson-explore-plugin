#!/usr/bin/env python3
"""Structural statistics of a gate-level Verilog netlist (streamed).

    netlist_stats.py anon/netlist.v [--liberty cells.lib ... --map name_map.json] \\
        [--top-nets 25] [--fanout-threshold 32] [--hier-depth 2] [--out-md netlist_stats.md] [--out-json netlist_stats.json]

Run it on the ANONYMIZED netlist.  Reports: cell histogram by class /
function / drive / VT, sequential / multibit / clock-gate / tie counts,
buffer and inverter chains (depth histogram, longest examples), high-fanout
nets with their drivers (unbuffered / weak-driver flags), undriven and
dangling nets, unconnected input pins, dont_touch/keep attributes, per-
hierarchy cell counts (flat '/' names, or the module tree of a hierarchical
netlist), and area if a Liberty file is given.

Pin directions come from --liberty when given (cell names are translated
through --map's celltype table so the anonymized netlist still matches);
otherwise output pins are recognised by name (Y, Z, ZN, Q, QN, X, CO, S, ...).
The liberty file itself is only read locally; nothing from it is printed
except per-cell area totals under the anonymized cell names.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bdlib import (drive_value, fmt, is_output_pin, md_table, open_text, parse_cell, strip_escape,  # noqa: E402
                    verilog_statements)

INST_RE = re.compile(r"^(\\\S+|[A-Za-z_][\w$]*)\s*(#\s*\(.*?\)\s*)?(\\\S+|[A-Za-z_][\w$]*)\s*(\[[^\]]*\])?\s*\((.*)\)\s*;$", re.S)
CONN_RE = re.compile(r"\.\s*(\\\S+|[A-Za-z_][\w$]*)\s*\(\s*((?:[^()]|\([^()]*\))*)\)")
DECL_KW = {"input", "output", "inout", "wire", "reg", "logic", "tri", "supply0", "supply1", "wand", "wor", "tri0", "tri1"}
CONST = re.compile(r"^\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+$|^\d+$")
ATTR = re.compile(r"\(\*\s*(.*?)\s*\*\)")
CLOCK_CLASSES = ("clock_buffer", "clock_inverter", "clock_logic", "clock_gate")
CLOCK_PINS = {"CLK", "CK", "CP", "CPN", "CKN", "CLKN", "C", "G", "GN", "E", "GATE"}


def parse_liberty(paths, cell_map: dict) -> tuple[dict, dict, dict]:
    outputs, area, kind = {}, {}, {}
    for p in paths or []:
        cell = pin = None
        depth = 0
        cell_depth = pin_depth = None
        with open_text(p) as f:
            for line in f:
                m = re.match(r"\s*cell\s*\(\s*\"?([^\")\s]+)", line)
                if m:
                    cell = cell_map.get(m.group(1), m.group(1))
                    outputs.setdefault(cell, set())
                    cell_depth = depth
                m = re.match(r"\s*pin\s*\(\s*\"?([^\")\s]+)", line)
                if m and cell:
                    pin, pin_depth = m.group(1), depth
                m = re.match(r"\s*direction\s*:\s*\"?(\w+)", line)
                if m and cell and pin and m.group(1) in ("output", "inout"):
                    outputs[cell].add(pin)
                m = re.match(r"\s*area\s*:\s*([\d.eE+-]+)", line)
                if m and cell and pin is None:
                    area[cell] = float(m.group(1))
                if cell and re.match(r"\s*(ff|latch|ff_bank|latch_bank)\s*\(", line):
                    kind[cell] = "sequential"
                if cell and "clock_gating_integrated_cell" in line:
                    kind[cell] = "clock_gate"
                depth += line.count("{") - line.count("}")
                if pin is not None and pin_depth is not None and depth <= pin_depth:
                    pin = None
                if cell is not None and cell_depth is not None and depth <= cell_depth:
                    cell, pin = None, None
    return outputs, area, kind


def _nets(expr: str) -> list[str]:
    expr = expr.strip()
    if not expr:
        return []
    if expr.startswith("{"):
        parts = [x.strip() for x in expr.strip("{} ").split(",")]
    else:
        parts = [expr]
    out = []
    for p in parts:
        p = strip_escape(p.strip())
        if p and not CONST.match(p):
            out.append(p)
    return out


def stats(path: Path, outputs=None, area=None, lib_kind=None, top_nets=25, fo_thr=32, hier_depth=2) -> dict:
    outputs, area, lib_kind = outputs or {}, area or {}, lib_kind or {}
    modules = set()
    with open_text(path) as f:
        for line in f:
            m = re.match(r"^\s*module\s+(\\\S+|[A-Za-z_][\w$]*)", line)
            if m:
                modules.add(strip_escape(m.group(1)))
    types = Counter()
    loads = Counter()
    driver_type: dict[str, str] = {}
    multi_driven = Counter()
    bufinv: dict[str, tuple[str, str, str]] = {}  # inst -> (in_net, out_net, type)
    unconnected_in, unconnected_out = Counter(), Counter()
    attrs = Counter()
    mod_cells = defaultdict(Counter)
    mod_children = defaultdict(list)
    instantiated = set()
    ports = {}
    hier = Counter()
    hier_area = Counter()
    seq_by_fn = Counter()
    cur = None
    n_inst = 0
    sub_conns = []
    clockish: dict = {}
    clock_pin_nets: set = set()
    multi = len(modules) > 1

    def q(mod, n):  # per-module net namespace in hierarchical netlists
        return f"{mod}::{n}" if multi else n
    for _, st in verilog_statements(path):
        for am in ATTR.finditer(st):
            for kv in am.group(1).split(","):
                key = kv.split("=")[0].strip().lower()
                if key in ("dont_touch", "keep", "size_only", "keep_hierarchy", "dont_use", "preserve"):
                    attrs[key] += 1
        st = ATTR.sub(" ", st).strip()
        if not st:
            continue
        head = st.split(None, 1)[0]
        if head == "module":
            m = re.match(r"module\s+(\\\S+|[A-Za-z_][\w$]*)", st)
            cur = strip_escape(m.group(1)) if m else None
            continue
        if head == "endmodule":
            cur = None
            continue
        if head in DECL_KW:
            if head in ("input", "output", "inout") and cur:
                body = re.sub(r"(?<!\S)\[[^\]]*\]", " ", st[len(head):])   # vector range, not an escaped name's index
                for w in re.findall(r"\\\S+|[A-Za-z_][\w$]*", body):
                    if w not in DECL_KW and w != "signed":
                        ports.setdefault(cur, {})[strip_escape(w)] = head
            continue
        if head == "assign":
            m = re.match(r"assign\s+(.+?)\s*=\s*(.+?);$", st, re.S)
            if m:
                for n in _nets(m.group(2)):
                    loads[q(cur, n)] += 1
                for n in _nets(m.group(1)):
                    driver_type.setdefault(q(cur, n), "<assign>")
            continue
        m = INST_RE.match(st)
        if not m:
            continue
        typ, inst, conns = strip_escape(m.group(1)), strip_escape(m.group(3)), m.group(5)
        if typ in modules:
            instantiated.add(typ)
            mod_children[cur].append((inst, typ))
            for cm in CONN_RE.finditer(conns):     # resolved after the pass, when every port direction is known
                for n in _nets(cm.group(2)):
                    sub_conns.append((cur, typ, strip_escape(cm.group(1)), n))
            continue
        n_inst += 1
        types[typ] += 1
        mod_cells[cur][typ] += 1
        if "/" in inst:
            key = "/".join(inst.split("/")[:-1][:hier_depth]) or "<top>"
        else:
            key = "<top>"
        hier[key] += 1
        if typ in area:
            hier_area[key] += area[typ]
        info = parse_cell(typ)
        cls = lib_kind.get(typ) or info["class"]
        if cls == "sequential":
            seq_by_fn[info["function"]] += 1
        ins, outs = [], []
        for cm in CONN_RE.finditer(conns):
            pin = strip_escape(cm.group(1))
            ns = _nets(cm.group(2))
            isout = is_output_pin(pin, outputs if outputs else None, typ)
            if not ns:
                if not cm.group(2).strip():
                    if isout:
                        unconnected_out[typ] += 1
                    else:
                        unconnected_in[f"{info['function']}.{pin}"] += 1
                continue
            if cls in ("sequential", "clock_gate") and not isout and pin.upper() in CLOCK_PINS:
                clock_pin_nets.update(q(cur, x) for x in ns)
            for n in ns:
                n = q(cur, n)
                if isout:
                    if n in driver_type:
                        multi_driven[n] += 1
                    driver_type[n] = typ
                    outs.append(n)
                else:
                    loads[n] += 1
                    ins.append(n)
        if cls in ("buffer", "inverter", "clock_buffer", "clock_inverter") and len(ins) == 1 and len(outs) == 1:
            bufinv[inst] = (ins[0], outs[0], typ)
        if cls in CLOCK_CLASSES or cls in ("buffer", "inverter"):
            clockish[inst] = (cls, tuple(ins), tuple(outs), info["function"])
    # top module and its ports
    roots = [m for m in modules if m not in instantiated]
    top = roots[0] if len(roots) == 1 else None
    for par, typ, pin, n in sub_conns:
        d = (ports.get(typ) or {}).get(pin)
        if d == "output":
            driver_type.setdefault(q(par, n), f"<{typ} output>")
        elif d == "input":
            loads[q(par, n)] += 1
        else:
            driver_type.setdefault(q(par, n), f"<{typ} port>")
            loads[q(par, n)] += 1
    for mod in modules:
        mp = ports.get(mod) or {}
        tag = "<input port>" if mod == top else "<module input>"
        for p, d in mp.items():
            if d == "input":
                driver_type.setdefault(q(mod, p), tag)
            elif d == "output":
                loads[q(mod, p)] += 1
    # vector ports (input [3:0] a) are connected bit by bit (a[3])
    def port_dir(n):
        mod, _, net = n.rpartition("::") if multi else (top, "", n)
        b = re.sub(r"\[\d+\]$", "", net)
        return (ports.get(mod) or {}).get(b) if b != net else None
    for n in list(loads):
        if port_dir(n) == "input":
            driver_type.setdefault(n, "<input port>")
    for n in list(driver_type):
        if port_dir(n) == "output":
            loads[n] += 1
    # classify
    by_class, by_fn, by_drive, by_vt = Counter(), Counter(), Counter(), Counter()
    multibit = 0
    total_area = 0.0
    for t, c in types.items():
        info = parse_cell(t)
        cls = lib_kind.get(t) or info["class"]
        by_class[cls] += c
        by_fn[f"{info['function']} ({cls})"] += c
        by_drive[info["drive"] or "?"] += c
        if info["vt"]:
            by_vt[info["vt"]] += c
        if info["multibit"]:
            multibit += c
        total_area += area.get(t, 0.0) * c
    # buffer / inverter chains: consecutive buf/inv joined by fanout-1 nets
    by_in = defaultdict(list)
    out_of = {}
    for inst, (i, o, t) in bufinv.items():
        by_in[i].append(inst)
        out_of[o] = inst
    nxt = {}
    for inst, (i, o, t) in bufinv.items():
        if loads.get(o, 0) == 1 and len(by_in.get(o, [])) == 1:
            nxt[inst] = by_in[o][0]
    has_prev = set(nxt.values())
    chains = []
    for inst in bufinv:
        if inst in has_prev:
            continue
        ch = [inst]
        seen = {inst}
        while ch[-1] in nxt and nxt[ch[-1]] not in seen:
            ch.append(nxt[ch[-1]])
            seen.add(ch[-1])
        if len(ch) >= 2:
            chains.append(ch)
    chains.sort(key=len, reverse=True)
    inv_pairs = sum(1 for ch in chains for a, b in zip(ch, ch[1:])
                    if parse_cell(bufinv[a][2])["class"].endswith("inverter") and parse_cell(bufinv[b][2])["class"].endswith("inverter"))
    depth_hist = Counter(min(len(c), 10) for c in chains)
    # buffer trees: buf/inv whose output feeds >=2 buf/inv
    trees = sum(1 for inst, (i, o, t) in bufinv.items() if len(by_in.get(o, [])) >= 2)
    # nets
    bit_bases = {re.sub(r"\[\d+\]$", "", n) for n in loads if n.endswith("]")} | \
        {re.sub(r"\[\d+\]$", "", n) for n in driver_type if n.endswith("]")}
    undriven = [n for n in loads if n not in driver_type and n not in bit_bases]  # a vector port's base name is not a net
    dangling = [n for n, t in driver_type.items() if loads.get(n, 0) == 0 and not t.startswith("<")]
    hf = sorted(loads.items(), key=lambda kv: -kv[1])[:top_nets]
    hf_rows = []
    for n, fo in hf:
        t = driver_type.get(n)
        info = parse_cell(t) if t and not t.startswith("<") else {"class": t or "undriven", "drive": None}
        flags = []
        if fo >= fo_thr and info["class"] not in ("buffer", "clock_buffer", "inverter", "clock_inverter", "<input port>", "tie"):
            flags.append("unbuffered")
        dv = drive_value(info.get("drive"))
        if fo >= fo_thr and dv is not None and dv <= 1:
            flags.append("weak driver")
        if info["class"] == "tie":
            flags.append("tie net")
        hf_rows.append({"net": n, "fanout": fo, "driver_type": t, "driver_class": info["class"],
                        "driver_drive": info.get("drive"), "flags": flags})
    # module tree rollup (hierarchical netlists)
    memo = {}
    def total(m, stack=()):
        if m in memo:
            return memo[m]
        if m in stack:
            return 0
        t = sum(mod_cells[m].values()) + sum(total(c, stack + (m,)) for _, c in mod_children.get(m, []))
        memo[m] = t
        return t
    mod_rows = []
    if len(modules) > 1:
        inst_count = Counter(c for ch in mod_children.values() for _, c in ch)
        for m in sorted(modules, key=lambda x: -total(x)):
            mod_rows.append({"module": m, "own_cells": sum(mod_cells[m].values()), "total_cells": total(m),
                             "instantiations": inst_count.get(m, 0 if m != top else 1)})
    # clock network: backwards from sequential / ICG clock pins through buffers, inverters and clock cells
    clock_nets = set(clock_pin_nets)
    drives = defaultdict(list)
    for inst, (cls, ins, outs, fn_) in clockish.items():
        for o_ in outs:
            drives[o_].append(inst)
    work = list(clock_nets)
    on_clock = set()
    while work:
        n_ = work.pop()
        for inst in drives.get(n_, []):
            if inst in on_clock:
                continue
            on_clock.add(inst)
            for i_ in clockish[inst][1]:
                if i_ not in clock_nets:
                    clock_nets.add(i_)
                    work.append(i_)
    clock_on_data = Counter(clockish[i][3] for i in clockish if clockish[i][0] in CLOCK_CLASSES and i not in on_clock
                            and clockish[i][0] != "clock_gate")
    data_on_clock = Counter(clockish[i][3] for i in on_clock if clockish[i][0] not in CLOCK_CLASSES)
    fanouts = list(loads.values())
    fo_hist = Counter()
    for v in fanouts:
        fo_hist["1" if v <= 1 else "2-4" if v <= 4 else "5-16" if v <= 16 else "17-64" if v <= 64 else "65-256" if v <= 256 else ">256"] += 1
    return {
        "top": top, "modules": len(modules), "instances": n_inst, "cell_types": len(types),
        "area_um2": total_area if area else None, "by_class": dict(by_class.most_common()),
        "by_function": dict(by_fn.most_common(40)), "by_drive": dict(by_drive.most_common()), "by_vt": dict(by_vt.most_common()),
        "sequential": {"total": by_class.get("sequential", 0), "multibit": multibit, "by_function": dict(seq_by_fn.most_common()),
                       "clock_gates": by_class.get("clock_gate", 0)},
        "ties": by_class.get("tie", 0),
        "clock_network": {"traced": bool(clock_pin_nets), "clock_pin_nets": len(clock_pin_nets), "cells_on_clock": len(on_clock),
                          "clock_class_cells_on_data_nets": sum(clock_on_data.values()),
                          "clock_class_on_data_by_function": dict(clock_on_data.most_common(10)),
                          "data_buffers_on_clock": sum(data_on_clock.values()),
                          "data_buffers_on_clock_by_function": dict(data_on_clock.most_common(10)),
                          "note": "traced backwards from sequential/ICG clock pins through buf/inv/clock cells; "
                                  "stops at module ports in hierarchical netlists"},
        "buffers": {"buffers": by_class.get("buffer", 0) + by_class.get("clock_buffer", 0),
                    "inverters": by_class.get("inverter", 0) + by_class.get("clock_inverter", 0),
                    "chains_ge2": len(chains), "cells_in_chains": sum(len(c) for c in chains),
                    "max_chain": len(chains[0]) if chains else 0, "chain_depth_hist": {str(k) + ("+" if k == 10 else ""): v for k, v in sorted(depth_hist.items())},
                    "inverter_pairs": inv_pairs, "buffer_tree_nodes": trees,
                    "longest_chains": [[f"{x} ({bufinv[x][2]})" for x in c] for c in chains[:5]]},
        "nets": {"with_loads": len(loads), "undriven": len(undriven), "undriven_examples": undriven[:10],
                 "dangling_outputs": len(dangling), "dangling_examples": dangling[:10],
                 "multi_driven": len(multi_driven), "multi_driven_examples": list(multi_driven)[:10],
                 "fanout_hist": dict(fo_hist), "max_fanout": max(fanouts) if fanouts else 0},
        "high_fanout": hf_rows, "fanout_threshold": fo_thr,
        "unconnected_input_pins": dict(unconnected_in.most_common(20)), "unconnected_input_total": sum(unconnected_in.values()),
        "unconnected_output_pins": sum(unconnected_out.values()),
        "attributes": dict(attrs),
        "hierarchy": [{"prefix": k, "cells": v, "area_um2": hier_area.get(k) if area else None} for k, v in hier.most_common(30)],
        "modules_tree": mod_rows[:40],
        "pin_directions": "liberty" if outputs else "pin-name heuristic",
    }


def to_md(d: dict) -> str:
    o = ["# Netlist statistics", ""]
    o.append(f"- {d['instances']:,} leaf cells of {d['cell_types']} types, {d['modules']} module(s), top `{d['top']}`"
             + (f", area {fmt(d['area_um2'])} um2" if d["area_um2"] else "") + f"; pin directions from {d['pin_directions']}")
    s = d["sequential"]
    o.append(f"- sequential {s['total']:,} (multibit {s['multibit']:,}), clock gates {s['clock_gates']:,}, tie cells {d['ties']:,}")
    ck = d.get("clock_network") or {}
    if ck.get("traced"):
        o.append(f"- clock network (traced from {ck['clock_pin_nets']:,} clock-pin nets): {ck['cells_on_clock']:,} cells on it; "
                 f"clock-class cells on data nets {ck['clock_class_cells_on_data_nets']:,} {ck['clock_class_on_data_by_function'] or ''}; "
                 f"data buffers/inverters on the clock {ck['data_buffers_on_clock']:,} {ck['data_buffers_on_clock_by_function'] or ''}")
    b = d["buffers"]
    o.append(f"- buffers {b['buffers']:,}, inverters {b['inverters']:,}; {b['chains_ge2']:,} buf/inv chains of length >=2 "
             f"({b['cells_in_chains']:,} cells, longest {b['max_chain']}), {b['inverter_pairs']:,} back-to-back inverter pairs, "
             f"{b['buffer_tree_nodes']:,} buffer-tree nodes")
    n = d["nets"]
    o.append(f"- nets with loads {n['with_loads']:,}; undriven {n['undriven']:,}, dangling outputs {n['dangling_outputs']:,}, "
             f"multi-driven {n['multi_driven']:,}; max fanout {n['max_fanout']:,}; unconnected input pins {d['unconnected_input_total']:,}")
    if d["attributes"]:
        o.append(f"- attributes: {d['attributes']}")
    o.append("")
    tot = max(d["instances"], 1)
    o.append("## Cells by class")
    o.append(md_table(["class", "cells", "%"], [[k, v, f"{100 * v / tot:.1f}"] for k, v in d["by_class"].items()]))
    o.append("## Top functions")
    o.append(md_table(["function (class)", "cells"], [[k, v] for k, v in list(d["by_function"].items())[:25]]))
    o.append("## Drive strengths")
    o.append(md_table(["drive", "cells"], [[k, v] for k, v in d["by_drive"].items()]))
    if d["by_vt"]:
        o.append("## VT / track variants")
        o.append(md_table(["vt", "cells"], [[k, v] for k, v in d["by_vt"].items()]))
    if s["by_function"]:
        o.append("## Sequential cells")
        o.append(md_table(["function", "cells"], [[k, v] for k, v in s["by_function"].items()]))
    o.append("## Buffer/inverter chain depth")
    o.append(md_table(["length", "chains"], [[k, v] for k, v in b["chain_depth_hist"].items()]))
    for c in b["longest_chains"][:3]:
        o.append("- " + " → ".join(f"`{x}`" for x in c))
    o.append("")
    o.append(f"## Highest-fanout nets (flag threshold {d['fanout_threshold']})")
    o.append(md_table(["net", "fanout", "driver", "class", "drive", "flags"],
                      [[f"`{r['net']}`", r["fanout"], str(r["driver_type"]), r["driver_class"], r["driver_drive"] or "",
                        ", ".join(r["flags"])] for r in d["high_fanout"]]))
    o.append("## Fanout distribution")
    o.append(md_table(["fanout", "nets"], [[k, v] for k, v in d["nets"]["fanout_hist"].items()]))
    if n["undriven"] or n["multi_driven"] or n["dangling_outputs"]:
        o.append("## Connectivity problems")
        o.append(f"- undriven: {', '.join(f'`{x}`' for x in n['undriven_examples'])}")
        o.append(f"- multi-driven: {', '.join(f'`{x}`' for x in n['multi_driven_examples'])}")
        o.append(f"- dangling outputs: {', '.join(f'`{x}`' for x in n['dangling_examples'])}")
        o.append("")
    if d["unconnected_input_pins"]:
        o.append("## Unconnected input pins")
        o.append(md_table(["function.pin", "count"], [[k, v] for k, v in d["unconnected_input_pins"].items()]))
    o.append("## Cells per hierarchy prefix")
    o.append(md_table(["prefix", "cells", "area"], [[f"`{r['prefix']}`", r["cells"], r["area_um2"]] for r in d["hierarchy"]]))
    if d["modules_tree"]:
        o.append("## Module tree")
        o.append(md_table(["module", "own cells", "total cells", "instantiations"],
                          [[f"`{r['module']}`", r["own_cells"], r["total_cells"], r["instantiations"]] for r in d["modules_tree"]]))
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("netlist")
    ap.add_argument("--liberty", action="append", default=[], help="for pin directions / area / ff detection (read locally)")
    ap.add_argument("--map", help="name_map.json, to translate liberty cell names to the anonymized ones")
    ap.add_argument("--top-nets", type=int, default=25)
    ap.add_argument("--fanout-threshold", type=int, default=32)
    ap.add_argument("--hier-depth", type=int, default=2)
    ap.add_argument("--out-md"); ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    cell_map = json.loads(Path(a.map).read_text()).get("celltypes", {}) if a.map else {}
    outs, area, kind = parse_liberty(a.liberty, cell_map) if a.liberty else ({}, {}, {})
    d = stats(Path(a.netlist), outs, area, kind, a.top_nets, a.fanout_threshold, a.hier_depth)
    md = to_md(d)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(d, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
