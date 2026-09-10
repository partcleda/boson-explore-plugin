#!/usr/bin/env python3
"""Sweep clock period and RTL parameters through boson, report the
area/power/timing tradeoff.

Drives `boson` (a real synthesis+STA+power run per sweep point, no
approximation) via generated .tcl scripts, then parses the plain-text
`report_qor` / `report_area` / `report_power` output boson prints.

Usage:
    boson_dse.py --rtl designs/picorv32/picorv32.v --top picorv32 \\
        --liberty /path/to/std_cell.lib \\
        --periods 8,10,12,16,20 \\
        --presets min-area,balanced,max-perf \\
        --out results.md

Requires a `boson` binary on PATH (or --boson-bin / $BOSON_BIN) and a
Liberty file for your target library (or $BOSON_LIBERTY). boson itself is
partcl's product, not shipped in this repo — see partcl.com.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Every real RTL parameter picorv32.v exposes on its top module (all boolean
# 0/1 except the four address/mask constants, which we leave at RTL default
# since they don't change synthesis QoR). Presets below only ever set a
# subset — anything unset keeps picorv32's own default.
PARAM_PRESETS: dict[str, dict[str, int]] = {
    "min-area": {
        "BARREL_SHIFTER": 0,
        "TWO_STAGE_SHIFT": 0,
        "ENABLE_FAST_MUL": 0,
        "ENABLE_MUL": 0,
        "ENABLE_DIV": 0,
        "COMPRESSED_ISA": 0,
        "ENABLE_REGS_DUALPORT": 0,
        "ENABLE_REGS_16_31": 0,
        "ENABLE_COUNTERS": 0,
        "ENABLE_COUNTERS64": 0,
        "ENABLE_IRQ": 0,
        "ENABLE_IRQ_QREGS": 0,
        "ENABLE_IRQ_TIMER": 0,
        "ENABLE_PCPI": 0,
        "TWO_CYCLE_ALU": 1,
        "TWO_CYCLE_COMPARE": 1,
    },
    "balanced": {},  # picorv32's own defaults
    "max-perf": {
        "BARREL_SHIFTER": 1,
        "TWO_STAGE_SHIFT": 1,
        "ENABLE_FAST_MUL": 1,
        "ENABLE_MUL": 1,
        "ENABLE_DIV": 1,
        "COMPRESSED_ISA": 1,
        "ENABLE_REGS_DUALPORT": 1,
        "TWO_CYCLE_ALU": 0,
        "TWO_CYCLE_COMPARE": 0,
    },
}

QOR_WNS_RE = re.compile(r"^WNS:\s+([\-\d.]+|n/a)\s+ns\s+\((\w+)\)", re.M)
QOR_TNS_RE = re.compile(r"^TNS:\s+([\-\d.]+)\s+ns", re.M)
QOR_ENDPOINTS_RE = re.compile(r"^Endpoints:\s+(\d+)\s+Violating:\s+(\d+)", re.M)
AREA_CELLS_RE = re.compile(r"report_synth:\s+(\d+)\s+cells\s+\((\d+)\s+sequential\)")
AREA_UM2_RE = re.compile(r"total cell area:\s+([\d.]+)\s+um\^2")
# report_power's OpenSTA-shaped table: "Total   <internal> <switching> <leakage> <total> NN.N%"
POWER_TOTAL_RE = re.compile(
    r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.]+)%",
    re.M,
)


@dataclass
class SweepPoint:
    preset: str
    period_ns: float
    ok: bool = False
    error: str = ""
    wns_ns: float | None = None
    wns_status: str = ""
    tns_ns: float | None = None
    endpoints: int | None = None
    violating: int | None = None
    cells: int | None = None
    seq_cells: int | None = None
    area_um2: float | None = None
    power_internal_w: float | None = None
    power_switching_w: float | None = None
    power_leakage_w: float | None = None
    power_total_w: float | None = None
    raw_stdout: str = field(default="", repr=False)


def build_tcl(
    rtl: Path,
    top: str,
    liberty: Path,
    period_ns: float,
    gparams: dict[str, int],
    effort: str,
    vcd_path: Path,
) -> str:
    sdc = f"create_clock -name clk -period {period_ns} [get_ports clk]"
    gflags = " ".join(f"-G {name}={value}" for name, value in gparams.items())
    return f"""\
