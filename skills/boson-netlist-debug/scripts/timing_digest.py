#!/usr/bin/env python3
"""Digest boson timing reports into per-path structure + a design summary.

    timing_digest.py [--timing anon/timing_1.rpt ...] [--timing-json anon/timing_1.json ...] \\
        [--qor anon/qor_1.rpt] [--check-timing anon/check_timing_1.rpt] [--netlist anon/netlist.v] \\
        [--out-md timing_digest.md] [--out-json timing_digest.json]

Run it on the ANONYMIZED copies (anonymize.py --out ...), so the digest is
shareable as is.

Inputs and assumptions (adapt if a field is missing; say so in REPORT.md):
- Text: `report_timing` full-path tables (boson default / `-format pt`):
  `Startpoint:`/`Endpoint:`/`Path Group:`/`Path Type:` headers; point rows
  `<inst>/<pin> (<cell>) ... <incr> [&] <path> r|f`; net rows
  `<net> (net) <fanout> <cap>`; port rows `<port> (in|out)`; clock rows
  `clock <clk> (rise|fall edge)`, `clock network delay (ideal|propagated)`,
  `clock uncertainty`, `library setup|hold time`, `input|output external delay`,
  `data arrival|required time`, `slack (MET|VIOLATED)`. A trailing
  placement `Location` `(x,y)`, the `&` marker and the r/f edge are stripped
  first; Incr/Path are the two rightmost numbers of a point row, other columns
  are placed by the header's column positions; Fanout/Cap come from `(net)`
  rows. With Location present, each driver->load wire gets a Manhattan length
  (um) and each path a total wire length and bounding span. Times are in ns; a
  `time unit`/`units` header line rescales them, otherwise ns is assumed.
- JSON: boson native `report_timing -format json`, schema_version 1:
  `paths[]` with startpoint/endpoint/path_group/path_type/slack_ns/arrival_ns/
  required_ns/unconstrained and `points[]` {point, net, increment_ns,
  arrival_ns, fanout}; net pseudo-points (point == net) carry the fanout of
  the previous output. JSON start/end name the pin, text the instance; they
  are matched without the pin. JSON points carry no cell type; pass `--netlist` to
  look the instances up (streamed). Null values stay null (never 0).
- QoR: `report_qor` `Key: value` lines (WNS/TNS/Hold WNS/.../Endpoints).
- check_timing: `Warning:`/`Information:` lines and the object lists below them.
Text and JSON of the same run are both parsed; paths are de-duplicated by
(startpoint, endpoint, path_type), JSON preferred for numbers, text for cells.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bdlib import (fmt, is_output_pin, md_table, num, open_text, parse_cell, strip_escape,  # noqa: E402
                    verilog_statements)

CLOCK_PINS = {"CLK", "CK", "CP", "C", "G", "GN", "CLKN", "CKN", "GATE", "E", "EN"}
_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _nums(s: str) -> list[float]:
    return [float(x) for x in _NUM.findall(s)]


LOCATION = re.compile(r"\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)\s*$")
_NUM_SPAN = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
COLS = ("Fanout", "Cap", "DTrans", "Trans", "Derate", "Delta", "Incr", "Path")
UNIT_RE = re.compile(r"(?i)\b(?:time[ _]unit|units?)\b\s*[:=]?\s*(?:1\.?0*\s*)?(ns|ps|us|fs)\b")
UNIT_SCALE = {"ns": 1.0, "ps": 1e-3, "us": 1e3, "fs": 1e-6}


def header_columns(line: str) -> dict | None:
    """End offsets of the numeric columns in a 'Point  Fanout  Cap ... Incr  Path  Location' header."""
    if not re.match(r"\s*Point\s", line) or "Incr" not in line or "Path" not in line:
        return None
    cols = {}
    for m in re.finditer(r"\S+", line):
        if m.group(0) in COLS or m.group(0) == "Location":
            cols[m.group(0)] = m.end()
    return cols


def split_row(rest: str, offset: int, cols: dict | None, point_row: bool = True) -> dict:
    """Numbers of one point/net row keyed by column.  The trailing placement Location '(x,y)', the
    '&' (annotated) marker and the r/f edge are removed first, so coordinates never read as delays.
    With a header, each number goes to the column whose right edge it is closest to; without one,
    the last two numbers are Incr and Path."""
    out: dict = {}
    m = LOCATION.search(rest)
    if m:
        out["loc"] = (float(m.group(1)), float(m.group(2)))
        rest = rest[: m.start()]
    m = re.search(r"\s([rf])\s*$", rest)
    if m:
        out["edge"] = m.group(1)
        rest = rest[: m.start()]
    nums = [(float(x.group(0)), x.end() + offset) for x in _NUM_SPAN.finditer(rest)]
    if cols and all(c in cols for c in ("Incr", "Path")):
        num_cols = {c: e for c, e in cols.items() if c in COLS}
        for v, end in nums:
            c = min(num_cols, key=lambda k: abs(num_cols[k] - end))
            out.setdefault(c, v)
    if point_row and nums:
        # Incr and Path are always the two rightmost numbers of a point row: trust that over column
        # positions (an edited or re-indented report shifts columns, never the order)
        out["Path"] = nums[-1][0]
        out["Incr"] = nums[-2][0] if len(nums) >= 2 else None
    return out


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) if a and b else None


def parse_text(path: Path) -> list[dict]:
    paths, cur, phase = [], None, None
    cols = None
    scale, unit = 1.0, None
    with open_text(path) as f:
        for line in f:
            s = line.rstrip("\n")
            if cur is None and unit is None:
                um = UNIT_RE.search(s)
                if um:
                    unit = um.group(1).lower()
                    scale = UNIT_SCALE[unit]
            hc = header_columns(s)
            if hc:
                cols = hc
                continue
            m = re.match(r"\s*Startpoint:\s+(\S+)(?:\s+\((.*)\))?", s)
            if m:
                cur = {"source": "text", "startpoint": m.group(1), "start_desc": m.group(2), "points": [],
                       "launch": {}, "capture": {}, "time_unit": f"{unit or 'ns'}{'' if unit else ' (assumed)'}"}
                cd = re.search(r"clocked by (\S+?)\)?$", m.group(2) or "")
                if cd:
                    cur["launch"]["clock"] = cd.group(1)
                paths.append(cur)
                phase = "launch"
                continue
            if cur is None:
                continue
            m = re.match(r"\s*Endpoint:\s+(\S+)(?:\s+\((.*)\))?", s)
            if m:
                cur["endpoint"], cur["end_desc"] = m.group(1), m.group(2)
                cd = re.search(r"clocked by (\S+?)\)?$", m.group(2) or "")
                if cd:
                    cur["capture"]["clock"] = cd.group(1)
                continue
            m = re.match(r"\s*Path Group:\s+(\S+)", s)
            if m:
                cur["path_group"] = m.group(1)
                continue
            m = re.match(r"\s*Path Type:\s+(\S+)", s)
            if m:
                cur["path_type"] = m.group(1)
                continue
            m = re.match(r"\s*slack\s*\((\w+)\)\s+(-?[\d.]+)", s) or re.match(r"\s*slack\s+(-?[\d.]+)\s*\((\w+)\)", s)
            if m:
                a, b = m.groups()
                cur["status"], cur["slack_ns"] = (a, float(b) * scale) if not re.match(r"-?[\d.]+$", a) else (b, float(a) * scale)
                cur = None
                continue
            m = re.match(r"\s*data arrival time\s+(-?[\d.]+)", s)
            if m and phase == "launch":
                cur["arrival_ns"] = float(m.group(1)) * scale
                phase = "capture"
                continue
            m = re.match(r"\s*data required time\s+(-?[\d.]+)", s)
            if m:
                cur["required_ns"] = float(m.group(1)) * scale
                continue
            side = cur[phase] if phase in ("launch", "capture") else cur["capture"]
            m = re.match(r"\s*clock (\S+) \((rise|fall) edge\)(.*)", s)
            if m:
                side["clock"], side["edge"] = m.group(1), m.group(2)
                n = [x * scale for x in _nums(m.group(3))]
                side["edge_ns"] = n[-1] if n else None
                continue
            m = re.match(r"\s*clock network delay \((ideal|propagated)\)(.*)", s)
            if m:
                n = [x * scale for x in _nums(m.group(2))]
                side["network"], side["network_ns"] = m.group(1), (n[-2] if len(n) >= 2 else (n[0] if n else None))
                continue
            m = re.match(r"\s*clock uncertainty(.*)", s)
            if m:
                n = [x * scale for x in _nums(m.group(1))]
                cur["uncertainty_ns"] = n[-2] if len(n) >= 2 else None
                continue
            m = re.match(r"\s*library (setup|hold) time(.*)", s)
            if m:
                n = [x * scale for x in _nums(m.group(2))]
                cur[f"library_{m.group(1)}_ns"] = n[-2] if len(n) >= 2 else None
                continue
            m = re.match(r"\s*(input|output) external delay(.*)", s)
            if m:
                n = [x * scale for x in _nums(m.group(2))]
                cur[f"{m.group(1)}_delay_ns"] = n[-2] if len(n) >= 2 else (n[0] if n else None)
                continue
            m = re.match(r"\s+(\S+)\s+\(net\)(.*)", s)
            if m:
                # net rows carry Fanout and Cap of the net driven by the previous (output) point
                v = split_row(m.group(2), m.start(2), cols, point_row=False)
                if v.get("Fanout") is not None and v["Fanout"] != int(v["Fanout"]):
                    v = {}                                     # columns shifted: fall back to order (fanout, cap)
                n = _nums(m.group(2))
                fo = v.get("Fanout", n[0] if n else None)
                cap = v.get("Cap", n[1] if len(n) > 1 else None)
                if cur["points"] and phase == "launch":
                    cur["points"][-1]["net"] = m.group(1)
                    cur["points"][-1]["fanout"] = int(fo) if fo is not None else None
                    cur["points"][-1]["cap"] = cap
                continue
            m = re.match(r"\s+(\S+)\s+\(([^)\s]+)\)(.*)$", s)
            if m:
                obj, cell, rest = m.groups()
                v = split_row(rest.replace("&", " "), m.start(3), cols)
                sc = lambda k: v[k] * scale if v.get(k) is not None else None  # noqa: E731
                pt = {"point": obj, "cell": None if cell in ("in", "out", "inout") else cell,
                      "port_dir": cell if cell in ("in", "out", "inout") else None,
                      "incr_ns": sc("Incr"), "arrival_ns": sc("Path"), "edge": v.get("edge"),
                      "trans_ns": sc("Trans"), "loc": v.get("loc")}
                if "/" in obj:
                    pt["inst"], pt["pin"] = obj.rsplit("/", 1)
                else:
                    pt["inst"], pt["pin"] = None, obj
                if phase == "launch":
                    cur["points"].append(pt)
                elif pt["pin"] and pt["pin"].upper() in CLOCK_PINS and pt["arrival_ns"] is not None:
                    cur["capture"]["clock_pin_arrival_ns"] = pt["arrival_ns"]
    return paths


def parse_json(path: Path) -> tuple[list[dict], dict]:
    with open_text(path) as f:
        d = json.load(f)
    meta = {k: d.get(k) for k in ("schema_version", "timing_complete", "warnings", "message", "rtl_available")}
    if d.get("schema_version") not in (1, None):
        meta["note"] = f"unknown schema_version {d.get('schema_version')}; parsed as v1"
    out = []
    for p in d.get("paths") or []:
        q = {"source": "json", "startpoint": p.get("startpoint"), "endpoint": p.get("endpoint"),
             "path_group": p.get("path_group"), "path_type": p.get("path_type"), "slack_ns": num(p.get("slack_ns")),
             "arrival_ns": num(p.get("arrival_ns")), "required_ns": num(p.get("required_ns")),
             "unconstrained": p.get("unconstrained"), "launch": {}, "capture": {}, "points": []}
        if q["slack_ns"] is not None:
            q["status"] = "VIOLATED" if q["slack_ns"] < 0 else "MET"
        elif q["unconstrained"]:
            q["status"] = "UNCONSTRAINED"
        q["rtl_hint"] = {k: (p.get(k) or {}).get("name") for k in ("start_rtl", "end_rtl")}
        for pt in p.get("points") or []:
            o = pt.get("point") or ""
            if o and o == pt.get("net") and q["points"]:
                # net pseudo-point: carries the fanout of the net driven by the previous (output) point
                prev = q["points"][-1]
                prev["net"] = prev.get("net") or o
                if pt.get("fanout") is not None:
                    prev["fanout"] = pt.get("fanout")
                continue
            m = re.match(r"^(\S+)\s+\(([^)]+)\)$", o)
            cell = None
            if m:
                o, cell = m.groups()
            inst, pin = (o.rsplit("/", 1) if "/" in o else (None, o))
            q["points"].append({"point": o, "inst": inst, "pin": pin, "cell": cell, "net": pt.get("net"),
                                "incr_ns": num(pt.get("increment_ns")), "arrival_ns": num(pt.get("arrival_ns")),
                                "fanout": pt.get("fanout"), "rtl": (pt.get("rtl") or {}).get("name")})
        out.append(q)
    meta["groups"] = d.get("groups") or []
    return out, meta


def _no_pin(name):
    return re.sub(r"/[A-Z][A-Z0-9_]*$", "", name) if name else name


def lookup_cells(paths: list[dict], netlist: Path) -> int:
    want = {p["inst"] for q in paths for p in q["points"] if p.get("inst") and not p.get("cell")}
    if not want:
        return 0
    found = {}
    inst_re = re.compile(r"^(\\\S+|[A-Za-z_][\w$]*)\s+(?:#\s*\(.*?\)\s*)?(\\\S+|[A-Za-z_][\w$]*)\s*\(")
    for _, st in verilog_statements(netlist):
        m = inst_re.match(st)
        if m:
            name = strip_escape(m.group(2))
            if name in want:
                found[name] = strip_escape(m.group(1))
    for q in paths:
        for p in q["points"]:
            if not p.get("cell") and p.get("inst") in found:
                p["cell"] = found[p["inst"]]
    return len(found)


def analyse_path(q: dict) -> dict:
    pts = q["points"]
    outs = [p for p in pts if p.get("pin") and p.get("inst") and is_output_pin(p["pin"], None, p.get("cell"))]
    start_is_reg = bool(pts) and pts[0].get("pin", "").upper() in CLOCK_PINS
    comb = outs[1:] if start_is_reg and outs else outs
    if comb and not start_is_reg and comb[0] is pts[0]:
        comb = comb[1:]           # JSON paths start at the launch register's output pin
    end = pts[-1] if pts else {}
    if comb and end.get("inst") and comb[-1].get("inst") == end.get("inst"):
        comb = comb[:-1]
    # placement: the wire from each driving output pin to the next (load) pin on the path
    idx = {id(p): i for i, p in enumerate(pts)}
    wires = []
    for p in outs:
        i = idx[id(p)]
        if i + 1 < len(pts):
            nxt = pts[i + 1]
            d = _manhattan(p.get("loc"), nxt.get("loc"))
            if d is not None:
                wires.append({"driver": p.get("inst"), "cell": p.get("cell"), "load": nxt.get("point"), "net": p.get("net"),
                              "fanout": p.get("fanout"), "wire_um": round(d, 3), "wire_delay_ns": nxt.get("incr_ns")})
    wire_by_driver = {w["driver"]: w for w in wires}
    locs = [p["loc"] for p in pts if p.get("loc")]
    span = (max(x for x, _ in locs) - min(x for x, _ in locs) + max(y for _, y in locs) - min(y for _, y in locs)) if locs else None
    stages = []
    for p in comb:
        c = parse_cell(p.get("cell") or "?")
        w = wire_by_driver.get(p.get("inst")) or {}
        stages.append({"inst": p.get("inst"), "cell": p.get("cell"), "function": c["function"], "class": c["class"],
                       "drive": c["drive"], "vt": c["vt"], "delay_ns": p.get("incr_ns"), "fanout": p.get("fanout"),
                       "net": p.get("net"), "wire_um": w.get("wire_um"), "wire_delay_ns": w.get("wire_delay_ns")})
    wire = [p.get("incr_ns") for p in pts if p not in outs and p.get("incr_ns")]
    cls = Counter(s["class"] for s in stages)
    fn = Counter(s["function"] for s in stages)
    weak = [s for s in stages if s["drive"] and re.match(r"^(p\d+|0?\.?\d*|1|0P\d+)$", s["drive"], re.I)
            and (s["fanout"] or 0) >= 8]
    l, c = q.get("launch", {}), q.get("capture", {})
    launch_lat = None
    if start_is_reg and pts[0].get("arrival_ns") is not None:
        launch_lat = pts[0]["arrival_ns"] - (l.get("edge_ns") or 0.0)
    elif l.get("network_ns") is not None:
        launch_lat = l["network_ns"]
    cap_lat = None
    if c.get("clock_pin_arrival_ns") is not None:
        cap_lat = c["clock_pin_arrival_ns"] - (c.get("edge_ns") or 0.0)
    elif c.get("network_ns") is not None:
        cap_lat = c["network_ns"]
    skew = cap_lat - launch_lat if (cap_lat is not None and launch_lat is not None) else None
    cell_delay = sum(s["delay_ns"] or 0 for s in stages)
    return {
        "startpoint": q.get("startpoint"), "endpoint": q.get("endpoint"), "path_group": q.get("path_group"),
        "path_type": q.get("path_type"), "slack_ns": q.get("slack_ns"), "status": q.get("status"),
        "arrival_ns": q.get("arrival_ns"), "required_ns": q.get("required_ns"),
        "launch_clock": l.get("clock"), "capture_clock": c.get("clock"),
        "period_hint_ns": (c.get("edge_ns") - (l.get("edge_ns") or 0.0)) if c.get("edge_ns") is not None else None,
        "clock_network": l.get("network") or c.get("network"),
        "launch_latency_ns": launch_lat, "capture_latency_ns": cap_lat, "skew_ns": skew,
        "uncertainty_ns": q.get("uncertainty_ns"), "setup_time_ns": q.get("library_setup_ns"),
        "input_delay_ns": q.get("input_delay_ns"), "output_delay_ns": q.get("output_delay_ns"),
        "time_unit": q.get("time_unit", "ns"),
        "placed": bool(locs), "total_wire_um": round(sum(w["wire_um"] for w in wires), 3) if wires else None,
        "bbox_span_um": round(span, 3) if span is not None else None,
        "longest_wires": sorted(wires, key=lambda w: -w["wire_um"])[:5],
        "stages": len(stages), "cell_delay_ns": cell_delay, "wire_delay_ns": sum(wire) if wire else None,
        "class_histogram": dict(cls), "function_histogram": dict(fn.most_common()),
        "buffers": cls.get("buffer", 0) + cls.get("clock_buffer", 0), "inverters": cls.get("inverter", 0) + cls.get("clock_inverter", 0),
        "max_fanout": max([s["fanout"] or 0 for s in stages] or [0]),
        "slowest": sorted([s for s in stages if s["delay_ns"] is not None], key=lambda s: -s["delay_ns"])[:5],
        "weak_drivers_high_fanout": weak[:5],
        "vt_mix": dict(Counter(s["vt"] for s in stages if s["vt"])),
        "rtl_hint": q.get("rtl_hint"),
        "stage_list": stages,
        "objects": sorted({p.get("inst") for p in pts if p.get("inst")} | {p.get("net") for p in pts if p.get("net")}
                          | {q.get("startpoint") or "", q.get("endpoint") or ""} - {""}),
    }


def endpoint_group(name: str | None) -> str:
    if not name:
        return "?"
    n = re.sub(r"\[\d+\]", "[*]", name)
    return n.rsplit("/", 1)[0] + "/*" if "/" in n and n.rsplit("/", 1)[1].isupper() else n


def parse_qor(path: Path) -> dict:
    out = {}
    with open_text(path) as f:
        for line in f:
            for m in re.finditer(r"([A-Za-z][A-Za-z /_-]*?):\s+(-?[\d.]+|n/a)\s*(ns|ps|um2|mW|uW)?\s*(?:\((\w+)\))?", line):
                k = m.group(1).strip().lower().replace(" ", "_")
                v = None if m.group(2) == "n/a" else (float(m.group(2)) if "." in m.group(2) else int(m.group(2)))
                out[k] = v
                if m.group(4):
                    out[k + "_status"] = m.group(4)
            m = re.match(r"\s*Design:\s+(\S+)", line)
            if m:
                out["design"] = m.group(1)
    return out


def parse_check_timing(path: Path) -> dict:
    checks, warnings, cur = [], [], None
    counts = {}
    with open_text(path) as f:
        for line in f:
            s = line.rstrip("\n")
            m = re.match(r"\s*Information: Checking '(\w+)'", s)
            if m:
                checks.append(m.group(1))
                cur = None
                continue
            m = re.match(r"\s*(Warning|Error):\s*(.*)", s)
            if m:
                cur = {"severity": m.group(1), "text": m.group(2), "objects": []}
                warnings.append(cur)
                continue
            m = re.match(r"\s+(Pins|Endpoints|Startpoints):\s+(\d+)", s)
            if m:
                counts[m.group(1).lower()] = int(m.group(2))
                continue
            if cur is not None and s.startswith((" ", "\t")) and s.strip():
                cur["objects"].append(s.strip())
    for w in warnings:
        w["object_count"] = len(w["objects"])
        w["objects"] = w["objects"][:20]
    return {"checks_run": checks, "issues": warnings, "counts": counts}


def digest(text_files, json_files, qor_files, ct_files, netlist=None) -> dict:
    paths, meta = [], []
    for p in json_files:
        q, m = parse_json(Path(p))
        paths += q
        meta.append(m)
    text_paths = []
    for p in text_files:
        text_paths += parse_text(Path(p))
    # cells from text, numbers from JSON.  JSON names the start/end pin ('.../CP'); text names the instance.
    def key(q):
        return (_no_pin(q["startpoint"]), _no_pin(q.get("endpoint")), q.get("path_type") or "max")
    by_key = {}
    for q in text_paths:
        by_key.setdefault(key(q), q)
    seen = {key(q) for q in paths}
    for q in paths:
        t = by_key.get(key(q))
        if t:
            tp = {p["point"]: p for p in t["points"]}
            for p in q["points"]:
                tt = tp.get(p["point"]) or {}
                p["cell"] = p.get("cell") or tt.get("cell")
                for k in ("loc", "trans_ns", "cap"):
                    if p.get(k) is None and tt.get(k) is not None:
                        p[k] = tt[k]
                if p.get("fanout") is None and tt.get("fanout") is not None:
                    p["fanout"] = tt["fanout"]
            q["launch"], q["capture"] = t["launch"], t["capture"]
            for k in ("uncertainty_ns", "library_setup_ns", "input_delay_ns", "output_delay_ns"):
                q.setdefault(k, t.get(k))
    for q in text_paths:
        if key(q) not in seen:
            paths.append(q)
    found = lookup_cells(paths, Path(netlist)) if netlist else 0
    analysed = [analyse_path(q) for q in paths]
    analysed.sort(key=lambda a: (a["slack_ns"] is None, a["slack_ns"] if a["slack_ns"] is not None else 0))
    for i, a in enumerate(analysed, 1):
        a["id"] = f"P{i}"
    eg, sg = defaultdict(list), defaultdict(list)
    for a in analysed:
        eg[endpoint_group(a["endpoint"])].append(a["slack_ns"])
        sg[endpoint_group(a["startpoint"])].append(a["slack_ns"])
    def groups(g):
        rows = []
        for k, v in g.items():
            vv = [x for x in v if x is not None]
            rows.append({"group": k, "paths": len(v), "worst_slack_ns": min(vv) if vv else None,
                         "violating": sum(1 for x in vv if x < 0)})
        return sorted(rows, key=lambda r: (r["worst_slack_ns"] is None, r["worst_slack_ns"] or 0))
    qor = {}
    for p in qor_files:
        qor.update(parse_qor(Path(p)))
    ct = [parse_check_timing(Path(p)) for p in ct_files]
    cell_hist = Counter()
    for a in analysed:
        cell_hist.update(a["class_histogram"])
    return {"meta": meta, "netlist_cells_looked_up": found, "qor": qor, "check_timing": ct, "paths": analysed,
            "endpoint_groups": groups(eg), "startpoint_groups": groups(sg),
            "sample": {"paths": len(analysed), "violating": sum(1 for a in analysed if (a["slack_ns"] or 0) < 0),
                       "unconstrained": sum(1 for a in analysed if a["slack_ns"] is None),
                       "class_histogram_on_paths": dict(cell_hist)}}


def to_md(d: dict, detail: int = 10) -> str:
    o = ["# Timing digest", ""]
    q = d["qor"]
    if q:
        o.append("## report_qor")
        o.append(md_table(["metric", "value"], [[k, v] for k, v in q.items()]))
    for m in d["meta"]:
        if m.get("timing_complete") is False or m.get("warnings") or m.get("note"):
            o.append(f"> JSON report: timing_complete={m.get('timing_complete')} warnings={m.get('warnings')!r} {m.get('note') or ''}\n")
    s = d["sample"]
    o.append(f"## Reported path sample: {s['paths']} paths, {s['violating']} violating, {s['unconstrained']} unconstrained")
    o.append("_The sample is what report_timing printed (max_paths); design-wide numbers are in report_qor._\n")
    units = sorted({a.get("time_unit", "ns") for a in d["paths"]})
    if units:
        o.append(f"_Times in ns (report unit: {', '.join(units)}); distances in um from the report's Location column._\n")
    o.append(md_table(["id", "slack", "type", "stages", "arrival", "cell/wire delay", "skew", "bufs/invs", "max fo", "wire um", "start", "end"],
                      [[a["id"], a["slack_ns"], a["path_type"] or "", a["stages"], a["arrival_ns"],
                        f"{fmt(a['cell_delay_ns'])}/{fmt(a['wire_delay_ns'])}", a["skew_ns"],
                        f"{a['buffers']}/{a['inverters']}", a["max_fanout"], a.get("total_wire_um"),
                        f"`{a['startpoint']}`", f"`{a['endpoint']}`"]
                       for a in d["paths"]]))
    o.append("## Endpoint groups (bus bits folded)")
    o.append(md_table(["group", "paths", "violating", "worst slack"],
                      [[f"`{g['group']}`", g["paths"], g["violating"], g["worst_slack_ns"]] for g in d["endpoint_groups"][:25]]))
    o.append("## Startpoint groups")
    o.append(md_table(["group", "paths", "violating", "worst slack"],
                      [[f"`{g['group']}`", g["paths"], g["violating"], g["worst_slack_ns"]] for g in d["startpoint_groups"][:25]]))
    o.append("## Path detail")
    for a in d["paths"][:detail]:
        o.append(f"### {a['id']}: slack {fmt(a['slack_ns'])} ns ({a['status']}), {a['stages']} stages")
        o.append(f"- `{a['startpoint']}` -> `{a['endpoint']}` ({a['launch_clock']} -> {a['capture_clock']}, "
                 f"{a['clock_network'] or 'clock network ?'}; launch latency {fmt(a['launch_latency_ns'])}, "
                 f"capture latency {fmt(a['capture_latency_ns'])}, skew {fmt(a['skew_ns'])} ns, "
                 f"uncertainty {fmt(a['uncertainty_ns'])}, setup {fmt(a['setup_time_ns'])})")
        if a["period_hint_ns"] is not None:
            o.append(f"- capture edge - launch edge = {fmt(a['period_hint_ns'])} ns (compare with the SDC period: a mismatch means units or waveform were read differently)")
        if a["input_delay_ns"] is not None or a["output_delay_ns"] is not None:
            o.append(f"- I/O delay: input {fmt(a['input_delay_ns'])}, output {fmt(a['output_delay_ns'])} ns")
        o.append(f"- cell classes: {', '.join(f'{k} {v}' for k, v in sorted(a['class_histogram'].items(), key=lambda kv: -kv[1]))}")
        if a.get("placed"):
            o.append(f"- placement: total driver->load wire {fmt(a['total_wire_um'])} um, path bounding span "
                     f"{fmt(a['bbox_span_um'])} um; longest wires: " + ", ".join(
                         f"`{w['driver']}` {w['cell']} -> `{w['load']}` {fmt(w['wire_um'])} um "
                         f"({fmt(w['wire_delay_ns'])} ns, fo {w['fanout']})" for w in a["longest_wires"][:3]))
        if a["slowest"]:
            o.append("- slowest stages: " + ", ".join(f"`{s['inst']}` {s['cell']} {fmt(s['delay_ns'])} ns (fo {s['fanout']})" for s in a["slowest"]))
        if a["weak_drivers_high_fanout"]:
            o.append("- weak driver on high fanout: " + ", ".join(f"`{s['inst']}` {s['cell']} fo {s['fanout']}" for s in a["weak_drivers_high_fanout"]))
        if a["vt_mix"]:
            o.append(f"- VT mix: {a['vt_mix']}")
        if a.get("rtl_hint") and any(a["rtl_hint"].values()):
            o.append(f"- RTL hint (anonymized): {a['rtl_hint']}")
        o.append("")
    for ct in d["check_timing"]:
        o.append("## check_timing")
        o.append(f"checks run: {', '.join(ct['checks_run']) or '–'}; counts {ct['counts']}\n")
        o.append(md_table(["severity", "issue", "objects"], [[w["severity"], w["text"], w["object_count"]] for w in ct["issues"]]))
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timing", action="append", default=[])
    ap.add_argument("--timing-json", action="append", default=[])
    ap.add_argument("--qor", action="append", default=[])
    ap.add_argument("--check-timing", action="append", default=[])
    ap.add_argument("--netlist", help="look up cell types for JSON points (streamed)")
    ap.add_argument("--detail", type=int, default=10, help="paths to describe in detail")
    ap.add_argument("--out-md"); ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    d = digest(a.timing, a.timing_json, a.qor, a.check_timing, a.netlist)
    md = to_md(d, a.detail)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(d, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
