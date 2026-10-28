#!/usr/bin/env python3
"""Split the QoR gap between a boson netlist and a Synopsys DC netlist of the same RTL
into the part inside DesignWare (datapath operators) and the part outside it.

Inputs (see SKILL.md):
    <boson_dir>  from collect_boson.tcl: cells.tsv, paths.tsv, prov_cells.*.json
    <dc_dir>     from score_netlist.tcl on the DC netlist: cells.tsv, paths.tsv
    --dc-resources  optional DC `report_resources -hierarchy` text: implementations
                    and RTL lines for each DW cell

    dw_compare.py dw_boson dw_dc [--dc-resources res.rpt] [--json out.json]

DC cells are labelled DesignWare by the names DC gives them (instances or nets under
DP_OP_*, add_*, mult_*, DW*... hierarchy, kept after ungroup), plus unnamed cells
enclosed on all sides by one such region. boson cells are labelled by the datapath
block their provenance traces to. Both netlists must be timed by one engine with the
same libraries and SDC; the timing gap per endpoint is then split by the class of the
cells each path runs through.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import statistics
import sys
from pathlib import Path

# DC names a DesignWare/datapath resource after its operator and RTL line (add_123,
# mult_x_45, gte_x_7), its synthetic datapath cluster (DP_OP_391J5_123_6951) or the
# DW part (DW01_add_0, DW02_mult_2). Those names survive ungroup as hierarchy prefixes.
DC_OP = (r"add|sub|addsub|inc|dec|neg|abs|absval|mult|mul|lt|gt|lte|gte|leq|geq|cmp|"
         r"eq|ne|ash|ashr|sll|srl|sra|sla|shl|shr|rol|ror|div|rem|mod|sqrt")
DW_PART = re.compile(rf"^(?:DP_OP_\w+|DW(?:\d\d|_)\w*|(?:{DC_OP})(?:_x)?_\d+(?:_[A-Za-z0-9]+)*)$", re.I)

FAMILY_OF_DC_OP = {
    "add": "add", "sub": "add", "addsub": "add", "inc": "add", "dec": "add", "neg": "add",
    "abs": "add", "absval": "add",
    "mult": "multiply", "mul": "multiply",
    "lt": "compare", "gt": "compare", "lte": "compare", "gte": "compare", "leq": "compare",
    "geq": "compare", "cmp": "compare",
    "eq": "equality", "ne": "equality",
    "ash": "shift", "ashr": "shift", "sll": "shift", "srl": "shift", "sra": "shift",
    "sla": "shift", "shl": "shift", "shr": "shift", "rol": "shift", "ror": "shift",
    "div": "divide", "rem": "divide", "mod": "divide", "sqrt": "divide",
}
FAMILY_OF_BOSON_OP = {
    "Add": "add", "Sub": "add", "AddCarry": "add", "AddSub": "add", "Neg": "add",
    "Inc": "add", "Dec": "add", "Abs": "add",
    "Mul": "multiply", "AddTree": "multiply", "MulAdd": "multiply",
    "Lt": "compare", "Gt": "compare", "Le": "compare", "Ge": "compare", "Cmp": "compare",
    "Eq": "equality", "Ne": "equality",
    "Shl": "shift", "Shr": "shift", "Sshr": "shift", "Sshl": "shift", "Ashr": "shift",
    "Shift": "shift", "Rol": "shift", "Ror": "shift",
    "Div": "divide", "Mod": "divide", "Rem": "divide",
}
# What counts as "inside DesignWare". Equality is excluded by default: DC usually leaves
# ==/!= as random logic, so counting it on the boson side only would bias the split.
DW_FAMILIES = {"add", "multiply", "compare", "shift", "divide", "datapath"}

SEQ = re.compile(r"^(S?E?DF|DFF|SDF|EDF|DHL|DLL|DLH|LAT|LH[QX]|LN[QX]|ICG|CKLN|CKLH|TLAT|PREICG|CGL|CKGT)", re.I)
ICG = re.compile(r"^(ICG|CKLN|CKLH|TLAT|PREICG|CGL|CKGT)", re.I)
BUFINV = re.compile(r"^(BUF|INV|CKBUF|CKINV|HB|CKB|CKN|DLY)", re.I)
TIE = re.compile(r"^(TIE|LOGIC[01])", re.I)


def canon(name: str) -> str:
    """One spelling for hierarchical names: DC writes `\\a/b/U1` or `a.\\b/c`, boson `a.b`."""
    return name.replace("\\", "").replace(".", "/").replace(" ", "")


def dc_family(part: str) -> str:
    p = part.lower()
    if p.startswith("dp_op_"):
        return "datapath"
    if p.startswith("dw"):
        for key, fam in (("mult", "multiply"), ("prod", "multiply"), ("sqrt", "divide"),
                         ("div", "divide"), ("cmp", "compare"), ("shift", "shift"),
                         ("sh", "shift"), ("add", "add"), ("sub", "add"), ("inc", "add"),
                         ("dec", "add"), ("abs", "add")):
            if key in p:
                return fam
        return "datapath"
    op = re.match(rf"^({DC_OP})(?:_x)?_\d", p)
    return FAMILY_OF_DC_OP.get(op.group(1), "datapath") if op else "datapath"


def dw_region(name: str, dw_part=DW_PART):
    """(region path, family) of the innermost DW-named hierarchy level in `name`."""
    parts = canon(name).split("/")[:-1]
    for i in range(len(parts) - 1, -1, -1):
        if dw_part.match(parts[i]):
            return "/".join(parts[:i + 1]), dc_family(parts[i])
    return None


def read_cells(path: Path) -> dict:
    cells = {}
    with open(path) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 3:
                continue
            try:
                area = float(f[2])
            except ValueError:
                area = 0.0
            cells[f[0]] = {"ref": f[1], "area": area,
                           "outs": f[3].split() if len(f) > 3 and f[3] else [],
                           "ins": f[4].split() if len(f) > 4 and f[4] else []}
    if not cells:
        raise ValueError(f"{path}: no cells")
    return cells


def base_class(ref: str):
    if ICG.match(ref):
        return "clock gate"
    if SEQ.match(ref):
        return "register"
    if TIE.match(ref):
        return "tie"
    return None


def label_dc(cells: dict, dw_part=DW_PART, enclose_rounds: int = 3) -> dict:
    """cell -> {cls, family, region, how}. how: name (instance under a DW level), net (drives
    a net under one), enclosed (every driver and load is in one region), '' otherwise."""
    labels = {}
    for name, c in cells.items():
        bc = base_class(c["ref"])
        if bc:
            labels[name] = {"cls": bc, "family": bc, "region": None, "how": ""}
            continue
        hit, how = dw_region(name, dw_part), "name"
        if not hit:
            for net in c["outs"]:
                hit = dw_region(net + "/x", dw_part)
                if hit:
                    how = "net"
                    break
        if hit:
            labels[name] = {"cls": "dw" if hit[1] in DW_FAMILIES else "logic", "family": hit[1],
                            "region": hit[0], "how": how}
        else:
            labels[name] = {"cls": "logic", "family": "other logic", "region": None, "how": ""}
    drivers, loads = {}, collections.defaultdict(list)
    for name, c in cells.items():
        for n in c["outs"]:
            drivers[n] = name
        for n in c["ins"]:
            loads[n].append(name)
    for _ in range(enclose_rounds):
        changed = 0
        for name, c in cells.items():
            lab = labels[name]
            if lab["region"] or lab["cls"] != "logic":
                continue
            around = [drivers.get(n) for n in c["ins"]] + [l for n in c["outs"] for l in loads.get(n, [])]
            if not around or None in around:
                continue
            regions = {labels[x]["region"] for x in around}
            if len(regions) == 1 and None not in regions:
                src = labels[around[0]]
                labels[name] = {"cls": src["cls"], "family": src["family"], "region": src["region"],
                                "how": "enclosed"}
                changed += 1
        if not changed:
            break
    return labels


def dominant_block(story: dict):
    blocks = story.get("blocks") or []
    if not blocks:
        return None
    return max(blocks, key=lambda b: ((b.get("exact") or 0) > 0, b.get("exact") or 0, b.get("share") or 0))


def label_boson(cells: dict, stories: dict) -> dict:
    labels = {}
    for name, c in cells.items():
        bc = base_class(c["ref"])
        if bc:
            labels[name] = {"cls": bc, "family": bc, "region": None, "how": ""}
            continue
        story = stories.get(name)
        b = dominant_block(story) if story else None
        fam = FAMILY_OF_BOSON_OP.get((b or {}).get("op", ""), "other logic")
        if not b or fam == "other logic":
            labels[name] = {"cls": "logic", "family": "other logic", "region": None,
                            "how": "" if story else "no provenance"}
            continue
        origin = next((o for o in b.get("origins") or [] if isinstance(o, dict) and o.get("operator")),
                      next((o for o in b.get("origins") or [] if isinstance(o, dict)), {}))
        inst = canon(origin.get("instance") or "")
        labels[name] = {"cls": "dw" if fam in DW_FAMILIES else "logic", "family": fam,
                        "region": inst, "how": "exact" if (b.get("exact") or 0) > 0 else "inferred",
                        "block": b.get("block"), "op": b.get("op"), "width": b.get("width"),
                        "lowering": b.get("lowering") or "",
                        "rtl": f"{Path(origin.get('file') or '?').name}:{origin.get('line', 0)}"}
    return labels


def read_stories(boson_dir: Path) -> dict:
    files = sorted(glob.glob(str(boson_dir / "prov_cells.*.json"))) or \
        sorted(glob.glob(str(boson_dir / "prov_cells.json")))
    if not files:
        raise ValueError(f"{boson_dir}: no prov_cells*.json; compile with -provenance and run collect_boson.tcl")
    stories = {}
    for f in files:
        data = json.loads(Path(f).read_text())
        if not isinstance(data, list):
            raise ValueError(f"{f}: expected a cell-story array (was the design compiled with -provenance?)")
        for s in data:
            stories[s["cell"]] = s
    return stories


def read_paths(path: Path) -> list:
    paths, cur = [], None
    with open(path) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if f[0] == "P":
                cur = {"start": f[1], "end": f[2], "slack": float(f[3]), "arrival": float(f[4]),
                       "required": float(f[5]), "points": []}
                paths.append(cur)
            elif cur is not None and len(f) >= 3:
                try:
                    cur["points"].append((f[1], float(f[2])))
                except ValueError:
                    pass
    if not paths:
        raise ValueError(f"{path}: no timing paths")
    return paths


def path_classes(path: dict, labels: dict, by_family: bool = False) -> dict:
    """Delay per cell class along one path (ns). The launch register's clock-to-Q and any
    input delay are 'launch'; each later cell's input-net delay plus cell delay go to its class."""
    out = collections.Counter()
    prev_arr, launch_cell, started = 0.0, None, False
    for pin, arr in path["points"]:
        inc = arr - prev_arr
        prev_arr = arr
        cell = pin.rsplit("/", 1)[0] if "/" in pin else None
        if not started or (cell is not None and cell == launch_cell):
            started, launch_cell = True, launch_cell or cell
            out["launch"] += inc
            continue
        if cell is None or cell not in labels:
            # a port, or a hierarchical pin the cell table does not know
            out["port/unknown"] += inc
            continue
        lab = labels[cell]
        key = lab["family"] if by_family else lab["cls"]
        if lab["cls"] == "logic" and BUFINV.match(lab.get("ref", "")):
            key = "buffer/inverter"
        out[key] += inc
    return out


