---
name: boson-ppa-optimize
description: Iterate on Boson timing and PPA using constraints, synthesis settings, and engine fixes while preserving the design RTL. Use for closing timing, cleaning up SDC before optimization, investigating synthesis failures, choosing effort, or finding fmax. Supports an existing flow or an effort ladder; RTL variant comparisons belong to boson-timing-power-tradeoff.
---

# boson PPA optimisation

For an existing design with suspect constraints or a request to fix the synthesis
engine, follow the [constraint and engine iteration workflow](references/constraint-engine-loop.md)
before escalating effort. Preserve the user's RTL and latency requirements;
an engine-retiming request does not authorize hand-pipelining the design.

The helper below is a single-clock recipe generator. It creates a clock SDC;
`--sdc-extra` appends text, rather than replacing that generated clock. For an
existing multi-clock or mode-specific flow, iterate its Tcl directly so the
clock contract, source list, parameters and layout stage remain intact. Do not
derive a design fmax from global WNS across unrelated clocks or I/O checks.

For regressions after buffer insertion, resizing, or repeated placement, use the
[placement continuity workflow](references/placement-continuity.md) before
escalating synthesis effort. Compare timing and area on matched netlists; cell
movement alone does not establish a QoR regression.

`scripts/ppa_optimize.py` runs an escalation ladder against a target clock and
reports every rung. Each rung runs `compile` followed by `report_qor` /
`report_area` / random-activity `report_power`. Check the installed command
help and log for the actual stages: effort and LEF loading alone do not prove
that placement ran. Report unplaced results as unplaced.

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
  `report_timing -format rtl -max_paths 3` after the winning flow to
  locate it in the source), or `--eco`. For an agent's next iteration,
  export `report_timing -format json -max_paths 10 -file timing.json`
  in that same session. Read the [native timing traceback guide](../boson-rtl-timing-closure/references/rtl-traceback.md)
  before interpreting matches or handing the path to an RTL-editing skill.
  Follow the user's scope when choosing among these: if RTL must stay fixed,
  audit the surviving netlist and investigate engine changes instead.
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

## Skill feedback (last step, every run)

Before reporting, fill in Skill feedback. List every step you took that this
skill did not prescribe: commands, scripts and experiments, each with the
reason the skill's own steps were not enough. Record a question the skill had
no method for, any step whose guidance failed or misled (with the error), and
any input or coverage the skill needed and did not get.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-ppa-optimize --question "<the user's question>"
python3 $F add off_script|missing_framework|wrong_guidance|missing_input --what "..." [--why "..."] [--error "..."]
python3 $F coverage rungs_run=<n> closed=<yes|no> achieved_mhz=<f>
python3 $F outcome yes|partly|no --iterations <rungs or recipes>
python3 $F render
```

End the report with the rendered section, "none" lines included. Then offer
once to share it: `python3 $F share` (add `--map name_map.json` when a
`boson-netlist-debug` map exists) writes an anonymized copy and a `submit.tcl`
that sends it with boson's `report_feedback` when the user sources it. Never
send or source it without the user's explicit yes. See `feedback/README.md`.
