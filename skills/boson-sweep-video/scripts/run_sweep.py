#!/usr/bin/env python3
"""Run a boson design-space sweep: the cartesian product of RTL parameter
axes (`-G NAME=VALUE`) and clock periods, one real compile+place+STA+power
session per point, each writing a self-describing run directory:

    <runs>/<tag>/config.txt   key=value per axis + period_ps/effort/cmd
    <runs>/<tag>/flow.tcl     the exact script boson ran
    <runs>/<tag>/boson.log    stdout (progress lines live on stderr -> boson.err)
    <runs>/<tag>/qor.rpt  synth.rpt  power.rpt  design.def  time.txt  rc.txt
    <runs>/space.json         the sweep definition, consumed by collect.py / render_video.py

Restart-safe: a point whose rc.txt reads 0 is skipped; delete it to re-run.

Example (picorv32 on sky130):
    run_sweep.py --rtl designs/picorv32/picorv32.v --top picorv32 \\
        --liberty .local-assets/sky130_fd_sc_hd__tt_025C_1v80.lib \\
        --lef .local-assets/sky130_fd_sc_hd__nom.tlef --lef .local-assets/sky130_fd_sc_hd.lef \\
        --axis ENABLE_MUL=0,1 --axis BARREL_SHIFTER=0,1 --periods 8,20 \\
        --color-by ENABLE_MUL --marker-by BARREL_SHIFTER --runs runs
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def parse_axis(spec: str) -> tuple[str, list[str]]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(f"--axis expects NAME=v1,v2,... (got {spec!r})")
    name, vals = spec.split("=", 1)
    values = [v.strip() for v in vals.split(",") if v.strip()]
    if not values:
        raise argparse.ArgumentTypeError(f"--axis {name}: no values")
    return name.strip(), values


def parse_label(spec: str) -> tuple[str, str, str]:
    # AXIS:VALUE=Pretty text
    m = re.match(r"^([^:=]+):([^=]+)=(.+)$", spec)
    if not m:
        raise argparse.ArgumentTypeError(f"--label expects AXIS:VALUE=text (got {spec!r})")
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]", "-", s)


def build_flow(out: Path, rtl: Path, top: str, libs: list[Path], lefs: list[Path], extra_tcl: Path | None,
               period_ps: int, clock_port: str, sdc_extra: Path | None, gparams: dict[str, str],
               effort: str, compile_extra: str, vcd_cycles: int, tag: str) -> tuple[str, str]:
    """Returns (flow.tcl text, display command)."""
    sdc = out / f"clk_{period_ps}ps.sdc"
    sdc_lines = [f"create_clock -name clk -period {period_ps / 1000.0:g} [get_ports {clock_port}]"]
    if sdc_extra:
        sdc_lines.append(sdc_extra.read_text().rstrip())
    sdc.write_text("\n".join(sdc_lines) + "\n")
    gflags = " ".join(f"-G {k}={v}" for k, v in gparams.items())
    extra = f" {compile_extra}" if compile_extra else ""
    real_cmd = f"compile {rtl} -top {top} {gflags} -sdc {sdc} -effort {effort}{extra}".replace("  ", " ")
    show_cmd = f"compile {rtl.name} -top {top} {gflags} -sdc {sdc.name} -effort {effort}{extra}".replace("  ", " ")
    lines = [f"# boson-sweep-video point {tag}"]
    lines += [f"read_liberty {l}" for l in libs]
    lines += [f"read_lef {l}" for l in lefs]
    if extra_tcl:
        lines.append(f"source {extra_tcl}")
    lines += [
        f'puts "SWEEP: start {tag}"',
        real_cmd,
        "update_timing",
        f"report_qor > {out / 'qor.rpt'}",
        f"report_area > {out / 'synth.rpt'}",
        f"write_def {out / 'design.def'}",
        f"write_random_vcd -cycles {vcd_cycles} {out / 'random.vcd'}",
        f"report_power -vcd {out / 'random.vcd'} > {out / 'power.rpt'}",
        f'puts "SWEEP: done {tag}"',
        "",
    ]
    return "\n".join(lines), show_cmd


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, type=Path)
    ap.add_argument("--top", required=True)
    ap.add_argument("--liberty", action="append", type=Path, default=None, help="Liberty file (repeatable); default $BOSON_LIBERTY")
    ap.add_argument("--lef", action="append", type=Path, default=[], help="LEF file (repeatable; tech LEF first, then cell LEF). Required for placement/DEF.")
    ap.add_argument("--extra-tcl", type=Path, default=None, help="Tcl sourced after the libraries (e.g. set_layer_rc deck)")
    ap.add_argument("--axis", action="append", type=parse_axis, default=[], help="RTL parameter axis NAME=v1,v2 (repeatable, -> compile -G)")
    ap.add_argument("--periods", default="10", help="Clock periods in ns, comma-separated")
    ap.add_argument("--clock-port", default="clk")
    ap.add_argument("--sdc-extra", type=Path, default=None, help="Extra SDC lines appended after create_clock")
    ap.add_argument("--effort", default="medium", choices=["fast", "low", "medium", "high"])
    ap.add_argument("--compile-extra", default="", help="Extra verbatim compile flags (e.g. '-blackbox foo')")
    ap.add_argument("--vcd-cycles", type=int, default=500)
    ap.add_argument("--runs", type=Path, default=Path("runs"), help="Output root (must be under cwd for containerised boson)")
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"))
    ap.add_argument("--title", default=None, help="Video title, e.g. 'picorv32 · sky130 · design space'")
    ap.add_argument("--color-by", default=None, help="Axis that picks marker colour (<= 3 values recommended)")
    ap.add_argument("--marker-by", default=None, help="Axis that picks marker shape")
    ap.add_argument("--label", action="append", type=parse_label, default=[], help="Pretty name AXIS:VALUE=text (repeatable)")
    ap.add_argument("--timeout", type=int, default=7200, help="Per-point timeout (s)")
    ap.add_argument("--jobs", type=int, default=1, help="Points to run concurrently (each is one boson process; size to your GPU/RAM headroom)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    libs = a.liberty or ([Path(os.environ["BOSON_LIBERTY"])] if os.environ.get("BOSON_LIBERTY") else [])
    if not libs:
        ap.error("no liberty file: pass --liberty or set $BOSON_LIBERTY")
    for f in [a.rtl, *libs, *a.lef] + ([a.extra_tcl] if a.extra_tcl else []) + ([a.sdc_extra] if a.sdc_extra else []):
        if not f.exists():
            ap.error(f"not found: {f}")
    if shutil.which(a.boson_bin) is None and not Path(a.boson_bin).exists():
        ap.error(f"boson binary not found ({a.boson_bin!r}); pass --boson-bin or set $BOSON_BIN — see https://partcl.com")
    axes = dict(a.axis)
    for ax in (a.color_by, a.marker_by):
        if ax and ax not in axes and ax != "period_ps":
            ap.error(f"--color-by/--marker-by {ax!r} is not a declared --axis")
    periods_ps = [int(round(float(p) * 1000)) for p in a.periods.split(",") if p.strip()]
    axes_all = dict(axes); axes_all["period_ps"] = periods_ps

    runs = a.runs.resolve()
    runs.mkdir(parents=True, exist_ok=True)
    labels: dict[str, dict[str, str]] = {}
    for ax, val, text in a.label:
        labels.setdefault(ax, {})[val] = text
    space = dict(
        title=a.title or f"{a.top} · design space",
        design=a.top, top=a.top, rtl=a.rtl.name, effort=a.effort,
        axes=axes_all, color_by=a.color_by, marker_by=a.marker_by, labels=labels,
        libs=[str(l.resolve()) for l in libs], lefs=[str(l.resolve()) for l in a.lef],
        clock_port=a.clock_port, vcd_cycles=a.vcd_cycles,
    )
    (runs / "space.json").write_text(json.dumps(space, indent=1))

    combos = list(itertools.product(*[[(k, v) for v in vals] for k, vals in axes.items()]))
    plan = [(dict(c), p) for c in combos for p in periods_ps]
    print(f"[sweep] {len(plan)} points -> {runs} ({a.jobs} concurrent)", file=sys.stderr)

    def run_point(gparams, period_ps) -> bool:
        tag = "_".join(f"{safe(k)}-{safe(v)}" for k, v in gparams.items()) + f"_p{period_ps}"
        out = runs / tag
        rc_file = out / "rc.txt"
        if rc_file.exists() and rc_file.read_text().strip() == "0":
            print(f"[sweep] {tag}: done (skip)", file=sys.stderr); return True
        out.mkdir(exist_ok=True)
        flow, show_cmd = build_flow(out, a.rtl.resolve(), a.top, [l.resolve() for l in libs], [l.resolve() for l in a.lef],
                                    a.extra_tcl.resolve() if a.extra_tcl else None, period_ps, a.clock_port,
                                    a.sdc_extra, gparams, a.effort, a.compile_extra, a.vcd_cycles, tag)
        (out / "flow.tcl").write_text(flow)
        cfg = [f"{k}={v}" for k, v in gparams.items()] + [f"period_ps={period_ps}", f"effort={a.effort}", f"cmd={show_cmd}"]
        (out / "config.txt").write_text("\n".join(cfg) + "\n")
        if a.dry_run:
            print(f"[sweep] {tag}: {show_cmd}", file=sys.stderr); return True
        print(f"[sweep] {tag}: running ...", file=sys.stderr)
        t0 = time.time()
        with open(out / "boson.log", "w") as so, open(out / "boson.err", "w") as se:
            try:
                rc = subprocess.run([a.boson_bin, "--no-color", "-f", str(out / "flow.tcl")], stdout=so, stderr=se, timeout=a.timeout).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        wall = time.time() - t0
        (out / "time.txt").write_text(f"wall={wall:.1f}\n")
        ok = rc == 0 and "SWEEP: done" in (out / "boson.log").read_text()
        rc_file.write_text(f"{rc if rc else (0 if ok else 1)}\n")
        print(f"[sweep] {tag}: {'ok' if ok else 'FAILED (rc=%d)' % rc} in {wall:.0f}s", file=sys.stderr)
        return ok

    if a.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            results = list(pool.map(lambda gp: run_point(*gp), plan))
    else:
        results = [run_point(*gp) for gp in plan]
    failures = results.count(False)
    print(f"[sweep] finished: {len(plan) - failures}/{len(plan)} points ok", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
