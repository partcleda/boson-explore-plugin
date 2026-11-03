---
description: Check that boson read your Liberty files completely and correctly — missing cells, pins, fields or timing groups, merged or smaller tables, every table shape, every arc timed at exact table points.
argument-hint: <lib files...>
---

Run the `boson-diagnose` skill's Liberty check (`references/liberty.md`) on the
Liberty files below: dump boson's model with `dump_model.tcl` after reading
them exactly as the flow does, run `lib_inventory.py`, then `shape_census.py
--all` and `shape_probe.py --scope all`. Report every inventory finding and
every LOAD ERROR, MISMATCH, NO ARC and assumption-stating WARNING, each with the
cell, arc, file line and both numbers, plus the coverage lines. Offer to send
the anonymized summaries with `submit.tcl`; never send them without a yes.

Arguments: $ARGUMENTS
