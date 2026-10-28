---
description: Split the QoR gap between a boson netlist and a Synopsys DC netlist into the part inside DesignWare operators and the part outside, and calibrate boson's operators against DW.
argument-hint: <boson flow> <DC netlist> [DC report_resources] [--microbench]
---

Run the `boson-dc-designware-compare` skill for the design below. Use the same
libraries and the customer's SDC for both netlists. Collect from the boson
session with `-provenance`, time the DC netlist with `score_netlist.tcl` in a
fresh session, then run `dw_compare.py`. Report the area and timing split,
the label balance and endpoint pairing counts. If label balance is low, say
the split is inconclusive and give the DC settings that keep DW hierarchy.
With `--microbench`, also generate the operator bench and report the boson/DC
ratios once both halves have run.

Arguments: $ARGUMENTS
