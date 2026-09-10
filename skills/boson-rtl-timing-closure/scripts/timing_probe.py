#!/usr/bin/env python3
"""Probe a design's timing with boson and hand back the critical paths in a
form that maps to RTL: for each of the worst N paths, the launching and
capturing REGISTERS (synthesis keeps their RTL names), the logic depth, the
RTL-named nets the path passes through, and the slack.

Fast by default (`-effort fast`, layout-blind) so an edit-probe-edit loop
turns around in well under a minute on a small core; confirm a fix with
`--effort medium` (the timing-driven layout loop, several minutes).

    timing_probe.py --rtl design.v --top top --liberty cells.lib --period-ns 5 \\
        [--paths 5] [--effort fast|medium] [-G NAME=VALUE] [--json probe.json] [--diff prev.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ANON_NET = re.compile(r"^(n\d+|_\d+_|fanout_repair_\w+|net\d+|N\d+|\w*__bsn\w*|\w+_bsn)$")
ANON_INST = re.compile(r"^(g[sn]?\d+|fanout_repair_\w+|__boson_\w+|U\d+|_\d+_)$")


def parse_paths(text: str) -> list[dict]:
    paths = []
    blocks = re.split(r"\n(?=\s*Startpoint:)", text)
    for b in blocks:
        m = re.search(r"Startpoint:\s+(\S+)", b)
        if not m: continue
        p = {"startpoint": m.group(1)}
        e = re.search(r"Endpoint:\s+(\S+)", b); p["endpoint"] = e.group(1) if e else None
        s = re.search(r"slack\s*\((MET|VIOLATED)\)\s*(-?[\d.]+)", b) or re.search(r"slack\s+(-?[\d.]+)\s*\((MET|VIOLATED)\)", b)
        if s:
            a, c = s.groups()
            p["slack_ns"], p["status"] = (float(c), a) if a in ("MET", "VIOLATED") else (float(a), c)
        arr = re.search(r"data arrival time\s+(-?[\d.]+)", b); p["arrival_ns"] = float(arr.group(1)) if arr else None
        req = re.search(r"data required time\s+(-?[\d.]+)", b); p["required_ns"] = float(req.group(1)) if req else None
        # point lines: "<inst>/<pin> (<LIBCELL>) ... <incr> <path> r|f"  and  "<net> (net)  fanout cap"
        cells, nets = [], []
        for line in b.splitlines():
            mm = re.match(r"\s+(\S+)/(\S+)\s+\((\S+)\)\s+.*?(-?[\d.]+)\s+[&]?\s*(-?[\d.]+)\s+[rf]\b", line)
            if mm:
                inst, pin, lib = mm.group(1), mm.group(2), mm.group(3)
                cells.append({"inst": inst, "pin": pin, "cell": lib, "incr_ns": float(mm.group(4)), "path_ns": float(mm.group(5))})
                continue
            mn = re.match(r"\s+(\S+)\s+\(net\)\s+(\d+)\s+([\d.]+)", line)
            if mn:
                nets.append({"net": mn.group(1), "fanout": int(mn.group(2)), "cap": float(mn.group(3))})
        outputs = [c for c in cells if c["pin"] in ("Y", "Z", "Q", "QN", "X", "ZN", "OUT", "O", "S", "CO", "COUT")]
        p["stages"] = max(0, len(outputs) - 1)                 # combinational cells between launch and capture
        p["worst_cells"] = sorted(outputs, key=lambda c: -c["incr_ns"])[:3]
        p["named_nets"] = [n["net"] for n in nets if not ANON_NET.match(n["net"].rsplit(".", 1)[-1])][:12]
        p["high_fanout_nets"] = sorted(nets, key=lambda n: -n["fanout"])[:3]
        paths.append(p)
    return paths


def summarise(probe: dict) -> str:
    q = probe["qor"]
    out = [f"period {probe['period_ns']:g} ns · effort {probe['effort']} · WNS {q.get('wns_ns')} ns ({q.get('status')}) · "
           f"TNS {q.get('tns_ns')} ns · {q.get('violating')}/{q.get('endpoints')} endpoints violating · {probe['cells']} cells · {probe['wall_s']:.0f}s", ""]
    for i, p in enumerate(probe["paths"], 1):
        out.append(f"### path {i}: slack {p.get('slack_ns')} ns ({p.get('status')}), {p['stages']} logic stages, arrival {p.get('arrival_ns')} ns")
        out.append(f"- from `{p['startpoint']}`")
        out.append(f"- to   `{p['endpoint']}`")
        if p["named_nets"]:
            out.append("- RTL-named nets on the path: " + ", ".join(f"`{n}`" for n in p["named_nets"]))
        if p["worst_cells"]:
            out.append("- slowest stages: " + ", ".join(f"{c['cell']} {c['incr_ns']:.3f} ns" for c in p["worst_cells"]))
        if p["high_fanout_nets"] and p["high_fanout_nets"][0]["fanout"] >= 16:
            n = p["high_fanout_nets"][0]; out.append(f"- high fanout: `{n['net']}` drives {n['fanout']} loads")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, type=Path, nargs="+", help="RTL file(s)")
    ap.add_argument("--top", required=True)
    ap.add_argument("--liberty", action="append", type=Path, default=None)
    ap.add_argument("--lef", action="append", type=Path, default=[], help="Only needed with --effort medium/high (placement)")
    ap.add_argument("--period-ns", type=float, required=True); ap.add_argument("--clock-port", default="clk")
    ap.add_argument("--sdc-extra", type=Path, default=None)
    ap.add_argument("-G", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--effort", default="fast", choices=["fast", "low", "medium", "high"])
    ap.add_argument("--compile-extra", default="")
    ap.add_argument("--paths", type=int, default=5)
    ap.add_argument("--json", type=Path, default=None, help="Write the structured probe here")
    ap.add_argument("--diff", type=Path, default=None, help="Previous probe JSON to compare against")
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"))
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--keep", action="store_true", help="Keep the scratch dir (flow.tcl, boson.log, timing.rpt)")
    a = ap.parse_args()
    libs = a.liberty or ([Path(os.environ["BOSON_LIBERTY"])] if os.environ.get("BOSON_LIBERTY") else [])
    if not libs: ap.error("no liberty: --liberty or $BOSON_LIBERTY")
    for f in [*a.rtl, *libs, *a.lef]:
        if not f.exists(): ap.error(f"not found: {f}")
    if shutil.which(a.boson_bin) is None and not Path(a.boson_bin).exists():
        ap.error(f"boson binary not found ({a.boson_bin!r}); see https://partcl.com")

    d = Path(tempfile.mkdtemp(prefix=".probe_", dir=Path.cwd()))
    sdc = d / "clk.sdc"
    sdc.write_text(f"create_clock -name clk -period {a.period_ns:g} [get_ports {a.clock_port}]\n" + (a.sdc_extra.read_text() if a.sdc_extra else ""))
    gflags = " ".join(f"-G {g}" for g in a.G)
    rtl = " ".join(str(f.resolve()) for f in a.rtl)
    tcl = [f"read_liberty {l.resolve()}" for l in libs] + [f"read_lef {l.resolve()}" for l in a.lef] + [
        f"compile {rtl} -top {a.top} {gflags} -sdc {sdc} -effort {a.effort} {a.compile_extra}".replace("  ", " "),
        "update_timing", 'puts "===QOR==="', "puts [report_qor]", 'puts "===AREA==="', "puts [report_area]",
        f"report_timing -max_paths {a.paths} -format pt -file {d / 'timing.rpt'}",
    ]
    (d / "flow.tcl").write_text("\n".join(tcl) + "\n")
    t0 = time.time()
    print(f"[probe] compiling ({a.effort}) … log: {d / 'boson.log'}", file=sys.stderr)
    with open(d / "boson.log", "w") as log:   # streamed, so progress is visible while it runs
        proc = subprocess.run([a.boson_bin, "--no-color", "-f", str(d / "flow.tcl")], stdout=log, stderr=subprocess.STDOUT, text=True, timeout=a.timeout)
    wall = time.time() - t0
    out = (d / "boson.log").read_text(errors="replace")
    if proc.returncode != 0:
        print(out[-1500:], file=sys.stderr); print(f"[probe] boson exited {proc.returncode}; log at {d}", file=sys.stderr); return 2
    qor = {}
    m = re.search(r"^WNS:\s+(-?[\d.]+|n/a)\s+ns\s+\((\w+)\)", out, re.M)
    if m: qor["wns_ns"], qor["status"] = (None if m.group(1) == "n/a" else float(m.group(1))), m.group(2)
    m = re.search(r"^TNS:\s+(-?[\d.]+)", out, re.M); qor["tns_ns"] = float(m.group(1)) if m else None
    m = re.search(r"^Endpoints:\s+(\d+)\s+Violating:\s+(\d+)", out, re.M)
    if m: qor["endpoints"], qor["violating"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"report_synth: (\d+) cells", out); cells = int(m.group(1)) if m else None
    m = re.search(r"total cell area: ([\d.]+)", out); area = float(m.group(1)) if m else None
    rpt = (d / "timing.rpt").read_text() if (d / "timing.rpt").exists() else out
    probe = dict(period_ns=a.period_ns, effort=a.effort, params=a.G, qor=qor, cells=cells, area_um2=area, wall_s=wall,
                 paths=parse_paths(rpt), scratch=str(d))
    print(summarise(probe))
    if a.diff and a.diff.exists():
        prev = json.loads(a.diff.read_text())
        pw, cw = prev["qor"].get("wns_ns"), qor.get("wns_ns")
        print(f"## vs previous probe: WNS {pw} → {cw} ns ({(cw - pw):+.3f}), cells {prev.get('cells')} → {cells}, "
              f"violating {prev['qor'].get('violating')} → {qor.get('violating')}")
        pe = {p["endpoint"] for p in prev["paths"]}; ce = {p["endpoint"] for p in probe["paths"]}
        if ce - pe: print("- new worst endpoints: " + ", ".join(f"`{e}`" for e in sorted(ce - pe)))
        if pe - ce: print("- no longer in the worst list: " + ", ".join(f"`{e}`" for e in sorted(pe - ce)))
    if a.json:
        a.json.write_text(json.dumps(probe, indent=1))
    if not a.keep:
        shutil.rmtree(d, ignore_errors=True); probe["scratch"] = None
    else:
        print(f"[probe] scratch kept at {d}", file=sys.stderr)
    return 0 if qor.get("wns_ns") is not None and qor["wns_ns"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