def endpoint_keys(end: str):
    c = canon(end)
    cell, _, pin = c.rpartition("/")
    return c, re.sub(r"\[\d+\]|_\d+_$", "", cell) + "/" + pin


def area_table(cells, labels):
    t = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])  # cells, area, bufinv cells, bufinv area
    for name, c in cells.items():
        lab = labels[name]
        key = lab["family"] if lab["cls"] in ("dw", "logic") else lab["cls"]
        row = t[key]
        row[0] += 1
        row[1] += c["area"]
        if BUFINV.match(c["ref"]):
            row[2] += 1
            row[3] += c["area"]
    return t


def parse_resources(text: str) -> dict:
    """DC `report_resources [-hierarchy]`: resource cell -> {module, impl, ops: [(op, line)]}.
    Tolerant of column order: it reads every |-delimited table whose header names a Cell
    column and keeps Module, Implementation and Contained Operations when present."""
    res = collections.defaultdict(dict)
    header = None
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if s and not s.startswith("="):
                header = None if not s.startswith("-") else header
            continue
        cols = [x.strip() for x in s.strip("|").split("|")]
        low = [x.lower() for x in cols]
        if "cell" in low and any(k in " ".join(low) for k in ("module", "implementation", "operations")):
            header = low
            continue
        if not header or not cols or not cols[0]:
            continue
        rec = res[cols[0]]
        for h, v in zip(header, cols):
            if not v:
                continue
            if h.startswith("module"):
                rec["module"] = v
            elif "implementation" in h and "impl" not in rec:
                rec["impl"] = v
            elif "operation" in h:
                ops = rec.setdefault("ops", [])
                for tok in v.split():
                    m = re.match(r"^([a-z]+)(?:_x)?_(\d+)", tok)
                    if m:
                        ops.append((m.group(1), int(m.group(2))))
    return {k: v for k, v in res.items() if v}


