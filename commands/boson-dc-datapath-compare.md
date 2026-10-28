---
description: Split the QoR gap between a boson netlist and a Design Compiler netlist of the same RTL into the part inside the datapath operators and the part outside them, and compare isolated operators.
argument-hint: <boson flow> <DC netlist> [DC report_resources] [--microbench]
---

Run the `boson-dc-datapath-compare` skill for the design below. Use the same
libraries and the design's real SDC for both netlists. Collect from the boson
session with `-provenance`, time the DC netlist with `score_netlist.tcl` in a
fresh session, then run `dw_compare.py`. Report the area and timing split, the
label balance and the endpoint pairing counts. If label balance is low, say
the split is inconclusive and give the DC settings that keep operator
hierarchy. With `--microbench`, also generate the operator bench and report
the ratios once both halves have run. DC results are subject to the user's DC
license terms; keep them out of anything shared outside the user's machine.

Arguments: $ARGUMENTS
