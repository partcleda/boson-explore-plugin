#!/usr/bin/env python3
"""Compare what the Liberty files say with what boson's library model holds, for every
cell: missing or extra cells and pins, attribute values boson exposes, timing groups
against boson's arcs (dropped, merged, sense changed), boson's arcs against what
get_lib_timing_arcs reports, and every constraint table as boson stores it (shape,
axes, every value) against the file. Also lists every attribute and group in the
files that no boson query exposes, so nothing passes as "checked" unseen.

    lib_inventory.py lib_model/ my_a.lib [my_b.lib ...] [--out lib_inventory]

`lib_model/` comes from dump_model.tcl (pdb_query lib cell "" -tables, plus
get_lib_cells / get_lib_pins / get_lib_timing_arcs). Writes report.md and
results.json (local: they name cells) and summary.json (shareable: counts and
Liberty keywords only; attributes declared with define() are omitted).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shape_census import TEMPLATE_GROUPS, index_lengths, numbers, read_tree, walk  # noqa: E402

# Liberty attribute -> (boson query file, column, kind)
CELL_FIELDS = {"area": "num", "dont_use": "bool", "dont_touch": "bool", "cell_leakage_power": ("leakage_power", "num"),
               "is_level_shifter": "bool", "is_isolation_cell": "bool", "is_macro_cell": ("is_macro_cell", "bool"),
               "retention_cell": "str", "switch_cell_type": "str", "level_shifter_type": "str", "always_on": "bool"}
PIN_FIELDS = {"direction": "str", "function": "func", "capacitance": "num", "rise_capacitance": "num",
              "fall_capacitance": "num", "max_capacitance": "num", "max_transition": "num", "max_fanout": "num",
              "clock": ("is_clock_pin", "bool")}
# structure the comparison reads itself (pins, arcs, tables), not attributes to list as unchecked
STRUCTURAL = {"related_pin", "timing_type", "timing_sense", "when", "values", "index_1", "index_2", "index_3",
              "variable_1", "variable_2", "variable_3"}
CONSTRAINT_TABLES = ("rise_constraint", "fall_constraint")
UNIT_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3}


def camel(s: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in s.strip('"').split("_") if w)


def axis_key(s: str) -> str:
    """related_out_total_output_net_capacitance and boson's RelatedOutputNetCapacitance
    name the same axis"""
    k = re.sub(r"[^a-z]", "", s.lower())
    return "relatedoutputcap" if k.startswith("relatedout") else k


def tt_key(s: str) -> str:
    """timing_type spelling-insensitive: nochange_high_high == NoChangeHighHigh"""
    return re.sub(r"[^a-z]", "", s.lower())


def unit_ns(tu: str) -> float:
    m = re.fullmatch(r"\s*(\d*\.?\d*)\s*(fs|ps|ns|us)\s*", tu.strip('"') or "1ns")
    return float(m.group(1) or 1) * UNIT_NS[m.group(2)] if m else 1.0


def close(a: float, b: float, rel=2e-6, ab=1e-9) -> bool:
    return abs(a - b) <= ab + rel * max(abs(a), abs(b))


def norm_when(w: str | None) -> str:
    return re.sub(r"[\s\"()]", "", w or "")


def norm_func(f: str) -> str:
    return re.sub(r"[\s\"()]", "", f).replace("&", "*").replace("|", "+")


# ---------------------------------------------------------------- boson model
ARC_RE = re.compile(r"^\s{4}(\S+) -> (\S+)\s+timing_type=(\S+)\s+sense=(\S+)(?:\s+when=\"(.*)\")?\s*$")
TAB_RE = re.compile(r"^\s{8}(\w+): table=\d+ kind=(\S+) shape=(\S+) (.*?) values_ns=\[([^\]]*)\]")


def parse_model(path: Path) -> dict:
    cells, cur, arc, corner = {}, None, None, ""
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("cell "):
            m = re.match(r"cell (\S+) \(is_seq=(\w+)\)", line)
            cur = cells.setdefault(m.group(1), {"pins": {}, "arcs": []})
            cur["seq"] = m.group(2) == "true"
            arc = None
        elif cur is None:
            continue
        elif line.startswith("  pin "):
            m = re.match(r"  pin (\S+)\s+dir=(\S+) is_clock=(\w+)", line)
            if m:
                cur["pins"][m.group(1)] = {"dir": m.group(2).lower(), "clock": m.group(3) == "true"}
        elif ARC_RE.match(line):
            m = ARC_RE.match(line)
            arc = {"from": m.group(1), "to": m.group(2), "tt": m.group(3), "sense": m.group(4),
                   "when": m.group(5) or "", "tables": {}}
            cur["arcs"].append(arc)
        elif line.startswith("      source arc="):
            corner = (re.search(r"corner=(\S+)", line) or [None, ""])[1]
        elif arc is not None and TAB_RE.match(line):
            m = TAB_RE.match(line)
            axes = re.findall(r"axis_\d=(\w+)(?::\[([^\]]*)\])?", m.group(4))
            # a third, related-output-capacitance axis is listed apart from shape= and is
            # the outermost axis of the stored values
            outer = re.search(r"related_output_axis=(\w+):\[([^\]]*)\]", m.group(4))
            arc["tables"].setdefault(m.group(1), []).append({
                "corner": corner, "kind": m.group(2), "shape": [int(x) for x in m.group(3).split("x")],
                "axes": [(v, numbers(x) if x else []) for v, x in axes if v != "scalar"],
                "outer": (outer.group(1), numbers(outer.group(2))) if outer else None,
                "values": numbers(m.group(5))})
    return cells


def read_tsv(path: Path) -> dict:
    if not path.exists():
        return {}
    lines = path.read_text(errors="replace").splitlines()
    head = lines[0].split("\t")
    return {r[0]: dict(zip(head, r)) for r in (l.split("\t") for l in lines[1:]) if r}


# ---------------------------------------------------------------- Liberty text
def file_cells(paths: list[Path]) -> tuple[dict, dict, set, list]:
    cells, census, defined, files = {}, collections.Counter(), set(), []
    for path in paths:
        raw = gzip.open(path, "rt", errors="replace").read() if path.suffix == ".gz" else path.read_text(errors="replace")
        root = read_tree(raw)
        lib = next((g for g in root.children if g.head == "library"), None)
        if lib is None:
            continue
        scale = unit_ns(lib.attrs.get("time_unit", "1ns"))
        files.append({"file": str(path), "library": lib.args[0] if lib.args else "", "time_ns": scale})
        for d in lib.complex.get("define", []):
            if d:
                defined.add(d[0].strip('"'))
        templates = {g.args[0]: g for g in lib.children if g.head in TEMPLATE_GROUPS and g.args}
        for g in walk(lib):
            scope = g.parent.head if g.parent else ""
            census[("group", g.head, scope)] += 1
            for a in g.attrs:
                census[("attr", a, g.head)] += 1
            for a in g.complex:
                census[("attr", a, g.head)] += 1
        for c in (g for g in lib.children if g.head == "cell" and g.args):
            cells[c.args[0]] = parse_cell(c, templates, scale, str(path))
    return cells, census, defined, files


def parse_cell(c, templates, scale, path) -> dict:
    out = {"file": path, "line": c.line, "attrs": dict(c.attrs), "pins": {}, "groups": [], "bus": False,
           "storage": {g.head for g in c.children if g.head in ("ff", "latch", "ff_bank", "latch_bank", "statetable")}}

    def pins_of(g, in_test=False):
        for ch in g.children:
            if ch.head == "test_cell":
                continue
            if ch.head in ("bus", "bundle"):
                out["bus"] = True
            if ch.head == "pin":
                for name in ch.args:
                    out["pins"][name.strip('"')] = {"attrs": dict(ch.attrs), "line": ch.line}
                for t in (x for x in ch.children if x.head == "timing"):
                    tt = t.attrs.get("timing_type", "combinational")
                    tables = {}
                    for tab in t.children:
                        if "values" not in tab.complex:
                            continue
                        tname = tab.args[0] if tab.args else ""
                        tpl = templates.get(tname)
                        tidx = index_lengths(tpl) if tpl else {}
                        own = index_lengths(tab)
                        variables = [tpl.attrs[k] for k in sorted(tpl.attrs) if re.fullmatch(r"variable_\d", k)] if tpl else []
                        n = max(len(variables), max(own) if own else 0, max(tidx) if tidx else 0)
                        axes = [(camel(variables[k - 1]) if k - 1 < len(variables) else f"axis{k}",
                                 own.get(k, tidx.get(k, []))) for k in range(1, n + 1)] if tname != "scalar" else []
                        tables[tab.head] = {"axes": axes, "values": numbers(" ".join(tab.complex["values"][0])),
                                            "line": tab.line}
                    for rp in t.attrs.get("related_pin", "").split():
                        out["groups"].append({"to": name.strip('"'), "from": rp, "tt": camel(tt),
                                              "sense": camel(t.attrs["timing_sense"]) if "timing_sense" in t.attrs else "",
                                              "when": t.attrs.get("when", ""), "line": t.line, "tables": tables})
            if ch.head in ("bus", "bundle"):
                pins_of(ch, in_test)
    pins_of(c)
    out["scale"] = scale
    return out


# ---------------------------------------------------------------- comparison
def compare(model_dir: Path, libs: list[Path]) -> dict:
    model = parse_model(model_dir / "model.txt")
    q_cells = {k.split("/")[-1]: v for k, v in read_tsv(model_dir / "cells.tsv").items()}
    q_pins = read_tsv(model_dir / "pins.tsv")
    q_arcs = collections.Counter()
    for row in read_tsv(model_dir / "arcs.tsv").values():
        cell = row["from"].split("/")[0]
        q_arcs[(cell, row["from"].split("/")[-1], row["to"].split("/")[-1], tt_key(row["timing_type"]))] += 1
    fcells, census, defined, files = file_cells(libs)
    findings = collections.defaultdict(list)

    def add(kind, cell, detail, line=None, file=None):
        findings[kind].append({"cell": cell, "detail": detail, "line": line, "file": file})

    for name in sorted(set(fcells) - set(model)):
        add("cell missing in boson", name, "in the file, not in boson's model", fcells[name]["line"], fcells[name]["file"])
    for name in sorted(set(model) - set(fcells)):
        add("cell only in boson", name, "in boson's model, not in the files")
    checked = collections.Counter()
    tables_compared = 0
    for name, fc in fcells.items():
        mc = model.get(name)
        if mc is None:
            continue
        where = (fc["line"], fc["file"])
        # pins
        for p in sorted(set(fc["pins"]) - set(mc["pins"])):
            add("pin missing in boson", name, f"pin {p}", fc["pins"][p]["line"], fc["file"])
        for p in sorted(set(mc["pins"]) - set(fc["pins"])):
            if not fc["bus"]:
                add("pin only in boson", name, f"pin {p}", *where)
        # cell attributes
        qc = q_cells.get(name, {})
        for attr, spec in CELL_FIELDS.items():
            col, kind = (spec if isinstance(spec, tuple) else (attr, spec))
            if attr in fc["attrs"] and col in qc:
                checked[("cell", attr)] += 1
                if not same(fc["attrs"][attr], qc[col], kind):
                    add("field differs", name, f"cell {attr}: file {fc['attrs'][attr]!r}, boson {qc[col]!r}", *where)
        # an ff/latch group must make a sequential cell, a latch group a latch
        if qc:
            # a statetable (clock gates) holds state too
            seq = bool(fc["storage"])
            checked[("cell", "ff/latch group")] += 1
            if seq != (qc.get("is_sequential") == "true"):
                add("field differs", name, f"ff/latch group {'present' if seq else 'absent'} in the file, "
                    f"boson is_sequential={qc.get('is_sequential')}", *where)
            lat = bool(fc["storage"] & {"latch", "latch_bank"}) and not fc["storage"] & {"ff", "ff_bank"}
            if fc["storage"] - {"statetable"} and lat != (qc.get("is_latch") == "true"):
                add("field differs", name, f"latch group {'present' if lat else 'absent'} in the file, "
                    f"boson is_latch={qc.get('is_latch')}", *where)
        # pin attributes
        for p, fp in fc["pins"].items():
            qp = q_pins.get(f"{name}/{p}", {})
            mp = mc["pins"].get(p)
            for attr, spec in PIN_FIELDS.items():
                col, kind = (spec if isinstance(spec, tuple) else (attr, spec))
                if attr in fp["attrs"] and col in qp:
                    checked[("pin", attr)] += 1
                    if not same(fp["attrs"][attr], qp[col], kind):
                        add("field differs", name, f"pin {p} {attr}: file {fp['attrs'][attr]!r}, boson {qp[col]!r}",
                            fp["line"], fc["file"])
            fdir = fp["attrs"].get("direction", "").strip('"').lower()
            if mp and fdir and mp["dir"] != fdir:
                kind = "internal pin not kept as internal" if fdir == "internal" else "field differs"
                add(kind, name, f"pin {p} direction: file {fdir}, boson's model {mp['dir']}", fp["line"], fc["file"])
        # arcs: timing groups against the model, keyed by pin pair and timing_type
        fgroups = collections.defaultdict(list)
        for g in fc["groups"]:
            fgroups[(g["from"], g["to"], tt_key(g["tt"]))].append(g)
        marcs = collections.defaultdict(list)
        for a in mc["arcs"]:
            marcs[(a["from"], a["to"], tt_key(a["tt"]))].append(a)
        for key in sorted(set(fgroups) | set(marcs)):
            fg, ma = fgroups.get(key, []), marcs.get(key, [])
            label = f"{key[0]}->{key[1]} {(fg or ma)[0]['tt']}"
            line = fg[0]["line"] if fg else fc["line"]
            if fc["bus"] and (not fg or not ma):
                continue
            if len(ma) < len(fg):
                kind = "timing groups dropped" if not ma else "timing groups merged"
                add(kind, name, f"{label}: {len(fg)} group(s) in the file, {len(ma)} arc(s) in boson", line, fc["file"])
            elif len(ma) > len(fg):
                add("arcs only in boson", name, f"{label}: {len(fg)} group(s) in the file, {len(ma)} arc(s) in boson",
                    line, fc["file"])
            for g in fg:
                cands = [a for a in ma if norm_when(a["when"]) == norm_when(g["when"])]
                if g["when"] and not cands:
                    add("when condition lost", name, f"{label} when {g['when']!r}: no boson arc with it", g["line"], fc["file"])
                if g["sense"] and cands and not any(tt_key(a["sense"]) == tt_key(g["sense"]) for a in cands):
                    add("sense differs", name, f"{label}: file {g['sense']}, boson {', '.join(a['sense'] for a in cands)}",
                        g["line"], fc["file"])
                # constraint tables, every value
                for tname in CONSTRAINT_TABLES:
                    ft = g["tables"].get(tname)
                    if not ft:
                        continue
                    mts = [t for a in (cands or ma) for t in a["tables"].get(tname, [])]
                    if not mts:
                        add("constraint table missing in boson", name, f"{label} {tname}", ft["line"], fc["file"])
                        continue
                    tables_compared += 1
                    problem = table_diff(ft, mts, fc["scale"])
                    if problem:
                        add(problem[0], name, f"{label} {tname}: {problem[1]}", ft["line"], fc["file"])
            q = q_arcs.get((name,) + key, 0)
            if ma and q < len(ma):
                add("query collapses arcs", name, f"{label}: boson's model has {len(ma)}, get_lib_timing_arcs reports {q}",
                    line, fc["file"])

    checked_attrs = {a for _, a in checked} | STRUCTURAL
    unchecked = collections.Counter()
    for (kind, name, scope), n in census.items():
        if kind == "attr" and name not in checked_attrs and scope not in TEMPLATE_GROUPS:
            unchecked[(name, scope)] += n
    return {"files": files, "cells_file": len(fcells), "cells_model": len(model),
            "bus_cells": sum(c["bus"] for c in fcells.values()),
            "fields_checked": {f"{s}.{a}": n for (s, a), n in sorted(checked.items())},
            "constraint_tables_compared": tables_compared,
            "findings": {k: v for k, v in findings.items()},
            "not_visible_to_queries": [{"attribute": a, "in": s, "count": n,
                                        "user_defined": a in defined} for (a, s), n in unchecked.most_common()],
            "groups_in_files": [{"group": g, "in": s, "count": n} for (k, g, s), n in census.most_common() if k == "group"]}


def same(fv: str, qv: str, kind: str) -> bool:
    fv, qv = fv.strip().strip('"'), qv.strip()
    if kind == "num":
        try:
            return close(float(fv), float(qv), rel=1e-5)
        except ValueError:
            return fv == qv
    if kind == "bool":
        return fv.lower() in ("true", "1") if qv.lower() in ("true", "1") else fv.lower() not in ("true", "1")
    if kind == "func":
        return norm_func(fv) == norm_func(qv)
    return fv.lower() == qv.lower()


def table_diff(ft: dict, mts: list, scale: float):
    """None when one of boson's stored tables equals the file's; else (kind, detail)."""
    fdims = [len(v) for _, v in ft["axes"]]
    fvals = [x * scale for x in ft["values"]]
    best = None
    for mt in mts:
        mdims = [d for d in mt["shape"] if d != 1] or []
        if mt.get("outer"):
            mdims = mdims + [len(mt["outer"][1])]
        fd = [d for d in fdims if d != 1]
        if mdims != fd:
            n_f, n_m = math.prod(fd) if fd else 1, math.prod(mdims) if mdims else 1
            kind = "constraint table smaller in boson" if n_m < n_f else "constraint table reshaped"
            best = best or (kind, f"file {'x'.join(map(str, fdims)) or 'scalar'}, boson {'x'.join(map(str, mt['shape']))}")
            continue
        names_f = [n for n, v in ft["axes"] if len(v) != 1]
        m_axes = list(mt["axes"]) + ([mt["outer"]] if mt.get("outer") else [])
        names_m = [n for n, _ in m_axes]
        if names_f and names_m and [axis_key(n) for n in names_f] != [axis_key(n) for n in names_m[:len(names_f)]]:
            best = best or ("constraint table axes differ", f"file {names_f}, boson {names_m}")
            continue
        for (n, fv), (_, mv) in zip([a for a in ft["axes"] if len(a[1]) != 1], m_axes):
            fv_ns = [x * scale for x in fv] if n.endswith("Transition") else fv
            if len(fv_ns) == len(mv) and not all(close(a, b, rel=1e-5) for a, b in zip(fv_ns, mv)):
                ratio = mv[-1] / fv_ns[-1] if fv_ns[-1] else 0
                if ratio and abs(math.log10(abs(ratio)) - round(math.log10(abs(ratio)))) < 1e-4 and \
                        all(close(a * ratio, b, rel=1e-5) for a, b in zip(fv_ns, mv)):
                    continue  # unit conversion
                best = best or ("constraint table axes differ", f"axis {n}: file {fv[:4]}..., boson {mv[:4]}...")
                break
        else:
            mvals = mt["values"]
            if mt.get("outer") and len(fd) == 3:
                # file order (i1, i2, i3), i3 fastest; boson stores (i3, i1, i2), i2 fastest
                n1, n2, n3 = fd
                mvals = [mt["values"][k * n1 * n2 + i * n2 + j] if k * n1 * n2 + i * n2 + j < len(mt["values"]) else math.nan
                         for i in range(n1) for j in range(n2) for k in range(n3)]
            bad = [(i, a, b) for i, (a, b) in enumerate(zip(fvals, mvals)) if not close(a, b, rel=1e-5)]
            if len(fvals) != len(mt["values"]):
                best = best or ("constraint table smaller in boson", f"{len(fvals)} values in the file, {len(mt['values'])} in boson")
                continue
            if not bad:
                return None
            i, a, b = bad[0]
            best = best or ("constraint table values differ",
                            f"{len(bad)} of {len(fvals)} values differ; first at index {i}: file {a:.6g} ns, boson {b:.6g} ns")
    return best


ORDER = ["cell missing in boson", "pin missing in boson", "timing groups dropped", "timing groups merged",
         "when condition lost", "constraint table missing in boson", "constraint table smaller in boson",
         "constraint table reshaped", "constraint table axes differ", "constraint table values differ",
         "sense differs", "field differs", "internal pin not kept as internal", "query collapses arcs", "arcs only in boson", "pin only in boson",
         "cell only in boson"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("libs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("lib_inventory"))
    a = ap.parse_args()
    r = compare(a.model_dir, a.libs)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(r, indent=1))
    f = r["findings"]
    summary = {"schema": 1, "tool": "boson-diagnose/liberty-check",
               "cells": {"file": r["cells_file"], "boson": r["cells_model"], "bus_cells": r["bus_cells"]},
               "fields_checked": r["fields_checked"], "constraint_tables_compared": r["constraint_tables_compared"],
               "findings": {k: len(v) for k, v in f.items()},
               "not_visible_to_queries": [x for x in r["not_visible_to_queries"] if not x["user_defined"]][:80]}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    md = ["# Liberty files against boson's library model", "",
          f"cells: {r['cells_file']} in the files, {r['cells_model']} in boson; {r['bus_cells']} with bus/bundle pins "
          "(their bus-expanded pins and arcs are compared loosely).",
          f"fields compared on every cell/pin: {', '.join(f'{k} ({v})' for k, v in r['fields_checked'].items())}.",
          f"constraint tables compared value by value: {r['constraint_tables_compared']}.", ""]
    for kind in ORDER + sorted(set(f) - set(ORDER)):
        rows = f.get(kind)
        if not rows:
            continue
        md += [f"## {kind}: {len(rows)}", ""]
        md += [f"- {x['cell']}: {x['detail']}" + (f" ({Path(x['file']).name}:{x['line']})" if x.get("line") else "")
               for x in rows[:40]]
        if len(rows) > 40:
            md.append(f"- ... {len(rows) - 40} more in results.json")
        md.append("")
    if not f:
        md += ["No differences between the files and boson's model in what was compared.", ""]
    md += ["## In the files, not visible to any boson query", "",
           "These were read by boson or not; no query shows them, so this comparison cannot check them. "
           "Delay, transition and power tables are checked by `shape_probe.py --grid full` instead.", "",
           "| attribute | in group | count | user-defined |", "|---|---|---|---|"]
    md += [f"| {x['attribute']} | {x['in']} | {x['count']} | {'yes' if x['user_defined'] else ''} |"
           for x in r["not_visible_to_queries"][:60]]
    (a.out / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6]))
    for kind in ORDER + sorted(set(f) - set(ORDER)):
        if f.get(kind):
            print(f"  {kind}: {len(f[kind])}  e.g. {f[kind][0]['cell']}: {f[kind][0]['detail'][:140]}")
    print(f"\n-> {a.out}/report.md (local), {a.out}/summary.json (shareable)")
    serious = set(ORDER[:10])
    return 1 if any(f.get(k) for k in serious) else 0


if __name__ == "__main__":
    sys.exit(main())