UNLABELED = "arith, no DC DW"


def in_scope(region: str, dc_instances: set) -> bool:
    return any(region == h or region.startswith(h + "/") for h in dc_instances)


def compare(bo_dir: Path, dc_dir: Path, resources: dict | None = None, top: int = 0,
            scope: str = "labeled") -> dict:
    bo_cells, dc_cells = read_cells(bo_dir / "cells.tsv"), read_cells(dc_dir / "cells.tsv")
    stories = read_stories(bo_dir)
    bo_lab, dc_lab = label_boson(bo_cells, stories), label_dc(dc_cells)
    # DC labels DW only where its names survived; after ungroup most operators become
    # anonymous U cells. Counting boson's datapath everywhere against DC's surviving
    # names would put every adder DC flattened on the "inside DW" side. By default
    # boson datapath counts as DW only in instances where DC also shows DW cells.
    dc_instances = {l["region"].rsplit("/", 1)[0] if "/" in l["region"] else ""
                    for l in dc_lab.values() if l["cls"] == "dw"}
    bo_dw_all = sum(bo_cells[n]["area"] for n, l in bo_lab.items() if l["cls"] == "dw")
    dc_dw_all = sum(dc_cells[n]["area"] for n, l in dc_lab.items() if l["cls"] == "dw")
    out_of_scope = 0.0
    if scope == "labeled":
        for n, l in bo_lab.items():
            if l["cls"] == "dw" and not in_scope(l["region"], dc_instances):
                l["cls"], l["family"] = "logic", UNLABELED
                out_of_scope += bo_cells[n]["area"]
    for cells, lab in ((bo_cells, bo_lab), (dc_cells, dc_lab)):
        for n, c in cells.items():
            lab[n]["ref"] = c["ref"]
    if resources:
        for lab in dc_lab.values():
            if lab["region"]:
                r = resources.get(lab["region"].rsplit("/", 1)[-1])
                if r and lab["family"] == "datapath":
                    fams = {FAMILY_OF_DC_OP.get(op, "datapath") for op, _ in r.get("ops", [])}
                    lab["family"] = "multiply" if "multiply" in fams else (fams.pop() if len(fams) == 1 else "datapath")

    def coverage(lab, how_keys):
        dw = [l for l in lab.values() if l["cls"] == "dw"]
        return {k: sum(l["how"] == k for l in dw) for k in how_keys} | {"dw_cells": len(dw)}

    report = {
        "boson_cells": len(bo_cells), "dc_cells": len(dc_cells),
        "provenance_coverage": round(sum(n in stories for n in bo_cells) / len(bo_cells), 4),
        "dc_label_basis": coverage(dc_lab, ("name", "net", "enclosed")),
        "boson_label_basis": coverage(bo_lab, ("exact", "inferred")),
        "scope": scope, "dc_dw_instances": sorted(dc_instances),
        "boson_datapath_area_all": round(bo_dw_all, 3), "dc_dw_area_all": round(dc_dw_all, 3),
        "boson_datapath_outside_dc_dw_instances": round(out_of_scope, 3),
        # well below 1: DC's DW names did not survive for most operators
        "label_balance": round(dc_dw_all / bo_dw_all, 3) if bo_dw_all else None,
        "conclusive": bool(bo_dw_all) and dc_dw_all / bo_dw_all >= BALANCE_MIN,
    }

    # ---- area
    at_bo, at_dc = area_table(bo_cells, bo_lab), area_table(dc_cells, dc_lab)
    rows = []
    for key in sorted(set(at_bo) | set(at_dc), key=lambda k: (k not in DW_FAMILIES, k)):
        b, d = at_bo.get(key, [0, 0.0, 0, 0.0]), at_dc.get(key, [0, 0.0, 0, 0.0])
        rows.append({"class": key, "dw": key in DW_FAMILIES,
                     "boson_cells": b[0], "boson_area": round(b[1], 3), "boson_bufinv_area": round(b[3], 3),
                     "dc_cells": d[0], "dc_area": round(d[1], 3), "dc_bufinv_area": round(d[3], 3),
                     "delta_area": round(b[1] - d[1], 3)})
    tot_b = sum(r["boson_area"] for r in rows)
    tot_d = sum(r["dc_area"] for r in rows)
    dw_b = sum(r["boson_area"] for r in rows if r["dw"])
    dw_d = sum(r["dc_area"] for r in rows if r["dw"])
    report["area"] = {"rows": rows, "boson_total": round(tot_b, 3), "dc_total": round(tot_d, 3),
                      "boson_dw": round(dw_b, 3), "dc_dw": round(dw_d, 3),
                      "delta_total": round(tot_b - tot_d, 3), "delta_dw": round(dw_b - dw_d, 3),
                      "delta_outside_dw": round((tot_b - dw_b) - (tot_d - dw_d), 3),
                      "dw_ratio": round(dw_b / dw_d, 3) if dw_d else None,
                      "outside_ratio": round((tot_b - dw_b) / (tot_d - dw_d), 3) if tot_d - dw_d else None}

    # ---- per hierarchy instance (where DC put DesignWare)
    inst = collections.defaultdict(lambda: {"dc_area": 0.0, "dc_cells": 0, "boson_area": 0.0, "boson_cells": 0,
                                            "dc_regions": set(), "boson_blocks": set(), "dc_families": collections.Counter(),
                                            "boson_families": collections.Counter()})
    for cells, lab, side in ((dc_cells, dc_lab, "dc"), (bo_cells, bo_lab, "boson")):
        for n, l in lab.items():
            if l["cls"] != "dw" and l["family"] != UNLABELED:
                continue
            h = l["region"].rsplit("/", 1)[0] if side == "dc" and "/" in l["region"] else (l["region"] if side == "boson" else "")
            r = inst[h]
            r[f"{side}_area"] += cells[n]["area"]
            r[f"{side}_cells"] += 1
            r[f"{side}_families"][l["family"]] += 1
            if side == "dc":
                r["dc_regions"].add(l["region"].rsplit("/", 1)[-1])
            else:
                r["boson_blocks"].add(f"{l['rtl']} {l['op']}{l['width'] or ''} {l['lowering']}".strip())
    report["instances"] = sorted(({
        "instance": h or "(top)", "dc_area": round(r["dc_area"], 3), "dc_cells": r["dc_cells"],
        "boson_area": round(r["boson_area"], 3), "boson_cells": r["boson_cells"],
        "ratio": round(r["boson_area"] / r["dc_area"], 3) if r["dc_area"] else None,
        "dc_resources": sorted(r["dc_regions"])[:8],
        "dc_impl": sorted({(resources or {}).get(x, {}).get("impl", "") for x in r["dc_regions"]} - {""})[:4],
        "boson_blocks": sorted(r["boson_blocks"])[:8], "boson_block_count": len(r["boson_blocks"]),
        "dc_families": dict(r["dc_families"]), "boson_families": dict(r["boson_families"]),
    } for h, r in inst.items()), key=lambda x: -max(x["dc_area"], x["boson_area"]))

    # ---- timing, endpoint by endpoint
    bo_paths, dc_paths = read_paths(bo_dir / "paths.tsv"), read_paths(dc_dir / "paths.tsv")
    dc_exact, dc_group = {}, collections.defaultdict(list)
    for p in dc_paths:
        e, g = endpoint_keys(p["end"])
        dc_exact[e] = p
        dc_group[g].append(p)
    pairs, used_groups = [], set()
    bo_sorted = sorted(bo_paths, key=lambda p: p["slack"])
    unmatched_bo = []
    for p in bo_sorted:
        e, g = endpoint_keys(p["end"])
        if e in dc_exact:
            pairs.append(("exact", p, dc_exact[e]))
        else:
            unmatched_bo.append((g, p))
    bo_group_worst = {}
    for g, p in unmatched_bo:
        bo_group_worst.setdefault(g, p)
    for g, p in bo_group_worst.items():
        if g in dc_group:
            pairs.append(("group", p, min(dc_group[g], key=lambda x: x["slack"])))
            used_groups.add(g)
    pairs.sort(key=lambda x: x[1]["slack"])
    failing = [x for x in pairs if x[1]["slack"] < 0]
    sel = failing if not top else pairs[:top]
    bo_fail = sum(p["slack"] < 0 for p in bo_paths)
    classes = collections.Counter()
    fams = collections.Counter()
    shares, seg_ratio = [], []
    detail = []
    for how, b, d in sel:
        cb, cd = path_classes(b, bo_lab), path_classes(d, dc_lab)
        fb, fd = path_classes(b, bo_lab, True), path_classes(d, dc_lab, True)
        gap = d["slack"] - b["slack"]
        delta = {k: cb.get(k, 0.0) - cd.get(k, 0.0) for k in set(cb) | set(cd)}
        delta["required/setup"] = d["required"] - b["required"]
        classes.update(delta)
        fams.update({k: fb.get(k, 0.0) - fd.get(k, 0.0) for k in (set(fb) | set(fd)) & DW_FAMILIES})
        if gap > 1e-6:
            shares.append(delta.get("dw", 0.0) / gap)
        if cb.get("dw", 0) > 0 and cd.get("dw", 0) > 0:
            seg_ratio.append(cb["dw"] / cd["dw"])
        detail.append({"match": how, "boson_endpoint": b["end"], "dc_endpoint": d["end"],
                       "boson_slack_ps": round(b["slack"] * 1e3, 1), "dc_slack_ps": round(d["slack"] * 1e3, 1),
                       "gap_ps": round(gap * 1e3, 1),
                       "boson_ps": {k: round(v * 1e3, 1) for k, v in cb.items()},
                       "dc_ps": {k: round(v * 1e3, 1) for k, v in cd.items()},
                       "delta_ps": {k: round(v * 1e3, 1) for k, v in delta.items()}})
    gap_sum = sum(d["slack"] - b["slack"] for _, b, d in sel)
    report["timing"] = {
        "boson_wns_ps": round(min(p["slack"] for p in bo_paths) * 1e3, 1),
        "dc_wns_ps": round(min(p["slack"] for p in dc_paths) * 1e3, 1),
        "boson_tns_ps": round(sum(min(0, p["slack"]) for p in bo_paths) * 1e3, 1),
        "dc_tns_ps": round(sum(min(0, p["slack"]) for p in dc_paths) * 1e3, 1),
        "boson_failing": bo_fail, "dc_failing": sum(p["slack"] < 0 for p in dc_paths),
        "boson_endpoints": len(bo_paths), "dc_endpoints": len(dc_paths),
        "paired": len(pairs), "paired_exact": sum(h == "exact" for h, _, _ in pairs),
        "paired_group": sum(h == "group" for h, _, _ in pairs),
        "selected": len(sel), "selection": f"top {top}" if top else "boson-failing endpoints",
        "selected_failing_unpaired": bo_fail - len(failing) if not top else None,
        "gap_sum_ps": round(gap_sum * 1e3, 1),
        "delta_by_class_ps": {k: round(v * 1e3, 1) for k, v in classes.most_common()},
        "share_by_class": {k: round(v / gap_sum, 3) for k, v in classes.most_common()} if gap_sum > 0 else {},
        "delta_by_dw_family_ps": {k: round(v * 1e3, 1) for k, v in fams.most_common()},
        "median_dw_share_per_endpoint": round(statistics.median(shares), 3) if shares else None,
        "dw_segment_delay_ratio_median": round(statistics.median(seg_ratio), 3) if seg_ratio else None,
        "dw_segment_pairs": len(seg_ratio),
        "worst": detail[:20],
    }
    return report


