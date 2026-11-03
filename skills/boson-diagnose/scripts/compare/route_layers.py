#!/usr/bin/env python3
"""Routed wire length by metal layer, for all signal nets and for long ones.

    route_layers.py routed.def [--long-um 200] [--use SIGNAL] [--out-md layers.md] [--out-json layers.json]

Reads the NETS section of a routed (or globally routed) DEF and sums each
net's wire length per layer (Manhattan between consecutive points of each
segment; vias counted, not measured). Prints the layer shares over every
net of the chosen USE and over the nets longer than --long-um. Use it on the
reference tool's routed design to see which layers its long nets were
planned for, and set the wire model of a compile-stage comparison to match
(a compile has no routing, so its wires are priced on a model).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cmp import md_table, read_def_routing  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("def_file")
    ap.add_argument("--long-um", type=float, action="append", help="length threshold(s), default 200")
    ap.add_argument("--use", default="SIGNAL", help="DEF USE of the nets counted (default SIGNAL; nets "
                                                     "without USE count as SIGNAL)")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    thresholds = sorted(a.long_um or [200.0])
    groups = {"all": Counter()} | {f">{t:g} um": Counter() for t in thresholds}
    nets = Counter()
    vias = Counter()
    for _, use, lengths, n_vias in read_def_routing(a.def_file):
        if use != a.use:
            continue
        total = sum(lengths.values())
        for name, counter in groups.items():
            if name == "all" or total > float(name[1:].split()[0]):
                counter.update(lengths)
                nets[name] += 1
                vias[name] += n_vias
    report = {name: {"nets": nets[name], "wire_um": sum(c.values()), "vias": vias[name],
                     "layers": {k: v for k, v in c.items()}} for name, c in groups.items()}
    layers = sorted({k for c in groups.values() for k in c}, key=_layer_order)
    o = ["# Routed wire by layer", "",
         md_table(["nets", "count", "wire (mm)", "vias"],
                  [[n, r["nets"], round(r["wire_um"] / 1000, 1), r["vias"]] for n, r in report.items()]),
         md_table(["layer"] + list(report),
                  [[ly] + [f"{100 * r['layers'].get(ly, 0.0) / r['wire_um']:.0f}%" if r["wire_um"] else "–"
                           for r in report.values()] for ly in layers])]
    md = "\n".join(o)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(report, indent=1))
    return 0


def _layer_order(name: str):
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)) if m else 999, name)


if __name__ == "__main__":
    raise SystemExit(main())
