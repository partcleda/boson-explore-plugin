---
name: boson-timing-power-tradeoff
description: Use when the user wants to explore the area/power/timing design space of an RTL block using boson (partcl's EDA toolkit) — e.g. "what does tightening the clock cost me in power", "sweep this design's parameters and show the tradeoff", "which config is smallest/fastest/lowest-power". Drives boson through real compile+STA+power runs per sweep point; not an estimate.
---

# boson timing/power/area tradeoff sweep

This skill runs a real design through boson's synthesis → STA → power flow
at multiple clock periods and/or multiple RTL parameter configurations, and
reports back an area/power/timing tradeoff table. Every row is a genuine
`compile` + `report_qor` + `report_area` + `report_power` run — there is no
model or interpolation, so a sweep of N points costs N real compiles.

## When to use this

The user wants to see a tradeoff, not just one number: "what happens to
power if I speed this up", "compare a lean config against a fast one",
"show me the Pareto frontier for this block". If they just want one timing
or power report for one configuration, run boson directly instead — this
skill is for comparing multiple points.

## Prerequisites (check before running)

1. A `boson` binary — on `PATH`, or pointed to with `$BOSON_BIN` /
   `--boson-bin`. boson is partcl's product (https://partcl.com), not
   shipped in this plugin. If it's missing, tell the user and stop.
2. A Liberty (`.lib`) file for the target standard-cell library — pointed to
   with `$BOSON_LIBERTY` / `--liberty`. The bundled example design
   (`designs/picorv32/picorv32.v`) is verified against SkyWater sky130
   (`sky130_fd_sc_hd`, open-source PDK — see https://github.com/google/skywater-pdk).
   Any Liberty file for the user's own library works too.
3. If `boson` runs via a container-based host wrapper (some installs do),
   every file path involved — the RTL, the liberty, and the script's own
   scratch directory — must resolve **under the current working
   directory**. The script already puts its scratch files under `cwd`; if
   the liberty file lives elsewhere and boson can't see it, copy or symlink
   it under the working directory first.

## Running the sweep

Use `scripts/boson_dse.py` in this skill's directory:

```
python3 scripts/boson_dse.py \
  --rtl designs/picorv32/picorv32.v --top picorv32 \
  --liberty <path-to-liberty> \
  --periods 6,8,12,20 \
  --presets min-area,balanced,max-perf \
  --out tradeoff.md
```

- `--periods`: comma-separated clock periods in **nanoseconds**. Include at
  least one period tight enough to violate (WNS < 0) and one comfortably
  met, so the table shows the actual timing wall, not just two MET points.
- `--presets`: which RTL parameter bundles to compare. Three are built in
  for picorv32 (`min-area` — barrel shifter/fast-mul/compressed-ISA/IRQ all
  off, two-cycle ALU; `balanced` — picorv32's own defaults; `max-perf` — all
  the speed features on). For a design other than picorv32, edit
  `PARAM_PRESETS` in the script (or pass `-G NAME=VALUE` overrides directly
  if you're driving boson yourself rather than through this script).
- `--effort fast|low|medium|high`: synthesis effort per point. `medium`
  (the default) is a reasonable balance; use `fast` for a quick first pass
  over many points, then re-run the interesting ones at `high`.

Each point takes anywhere from a few seconds to a couple minutes depending
on design size and effort — a 3-preset x 4-period sweep is 12 real compiles,
budget accordingly. Run it, don't approximate the numbers yourself.

## Reporting back

Present the resulting table (Preset / Period / Timing status / WNS / Cells
/ Area / Power) as-is — don't round or editorialize the numbers. Then add
your own read: which point looks like the best tradeoff for what the user
said they cared about, and why (e.g. "`balanced` at 12ns is MET with ~0.4ns
of margin at roughly half the power of `max-perf` — `min-area` can't close
timing below 16ns at all"). If a row errored, say so plainly and don't
silently drop it from the table.

If the user asks "why" a config costs what it does, you can point at which
picorv32 parameters differ between presets (e.g. `ENABLE_FAST_MUL` trades
area/power for a faster multiply) rather than re-running anything.