BALANCE_MIN = 0.5


def fmt(report: dict) -> str:
    o = []
    a, t = report["area"], report["timing"]
    # with most of DC's DW names gone, DC's anonymous operator cells land in "logic"
    # and every share below is an artefact of labelling, not a QoR finding
    ok = report["label_balance"] is not None and report["label_balance"] >= BALANCE_MIN
    o.append(f"cells: boson {report['boson_cells']}  dc {report['dc_cells']}  "
             f"(boson provenance coverage {report['provenance_coverage']:.1%})")
    o.append(f"DC DesignWare labels: {report['dc_label_basis']}   boson datapath labels: {report['boson_label_basis']}")
    bal = report["label_balance"]
    o.append(f"label balance: DC DW area {report['dc_dw_area_all']:.1f} vs boson datapath area {report['boson_datapath_area_all']:.1f} "
             f"(DC/boson {bal}); scope '{report['scope']}': boson datapath outside DC's DW instances "
             f"{report['boson_datapath_outside_dc_dw_instances']:.1f} is counted as '{UNLABELED}', not DW")
    if not ok:
        o.append("WARNING: DC's DesignWare names survive on a small part of the datapath (the DC run ungrouped DW). "
                 "The split below covers only the instances listed in dc_dw_instances; for a whole-design split rerun "
                 "DC with DW hierarchy kept (see SKILL.md) or supply that netlist.")
    o.append("\nAREA by class (DW families first; buf/inv = buffer+inverter area inside the class)")
    o.append(f"  {'class':16s} {'boson cells':>11s} {'boson area':>11s} {'buf/inv':>8s} {'dc cells':>9s} {'dc area':>10s} {'buf/inv':>8s} {'delta':>10s} {'ratio':>6s}")
    for r in a["rows"]:
        ratio = f"{r['boson_area'] / r['dc_area']:.2f}" if r["dc_area"] else "-"
        o.append(f"  {('*' if r['dw'] else ' ') + r['class']:16s} {r['boson_cells']:11d} {r['boson_area']:11.1f} {r['boson_bufinv_area']:8.1f} "
                 f"{r['dc_cells']:9d} {r['dc_area']:10.1f} {r['dc_bufinv_area']:8.1f} {r['delta_area']:+10.1f} {ratio:>6s}")
    share = a["delta_dw"] / a["delta_total"] if a["delta_total"] else 0
    o.append(f"  total boson {a['boson_total']:.1f}  dc {a['dc_total']:.1f}  delta {a['delta_total']:+.1f}: "
             f"inside DW {a['delta_dw']:+.1f} (boson/DC {a['dw_ratio']}), outside {a['delta_outside_dw']:+.1f} "
             f"(boson/DC {a['outside_ratio']})" + (f"  -> {share:.0%} of the area gap is inside DW" if ok and a["delta_total"] > 0 else
                "  -> DW share INCONCLUSIVE (label balance)" if not ok else ""))
    o.append("\nDW AREA by hierarchy instance (DC resource cells vs boson datapath blocks traced to that instance)")
    o.append(f"  {'instance':44s} {'dc area':>9s} {'boson':>9s} {'ratio':>6s}  dc resources / boson blocks")
    for r in report["instances"][:15]:
        ratio = f"{r['ratio']:.2f}" if r["ratio"] else ("no DC DW" if r["boson_area"] else "-")
        o.append(f"  {r['instance'][-44:]:44s} {r['dc_area']:9.1f} {r['boson_area']:9.1f} {ratio:>6s}  "
                 f"{','.join(r['dc_resources'][:3])}{' ' + '/'.join(r['dc_impl']) if r['dc_impl'] else ''} | "
                 f"{r['boson_block_count']} blocks: {'; '.join(r['boson_blocks'][:2])}")
    o.append(f"\nTIMING (one engine, same SDC): WNS boson {t['boson_wns_ps']} ps, dc {t['dc_wns_ps']} ps; "
             f"TNS boson {t['boson_tns_ps']}, dc {t['dc_tns_ps']}; failing boson {t['boson_failing']}/{t['boson_endpoints']}, "
             f"dc {t['dc_failing']}/{t['dc_endpoints']}")
    o.append(f"  paired endpoints {t['paired']} ({t['paired_exact']} by name, {t['paired_group']} by register group); "
             f"split over {t['selected']} {t['selection']}"
             + (f", {t['selected_failing_unpaired']} failing endpoints could not be paired" if t["selected_failing_unpaired"] else ""))
    o.append(f"  summed slack gap (dc - boson) {t['gap_sum_ps']} ps, split by where the delay sits:")
    for k, v in t["delta_by_class_ps"].items():
        o.append(f"    {k:18s} {v:+12.1f} ps  " + (f"{t['share_by_class'].get(k, 0):+7.1%}" if ok else "   n/a"))
    if not ok:
        o.append("  INCONCLUSIVE: dw/logic deltas largely cancel because DC's ungrouped operator cells are counted as logic.")
    if t["delta_by_dw_family_ps"]:
        o.append("  inside DW by family: " + ", ".join(f"{k} {v:+.1f} ps" for k, v in t["delta_by_dw_family_ps"].items()))
    if ok:
        o.append(f"  median per-endpoint DW share of the gap: {t['median_dw_share_per_endpoint']}; "
                 f"median DW-segment delay boson/DC: {t['dw_segment_delay_ratio_median']} over {t['dw_segment_pairs']} paths through DW in both")
    o.append("\n  worst paired endpoints (ps; delta = boson - dc delay per class, required/setup = dc - boson required)")
    for d in t["worst"][:10]:
        o.append(f"  {d['boson_endpoint'][-48:]:48s} [{d['match']}] boson {d['boson_slack_ps']:+.1f} dc {d['dc_slack_ps']:+.1f} gap {d['gap_ps']:+.1f}: "
                 + " ".join(f"{k} {v:+.1f}" for k, v in sorted(d["delta_ps"].items(), key=lambda kv: -abs(kv[1])) if abs(v) >= 0.5))
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boson_dir", type=Path)
    ap.add_argument("dc_dir", type=Path)
    ap.add_argument("--dc-resources", type=Path, help="DC report_resources -hierarchy text")
    ap.add_argument("--top", type=int, default=0, help="split the N worst paired boson endpoints instead of all failing ones")
    ap.add_argument("--scope", choices=("labeled", "all"), default="labeled",
                    help="labeled (default): boson datapath counts as DW only in instances where DC shows DW cells; "
                         "all: everywhere (valid only when the DC netlist kept every DW instance)")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    try:
        res = parse_resources(a.dc_resources.read_text()) if a.dc_resources else None
        report = compare(a.boson_dir, a.dc_dir, res, a.top, a.scope)
    except (OSError, ValueError, KeyError) as e:
        print(f"dw_compare: {e}", file=sys.stderr)
        return 1
    print(fmt(report))
    if a.json:
        a.json.write_text(json.dumps(report, indent=1, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
