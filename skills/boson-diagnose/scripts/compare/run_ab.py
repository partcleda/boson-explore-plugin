#!/usr/bin/env python3
"""What differs between two or more boson runs of the same design and deck.

    run_ab.py old=run_old.log new=run_new.log \\
        [--journal old=old.jsonl --journal new=new.jsonl] [--qor old=old_qor.rpt --qor new=new_qor.rpt] \\
        [--out-md ab.md] [--out-json ab.json]

Use it before reading anything into a QoR difference between two boson
versions (or two decks): it reports the settings that silently differ.

- boson version of each run;
- wire model: every route calibration (PAR-252) with the resistance and
  capacitance per um before and after, flagged when it hit the 0.5x / 2x
  hold; PAR-253 (calibration refused). A run whose wire model moved times
  every wire differently from a run whose model did not;
- app variables that differ (from each journal's header);
- message IDs whose counts differ (warnings and errors);
- QoR from report_qor, side by side;
- the journal's stage checkpoints in order, with the WNS / TNS / area change
  of each stage, and the stage that lost the most TNS in each run (e.g. a
  banking or repair step that undid a placement gain).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "debug"))
from _cmp import md_table  # noqa: E402
from _bdlib import open_text  # noqa: E402
from timing_digest import parse_qor  # noqa: E402

VERSION = re.compile(r"\bboson\s+v?(\d+\.\d+\.\d+)")
CALIBRATED = re.compile(r"PAR-252.*?([\d.]+) to ([\d.]+) ohm/um and ([\d.]+) to ([\d.]+) fF/um")
MESSAGE = re.compile(r"\b(Error|Warning)\b:?\s*\(?([A-Z]+-\d+)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="label=boson.log")
    ap.add_argument("--journal", action="append", default=[], help="label=decisions.jsonl")
    ap.add_argument("--qor", action="append", default=[], help="label=report_qor output")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    journals = dict(j.split("=", 1) for j in a.journal)
    qors = dict(q.split("=", 1) for q in a.qor)
    report = {}
    for label, log in (r.split("=", 1) for r in a.runs):
        r = read_log(Path(log))
        if label in journals:
            r.update(read_journal(Path(journals[label])))
        if label in qors:
            r["qor"] = parse_qor(Path(qors[label]))
        report[label] = r
    md = to_md(report)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(report, indent=1))
    return 0


def read_log(path: Path) -> dict:
    version, calibrations, refused, messages = None, [], 0, Counter()
    with open_text(path) as f:
        for line in f:
            if version is None and (m := VERSION.search(line)):
                version = m.group(1)
            if m := CALIBRATED.search(line):
                r0, r1, c0, c1 = map(float, m.groups())
                held = (r0 and r1 / r0 >= 1.99) or (r0 and r1 / r0 <= 0.501) or \
                       (c0 and c1 / c0 >= 1.99) or (c0 and c1 / c0 <= 0.501)
                calibrations.append({"res_from": r0, "res_to": r1, "cap_from": c0, "cap_to": c1, "at_hold": bool(held)})
            if "PAR-253" in line:
                refused += 1
            for m in MESSAGE.finditer(line):
                messages[f"{m.group(1)} {m.group(2)}"] += 1
    return {"version": version, "calibrations": calibrations, "calibration_refused": refused,
            "messages": dict(messages)}


def read_journal(path: Path) -> dict:
    app_vars, checkpoints = {}, []
    with open_text(path) as f:
        for line in f:
            if '"header"' not in line and '"checkpoint"' not in line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "header":
                app_vars = r.get("app_vars") or {}
            elif r.get("kind") == "checkpoint":
                checkpoints.append({"label": r.get("label") or r.get("stage"), "t_s": r.get("t_s"),
                                    **{k: (r.get("metrics") or {}).get(k)
                                       for k in ("wns_ns", "tns_ns", "area_um2", "violating_endpoints")}})
    prev = None
    for c in checkpoints:
        for k in ("wns_ns", "tns_ns", "area_um2"):
            c["d_" + k] = c[k] - prev[k] if prev and c[k] is not None and prev[k] is not None else None
        prev = c
    return {"app_vars": app_vars, "checkpoints": checkpoints}


def to_md(report: dict) -> str:
    labels = list(report)
    o = ["# boson run A/B", ""]
    o.append(md_table(["run", "boson", "wire model calibrations (ohm/um; fF/um)", "refused (PAR-253)"],
                      [[f"`{lb}`", r["version"] or "?",
                        "; ".join(f"{c['res_from']:g} -> {c['res_to']:g}; {c['cap_from']:g} -> {c['cap_to']:g}"
                                  + (" (at the 2x/0.5x hold)" if c["at_hold"] else "")
                                  for c in r["calibrations"]) or "none",
                        r["calibration_refused"]] for lb, r in report.items()]))
    moved = [lb for lb, r in report.items() if r["calibrations"]]
    if moved and len(moved) < len(labels):
        o.append(f"**The wire model differs between runs**: {', '.join(f'`{x}`' for x in moved)} recalibrated it from "
                 "the global route and the others did not, so every wire is timed differently. For a like-for-like "
                 "comparison rerun with `set_app_var wire_price_route_calibration off` (or the same setting in "
                 "every run), and check the model with `report_layer_rc`.")
        o.append("")
    if any("app_vars" in r for r in report.values()):
        names = sorted({k for r in report.values() for k in r.get("app_vars", {})})
        diff = [[f"`{k}`"] + [str(report[lb].get("app_vars", {}).get(k, "(default)")) for lb in labels] for k in names
                if len({str(report[lb].get("app_vars", {}).get(k)) for lb in labels}) > 1]
        o.append("## App variables that differ")
        o.append(md_table(["app var"] + [f"`{lb}`" for lb in labels], diff))
    ids = sorted({k for r in report.values() for k in r["messages"]})
    diff = [[k] + [report[lb]["messages"].get(k, 0) for lb in labels] for k in ids
            if len({report[lb]["messages"].get(k, 0) for lb in labels}) > 1]
    o.append("## Messages whose counts differ")
    o.append(md_table(["message"] + [f"`{lb}`" for lb in labels], diff))
    if any("qor" in r for r in report.values()):
        keys = [k for k in ("wns", "tns", "hold_wns", "hold_tns", "setup_violating", "hold_violating", "area",
                            "cell_area", "leakage_power", "total_power")
                if any(k in report[lb].get("qor", {}) for lb in labels)]
        o.append("## QoR")
        o.append(md_table(["metric"] + [f"`{lb}`" for lb in labels],
                          [[k] + [report[lb].get("qor", {}).get(k, "–") for lb in labels] for k in keys]))
    for lb in labels:
        cps = report[lb].get("checkpoints")
        if not cps:
            continue
        worst = min((c for c in cps if c["d_tns_ns"] is not None), key=lambda c: c["d_tns_ns"], default=None)
        o.append(f"## Stage checkpoints of `{lb}`")
        o.append(md_table(["stage", "t (s)", "WNS ns", "dWNS", "TNS ns", "dTNS", "area um2", "darea", "violators"],
                          [[str(c["label"]), c["t_s"], c["wns_ns"], c["d_wns_ns"], c["tns_ns"], c["d_tns_ns"],
                            c["area_um2"], c["d_area_um2"], c["violating_endpoints"]] for c in cps]))
        if worst and worst["d_tns_ns"] < 0:
            o.append(f"- largest TNS loss: `{worst['label']}` ({worst['d_tns_ns']:+.3f} ns)")
            o.append("")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
