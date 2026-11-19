#!/usr/bin/env python3
"""Generic PPA optimisation with boson: close timing at a target clock with
the cheapest optimisation recipe that works, and/or find the design's fmax.

Effort ladder (each rung is one real compile + STA run; the ladder stops at
the first rung that MEETS timing unless --full-ladder):

    0  -effort medium            the standard compile (map + setup/DRV repair)
    1  -effort medium -retime    + pipeline-register retiming (same cycle behaviour)
    2  -effort high              strongest map and setup repair
                                 (sets compile_allow_high_effort true)
    3  -effort high -retime      both

Each rung reports two rows from one compile: the netlist as `compile` returns
it, and the same netlist after an extra `repair_timing -setup`. Compile already
repairs setup, so the extra repair is usually a no-op; it can recover a little
WNS/TNS, and it stops at once when timing is met. --no-extra-repair skips it.

--find-fmax runs a short period search using achieved clock
(1/(period - WNS)) as the estimator, at the winning recipe.

    ppa_optimize.py --rtl design.v --top top --liberty cells.lib \\
        --target-ns 7 --find-fmax --out ppa.md

Every number reported comes from report_qor / report_area / report_power.
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
from dataclasses import dataclass, asdict
from pathlib import Path

# (label, compile flags, Tcl run before compile)
LADDER = [
    ("medium", "-effort medium", []),
    ("medium+retime", "-effort medium -retime", []),
    ("high", "-effort high", ["set_app_var compile_allow_high_effort true"]),
    ("high+retime", "-effort high -retime", ["set_app_var compile_allow_high_effort true"]),
]
REPAIR = "repair_timing -setup"

WNS_RE = re.compile(r"^WNS:\s+(-?[\d.]+|n/a)\s+ns\s+\((\w+)\)", re.M)
TNS_RE = re.compile(r"^TNS:\s+(-?[\d.]+) ns", re.M)
HOLD_RE = re.compile(r"^Hold WNS:\s+(-?[\d.]+) ns", re.M)
VIOL_RE = re.compile(r"^Endpoints:\s+(\d+)\s+Violating:\s+(\d+)", re.M)
CELLS_RE = re.compile(r"report_synth: (\d+) cells")
AREA_RE = re.compile(r"total cell area: ([\d.]+) um\^2")
POWER_RE = re.compile(r"^Total\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)", re.M)
MAXCAP_RE = re.compile(r"^Max capacitance violations: (\d+)", re.M)


@dataclass
class Result:
    label: str
    period_ns: float
    flags: str
    stage: str = "compile"
    ok: bool = False
    error: str = ""
    wns_ns: float | None = None
    status: str = ""
    tns_ns: float | None = None
    hold_wns_ns: float | None = None
    violating: int | None = None
    max_cap_viol: int | None = None
    cells: int | None = None
    area_um2: float | None = None
    power_w: float | None = None
    wall_s: float = 0.0
    fmax_mhz: float | None = None

    def met(self): return self.ok and self.wns_ns is not None and self.wns_ns >= 0


class Runner:
    def __init__(self, a, workdir: Path):
        self.a, self.workdir = a, workdir
        self.n = 0

    def tcl_head(self):
        lines = [f"read_liberty {l}" for l in self.a.liberty]
        if self.a.extra_tcl:
            lines.append(f"source {self.a.extra_tcl.resolve()}")
        return lines

    def compile_line(self, sdc, flags: str, rtl: str | None = None) -> str:
        prov = " -provenance" if self.a.provenance else ""
        return (f"compile {rtl or self.a.rtl.resolve()} -top {self.a.top} {self.a.gflags} -sdc {sdc} "
                f"{flags}{prov} {self.a.compile_extra}").replace("  ", " ").strip()

    def run(self, label: str, period_ns: float, flags: str, pre: list[str]) -> list[Result]:
        """One compile; returns the compile row and, unless disabled, the extra-repair row."""
        self.n += 1
        d = self.workdir / f"{self.n:02d}_{re.sub(r'[^A-Za-z0-9.+-]', '-', label)}_{period_ns:g}ns"
        d.mkdir(parents=True, exist_ok=True)
        sdc = d / "clk.sdc"
        sdc_text = f"create_clock -name clk -period {period_ns:g} [get_ports {self.a.clock_port}]\n"
        if self.a.sdc_extra:
            sdc_text += self.a.sdc_extra.read_text()
        sdc.write_text(sdc_text)

        def measure(tag: str) -> list[str]:
            m = ["update_timing",
                 f'puts "==={tag}:QOR==="', "puts [report_qor]",
                 f'puts "==={tag}:AREA==="', "puts [report_area]"]
            if not self.a.no_power:
                m += [f'puts "==={tag}:POWER==="', f"puts [report_power -vcd {d / 'random.vcd'}]"]
            return m

        lines = self.tcl_head() + pre + [self.compile_line(sdc, flags)]
        if not self.a.no_power:
            lines.append(f"write_random_vcd -cycles {self.a.vcd_cycles} {d / 'random.vcd'}")
        lines += measure("COMPILE")
        lines += [f"report_timing -max_paths 10 -format json -file {d / 'timing_compile.json'}"]
        if not self.a.no_extra_repair:
            lines += [REPAIR] + measure("REPAIR")
            lines += [f"report_timing -max_paths 10 -format json -file {d / 'timing_repair.json'}"]
        lines += [f"write_verilog {d / 'netlist.v'}"]
        (d / "flow.tcl").write_text("\n".join(lines) + "\n")

        print(f"[ppa] {label} @ {period_ns:g} ns: {flags}", file=sys.stderr)
        rows = [Result(label=label, period_ns=period_ns, flags=flags, stage="compile")]
        if not self.a.no_extra_repair:
            rows.append(Result(label=label, period_ns=period_ns, flags=flags, stage="+" + REPAIR))
        t0 = time.time()
        try:
            proc = subprocess.run([self.a.boson_bin, "--no-color", "-f", str(d / "flow.tcl")],
                                  capture_output=True, text=True, timeout=self.a.timeout)
            out = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            for r in rows: r.error = f"timed out after {self.a.timeout}s"
            return rows
        wall = time.time() - t0
        (d / "boson.log").write_text(out)
        if proc.returncode != 0:
            msg = f"boson exited {proc.returncode}: " + (out.strip().splitlines()[-1][:200] if out.strip() else "")
            for r in rows: r.error = msg
            return rows
        for r, tag in zip(rows, ("COMPILE", "REPAIR")):
            sect = _section(out, tag)
            r.wall_s = wall
            m = WNS_RE.search(sect)
            if m:
                r.wns_ns = None if m.group(1) == "n/a" else float(m.group(1)); r.status = m.group(2)
            r.tns_ns = _num(TNS_RE, sect); r.hold_wns_ns = _num(HOLD_RE, sect)
            m = VIOL_RE.search(sect); r.violating = int(m.group(2)) if m else None
            r.max_cap_viol = _num(MAXCAP_RE, sect, int)
            r.cells = _num(CELLS_RE, sect, int); r.area_um2 = _num(AREA_RE, sect)
            m = POWER_RE.search(sect); r.power_w = float(m.group(4)) if m else None
            r.ok = r.wns_ns is not None
            if r.ok:
                r.fmax_mhz = 1000.0 / (period_ns - r.wns_ns)
            else:
                r.error = "could not parse report_qor (see boson.log)"
            print(f"[ppa]   {r.stage:>22}: {r.status or 'ERROR'} WNS {r.wns_ns} ns · TNS {r.tns_ns} · {r.cells} cells · "
                  f"{r.area_um2} um² · {(r.power_w or 0) * 1e3:.1f} mW", file=sys.stderr)
        print(f"[ppa]   wall {wall:.0f}s · {d}", file=sys.stderr)
        return rows


def _section(out: str, tag: str) -> str:
    """The text between ===TAG:QOR=== and the next stage's marker."""
    i = out.find(f"==={tag}:QOR===")
    if i < 0:
        return ""
    j = out.find("===REPAIR:QOR===", i + 1) if tag == "COMPILE" else -1
    return out[i:j if j > 0 else len(out)]


