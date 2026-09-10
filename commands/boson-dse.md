---
description: Sweep clock period and RTL parameters through boson and report the area/power/timing tradeoff.
argument-hint: [--rtl path] [--liberty path] [--periods ns,ns,...] [--presets a,b,...]
---

Run a boson design-space-exploration sweep using
`skills/boson-timing-power-tradeoff/scripts/boson_dse.py`. If the user gave
arguments below, pass them straight through to the script; otherwise use
the bundled picorv32 example (`designs/picorv32/picorv32.v`, top
`picorv32`) with a sensible default period sweep that includes at least one
violating and one met point.

Before running, confirm a `boson` binary and a Liberty file are available
(env vars `$BOSON_BIN` / `$BOSON_LIBERTY`, or ask the user). Follow the
full instructions and reporting format in the
`boson-timing-power-tradeoff` skill.

Arguments: $ARGUMENTS
