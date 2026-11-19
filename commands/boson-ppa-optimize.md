---
description: Close timing at a target clock with the cheapest boson recipe that works (compile -effort medium → high, each with an optional extra repair_timing -setup), and/or find fmax.
argument-hint: --rtl path --top name [--target-ns T] [--find-fmax] [--full-ladder] [--provenance]
---

Run the `boson-close-timing` skill's effort ladder (`references/ladder.md`): `scripts/ppa_optimize.py` with the
arguments below (default to the bundled picorv32 example if none are
given, with `--target-ns 7 --find-fmax`). Confirm `boson` and a Liberty
file are available first. Estimate the wall time, run it in the
background, report each rung as it lands, and finish with the skill's
reporting format (ladder table, verdict, recommended recipe).

Arguments: $ARGUMENTS
