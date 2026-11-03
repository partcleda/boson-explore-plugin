#!/usr/bin/env python3
"""Collect every finished sweep point under <runs>/ into <runs>/summary.json.

Parses boson's fixed-format report_qor / report_area / report_power text and
the compile progress lines from the logs; nothing here is design-specific —
the parameter axes come from <runs>/space.json."""
import json
import re
import sys
from pathlib import Path


def rd(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def num(rx, text, cast=float, default=None):
    m = re.search(rx, text, re.M)
    return cast(m.group(1)) if m else default


def collect(d: Path, axes: list[str]) -> dict:
    cfg = {}
    for line in rd(d / "config.txt").splitlines():
        if "=" in line:
            k, v = line.split("=", 1); cfg[k.strip()] = v.strip()
    qor, synth, power, tm = rd(d / "qor.rpt"), rd(d / "synth.rpt"), rd(d / "power.rpt"), rd(d / "time.txt")
    log = rd(d / "boson.log") + "\n" + rd(d / "boson.err")
    rc = num(r"^(\d+)", rd(d / "rc.txt"), int)
    row = dict(tag=d.name, params={k: cfg.get(k) for k in axes if k != "period_ps"},
               period_ps=float(cfg.get("period_ps", 0) or 0), effort=cfg.get("effort"), cmd=cfg.get("cmd", ""),
               rc=rc, done=(rc == 0) and ("SWEEP: done" in log))
    row["wns_ns"] = num(r"^WNS:\s+(-?[\d.]+) ns", qor)
    row["tns_ns"] = num(r"^TNS:\s+(-?[\d.]+) ns", qor)
    row["hold_wns_ns"] = num(r"^Hold WNS:\s+(-?[\d.]+) ns", qor)
    row["endpoints"] = num(r"^Endpoints:\s+(\d+)", qor, int)
    row["violating"] = num(r"^Endpoints:\s+\d+\s+Violating:\s+(\d+)", qor, int)
    row["cells"] = num(r"report_synth: (\d+) cells", synth, int)
    row["seq_cells"] = num(r"\((\d+) sequential\)", synth, int)
    row["area_um2"] = num(r"total cell area: ([\d.]+) um\^2", synth)
    m = re.search(r"^Total\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)", power, re.M)
    if m:
        row.update(power_internal_w=float(m.group(1)), power_switching_w=float(m.group(2)),
                   power_leakage_w=float(m.group(3)), power_w=float(m.group(4)))
    row["wall_s"] = num(r"wall=([\d.]+)", tm)
    row["compile_s"] = num(r"\[compile\] \+([\d.]+)s done", log)
    iters = re.findall(r"\[layout-loop\] iter (\d+)/(\d+): WNS (-?[\d.]+) ps\s+TNS (-?[\d.]+) ps\s+area (\d+) um\^2\s+HPWL (\d+) um.*?\(\+([\d.]+)s\)", log)
    row["loop"] = [dict(it=int(a), of=int(b), wns_ps=float(c), tns_ps=float(dd), area_um2=float(e), hpwl_um=float(f), t_s=float(g))
                   for a, b, c, dd, e, f, g in iters]
    row["compile_lines"] = re.findall(r"^\[compile\] \+[\d.]+s .*$", log, re.M)
    row["setup_lines"] = re.findall(r"^(?:read_liberty|read_lef):.*$", log, re.M)[:4]
    v = re.search(r"boson v?([\d][\w.]*) \(build ([0-9a-f]+)\)", log)
    row["boson_version"] = f"v{v.group(1)} (build {v.group(2)})" if v else None
    row["has_def"] = (d / "design.def").exists()
    if row["wns_ns"] is not None and row["period_ps"]:
        row["fmax_ghz"] = 1000.0 / (row["period_ps"] - 1000.0 * row["wns_ns"])
    return row


def main(runs: Path) -> list[dict]:
    space = json.loads((runs / "space.json").read_text())
    axes = list(space["axes"].keys())
    rows = [collect(d, axes) for d in sorted(runs.iterdir()) if d.is_dir() and (d / "config.txt").exists()]
    (runs / "summary.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        print(f"{r['tag']:40s} done={str(r['done']):5} cells={r['cells']} area={r['area_um2']} wns={r['wns_ns']} "
              f"fmax={r.get('fmax_ghz')} P={r.get('power_w')} wall={r['wall_s']}")
    return rows


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "runs"))
