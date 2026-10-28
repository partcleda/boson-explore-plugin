#!/usr/bin/env python3
"""Operator-level calibration of boson against DesignWare: the same isolated operator
(registered inputs and outputs, one clock) synthesized by both tools on the same
library, at a tight period (delay corner) and a relaxed one (area corner).

    dw_microbench.py gen  <dir> [--ops add:32,mult:16,...] [--tight 100] [--relaxed 2000]
                                [--lib-time-unit-ns 0.001]
    # in boson:  read_liberty ...; source <dir>/run_boson.tcl   -> <dir>/boson.tsv
    # in dc_shell: set target/link library; source <dir>/run_dc.tcl -> <dir>/dc.tsv
    dw_microbench.py compare <dir>

Periods are in the library's time unit (what the SDC means), e.g. ps for ASAP7.
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

# op -> (operands, body). `a`, `b`, `c` are W-bit, the result `y` is sized per op.
OPS = {
    "add":    ("a + b", "W"),
    "sub":    ("a - b", "W"),
    "addc":   ("a + b + c", "W+2"),
    "mult":   ("a * b", "2*W"),
    "smult":  ("$signed(a) * $signed(b)", "2*W"),
    "mac":    ("a * b + c", "2*W"),
    "cmp":    ("{{(W-1){1'b0}}, a < b}", "W"),
    "eq":     ("{{(W-1){1'b0}}, a == b}", "W"),
    "shl":    ("a << b[$clog2(W)-1:0]", "W"),
    "shr":    ("a >> b[$clog2(W)-1:0]", "W"),
    "inc":    ("a + 1'b1", "W"),
}
DEFAULT = "add:16,add:32,add:64,sub:32,addc:32,mult:8,mult:16,mult:32,smult:16,mac:16,cmp:32,eq:32,shl:32,shr:32,inc:32"


def rtl(op: str, w: int) -> str:
    expr, yw = OPS[op]
    yw = yw.replace("W", str(w))
    return f"""module mb_{op}_{w} #(parameter W = {w}) (
  input  logic clk,
  input  logic [W-1:0] a_i, b_i, c_i,
  output logic [{yw}-1:0] y_o
);
  logic [W-1:0] a, b, c;
  logic [{yw}-1:0] y;
  always_ff @(posedge clk) begin a <= a_i; b <= b_i; c <= c_i; y_o <= y; end
  assign y = {expr};
endmodule
"""


def gen(d: Path, ops: str, tight: float, relaxed: float, unit_ns: float) -> None:
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in ops.split(","):
        op, w = spec.split(":")
        if op not in OPS:
            raise SystemExit(f"unknown op {op}; known: {', '.join(OPS)}")
        top = f"mb_{op}_{w}"
        (d / f"{top}.sv").write_text(rtl(op, int(w)))
        for corner, period in (("tight", tight), ("relaxed", relaxed)):
            sdc = d / f"{top}.{corner}.sdc"
            sdc.write_text(f"create_clock -name clk -period {period} [get_ports clk]\n"
                           f"set_input_delay 0 -clock clk [remove_from_collection [all_inputs] [get_ports clk]]\n"
                           f"set_output_delay 0 -clock clk [all_outputs]\n")
            rows.append((top, op, w, corner, period))
    lst = "\n".join(f"  {{{t} {o} {w} {c} {p}}}" for t, o, w, c, p in rows)
    (d / "run_boson.tcl").write_text(f"""# boson: read_liberty your libraries first, then source this file.
# Delay = period - slack (ns); area = sum of cell areas.
set mb_dir [file dirname [info script]]
set fh [open $mb_dir/boson.tsv w]
puts $fh "tool\\ttop\\top\\twidth\\tcorner\\tperiod\\tslack_ns\\tdelay_ns\\tarea\\tcells"
foreach r {{
{lst}
}} {{
    lassign $r top op w corner period
    if {{[catch {{compile $mb_dir/$top.sv -top $top -sdc $mb_dir/$top.$corner.sdc}} e]}} {{ puts "MB FAIL $top $corner: $e"; continue }}
    update_timing
    set slack [get_attribute [get_timing_paths -max_paths 1] slack]
    set area 0.0; set n 0
    foreach_in_collection c [get_cells *] {{ set area [expr {{$area + [get_attribute $c area]}}]; incr n }}
    set pns [expr {{$period * {unit_ns}}}]
    puts $fh "boson\\t$top\\t$op\\t$w\\t$corner\\t$period\\t$slack\\t[expr {{$pns - $slack}}]\\t$area\\t$n"
    flush $fh
}}
close $fh
puts "microbench: boson.tsv written"
""")
    (d / "run_dc.tcl").write_text(f"""# dc_shell: set target_library/link_library first, then source this file.
