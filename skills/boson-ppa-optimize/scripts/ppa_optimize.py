#!/usr/bin/env python3
"""Generic PPA optimisation with boson: close timing at a target clock with
the cheapest optimisation recipe that works, and/or find the design's fmax.

Escalation ladder (each rung is one real compile+place+STA run; the ladder
stops at the first rung that MEETS timing unless --full-ladder):

    0  -effort medium                       baseline
    1  -effort high                         more synthesis/loop effort
    2  -effort high -draws 3                best-of-3 placement seeds
    3  -effort high -select_candidates      AIG / timing-AIG / XMG race through the loop
    4  -effort high -datapath_search        architecture beam search (adders, muls, muxes)

then optionally `eco_optimize` (upsize / Vt-swap / downsize ECO loop) on the
best rung. --find-fmax runs a short period search using achieved clock
(1/(period - WNS)) as the estimator, at the winning recipe.

    ppa_optimize.py --rtl design.v --top top --liberty cells.lib \\
        --lef tech.tlef --lef cells.lef --target-ns 7 --find-fmax --out ppa.md

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

LADDER = [
    ("medium", "-effort medium"),
    ("high", "-effort high"),
    ("high+draws3", "-effort high -draws 3"),
    ("high+candidates", "-effort high -select_candidates"),
    ("high+datapath", "-effort high -datapath_search"),
]

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
        lines = [f"read_liberty {l}" for l in self.a.liberty] + [f"read_lef {l}" for l in self.a.lef]
        if self.a.wire_rc:
            cap, res = self.a.wire_rc
            lines.append(f"set_wire_rc -capacitance {cap} -resistance {res}")
        if self.a.extra_tcl:
            lines.append(f"source {self.a.extra_tcl.resolve()}")
        return lines

    def run(self, label: str, period_ns: float, flags: str, post: list[str] | None = None) -> Result:
        self.n += 1
        d = self.workdir / f"{self.n:02d}_{re.sub(r'[^A-Za-z0-9.+-]', '-', label)}_{period_ns:g}ns"
        d.mkdir(parents=True, exist_ok=True)
        sdc = d / "clk.sdc"
        sdc_text = f"create_clock -name clk -period {period_ns:g} [get_ports {self.a.clock_port}]\n"
        if self.a.sdc_extra:
            sdc_text += self.a.sdc_extra.read_text()
        sdc.write_text(sdc_text)
        lines = self.tcl_head() + [
            f"compile {self.a.rtl.resolve()} -top {self.a.top} {self.a.gflags} -sdc {sdc} {flags} {self.a.compile_extra}".replace("  ", " "),
        ] + (post or []) + [
            "update_timing",
            'puts "===QOR==="', "puts [report_qor]",
            'puts "===AREA==="', "puts [report_area]",
        ]
        if not self.a.no_power:
            lines += [f"write_random_vcd -cycles {self.a.vcd_cycles} {d / 'random.vcd'}",
                      'puts "===POWER==="', f"puts [report_power -vcd {d / 'random.vcd'}]"]
        (d / "flow.tcl").write_text("\n".join(lines) + "\n")
        r = Result(label=label, period_ns=period_ns, flags=flags)
        print(f"[ppa] {label} @ {period_ns:g} ns: {flags}{' + ' + ' ; '.join(post) if post else ''}", file=sys.stderr)
        t0 = time.time()
        try:
            proc = subprocess.run([self.a.boson_bin, "--no-color", "-f", str(d / "flow.tcl")], capture_output=True, text=True, timeout=self.a.timeout)
            out = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            r.error = f"timed out after {self.a.timeout}s"; return r
        r.wall_s = time.time() - t0
        (d / "boson.log").write_text(out)
        if proc.returncode != 0:
            r.error = f"boson exited {proc.returncode}: " + out.strip().splitlines()[-1][:200] if out.strip() else "boson failed"
            return r
        m = WNS_RE.search(out)
        if m:
            r.wns_ns = None if m.group(1) == "n/a" else float(m.group(1)); r.status = m.group(2)
        r.tns_ns = _num(TNS_RE, out); r.hold_wns_ns = _num(HOLD_RE, out)
        m = VIOL_RE.search(out); r.violating = int(m.group(2)) if m else None
        r.max_cap_viol = _num(MAXCAP_RE, out, int)
        r.cells = _num(CELLS_RE, out, int); r.area_um2 = _num(AREA_RE, out)
        m = POWER_RE.search(out); r.power_w = float(m.group(4)) if m else None
        r.ok = r.wns_ns is not None
        if r.ok:
            r.fmax_mhz = 1000.0 / (period_ns - r.wns_ns)
        else:
            r.error = "could not parse report_qor (see boson.log)"
        print(f"[ppa]   -> {r.status or 'ERROR'} WNS {r.wns_ns} ns · {r.cells} cells · {r.area_um2} um² · "
              f"{(r.power_w or 0) * 1e3:.1f} mW · {r.wall_s:.0f}s", file=sys.stderr)
        return r


def _num(rx, text, cast=float):
    m = rx.search(text); return cast(m.group(1)) if m else None


def fmt(r: Result) -> str:
    if not r.ok:
        return f"| {r.label} | {r.period_ns:g} | ERROR: {r.error[:60]} | | | | | |"
    pw = f"{r.power_w * 1e3:.1f}" if r.power_w is not None else "n/a"
    return (f"| {r.label} | {r.period_ns:g} | {r.status} | {r.wns_ns:+.3f} | {r.fmax_mhz:.0f} | {r.cells:,} | "
            f"{r.area_um2:,.0f} | {pw} |")


HEADER = ("| recipe | period (ns) | timing | WNS (ns) | achieved (MHz) | cells | area (µm²) | power (mW) |\n"
          "|---|---|---|---|---|---|---|---|")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, type=Path); ap.add_argument("--top", required=True)
    ap.add_argument("--liberty", action="append", type=Path, default=None)
    ap.add_argument("--lef", action="append", type=Path, default=[])
    ap.add_argument("--extra-tcl", type=Path, default=None); ap.add_argument("--sdc-extra", type=Path, default=None)
    ap.add_argument("--wire-rc", nargs=2, type=float, metavar=("fF_per_um", "ohm_per_um"), default=None,
                    help="set_wire_rc calibration for the PDK (boson only knows ASAP7's by default)")
    ap.add_argument("-G", action="append", default=[], metavar="NAME=VALUE", help="top-parameter override (repeatable)")
    ap.add_argument("--compile-extra", default=""); ap.add_argument("--clock-port", default="clk")
    ap.add_argument("--target-ns", type=float, default=None, help="Clock period to close timing at")
    ap.add_argument("--find-fmax", action="store_true", help="Search for the fastest closable period (at the winning recipe)")
    ap.add_argument("--fmax-probes", type=int, default=3, help="Max period probes for --find-fmax")
    ap.add_argument("--start-rung", type=int, default=0); ap.add_argument("--max-rung", type=int, default=len(LADDER) - 1)
    ap.add_argument("--full-ladder", action="store_true", help="Run every rung even after one meets timing")
    ap.add_argument("--eco", action="store_true", help="Run eco_optimize on the winning rung and report the delta")
    ap.add_argument("--no-power", action="store_true"); ap.add_argument("--vcd-cycles", type=int, default=500)
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"))
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--workdir", type=Path, default=None, help="Where runs go (default: .ppa_<pid> under cwd, kept)")
    ap.add_argument("--out", type=Path, default=None, help="Write the Markdown report here")
    a = ap.parse_args()

    a.liberty = a.liberty or ([Path(os.environ["BOSON_LIBERTY"])] if os.environ.get("BOSON_LIBERTY") else [])
    if not a.liberty: ap.error("no liberty file: --liberty or $BOSON_LIBERTY")
    if not (a.target_ns or a.find_fmax): ap.error("give --target-ns and/or --find-fmax")
    for f in [a.rtl, *a.liberty, *a.lef]:
        if not f.exists(): ap.error(f"not found: {f}")
    if shutil.which(a.boson_bin) is None and not Path(a.boson_bin).exists():
        ap.error(f"boson binary not found ({a.boson_bin!r}); see https://partcl.com")
    a.liberty = [l.resolve() for l in a.liberty]; a.lef = [l.resolve() for l in a.lef]
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
        for i, (label, flags) in enumerate(LADDER):
            if i < a.start_rung or i > a.max_rung: continue
            r = R.run(label, target, flags); results.append(r); report.append(fmt(r))
            if r.met() and (winner is None or r.area_um2 < winner.area_um2):
                winner = r
            if r.met() and not a.full_ladder:
                break
        best = winner or max((r for r in results if r.ok), key=lambda r: r.wns_ns, default=None)
        if best is None:
            report.append("\nNo rung produced a timing report — check the boson.log files under " + str(workdir))
        elif winner:
            report.append(f"\n**Winner:** `{winner.flags}` meets {target:g} ns with WNS {winner.wns_ns:+.3f} ns at "
                          f"{winner.cells:,} cells / {winner.area_um2:,.0f} µm²" + (f" / {winner.power_w * 1e3:.1f} mW" if winner.power_w else "") + ".")
        else:
            report.append(f"\n**No rung closes {target:g} ns.** Best is `{best.flags}` at WNS {best.wns_ns:+.3f} ns "
                          f"(achievable ≈ {1000 / best.fmax_mhz:.2f} ns / {best.fmax_mhz:.0f} MHz). Options: relax the target, "
                          f"pipeline the critical path in RTL (report_timing names it), or run --eco.")
        if a.eco and best is not None:
            post = ["eco_optimize -rounds 3", "repair_design"]
            r = R.run(best.label + "+eco", target, best.flags, post=post); results.append(r)
            report += ["", "### After `eco_optimize -rounds 3 ; repair_design` on the best rung", "", HEADER, fmt(best), fmt(r)]
            if r.ok and best.ok:
                report.append(f"\nECO delta: WNS {best.wns_ns:+.3f} → {r.wns_ns:+.3f} ns, area {best.area_um2:,.0f} → {r.area_um2:,.0f} µm²" +
                              (f", power {best.power_w * 1e3:.1f} → {r.power_w * 1e3:.1f} mW" if best.power_w and r.power_w else "") + ".")
            if r.met() and (winner is None or r.area_um2 <= winner.area_um2):
                winner = r

    if a.find_fmax:
        recipe = (winner or (max((r for r in results if r.ok), key=lambda r: r.wns_ns) if results else None))
        flags = recipe.flags if recipe else LADDER[a.start_rung][1]
        label = recipe.label if recipe else LADDER[a.start_rung][0]
        report += ["", f"## fmax search (`{flags}`)", "", HEADER]
        probe = target or 10.0
        if recipe and recipe.ok:
            probe = 1000.0 / recipe.fmax_mhz; report.append(fmt(recipe))
        best_met, best_viol = (recipe if recipe and recipe.met() else None), None
        for _ in range(a.fmax_probes):
            probe = round(probe, 2)
            r = R.run(label, probe, flags); results.append(r); report.append(fmt(r))
            if not r.ok: break
            if r.met():
                if best_met is None or probe < best_met.period_ns: best_met = r
                probe = 1000.0 / r.fmax_mhz * 0.98         # tighten toward what it actually achieved
            else:
                if best_viol is None or probe > best_viol.period_ns: best_viol = r
                probe = 1000.0 / r.fmax_mhz * 1.03         # back off just past the achieved period
            if best_met and best_viol and best_viol.period_ns > best_met.period_ns * 0.97:
                break
        if best_met:
            report.append(f"\n**fmax ≈ {best_met.fmax_mhz:.0f} MHz** — closes at {best_met.period_ns:g} ns "
                          f"(WNS {best_met.wns_ns:+.3f}) with {best_met.cells:,} cells / {best_met.area_um2:,.0f} µm²." +
                          (f" Tightest probe that failed: {best_viol.period_ns:g} ns." if best_viol else ""))
        elif best_viol:
            report.append(f"\nNo probe met timing; best achieved ≈ {best_viol.fmax_mhz:.0f} MHz at the {best_viol.period_ns:g} ns probe.")

    if winner:
        recipe_tcl = "\n".join(R.tcl_head() + [
            f"create_clock -name clk -period {winner.period_ns:g} [get_ports {a.clock_port}]   ;# -> clk.sdc",
            f"compile {a.rtl.name} -top {a.top} {a.gflags} -sdc clk.sdc {winner.flags} {a.compile_extra}".replace("  ", " "),
            "report_qor", "report_area"])
        report += ["", "## Recommended recipe", "", "```tcl", recipe_tcl, "```"]
    report.append(f"\nRun artefacts (flow.tcl + boson.log per rung): `{workdir}`")
    text = "\n".join(report)
    print(text)
    if a.out:
        a.out.write_text(text + "\n")
    (workdir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
