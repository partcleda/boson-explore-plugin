#!/usr/bin/env python3
"""Logic levels on the paths of a boson `report_timing` text report.

A level is one cell instance on the path that is not a buffer, inverter,
delay cell, register or clock gate. Buffers and inverters are excluded
because repair adds and removes them; the remaining count is the depth the
logic itself needs, comparable across runs, efforts and RTL variants.

  python3 path_levels.py timing.rpt [more.rpt ...] [--exclude REGEX] [--json out.json]

Library cell names differ between libraries. The default exclusion matches
common buffer/inverter/delay/flop/clock-gate names (BUF, INV, CKB, CKN, DEL,
DLY, DF, SDF, LAT, CKLN, ICG); pass --exclude for another naming scheme and
check the printed cell mix to confirm it excluded the right cells.
"""
import argparse
import collections
import json
import re
import sys

DEFAULT_EXCLUDE = r"^(BUF|INV|CKB|CKN|CLKBUF|CLKINV|DEL|DLY|DF|SDF|DFF|LAT|CKLN|ICG|TIE)"
POINT = re.compile(r"^\s*(\S+)/(\S+)\s+\(([A-Za-z_][\w]*)\)")
START = re.compile(r"^\s*Startpoint:\s*(\S+)")
END = re.compile(r"^\s*Endpoint:\s*(\S+)")
SLACK = re.compile(r"^\s*slack\s*\((\w+)\)\s+(-?[\d.]+)")


def paths(text):
    cur = None
    for line in text.splitlines():
        m = START.match(line)
        if m:
            if cur:
                yield cur
            cur = {"start": m.group(1), "end": None, "slack": None, "cells": []}
            continue
        if cur is None:
            continue
        m = END.match(line)
        if m:
            cur["end"] = m.group(1)
            continue
        m = SLACK.match(line)
        if m:
            cur["slack"] = float(m.group(2))
            continue
        m = POINT.match(line)
        if m:
            inst, lib_cell = m.group(1), m.group(3)
            if not cur["cells"] or cur["cells"][-1][0] != inst:
                cur["cells"].append((inst, lib_cell))
    if cur:
        yield cur


def family(lib_cell):
    # Drop the drive strength and library suffix: ND4D1BWP... -> ND4, NAND2_X1 -> NAND2.
    for suffix in (r"D\d+BWP.*$", r"_[xX]\d+.*$", r"_\d+$"):
        stem = re.sub(suffix, "", lib_cell)
        if stem != lib_cell:
            return stem
    return lib_cell


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE,
                    help="regex on the library cell name of cells that are not levels")
    ap.add_argument("--json", help="write per-path rows here")
    a = ap.parse_args()
    exclude = re.compile(a.exclude)
    rows = []
    for f in a.reports:
        for i, p in enumerate(paths(open(f).read())):
            logic = [c for _, c in p["cells"] if not exclude.match(c)]
            mix = collections.Counter(family(c) for c in logic).most_common(6)
            rows.append({"report": f, "path": i + 1, "start": p["start"], "end": p["end"],
                         "slack_ns": p["slack"], "cells": len(p["cells"]), "levels": len(logic),
                         "mix": mix})
    if not rows:
        sys.exit("no paths found: pass a text `report_timing` report (not -format json)")
    print(f"{'report':30} {'path':>4} {'slack(ns)':>10} {'levels':>6} {'cells':>5}  endpoint / top cell types")
    for r in rows:
        slack = "-" if r["slack_ns"] is None else f"{r['slack_ns']:.3f}"
        mix = ", ".join(f"{k}x{v}" for k, v in r["mix"])
        print(f"{r['report'][-30:]:30} {r['path']:>4} {slack:>10} {r['levels']:>6} {r['cells']:>5}  {r['end']}  [{mix}]")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
