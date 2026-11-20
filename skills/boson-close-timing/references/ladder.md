# boson effort ladder

For an existing design with suspect constraints or a request to fix the synthesis
engine, follow the [constraint and engine iteration workflow](constraint-engine-loop.md)
before raising effort. Preserve the user's RTL and latency requirements;
an engine-retiming request does not authorize hand-pipelining the design.

The helper below is a single-clock recipe generator. It creates a clock SDC;
`--sdc-extra` appends text, rather than replacing that generated clock. For an
existing multi-clock or mode-specific flow, iterate its Tcl directly so the
clock contract, source list, parameters and flow stage remain intact. Do not
derive a design fmax from global WNS across unrelated clocks or I/O checks.

For regressions after buffer insertion, resizing, or repeated placement, use the
[placement continuity workflow](placement-continuity.md) before
escalating synthesis effort. Compare timing and area on matched netlists; cell
movement alone does not establish a QoR regression.

`scripts/ppa_optimize.py` runs an effort ladder against a target clock and
reports every rung. Each rung is one logical `compile` followed by
`report_qor` / `report_area` / random-activity `report_power`, then the same
reports again after an extra `repair_timing -setup`.

| rung | recipe | what it buys |
|---|---|---|
| 0 | `compile -effort medium` | the standard compile: one technology map, then setup, design-rule and clock-gating hold repair. Same as `compile` with no `-effort` |
| 1 | `compile -effort medium -retime` | the medium compile plus retiming in two places: registers move across datapath operators before mapping, and, only when setup repair leaves timing unmet, flops move in the mapped netlist toward the clock period with the fewest added registers, followed by one more setup repair. Preserves cycle-by-cycle behaviour, clocks, clock gating, enables and resets; latches are not moved. A design medium closes comes out the same as medium. When the clock is out of reach, `compile_retime_register_growth` (default 0.3) caps the added register bits |
| 2 | `compile -effort high` (after `set_app_var compile_allow_high_effort true`) | the strongest map and a setup repair run until timing is met or gains stop. Costs several × medium wall time and more memory; on a large design it can run for hours, which is why boson asks for the app variable |
| 3 | `compile -effort high -retime` | both |

Each rung prints two rows from the same compile:

- **compile**: the netlist exactly as `compile` returns it. This is the
  number to quote; compile already repairs setup, DRVs and clock-gating hold.
- **+repair_timing -setup**: the same netlist after one more setup repair.
  It is usually equal or slightly better, and it stops immediately when
  timing is met, so it costs little. Recommend it only when it moved the
  numbers. `--no-extra-repair` drops it.

Always try `-retime` before concluding a design with pipeline registers
cannot close: it keeps the RTL and its latency, so it is within this skill's
scope. It costs nothing where medium already closes, and where medium misses it
moves only as many flops as the clock needs (measured: cv32e40p on ASAP7
-84 → -74 ps for +7% area; a 32-bit pipelined MAC on ASAP7 -208 → -7 ps;
picorv32 on sky130 at 2.6 ns -298 → -130 ps for +3.6% area). Read the two
log lines before crediting retiming; the script prints both per rung and
labels the row `moved: N word-level, M netlist` (or `netlist met first`):

- `retime: ... N moved`: word-level registers moved before mapping.
- `netlist retime: ... N cells moved, ... flops A -> B cells`: flops moved
  across N gates of the mapped netlist, turning A flop cells into B.
  `netlist retime: timing is met ...; nothing to retime` means setup repair
  closed it first. `graph slack ... (STA WNS ...)` shows how close the
  retiming model is to STA before any move.

When anything moved, say so in the report: register names change, and an
equivalence check must be sequential, not combinational. When nothing moved,
the row equals medium's. The netlist pass stops short when backward moves
would need reset values it cannot justify (the `netlist retime:` line counts
the gates held `for reset values`); that is a limit of the engine, not of the
design.

`--no-retime` skips those rungs when the user's sign-off cannot accept moved
registers. `-retime` is not supported with `-hier-verilog`.

The ladder stops at the first rung that MEETS timing (WNS ≥ 0): the point is
the *cheapest* recipe that works. `--full-ladder` runs every rung anyway,
which is how to answer "is high worth it on this design". Among met rows the
smallest area wins.

```
S=skills/boson-close-timing/scripts
python3 $S/ppa_optimize.py --rtl designs/picorv32/picorv32.v --top picorv32 \
  --liberty <cells.lib> --target-ns 7 --find-fmax --out ppa_report.md
```

