#!/usr/bin/env python3
"""Inventory every table *shape* in Liberty files, so each distinct shape can be put
through boson once (shape_probe.py).

It measures shapes and does not interpret the library. For every template
(lu_table_template, power_lut_template, ...) it records its variables and index
lengths; for every table group (cell_rise, fall_constraint, rise_power, ...) its
template, the timing_type it sits under, the index lengths in effect (the table's own
index_N overrides the template's), and the number of values. Tables are grouped into
classes by (table, timing_type, variables, dimensions, overrides). For each class
it keeps the first example's cell and its line range, plus the example's numbers,
so a probe can compare boson against the table.

    shape_census.py lib1.lib [lib2.lib ...] --json shapes.json

Also flags tables whose value count does not match the index grid
(rows x columns x ...): either the file is wrong, or the reader must know a rule
for it.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

TOKEN = re.compile(r'''
    (?P<ws>[ \t\r]+|\\\n|\n) |
    (?P<comment>/\*.*?\*/|//[^\n]*) |
    (?P<str>"(?:[^"\\]|\\.|\\\n)*") |
    (?P<punct>[(){}:;,]) |
    (?P<word>[^\s(){}:;,"]+)
''', re.S | re.X)
TEMPLATE_GROUPS = {"lu_table_template", "power_lut_template", "ocv_table_template",
                   "output_current_template", "pg_current_template", "compact_lut_template",
                   "base_curves", "noise_lut_template", "propagation_lut_template",
                   "iv_lut_template", "maxcap_lut_template", "maxtrans_lut_template"}


def tokens(text: str):
    line = 1
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        val = m.group(kind)
        if kind not in ("ws", "comment"):
            yield kind, val, line
        line += val.count("\n")


def numbers(s: str) -> list[float]:
    out = []
    for x in re.split(r"[,\s\\]+", s.strip().strip('"').replace('"', " ")):
        if x:
            try:
                out.append(float(x))
            except ValueError:
                return []
    return out


class Group:
    __slots__ = ("head", "args", "line", "end", "attrs", "complex", "children", "parent")

    def __init__(self, head, args, line, parent):
        self.head, self.args, self.line, self.parent = head, args, line, parent
        self.end = line
        self.attrs, self.complex, self.children = {}, {}, []


def read_tree(text: str) -> Group:
    """Group/attribute structure only: `head (args) { ... }`, `name : value ;`,
    `name (args) ;`. Values stay as text."""
    root = Group("<file>", [], 0, None)
    cur = root
    toks = list(tokens(text))
    i, n = 0, len(toks)
    while i < n:
        kind, val, line = toks[i]
        if val == "}":
            cur.end = line
            cur = cur.parent or root
            i += 1
            continue
        if kind in ("word", "str") and i + 1 < n and toks[i + 1][1] == ":":
            j = i + 2
            parts = []
            # a simple attribute ends at ';' or '}', or at the end of its line when
            # the library omits the semicolon
            while j < n and toks[j][1] not in (";", "}") and not (parts and toks[j][2] > toks[j - 1][2]):
                parts.append(toks[j][1])
                j += 1
            cur.attrs[val] = " ".join(parts).strip('"')
            i = j + 1 if j < n and toks[j][1] == ";" else j
            continue
        if kind in ("word", "str") and i + 1 < n and toks[i + 1][1] == "(":
            j, depth, args = i + 2, 1, []
            while j < n and depth:
                if toks[j][1] == "(":
                    depth += 1
                elif toks[j][1] == ")":
                    depth -= 1
                    if not depth:
                        break
                if toks[j][1] != ",":
                    args.append(toks[j][1])
                j += 1
            nxt = toks[j + 1][1] if j + 1 < n else ";"
            if nxt == "{":
                g = Group(val, [a.strip('"') for a in args], line, cur)
                cur.children.append(g)
                cur = g
                i = j + 2
            else:
                cur.complex.setdefault(val, []).append(args)
                i = j + 2 if nxt == ";" else j + 1
            continue
        i += 1
    return root


def walk(g: Group):
    yield g
    for c in g.children:
        yield from walk(c)


def ancestor(g: Group, head: str):
    while g is not None and g.head != head:
        g = g.parent
    return g


def index_lengths(g: Group) -> dict[int, list[float]]:
    out = {}
    for k, v in g.complex.items():
        m = re.fullmatch(r"index_(\d)", k)
        if m and v:
            out[int(m.group(1))] = numbers(" ".join(v[0]))
    return out


PROBEABLE = {"cell_rise", "cell_fall", "rise_transition", "fall_transition", "rise_constraint", "fall_constraint"}


def census(paths: list[Path], every: bool = False) -> dict:
    templates, classes, problems, files, instances = {}, {}, [], [], []
    for path in paths:
        raw = gzip.open(path, "rt", errors="replace").read() if path.suffix == ".gz" else path.read_text(errors="replace")
        root = read_tree(raw)
        lib = next((g for g in root.children if g.head == "library"), None)
        if lib is None:
            problems.append({"file": str(path), "problem": "no library group"})
            continue
        first_cell = next((g for g in lib.children if g.head == "cell"), None)
        files.append({"file": str(path), "library": lib.args[0] if lib.args else "",
                      "time_unit": lib.attrs.get("time_unit", ""),
                      "capacitive_load_unit": [" ".join(a) for a in lib.complex.get("capacitive_load_unit", [])],
                      "header_end_line": (first_cell.line - 1) if first_cell else lib.end,
                      "cells": sum(g.head == "cell" for g in lib.children)})
        local, tgroups = {}, {}
        for g in lib.children:
            if g.head in TEMPLATE_GROUPS and g.args:
                variables = [g.attrs[k] for k in sorted(g.attrs) if re.fullmatch(r"variable_\d", k)]
                idx = index_lengths(g)
                tgroups[g.args[0]] = g
                local[g.args[0]] = {"kind": g.head, "variables": variables,
                                    "dims": [len(idx[k]) for k in sorted(idx)], "line": g.line}
                templates[f"{path.name}:{g.args[0]}"] = local[g.args[0]]
        for g in walk(lib):
            if "values" not in g.complex or g.head in TEMPLATE_GROUPS:
                continue
            tname = g.args[0] if g.args else ""
            tpl = local.get(tname)
            own = index_lengths(g)
            if tname == "scalar" or (tpl is None and not own):
                variables, dims = [], []
            else:
                variables = (tpl or {}).get("variables", [])
                tdims = (tpl or {}).get("dims", [])
                ndim = max(len(tdims), max(own) if own else 0)
                dims = [len(own[k]) if k in own else (tdims[k - 1] if k - 1 < len(tdims) else 0)
                        for k in range(1, ndim + 1)]
            rows = g.complex["values"][0]
            vals = numbers(" ".join(rows))
            expected = 1
            for d in dims:
                expected *= d
            cell = ancestor(g, "cell")
            timing = ancestor(g, "timing")
            pin = ancestor(g, "pin") or ancestor(g, "bus") or ancestor(g, "bundle")
            ttype = timing.attrs.get("timing_type", "combinational") if timing else ""
            owner = g.parent.head if g.parent else ""
            key = (g.head, owner, ttype, tuple(variables), tuple(dims), tuple(sorted(own)))
            # line ranges of the cell's timing and internal_power groups, so a probe can keep
            # only the group this table belongs to
            unit = timing or ancestor(g, "internal_power")
            rp = (timing.attrs.get("related_pin", "") if timing else "").split()
            rpg = next((x for x in walk(cell) if x.head == "pin" and rp and rp[0] in x.args), None) if cell else None
            loc = {"file": str(path), "cell": cell.args[0] if cell and cell.args else "",
                   "related_direction": rpg.attrs.get("direction", "") if rpg else "",
                   "related_is_clock": (rpg.attrs.get("clock", "").lower() == "true") if rpg else False,
                   "cell_has_latch": any(x.head in ("latch", "latch_bank") for x in cell.children) if cell else False,
                   "cell_lines": [cell.line, cell.end] if cell else None, "line": g.line,
                   "pin": pin.args[0] if pin and pin.args else "",
                   "related_pin": timing.attrs.get("related_pin", "") if timing else "",
                   "timing_sense": timing.attrs.get("timing_sense", "") if timing else "",
                   "when": timing.attrs.get("when", "") if timing else "",
                   "template": tname,
                   "group_lines": [unit.line, unit.end] if unit else None,
                   "removable": [[x.line, x.end] for x in walk(cell) if x.head in ("timing", "internal_power")]
                   if cell else []}
            if len(vals) != expected:
                problems.append({**loc, "table": g.head, "dims": dims, "values": len(vals), "expected": expected,
                                 "problem": "value count does not match the index grid"})
            tpl_idx = {}
            if tpl:
                tpl_idx = index_lengths(tgroups[tname])
            eff = {k: own.get(k, tpl_idx.get(k, [])) for k in range(1, len(dims) + 1)}
            if every and g.head in PROBEABLE and timing is not None and cell is not None:
                instances.append({**loc, "table": g.head, "timing_type": ttype, "variables": variables, "dims": dims,
                                  "index": {str(k): v for k, v in eff.items()}, "values": vals})
            c = classes.get(key)
            if c is None:
                classes[key] = c = {"table": g.head, "owner": owner, "timing_type": ttype, "variables": variables,
                                    "dims": dims, "overrides": sorted(own), "rows": len(rows), "count": 0,
                                    "example": {**loc, "index": {str(k): v for k, v in eff.items()}, "values": vals}}
            c["count"] += 1
    return {"files": files, "templates": templates,
            "classes": sorted(classes.values(), key=lambda c: (-len(c["dims"]), c["table"], c["timing_type"])),
            "problems": problems, "instances": instances}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("libs", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, default=Path("shapes.json"))
    ap.add_argument("--all", action="store_true",
                    help="also record every delay, transition and constraint table, for shape_probe.py --scope all")
    a = ap.parse_args()
    r = census(a.libs, a.all)
    a.json.write_text(json.dumps(r, indent=1))
    for f in r["files"]:
        print(f"{f['file']}: library {f['library']}, {f['cells']} cells, time_unit {f['time_unit']}, "
              f"cap unit {f['capacitive_load_unit']}")
    print(f"\n{len(r['classes'])} table shape classes ({sum(c['count'] for c in r['classes'])} tables):")
    print(f"  {'count':>6s}  {'table':22s} {'in':10s} {'timing_type':22s} {'dims':10s} variables")
    for c in r["classes"]:
        dims = "x".join(map(str, c["dims"])) or "scalar"
        ov = f" (own index_{','.join(map(str, c['overrides']))})" if c["overrides"] else ""
        print(f"  {c['count']:6d}  {c['table']:22s} {c['owner']:10s} {c['timing_type'][:22]:22s} {dims:10s} "
              f"{', '.join(c['variables']) or '-'}{ov}")
    if r["problems"]:
        print(f"\n{len(r['problems'])} table(s) whose value count does not match the grid (first 10):")
        for p in r["problems"][:10]:
            print(f"  {p.get('file')}:{p.get('line')} {p.get('cell')} {p.get('table')} dims {p.get('dims')} "
                  f"values {p.get('values')} expected {p.get('expected')}")
    print(f"\n-> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