# Uses compile_ultra (DesignWare available). Slack is in library units, converted to ns.
set mb_dir [file dirname [info script]]
set fh [open $mb_dir/dc.tsv w]
puts $fh "tool\\ttop\\top\\twidth\\tcorner\\tperiod\\tslack_ns\\tdelay_ns\\tarea\\tcells"
foreach r {{
{lst}
}} {{
    lassign $r top op w corner period
    remove_design -all
    analyze -format sverilog $mb_dir/$top.sv
    elaborate $top
    current_design $top
    link
    source $mb_dir/$top.$corner.sdc
    compile_ultra
    set slack [get_attribute [get_timing_paths -max_paths 1] slack]
    redirect -variable ar {{report_area}}
    regexp {{Total cell area:\\s+([0-9.]+)}} $ar -> area
    set n [sizeof_collection [get_cells -hier * -filter "is_hierarchical == false"]]
    set sns [expr {{$slack * {unit_ns}}}]
    set pns [expr {{$period * {unit_ns}}}]
    puts $fh "dc\\t$top\\t$op\\t$w\\t$corner\\t$period\\t$sns\\t[expr {{$pns - $sns}}]\\t$area\\t$n"
    flush $fh
}}
close $fh
puts "microbench: dc.tsv written"
""")
    print(f"wrote {len(rows) // 2} operators x 2 corners to {d}")


def read(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    lines = path.read_text().splitlines()
    head = lines[0].split("\t")
    for line in lines[1:]:
        r = dict(zip(head, line.split("\t")))
        out[(r["top"], r["corner"])] = r
    return out


def compare(d: Path) -> int:
    bo, dc = read(d / "boson.tsv"), read(d / "dc.tsv")
    if not bo or not dc:
        print(f"need both {d}/boson.tsv and {d}/dc.tsv", file=sys.stderr)
        return 1
    print(f"{'operator':16s} {'delay bo/dc (ps)':>20s} {'ratio':>6s} {'area@tight bo/dc':>20s} {'ratio':>6s} {'area@relaxed bo/dc':>20s} {'ratio':>6s}")
    ratios = collections.defaultdict(list)
    for top in sorted({k[0] for k in bo} & {k[0] for k in dc}):
        cells = []
        for corner, field in (("tight", "delay_ns"), ("tight", "area"), ("relaxed", "area")):
            b, c = bo.get((top, corner)), dc.get((top, corner))
            if not b or not c:
                cells.append(None)
                continue
            vb, vc = float(b[field]), float(c[field])
            scale = 1e3 if field == "delay_ns" else 1
            cells.append((vb * scale, vc * scale, vb / vc if vc else None))
            if vc:
                ratios[(corner, field)].append(vb / vc)
        txt = " ".join(f"{'-':>20s} {'-':>6s}" if x is None else f"{x[0]:9.1f}/{x[1]:<10.1f} {x[2]:6.2f}" for x in cells)
        print(f"{top:16s} {txt}")
    for (corner, field), rs in ratios.items():
        rs.sort()
        geo = 1.0
        for r in rs:
            geo *= r
        geo **= 1 / len(rs)
        print(f"geomean boson/DC {field.replace('_ns', '')}@{corner}: {geo:.3f} over {len(rs)} operators "
              f"(range {rs[0]:.2f}..{rs[-1]:.2f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("dir", type=Path)
    g.add_argument("--ops", default=DEFAULT, help=f"op:width list; ops: {', '.join(OPS)}")
    g.add_argument("--tight", type=float, default=100, help="delay-corner period, library time units")
    g.add_argument("--relaxed", type=float, default=2000, help="area-corner period, library time units")
    g.add_argument("--lib-time-unit-ns", type=float, default=0.001, help="ns per library time unit (0.001 for ps, 1 for ns)")
    c = sub.add_parser("compare")
    c.add_argument("dir", type=Path)
    a = ap.parse_args()
    if a.cmd == "gen":
        gen(a.dir, a.ops, a.tight, a.relaxed, a.lib_time_unit_ns)
        return 0
    return compare(a.dir)


if __name__ == "__main__":
    sys.exit(main())