- `--target-ns T`: close timing at T ns.
- `--find-fmax`: after the ladder (or alone), probe periods using achieved
  clock (1/(period − WNS)) as the estimator: tighten 2 % past what the run
  achieved when it meets, back off 3 % when it violates, ≤ 3 probes.
  Reports fmax and the tightest failing probe.
- `-G NAME=VALUE` (repeatable) fixes RTL parameters; `--extra-tcl` is
  sourced before compile (dont_use lists, app variables); `--sdc-extra`
  appends IO delays, false paths and the like to the generated clock.
- `--provenance` adds `compile -provenance` (the netlist is identical), so
  a failing rung can go straight to `report_provenance` (see below).
- `--start-rung/--max-rung` bound the ladder; `--no-power` skips the VCD
  power step; `--workdir` keeps each rung's `flow.tcl`, `boson.log`,
  `timing_compile.json` / `timing_repair.json` and `netlist.v`.

### Settings that are not rungs

These still parse but are not part of the recommended flow. Do not add them
to a ladder or suggest them for closing timing:

- `-timing_driven` / `-timing_only` / `-no_place` (the timing-driven loop):
  in boson's own benchmarks it wrote the same netlist as the plain compile
  at the same effort, for 1–5× the wall time. `-draws`, `-select_candidates`,
  `-portfolio`, `-max_iters` and `-damping` act only inside that loop
  (`-draws` is ignored unless an experimental variable is on).
- `-datapath_search` (and `-datapath`, `-sigmaopt`, `-arch_search`) are
  retired; compile rejects them as unknown options. Architecture selection
  is part of every compile now (the datapath compiler).
- `-effort fast` / `-fast` / `-effort low` are quick probes, not recipes:
  `-fast` reports a zero-wire-load WNS that is not comparable with medium's.
- `eco_optimize` is experimental. Use `repair_timing -setup` for extra
  setup repair, and `repair_design` for design-rule repair.

When `help compile` on the installed build says something different, trust
the build: run `help compile all` and `help <app_variable>` before changing
the recipe.

## Prerequisites

A `boson` binary (`$BOSON_BIN`) and Liberty. If boson runs via a container
wrapper, keep every path under the current working directory (the script
defaults its workdir to `.ppa_*` under cwd for that reason). The ladder is
logical synthesis; it needs no LEF. Its numbers come from compile's wire
model; if the user's flow runs further steps after compile, rerun the
winning recipe through them and report those numbers separately.

## How to use it well

- Budget before launching: rungs 0 and 1 are one compile each; rungs 2 and
  3 are several × that on larger designs. Tell the user the expected wall time, run it in the
  background, and report rungs as they land (the script prints each rung to
  stderr).
- If nothing closes, the path is almost always structural. Do not reach for
  more settings. Read it:
  - `timing_compile.json` in the best rung's directory has the worst paths;
    walk them cell by cell (`report_timing -max_paths N -input_pins -nets
    -capacitance -transition_time`) and name the stages that should not be
    there.
  - Rerun the winning rung with `--provenance` and, in that session,
    `report_provenance [get_timing_paths -max_paths 1]` traces each stage
    to its RTL line, datapath block and the passes that rewrote it.
  - `report_timing -format rtl -max_paths 3` locates the path in source.
    Read the [native timing traceback guide](../../boson-rtl-optimize/references/rtl-traceback.md)
    before handing the path to an RTL-editing skill.
  Then relax the target, change the RTL (`boson-rtl-optimize`), or, when
  the question becomes "why did boson build this", hand over to
  `boson-diagnose`. Follow the user's scope: if the RTL must stay fixed,
  audit the netlist and investigate engine changes instead.
- Hold: `report_qor` prints Hold WNS. Before clock-tree synthesis it is an
  ideal-clock number; compile already closes clock-gating-enable hold and
  leaves register hold for after CTS. Say so rather than "fixing" it.
- Don't run `--full-ladder --find-fmax` on a large design in one go unless
  the user asked for the whole map; it multiplies wall time.

## Reporting back

Paste the ladder table as-is, then the one-line verdict (winning recipe,
or "does not close, best achieved X MHz"), then the recommended-recipe Tcl
block from the report. Say whether the extra `repair_timing -setup` changed
anything. If the user's real question was "which effort should I use day to
day", answer it from the table (e.g. "medium already closes with 0.3 ns
margin; high costs 3× wall time for +0.1 ns"); medium is the default
answer unless high measurably pays.

## Skill feedback

Fill in the skill's feedback section (see SKILL.md). Coverage for this method:

```sh
python3 $F coverage rungs_run=<n> closed=<yes|no> achieved_mhz=<f> extra_repair_helped=<yes|no>
```
