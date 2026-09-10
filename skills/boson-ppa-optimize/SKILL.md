---
name: boson-ppa-optimize
description: Use when the user wants boson to OPTIMISE a design's PPA — "close timing at X ns", "what's the fmax of this block", "get the area/power down while still meeting timing", "which boson effort/flags should I use". Escalates through boson's real optimisation levers (effort, best-of-K placement, candidate race, datapath search, ECO) one real run at a time, stops at the cheapest recipe that meets timing, and can search for fmax. Not for comparing RTL variants (that's boson-timing-power-tradeoff).
---

# boson PPA optimisation

`scripts/ppa_optimize.py` runs an escalation ladder against a target clock and
reports every rung. Each rung is one real `compile` (synthesis + timing-driven
placement + STA) followed by `report_qor` / `report_area` / random-activity
`report_power`. Nothing is estimated.

| rung | recipe | what it buys |
|---|---|---|
| 0 | `-effort medium` | baseline (default) |
| 1 | `-effort high` | more synthesis + layout-loop effort |
| 2 | `-effort high -draws 3` | best-of-3 placement seeds (~3× loop wall time) |
| 3 | `-effort high -select_candidates` | races AIG / timing-AIG / XMG mappings through the loop, keeps the winner |
| 4 | `-effort high -datapath_search` | architecture beam search on adders / multipliers / mux trees (heaviest) |

The ladder stops at the first rung that MEETS timing (WNS ≥ 0) — the point is
the *cheapest* recipe that works, not the most expensive. `--full-ladder`
runs every rung anyway (useful when the user also wants the area/power
tradeoff between recipes). `--eco` then runs `eco_optimize -rounds 3 ;
repair_design` on the best rung and reports the delta.

```
S=skills/boson-ppa-optimize/scripts
python3 $S/ppa_optimize.py --rtl designs/picorv32/picorv32.v --top picorv32 \
  --liberty <cells.lib> --lef <tech.tlef> --lef <cells.lef> \
  --target-ns 7 --find-fmax --out ppa_report.md
```

- `--target-ns T` — close timing at T ns.
- `--find-fmax` — after the ladder (or alone), probe periods using achieved
  clock (1/(period − WNS)) as the estimator: tighten 2 % past what the run
  achieved when it meets, back off 3 % when it violates, ≤ 3 probes.
  Reports fmax and the tightest failing probe.
- `-G NAME=VALUE` (repeatable) fixes RTL parameters; `--wire-rc <fF/um> <ohm/um>`
  calibrates `set_wire_rc` for PDKs boson doesn't know (it only has ASAP7
  built in — sky130 runs on a generic default and says so in the log).
- `--start-rung/--max-rung` bound the ladder; `--no-power` skips the VCD
  power step; `--workdir` keeps the per-rung `flow.tcl` + `boson.log`.

## Prerequisites

Same as the other skills: a `boson` binary (`$BOSON_BIN`), Liberty **and
LEF** (placement needs footprints), and — if boson runs via a container
wrapper — every path under the current working directory (the script
defaults its workdir to `.ppa_*` under cwd for that reason).

## How to use it well

- Budget before launching: rung 0/1 cost one compile each; rung 2 is ~3×
  the loop time; rungs 3–4 can be several × a plain compile on big
  designs. Tell the user the expected wall time, run it in the background,
  and report rungs as they land (the script prints each rung to stderr).
- If nothing closes, the script says what *was* achieved and names the
  levers left: relax the target, pipeline the critical path in RTL (run
  `report_timing -max_paths 3` in a boson session on the winning
  workdir's `flow.tcl` to name it), or `--eco`.
- Hold: `report_qor` prints Hold WNS; boson's `repair_timing -hold` is
  post-CTS, so on a pre-CTS netlist a hold number is ideal-clock only —
  say so rather than "fixing" it.
- Don't run `--full-ladder --find-fmax --eco` on a large design in one go
  unless the user asked for the whole map; it multiplies wall time.

## Reporting back

Paste the ladder table as-is, then the one-line verdict (winning recipe,
or "does not close, best achieved X MHz"), then the recommended-recipe Tcl
block from the report. If the user's real question was "which effort
should I use day to day", answer it from the table (e.g. "medium already
closes with 0.3 ns margin; high costs 2× wall time for +0.1 ns").
