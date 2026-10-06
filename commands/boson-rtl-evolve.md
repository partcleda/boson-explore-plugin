---
description: Evolve the RTL against a PPA objective (Fmax, area or power, with optional caps) with boson as the evaluator. Every candidate passes an equivalence gate before it is scored.
argument-hint: --rtl files --top name --sdc file --objective fmax|area|power [--cap area=+15%] [--budget N]
---

Run the `boson-rtl-evolve` skill on the arguments below. Freeze the SDC,
the clock and the flow script, and score the original RTL first. Then
iterate: one hypothesis per candidate, each committed, gated (lint, formal
equivalence, lockstep co-simulation with directed corners) and scored by
boson, with a ledger row per candidate. Stay within the budget. Declare
the final as an explicit commit, rerun it, sign it off, and report it in
the skill's format.

Arguments: $ARGUMENTS