def _num(rx, text, cast=float):
    m = rx.search(text); return cast(m.group(1)) if m else None


def fmt(r: Result) -> str:
    if not r.ok:
        return f"| {r.label} | {r.stage} | {r.period_ns:g} | ERROR: {r.error[:60]} | | | | | | |"
    pw = f"{r.power_w * 1e3:.1f}" if r.power_w is not None else "n/a"
    tns = f"{r.tns_ns:+.3f}" if r.tns_ns is not None else "n/a"
    cells = f"{r.cells:,}" if r.cells is not None else "n/a"
    area = f"{r.area_um2:,.0f}" if r.area_um2 is not None else "n/a"
    return (f"| {r.label} | {r.stage} | {r.period_ns:g} | {r.status} | {r.wns_ns:+.3f} | {tns} | {r.fmax_mhz:.0f} | "
            f"{cells} | {area} | {pw} |")


HEADER = ("| effort | stage | period (ns) | timing | WNS (ns) | TNS (ns) | achieved (MHz) | cells | area (µm²) | power (mW) |\n"
          "|---|---|---|---|---|---|---|---|---|---|")


def _better(a: Result | None, b: Result) -> bool:
    """Is b a better winner than a: met, then smaller area."""
    return b.met() and (a is None or (b.area_um2 or 0) < (a.area_um2 or 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, type=Path); ap.add_argument("--top", required=True)
    ap.add_argument("--liberty", action="append", type=Path, default=None)
    ap.add_argument("--extra-tcl", type=Path, default=None,
                    help="Tcl sourced after the libraries and before compile (dont_use lists, app variables)")
    ap.add_argument("--sdc-extra", type=Path, default=None, help="SDC text appended after the generated clock")
    ap.add_argument("-G", action="append", default=[], metavar="NAME=VALUE", help="top-parameter override (repeatable)")
    ap.add_argument("--compile-extra", default=""); ap.add_argument("--clock-port", default="clk")
    ap.add_argument("--target-ns", type=float, default=None, help="Clock period to close timing at")
    ap.add_argument("--find-fmax", action="store_true", help="Search for the fastest closable period (at the winning recipe)")
    ap.add_argument("--fmax-probes", type=int, default=3, help="Max period probes for --find-fmax")
    ap.add_argument("--start-rung", type=int, default=0); ap.add_argument("--max-rung", type=int, default=len(LADDER) - 1)
    ap.add_argument("--full-ladder", action="store_true", help="Run every rung even after one meets timing")
    ap.add_argument("--no-retime", action="store_true",
                    help="Skip the -retime rungs (e.g. a flow whose sign-off cannot accept moved registers)")
    ap.add_argument("--no-extra-repair", action="store_true",
                    help=f"Skip the extra `{REPAIR}` after compile (report the compile row only)")
    ap.add_argument("--provenance", action="store_true",
                    help="compile -provenance (same netlist; enables report_provenance in a follow-up session)")
    ap.add_argument("--no-power", action="store_true"); ap.add_argument("--vcd-cycles", type=int, default=500)
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"))
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--workdir", type=Path, default=None, help="Where runs go (default: .ppa_<pid> under cwd, kept)")
    ap.add_argument("--out", type=Path, default=None, help="Write the Markdown report here")
    a = ap.parse_args()

    a.liberty = a.liberty or ([Path(os.environ["BOSON_LIBERTY"])] if os.environ.get("BOSON_LIBERTY") else [])
    if not a.liberty: ap.error("no liberty file: --liberty or $BOSON_LIBERTY")
    if not (a.target_ns or a.find_fmax): ap.error("give --target-ns and/or --find-fmax")
    for f in [a.rtl, *a.liberty]:
        if not f.exists(): ap.error(f"not found: {f}")
    if shutil.which(a.boson_bin) is None and not Path(a.boson_bin).exists():
        ap.error(f"boson binary not found ({a.boson_bin!r}); see https://partcl.com")
    a.liberty = [l.resolve() for l in a.liberty]
    a.gflags = " ".join(f"-G {g}" for g in a.G)
    workdir = a.workdir or Path(tempfile.mkdtemp(prefix=".ppa_", dir=Path.cwd()))
    workdir.mkdir(parents=True, exist_ok=True)
    R = Runner(a, workdir)
    report: list[str] = []
    results: list[Result] = []

    target = a.target_ns
    winner: Result | None = None
    if target:
        report += [f"## Closing timing at {target:g} ns", "", HEADER]
        for i, (label, flags, pre) in enumerate(LADDER):
            if i < a.start_rung or i > a.max_rung: continue
            if a.no_retime and "-retime" in flags: continue
            rows = R.run(label, target, flags, pre); results += rows
            report += [fmt(r) for r in rows]
            for r in rows:
                if _better(winner, r): winner = r
            if any(r.met() for r in rows) and not a.full_ladder:
                break
        best = winner or max((r for r in results if r.ok), key=lambda r: r.wns_ns, default=None)
        if best is None:
            report.append("\nNo rung produced a timing report — check the boson.log files under " + str(workdir))
        elif winner:
            how = f"`{winner.flags}`" + (f" + `{REPAIR}`" if winner.stage != "compile" else "")
            report.append(f"\n**Winner:** {how} meets {target:g} ns with WNS {winner.wns_ns:+.3f} ns at "
                          f"{winner.cells:,} cells / {winner.area_um2:,.0f} µm²" + (f" / {winner.power_w * 1e3:.1f} mW" if winner.power_w else "") + ".")
        else:
            report.append(f"\n**No rung closes {target:g} ns.** Best is `{best.flags}` ({best.stage}) at WNS {best.wns_ns:+.3f} ns "
                          f"(achievable ≈ {1000 / best.fmax_mhz:.2f} ns / {best.fmax_mhz:.0f} MHz). The critical path is "
                          f"most likely structural: read it (timing_*.json in the rung's directory), trace it to RTL with "
                          f"`compile -provenance` + `report_provenance`, then relax the target or change the RTL "
                          f"(boson-rtl-optimize).")

    if a.find_fmax:
        recipe = (winner or (max((r for r in results if r.ok), key=lambda r: r.wns_ns) if results else None))
        idx = next((i for i, l in enumerate(LADDER) if recipe and l[1] == recipe.flags), a.start_rung)
        label, flags, pre = LADDER[idx]
        report += ["", f"## fmax search (`{flags}`)", "", HEADER]
        probe = target or 10.0
        if recipe and recipe.ok:
            report.append(fmt(recipe))
            # step off what the target run achieved: tighter if it met, looser if not
            probe = 1000.0 / recipe.fmax_mhz * (0.98 if recipe.met() else 1.03)
        best_met, best_viol = (recipe if recipe and recipe.met() else None), None
        tried = {recipe.period_ns} if recipe else set()
        for _ in range(a.fmax_probes):
            probe = round(probe, 2)
            if probe in tried:
                probe = round(probe * (0.98 if best_viol is None else 1.01), 2)
            tried.add(probe)
            rows = R.run(label, probe, flags, pre); results += rows
            report += [fmt(r) for r in rows]
            ok_rows = [r for r in rows if r.ok]
            if not ok_rows: break
            r = max(ok_rows, key=lambda r: r.wns_ns)     # the better of compile / +repair at this period
            if r.met():
                if best_met is None or probe < best_met.period_ns: best_met = r
                probe = 1000.0 / r.fmax_mhz * 0.98         # tighten toward what it actually achieved
            else:
                if best_viol is None or probe > best_viol.period_ns: best_viol = r
                probe = 1000.0 / r.fmax_mhz * 1.03         # back off just past the achieved period
            if best_met and best_viol and best_viol.period_ns > best_met.period_ns * 0.97:
                break
        if best_met:
            bound = "≈" if best_viol else "≥"
            report.append(f"\n**fmax {bound} {best_met.fmax_mhz:.0f} MHz** — closes at {best_met.period_ns:g} ns "
                          f"(WNS {best_met.wns_ns:+.3f}, {best_met.stage}) with {best_met.cells:,} cells / {best_met.area_um2:,.0f} µm²." +
                          (f" Tightest probe that failed: {best_viol.period_ns:g} ns." if best_viol else
                           f" No probe failed, so this is a lower bound; raise --fmax-probes to search further."))
            if winner is None: winner = best_met   # without --target-ns the recipe is the fmax point
        elif best_viol:
            report.append(f"\nNo probe met timing; best achieved ≈ {best_viol.fmax_mhz:.0f} MHz at the {best_viol.period_ns:g} ns probe.")

    if winner:
        pre = next((l[2] for l in LADDER if l[1] == winner.flags), [])
        recipe_tcl = "\n".join(R.tcl_head() + pre + [
            f"# clk.sdc: create_clock -name clk -period {winner.period_ns:g} [get_ports {a.clock_port}]",
            R.compile_line("clk.sdc", winner.flags, rtl=a.rtl.name),
        ] + ([REPAIR + "   ;# optional: the winning row used it"] if winner.stage != "compile" else []) + [
            "report_qor", "report_area", "write_verilog netlist.v"])
        report += ["", "## Recommended recipe", "", "```tcl", recipe_tcl, "```"]
    report.append(f"\nRun artefacts (flow.tcl, boson.log, timing_*.json, netlist.v per rung): `{workdir}`")
    text = "\n".join(report)
    print(text)
    if a.out:
        a.out.write_text(text + "\n")
    (workdir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
