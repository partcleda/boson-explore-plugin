---
description: Check that boson reads every table shape in your Liberty files — 3-D constraints, unusual axis orders, 1-D/scalar tables, index overrides — by loading one real example of each shape and timing it at exact table points.
argument-hint: <lib files...>
---

Run the `boson-diagnose` skill's Liberty table shapes method
(`references/liberty-shapes.md`) on the Liberty files below: run
`shape_census.py` on all of them, then `shape_probe.py` with the installed
boson. Report the coverage line and every LOAD ERROR, MISMATCH, NO ARC and
assumption-stating WARNING, each with its shape, the number of tables
affected and the example line. Offer to send the anonymized
`shapes_summary.json` with `submit.tcl`; never send it without a yes.

Arguments: $ARGUMENTS
