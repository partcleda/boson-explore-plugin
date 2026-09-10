---
description: Close timing at a target clock with the cheapest boson recipe that works (effort → draws → candidate race → datapath search → ECO), and/or find fmax.
argument-hint: --rtl path --top name [--target-ns T] [--find-fmax] [--eco] [--full-ladder]
---

Run the `boson-ppa-optimize` skill: `scripts/ppa_optimize.py` with the
arguments below (default to the bundled picorv32 example if none are
given, with `--target-ns 7 --find-fmax`). Confirm `boson`, a Liberty file
and LEF files are available first. Estimate the wall time, run it in the
background, report each rung as it lands, and finish with the skill's
reporting format (ladder table, verdict, recommended recipe).

Arguments: $ARGUMENTS
