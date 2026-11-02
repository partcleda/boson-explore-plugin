#!/usr/bin/env python3
"""Put one example of every table shape (from shape_census.py) through boson.

For each example cell it writes a mini library: the source file's own header, verbatim
(units, templates, operating conditions), plus that cell's text, verbatim. It loads the
mini library in a fresh boson session and records:
- whether it loads, and every message boson prints (beyond those the header alone
  produces);
- check_library's verdict for the cell, and whether an arc of the table's timing_type
  exists;
- for delay, transition, clock-to-Q, setup and hold tables, boson's own timing of
  the arc at two exact index points (no interpolation), compared with the table entry.

    shape_probe.py shapes.json --boson /path/to/boson [--out shape_probe] [--jobs 4]

Writes <out>/report.md (local: names the cells), <out>/results.json (local), and
<out>/shapes_summary.json (shareable: Liberty keywords, dimensions, counts and
verdicts only, with no library, cell, pin or template names and no values). It also
writes <out>/submit.tcl, which sends the summary with boson's report_feedback only
if the user sources it.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DELAY = {"cell_rise": ("rise", "delay"), "cell_fall": ("fall", "delay"),
         "rise_transition": ("rise", "transition"), "fall_transition": ("fall", "transition")}
CONSTRAINT = {"rise_constraint": "rise", "fall_constraint": "fall"}
SLEW_VARS = {"input_net_transition", "input_transition_time"}
LOAD_VARS = {"total_output_net_capacitance", "output_net_capacitance"}
MSG = re.compile(r"^(Error|Warning|Information): (.*?)(?: \(([A-Z]+-\d+)\))?$")


def unit_ns(time_unit: str) -> float:
    m = re.fullmatch(r"\s*(\d*\.?\d*)\s*(ps|ns|us|fs)\s*", time_unit.strip('"') or "1ns")
    if not m:
        return 1.0
    return (float(m.group(1) or 1)) * {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3}[m.group(2)]


def probe_plan(c: dict, scale: float) -> tuple[list[dict], str]:
    """Probes for one shape class, or the reason it is not probed."""
    ex, tt = c["example"], c["timing_type"]
    vals, idx = ex["values"], ex["index"]
    dims, variables = c["dims"], c["variables"]
    if not ex.get("related_pin") or not ex.get("pin"):
        return [], "library- or cell-level table (not under a timing group with a related_pin)"
    if ex.get("related_direction") in ("output", "internal"):
        return [], f"arc from an {ex['related_direction']} pin: its slew cannot be set by the probe"
    if c["table"] in DELAY:
        if tt.startswith("combinational") or tt == "":
            if ex.get("related_is_clock"):
                return [], "combinational arc from a clock pin (e.g. a clock gate): not timed by an ideal-clock probe"
            mode = "comb"
        elif tt in ("rising_edge", "falling_edge"):
            mode = "edge"
        else:
            return [], f"timing_type {tt} is not probed"
        known = SLEW_VARS | LOAD_VARS
    elif c["table"] in CONSTRAINT:
        if tt.startswith(("setup_", "recovery_")):
            mode = "setup"
        elif tt.startswith(("hold_", "removal_")):
            mode = "hold"
        else:
            return [], f"timing_type {tt} is not probed"
        known = {"related_pin_transition", "constrained_pin_transition"}
    else:
        return [], f"{c['table']} tables are not probed"
    if any(v not in known for v in variables):
        return [], f"variable(s) {', '.join(v for v in variables if v not in known)} are not probed"
    if len(vals) != max(1, _prod(dims)):
        return [], "value count does not match the index grid"
    probes = []
    # two off-diagonal points: on a square grid a diagonal point reads the same entry
    # from a transposed table, so it cannot catch swapped axes
    for pick in (0, 1):
        pos = [min(d - 1, 1) if (k + pick) % 2 == 0 else d - 1 for k, d in enumerate(dims)]
        flat = 0
        for k, d in enumerate(dims):
            flat = flat * d + pos[k]
        point = {variables[k]: idx[str(k + 1)][pos[k]] for k in range(len(dims))}
        p = {"cell": ex["cell"], "from": ex["related_pin"].split()[0], "to": ex["pin"], "mode": mode,
             "clock_edge": "fall" if tt.endswith("falling") or tt == "falling_edge" else "rise",
             "point": point, "position": pos, "expected_ns": vals[flat] * scale,
             "slew": 0.0, "dslew": 0.0, "load": 0.0}
        for v, x in point.items():
            if v in SLEW_VARS or v == "related_pin_transition":
                p["slew"] = x
            elif v in LOAD_VARS:
                p["load"] = x
            elif v == "constrained_pin_transition":
                p["dslew"] = x
        if c["table"] in DELAY:
            p["edge"], p["quantity"] = DELAY[c["table"]]
        else:
            p["edge"], p["quantity"] = CONSTRAINT[c["table"]], "delay"
        probes.append(p)
        if not dims:
            break
    return probes, ""


def isolable(lines: list[str], ranges: list) -> bool:
    """Groups can be removed by whole lines only when each starts its line and its
    closing brace stands alone on the last line."""
    for s, e in ranges:
        if not re.match(r"\s*(timing|internal_power)\s*\(", lines[s - 1]) or lines[e - 1].strip() != "}":
            return False
    return True


def _prod(xs):
    out = 1
    for x in xs:
        out *= x
    return out


def run_boson(boson: str, tcl: Path, cwd: Path, timeout: int) -> str:
    try:
        # one stream, in write order: messages must land between the section markers
        r = subprocess.run([boson], input=f"source {tcl.name}\nexit\n", stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, cwd=cwd, timeout=timeout)
        return r.stdout
    except subprocess.TimeoutExpired as e:
        return (e.stdout or "") + f"\nError: boson did not finish in {timeout} s (TIMEOUT-1)\n"


def messages(log: str) -> list[dict]:
    out = []
    for line in log.splitlines():
        m = MSG.match(line.strip())
        if m and m.group(1) != "Information":
            out.append({"severity": m.group(1), "id": m.group(3) or "", "text": m.group(2)})
    return out


def probe_one(job: dict) -> dict:
    d: Path = job["dir"]
    d.mkdir(parents=True, exist_ok=True)
    lines = job["lines"]
    a, b = job["cell_lines"]
    body = lines[a - 1:b]
    keep, drop = job.get("keep"), job.get("drop") or []
    if keep is not None:
        # every other timing/internal_power group of the cell is removed, so messages and
        # probe values belong to this table's group alone
        gone = set()
        for s, e in drop:
            if [s, e] != keep and not (keep[0] <= s and e <= keep[1]):
                gone.update(range(s, e + 1))
        body = [l for n, l in enumerate(body, a) if n not in gone]
    (d / "mini.lib").write_text("".join(lines[:job["header_end"]]) + "".join(body) + "}\n")
    tcl = [f"set_app_var libcache_dir {d / 'libcache'}", "read_liberty mini.lib",
           "puts \"CHECKLIB_BEGIN\"", "catch {check_library}", "puts \"CHECKLIB_END\""]
    if job["cell"] != "-":
        tcl += [f"foreach_in_collection a [get_lib_timing_arcs -quiet -of_objects [get_lib_pins -quiet \"{job['cell']}/*\"]] "
           "{ puts \"ARC [get_attribute $a from_pin] [get_attribute $a to_pin] [get_attribute $a timing_type]\" }"]
    for i, p in enumerate(job["probes"]):
        tcl += [f"puts \"PROBE_BEGIN {i}\"",
                f"set probe_cell {{{p['cell']}}}; set probe_from {{{p['from']}}}; set probe_to {{{p['to']}}}",
                f"set probe_mode {p['mode']}; set probe_slew {p['slew']}; set probe_dslew {p['dslew']}; "
                f"set probe_load {p['load']}; set probe_unit_ns {job['unit_ns']}; set probe_clock_edge {p['clock_edge']}",
                f"if {{[catch {{source {HERE / 'probe_table.tcl'}}} e]}} {{ puts \"PROBE_ERROR $e\" }}",
                f"puts \"PROBE_END {i}\""]
    (d / "run.tcl").write_text("\n".join(tcl) + "\n")
    log = run_boson(job["boson"], d / "run.tcl", d, job["timeout"])
    (d / "boson.log").write_text(log)
    loaded = re.search(r"read_liberty: loaded .*\((\d+) cells?\)", log)
    check = ""
    if "CHECKLIB_BEGIN" in log:
        for line in log.split("CHECKLIB_BEGIN", 1)[1].split("CHECKLIB_END", 1)[0].splitlines():
            if line.strip().startswith(job["cell"] + " "):
                check = " ".join(line.split()[1:])
    arcs = [l.split()[1:] for l in log.splitlines() if l.startswith("ARC ")]
    results = []
    for i, p in enumerate(job["probes"]):
        seg = log.split(f"PROBE_BEGIN {i}", 1)[-1].split(f"PROBE_END {i}", 1)[0]
        got = None
        # an error inside a sourced file stops that file without raising to catch
        err = next((l.strip() for l in seg.splitlines() if l.startswith("PROBE_ERROR") or l.startswith("Error:")), "")
        for l in seg.splitlines():
            f = l.split()
            if len(f) >= 3 and f[0] == "PROBE" and f[2] == p["edge"]:
                vals = f[3:]
                k = 0 if p["quantity"] == "delay" else 1
                if len(vals) > k:
                    try:
                        got = float(vals[k])
                    except ValueError:
                        got = None
        ok = got is not None and abs(got - p["expected_ns"]) <= 1e-6 + 1e-4 * abs(p["expected_ns"])
        results.append({**{k: v for k, v in p.items()}, "got_ns": got, "match": ok, "error": err})
    return {"key": job["key"], "loaded_cells": int(loaded.group(1)) if loaded else 0,
            "messages": messages(log.split("CHECKLIB_BEGIN", 1)[0]), "check_library": check, "arcs": arcs,
            "probes": results, "dir": str(d)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shapes", type=Path)
    ap.add_argument("--boson", default=shutil.which("boson") or "boson")
    ap.add_argument("--out", type=Path, default=Path("shape_probe"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    census = json.loads(a.shapes.read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    a.out = a.out.resolve()
    files = {f["file"]: f for f in census["files"]}
    text = {f: Path(f).read_text(errors="replace").splitlines(keepends=True) for f in files}

    # baseline: the header alone, so header messages are not charged to a shape
    jobs, by_cell = [], {}
    for fname, f in files.items():
        jobs.append({"key": ("header", fname), "dir": a.out / f"header_{len(jobs)}", "lines": text[fname],
                     "header_end": f["header_end_line"], "cell_lines": (1, 0), "cell": "-", "probes": [],
                     "boson": a.boson, "timeout": a.timeout, "unit_ns": unit_ns(f["time_unit"])})
    plans, cls_job = [], {}
    for ci, c in enumerate(census["classes"]):
        ex = c["example"]
        if not ex.get("cell_lines"):
            # library-level tables (driver waveforms, ...) load with the header
            plans.append(([], "library-level table: loads with the header, see file messages"))
            continue
        scale = unit_ns(files[ex["file"]]["time_unit"])
        probes, why = probe_plan(c, scale)
        for p in probes:
            p["class"] = ci
        plans.append((probes, why))
        keep = ex.get("group_lines")
        drop = ex.get("removable") or []
        if keep and not isolable(text[ex["file"]], drop):
            keep = None
        job = {"key": ("class", ci), "dir": a.out / f"class_{ci:04d}", "lines": text[ex["file"]],
               "header_end": files[ex["file"]]["header_end_line"], "cell_lines": tuple(ex["cell_lines"]),
               "cell": ex["cell"], "probes": probes, "boson": a.boson, "timeout": a.timeout,
               "unit_ns": scale, "keep": keep, "drop": drop}
        jobs.append(job)
        cls_job[ci] = job
        ck = (ex["file"], ex["cell"])
        if ck not in by_cell:
            by_cell[ck] = {"key": ("cell",) + ck, "dir": a.out / f"cell_{len(by_cell):04d}", "lines": text[ex["file"]],
                           "header_end": files[ex["file"]]["header_end_line"], "cell_lines": tuple(ex["cell_lines"]),
                           "cell": ex["cell"], "probes": [], "boson": a.boson, "timeout": a.timeout, "unit_ns": scale}
            jobs.append(by_cell[ck])
    print(f"{len(census['classes'])} shape classes, {len(by_cell)} example cells, "
          f"{sum(len(p) for p, _ in plans)} probes; running boson once per class ...", flush=True)
    with cf.ThreadPoolExecutor(a.jobs) as pool:
        done = {tuple(r["key"]): r for r in pool.map(probe_one, jobs)}

    header_msgs = {}
    for fname in files:
        header_msgs[fname] = {(m["id"], m["text"]) for m in done[("header", fname)]["messages"]}
    rows, summary = [], {}
    for ci, c in enumerate(census["classes"]):
        ex = c["example"]
        probes, why = plans[ci]
        r = done.get(("class", ci))
        isolated = bool(cls_job.get(ci, {}).get("keep"))
        hdr = header_msgs.get(ex["file"], set())
        whole = done.get(("cell", ex["file"], ex["cell"])) or {}
        in_cell = {(m["id"], m["text"]) for m in whole.get("messages", [])} - hdr
        # a message is this table's when the verbatim cell prints it and the cell cut down
        # to this table's group still prints it; one only the cut-down cell prints is an
        # artefact of removing the other groups
        own = [m for m in (r or {}).get("messages", []) if (m["id"], m["text"]) in in_cell
               or (not isolated and (m["id"], m["text"]) not in hdr)]
        pr = [p for p in (r or {}).get("probes", []) if p.get("class") == ci]
        arc_present = any(len(x) >= 3 and x[2] == c["timing_type"] for x in (r or {}).get("arcs", [])) \
            if c["timing_type"] else None
        if r is None:
            verdict = "library-level, not probed"
        elif any(m["severity"] == "Error" for m in own) or not r["loaded_cells"]:
            verdict = "LOAD ERROR"
        elif pr and any(p["got_ns"] is None for p in pr):
            # the probe could not measure: an older boson, or a probe limitation, not a
            # finding about the library
            verdict = "PROBE FAILED"
        elif pr and not all(p["match"] for p in pr):
            verdict = "MISMATCH"
        elif c["timing_type"] and arc_present is False:
            verdict = "NO ARC"
        elif own:
            verdict = "WARNING"
        elif pr:
            verdict = "OK (timed exactly)"
        else:
            verdict = "loaded, not probed"
        rows.append({"class": ci, **{k: c[k] for k in ("table", "owner", "timing_type", "variables", "dims",
                                                         "overrides", "count")},
                     "verdict": verdict, "why_not_probed": why if not pr else "", "messages": own,
                     "check_library": (r or {}).get("check_library", ""), "arc_present": arc_present,
                     "isolated": isolated, "cell_messages": sorted({m["id"] for m in whole.get("messages", [])
                                                                     if (m["id"], m["text"]) in in_cell}),
                     "probes": pr, "example": {k: ex[k] for k in ("file", "cell", "pin", "related_pin", "line", "template")},
                     "work_dir": (r or {}).get("dir", "")})
        summary.setdefault(verdict, 0)
        summary[verdict] += 1

    (a.out / "results.json").write_text(json.dumps(rows, indent=1))
    # messages the header alone produces are about the file (units, templates, defaults),
    # not one shape: reported once per file
    file_msgs = [{"file": f, "messages": done[("header", f)]["messages"]} for f in files]
    shareable = {"schema": 1, "tool": "boson-liberty-shapes",
                 "file_message_ids": sorted({m["id"] for fm in file_msgs for m in fm["messages"] if m["id"]}),
                 "classes": [
        {k: r[k] for k in ("table", "owner", "timing_type", "variables", "dims", "overrides", "count", "verdict")}
        | {"message_ids": sorted({m["id"] for m in r["messages"] if m["id"]}),
           "probe_matches": [p["match"] for p in r["probes"]]} for r in rows], "verdicts": summary}
    (a.out / "shapes_summary.json").write_text(json.dumps(shareable, indent=1))
    (a.out / "submit.tcl").write_text(
        "# Sends shapes_summary.json (Liberty keywords, dimensions, counts, verdicts; no names or values)\n"
        "# to partcl. Source in boson only if you agree to send it.\n"
        "set fh [open [file join [file dirname [info script]] shapes_summary.json]]\n"
        "set msg [string trim [read $fh]]\nclose $fh\n"
        "if {[string length $msg] > 3800} { set msg [string range $msg 0 3799] }\n"
        "report_feedback -category bug -message $msg -context \"skill=boson-liberty-shapes\"\n")

    total = sum(r["count"] for r in rows)
    probed_tables = sum(r["count"] for r in rows if r["probes"])
    exact_tables = sum(r["count"] for r in rows if r["verdict"] == "OK (timed exactly)")
    shareable["tables"] = {"total": total, "in_probed_classes": probed_tables, "in_exact_classes": exact_tables}
    (a.out / "shapes_summary.json").write_text(json.dumps(shareable, indent=1))
    md = ["# Liberty table shapes through boson", "",
          f"{total} tables; {probed_tables} ({probed_tables / max(total, 1):.0%}) are in shape classes that were "
          f"timed, {exact_tables} in classes boson timed exactly.", "",
          f"{len(rows)} shape classes from {len(files)} file(s). Verdicts: "
          + ", ".join(f"{k} {v}" for k, v in sorted(summary.items())), ""]
    for fm in file_msgs:
        if fm["messages"]:
            md += [f"Messages from the header of {Path(fm['file']).name} alone (units, templates, defaults):", ""]
            md += [f"- {m['severity']} {m['id']}: {m['text'][:300]}" for m in fm["messages"]] + [""]
    if summary.get("PROBE FAILED"):
        md += [f"**{summary['PROBE FAILED']} class(es): the probe returned no value.** That is not a finding about "
               "the library: the boson build may predate a query the probe uses, or the arc could not be timed "
               "in isolation. Rerun with a current boson, then read the class's `boson.log`.", ""]
    if census.get("problems"):
        md += [f"**{len(census['problems'])} table(s) in the files themselves have a value count that does not "
               "match their index grid** (see shapes.json `problems`).", ""]
    md += ["| # | verdict | count | table | timing_type | dims | variables | example | detail |", "|---|---|---|---|---|---|---|---|---|"]
    order = {"LOAD ERROR": 0, "MISMATCH": 1, "NO ARC": 2, "WARNING": 3, "PROBE FAILED": 4,
             "loaded, not probed": 5, "library-level, not probed": 6, "OK (timed exactly)": 7}
    for r in sorted(rows, key=lambda r: (order.get(r["verdict"], 9), r["class"])):
        dims = "x".join(map(str, r["dims"])) or "scalar"
        detail = []
        for m in r["messages"][:3]:
            detail.append(f"{m['severity']} {m['id']}: {m['text'][:160]}")
        for p in r["probes"]:
            if not p["match"]:
                detail.append(f"at {p['point']}: table {p['expected_ns']:.6g} ns, boson "
                              f"{'none' if p['got_ns'] is None else format(p['got_ns'], '.6g')} ns {p['error']}")
        if r["why_not_probed"]:
            detail.append(f"not probed: {r['why_not_probed']}")
        ex = r["example"]
        md.append(f"| {r['class']} | {r['verdict']} | {r['count']} | {r['table']} | {r['timing_type'] or '-'} | {dims} | "
                  f"{', '.join(r['variables']) or '-'} | {Path(ex['file']).name}:{ex['line']} {ex['cell']} "
                  f"{ex['related_pin']}->{ex['pin']} | {'<br>'.join(detail).replace('|', '/')} |")
    (a.out / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:4]))
    for r in rows:
        if r["verdict"] in ("LOAD ERROR", "MISMATCH", "NO ARC", "WARNING", "PROBE FAILED"):
            print(f"  class {r['class']}: {r['verdict']} {r['table']} {r['timing_type']} "
                  f"{'x'.join(map(str, r['dims'])) or 'scalar'} ({r['count']} tables) "
                  f"e.g. {r['example']['cell']} line {r['example']['line']}")
    print(f"\n-> {a.out}/report.md (local), {a.out}/shapes_summary.json (shareable), {a.out}/submit.tcl")
    return 1 if any(r["verdict"] in ("LOAD ERROR", "MISMATCH", "NO ARC") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