read_liberty {liberty}
compile {rtl} -top {top} {gflags} -effort {effort}
{sdc}
update_timing
puts "===QOR==="
puts [report_qor]
puts "===AREA==="
puts [report_area]
write_random_vcd -cycles 500 {vcd_path}
puts "===POWER==="
puts [report_power -vcd {vcd_path}]
"""


def run_point(
    boson_bin: str,
    rtl: Path,
    top: str,
    liberty: Path,
    preset: str,
    period_ns: float,
    effort: str,
    workdir: Path,
) -> SweepPoint:
    point = SweepPoint(preset=preset, period_ns=period_ns)
    gparams = PARAM_PRESETS[preset]
    vcd_path = workdir / f"{preset}_{period_ns}.vcd"
    tcl = build_tcl(rtl, top, liberty, period_ns, gparams, effort, vcd_path)
    tcl_path = workdir / f"{preset}_{period_ns}.tcl"
    tcl_path.write_text(tcl)

    try:
        proc = subprocess.run(
            [boson_bin, "-f", str(tcl_path)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        point.error = "boson run timed out after 600s"
        return point

    out = proc.stdout + "\n" + proc.stderr
    point.raw_stdout = out
    if proc.returncode != 0:
        point.error = f"boson exited {proc.returncode}: {out[-500:]}"
        return point

    m = QOR_WNS_RE.search(out)
    if m:
        point.wns_ns = None if m.group(1) == "n/a" else float(m.group(1))
        point.wns_status = m.group(2)
    m = QOR_TNS_RE.search(out)
    if m:
        point.tns_ns = float(m.group(1))
    m = QOR_ENDPOINTS_RE.search(out)
    if m:
        point.endpoints, point.violating = int(m.group(1)), int(m.group(2))

    m = AREA_CELLS_RE.search(out)
    if m:
        point.cells, point.seq_cells = int(m.group(1)), int(m.group(2))
    m = AREA_UM2_RE.search(out)
    if m:
        point.area_um2 = float(m.group(1))

    m = POWER_TOTAL_RE.search(out)
    if m:
        point.power_internal_w = float(m.group(1))
        point.power_switching_w = float(m.group(2))
        point.power_leakage_w = float(m.group(3))
        point.power_total_w = float(m.group(4))

    point.ok = point.wns_ns is not None or point.wns_status == "MET"
    if not point.ok and not point.error:
        point.error = "could not parse report_qor output — see raw log"
    return point


def render_markdown(points: list[SweepPoint]) -> str:
    lines = [
        "| Preset | Period (ns) | Timing | WNS (ns) | Cells | Area (um^2) | Power (mW) |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in points:
        if not p.ok:
            err = p.error.replace("|", "/").splitlines()[0][:80]
            lines.append(f"| {p.preset} | {p.period_ns} | ERROR: {err} | — | — | — | — |")
            continue
        wns = "n/a" if p.wns_ns is None else f"{p.wns_ns:.3f}"
        power_mw = "n/a" if p.power_total_w is None else f"{p.power_total_w * 1000:.4f}"
        area = "n/a" if p.area_um2 is None else f"{p.area_um2:.1f}"
        lines.append(
            f"| {p.preset} | {p.period_ns} | {p.wns_status} | {wns} | {p.cells} | {area} | {power_mw} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, type=Path, help="Path to picorv32.v (or another single-file RTL design)")
    ap.add_argument("--top", default="picorv32", help="Top module name (default: picorv32)")
    ap.add_argument("--liberty", type=Path, default=os.environ.get("BOSON_LIBERTY"), help="Liberty (.lib) file; defaults to $BOSON_LIBERTY")
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"), help="Path to the boson binary; defaults to $BOSON_BIN or 'boson' on PATH")
    ap.add_argument("--periods", default="8,12,20", help="Comma-separated clock periods in ns")
    ap.add_argument("--presets", default="min-area,balanced,max-perf", help="Comma-separated presets from: " + ", ".join(PARAM_PRESETS))
    ap.add_argument("--effort", default="medium", choices=["fast", "low", "medium", "high"])
    ap.add_argument("--out", type=Path, default=None, help="Write the Markdown table here (default: stdout only)")
    ap.add_argument("--keep-workdir", action="store_true", help="Don't delete the temp dir of generated .tcl/.vcd files")
    args = ap.parse_args()

    if args.liberty is None:
        ap.error("no liberty file given — pass --liberty or set $BOSON_LIBERTY")
    if not args.liberty.exists():
        ap.error(f"liberty file not found: {args.liberty}")
    if not args.rtl.exists():
        ap.error(f"RTL file not found: {args.rtl}")
    if shutil.which(args.boson_bin) is None and not Path(args.boson_bin).exists():
        ap.error(
            f"boson binary not found ({args.boson_bin!r}) — pass --boson-bin, set $BOSON_BIN, "
            "or put boson on PATH. boson is partcl's product; see https://partcl.com"
        )

    periods = [float(p) for p in args.periods.split(",") if p.strip()]
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    for preset in presets:
        if preset not in PARAM_PRESETS:
            ap.error(f"unknown preset {preset!r}; choose from {list(PARAM_PRESETS)}")

    # boson's host wrapper (many installs run it in a container that mounts
    # only the current working directory) can't see paths outside cwd, so
    # the scratch dir for generated .tcl/.vcd files has to live under cwd —
    # NOT the system tmp dir.
    workdir = Path(tempfile.mkdtemp(prefix=".boson_dse_", dir=Path.cwd()))
    points: list[SweepPoint] = []
    try:
        for preset in presets:
            for period in periods:
                print(f"[boson_dse] {preset} @ {period}ns ...", file=sys.stderr)
                point = run_point(
                    args.boson_bin, args.rtl.resolve(), args.top, args.liberty.resolve(),
                    preset, period, args.effort, workdir,
                )
                points.append(point)
                status = "ok" if point.ok else f"FAILED: {point.error}"
                print(f"[boson_dse]   -> {status}", file=sys.stderr)
    finally:
        if not args.keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"[boson_dse] workdir kept at {workdir}", file=sys.stderr)

    table = render_markdown(points)
    print(table)
    if args.out:
        args.out.write_text(table + "\n")
        print(f"[boson_dse] wrote {args.out}", file=sys.stderr)

    return 0 if all(p.ok for p in points) else 1


if __name__ == "__main__":
    raise SystemExit(main())
