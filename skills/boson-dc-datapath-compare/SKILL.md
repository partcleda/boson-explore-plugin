---
name: boson-dc-datapath-compare
description: Use when a boson netlist is being compared with a Design Compiler netlist of the same RTL and the question is which part of the QoR gap (area, WNS/TNS, per-endpoint slack) sits inside the datapath operators (adders, multipliers, comparators, shifters) and which part sits outside them — "is the gap in the datapath", "split the QoR gap", "compare the operators on their own". Times both netlists in one boson session, labels DC cells by their operator names and boson cells by provenance, splits area and each endpoint's slack gap by class, and compares isolated operators synthesized by both tools.
---

# Splitting the QoR gap between a boson and a Design Compiler netlist

Design Compiler builds adders, multipliers, comparators and shifters from its
datapath library (`DW01_add`, `DW02_mult`, synthetic `DP_OP_*` clusters, ...).
boson builds the same operators with its own datapath selector. When two
netlists of the same RTL differ in QoR, the useful question is *where* they
differ: inside those operators (architecture and mapping) or outside them
(control logic, muxing, sizing, buffering, registers, clock gating). This skill
answers it in two ways:

1. **In-design split** (`dw_compare.py`): label every cell of both netlists as
   datapath or not, time both netlists with one engine, and split the area gap
   and each endpoint's slack gap by the class of the cells involved.
2. **Operator comparison** (`dw_microbench.py`): the same isolated operators
   (registered in and out) synthesized by both tools on the same library at a
   tight and a relaxed clock. This gives delay and area per operator and width,
   with no surrounding logic to confound them.

Design Compiler, DesignWare and PrimeTime are trademarks of Synopsys, Inc.
They are named here only to describe the netlists and reports this skill
reads. The skill is provided as is, with no warranty and no liability, as
stated in the repository README and LICENSE.

## Your DC license governs the DC results

The DC netlist, its reports, and every result `run_dc.tcl` produces come from
your Design Compiler license and are subject to its terms. EDA licenses often
restrict publishing or sharing performance results. Use the outputs of this
skill under those terms. Do not publish or share DC results without checking
them, and keep DC numbers out of feedback and debug bundles sent to anyone.

## What boson already reports natively

For boson's own netlist, no script is needed:

- `report_provenance [get_timing_paths ...]` traces each stage of a path to its
  RTL origin and totals the path's delay by RTL source and by the pass that
  inserted cells.
- `report_resources` lists every word-level operator boson lowered, with
  widths and the architecture it chose.
- `boson-datapath-audit` turns these into a per-operator depth audit.

boson cannot attribute a foreign netlist this way, because that netlist has
no provenance. It also has no side-by-side comparison command. The scripts
here supply both: labels from DC's operator names, and one timer for both
netlists.

## Prerequisites

- The **same** Liberty files, SDC (the design's real SDC, verbatim) and RTL
  for both tools, with the same operating condition and wire model. If one
  netlist is placed and the other is not, the comparison is meaningless.
- A DC netlist **that kept its operator hierarchy**. By default
  `compile_ultra` ungroups datapath instances. Their cells become anonymous
  `U1234` and the labels are lost. For a split, run DC with:

  ```tcl
  set_app_var compile_ultra_ungroup_dw false   ;# keep each operator instance as hierarchy
  compile_ultra ...                             ;# the production options otherwise
  report_resources -hierarchy > dc_resources.rpt
  report_qor > dc_qor_kept.rpt
  write -format verilog -hierarchy -output dc_kept.v
  ```

  Keeping operator boundaries blocks some of DC's cross-boundary
  optimization. Compare `dc_qor_kept.rpt` with the production run's QoR and
  state the difference. The split is exact only for the hierarchy-kept run.
- With only an ungrouped netlist, the script still runs. It counts boson
  datapath only in the hierarchy instances where DC's operator names
  survived, and prints a `label balance` warning. Treat the whole-design
  shares as **inconclusive** in that case (see "Ungrouped netlists" below).

## Step 1: collect from the boson session

```tcl
read_liberty ...                               ;# the same libraries DC used
compile rtl.f -top top -sdc top.sdc -provenance  ;# production flow + -provenance
# ... place / repair if that is the stage being compared ...
set dw_dir dw_boson
source <plugin>/skills/boson-dc-datapath-compare/scripts/collect_boson.tcl
```

This writes `netlist.v`, `resources.rpt` (boson's `report_resources`),
`cells.tsv` (cell, lib cell, area, output nets, input nets),
`prov_cells.NNNN.json` (provenance per cell, in 5000-cell chunks) and
`paths.tsv`, the worst setup path to **every** endpoint. Every endpoint is
needed, not only the failing ones, so that each endpoint failing in one
netlist finds its counterpart in the other. `-provenance` does not change QoR.
Provenance JSON is about 8 KB per cell, so budget disk for large designs.

## Step 2: time the DC netlist in a fresh boson session

```tcl
read_liberty ...                               ;# same set, same order
set dw_netlist dc_kept.v ; set dw_top top ; set dw_sdc top.sdc ; set dw_dir dw_dc
source <plugin>/skills/boson-dc-datapath-compare/scripts/score_netlist.tcl
```

Both netlists are now timed by one engine, so a timer difference cannot pass
for a QoR difference. Check that this session's WNS for the DC netlist is close
to DC's own report. If a sign-off timer's number is the reference, also
re-score boson's `netlist.v` here and confirm it matches the in-session WNS.

## Step 3: split

```sh
python3 <plugin>/skills/boson-dc-datapath-compare/scripts/dw_compare.py dw_boson dw_dc \
    [--dc-resources dc_resources.rpt] [--scope labeled|all] [--top N] [--json split.json]
```

### Labels

- **DC**: a cell is datapath if its instance path has an operator-named level
  (`DP_OP_*`, `DW01_*`, `add_x_12`, `mult_45`, `gte_x_7`, ...), or if it
  drives a net under one (`how=net`), or if every driver and load around it
  is in one such region (`how=enclosed`). Hierarchy-kept netlists label by
  instance; ungrouped ones label by whatever names survived.
- **boson**: the datapath block the cell's provenance traces to, exact match
  first, then the largest share. Families: add (add/sub/inc/neg),
  multiply (Mul and its AddTree compressor), compare (<, >=), shift, divide.
  `==`/`!=` is reported as `equality` outside the datapath, because DC usually
  leaves it as random logic.
- **Both**: registers, clock gates and ties are separate classes. Buffers and
  inverters stay with the region they sit in; their area is shown per class.
- `--scope labeled` (the default) counts boson datapath only in instances
  where DC shows datapath cells. The rest is reported as `arith, no DC DW`.
  `--scope all` counts it everywhere. That is valid only when the DC netlist
  kept every operator instance, i.e. when `label balance` is near 1.

### Output

- **label balance**: DC datapath area divided by boson datapath area. Below
  0.5, DC's names did not survive for most operators. The script then prints
  `INCONCLUSIVE` in place of every share, and the split covers only
  `dc_dw_instances`.
- **AREA by class**: cells and area per family on each side, delta and ratio.
  The headline line gives the area gap inside the datapath and outside it.
- **Area by hierarchy instance**: DC operator cells against boson datapath
  blocks traced to the same instance. This is the most robust area comparison
  because it does not depend on matching individual operators. `no DC DW` marks
  instances where boson has datapath but DC kept no operator names.
- **TIMING**: endpoints are paired by name, or by register group when arrays
  were flattened differently (`regs_q[3][5]` in one netlist, `regs_q[29]` in
  the other). For each paired boson-failing endpoint, the gap
  `slack_dc - slack_boson` is split exactly into: `launch` (clock-to-Q, input
  delay), `dw` (datapath), `logic`, `buffer/inverter` (outside the datapath),
  `register` (net into D), and `required/setup` (setup time and clock
  differences). The class deltas sum to the gap. A negative class means the DC
  netlist spends more there.
- `median DW-segment delay boson/DC`: computed over paths that pass through
  the datapath in both netlists. It is the in-context counterpart of the
  microbench delay comparison.

When the split puts the gap inside the datapath, use `boson-datapath-audit` on
the worst blocks to see which architecture boson chose and how deep it mapped.
`--dc-resources` adds DC's implementation name per resource, so the two
architectures can be compared directly.

## Step 4: operator comparison

```sh
python3 <plugin>/skills/boson-dc-datapath-compare/scripts/dw_microbench.py gen mb \
    [--ops add:32,mult:16,cmp:32,shr:32,...] --tight 100 --relaxed 2000 --lib-time-unit-ns 0.001
# boson:     read_liberty ...;           source mb/run_boson.tcl   -> mb/boson.tsv
# dc_shell:  set target/link_library;    source mb/run_dc.tcl      -> mb/dc.tsv
python3 <plugin>/skills/boson-dc-datapath-compare/scripts/dw_microbench.py compare mb
```

Periods are in the library's time unit. `--tight` should fail in both tools,
so that the delay corner reads the operator's best delay (`period - slack`,
including clock-to-Q and setup, which are the same cells in both). `--relaxed`
should pass in both, so that it reads minimum area. `compare` prints the
per-operator delay and area ratios and their geomeans. Run it on the design's
library and at the widths its critical operators use (from
`report_resources`).

`run_dc.tcl` is plain `compile_ultra`. Add the design's `compile_ultra`
options when they are not the defaults. It runs on your machine under your DC
license, and its results are subject to that license (see above).

## Reporting

Report to the user who ran the skill:

1. The area gap: total, the part inside the datapath (with the area ratio),
   and the part outside it.
2. The timing gap: WNS/TNS on each side, failing endpoints, and the share of
   the summed endpoint gap in datapath, logic, buffering and setup. Give the
   label balance and the number of paired endpoints beside it.
3. The operator geomeans from the microbench (delay at tight, area at
   relaxed), by family.
4. What it implies, e.g. "X% of the slack gap is inside the datapath
   operators; the rest is control and buffering".

Never quote a datapath share when label balance is low; say it is
inconclusive and why. Never compare a placed netlist with an unplaced one, or
runs with different SDC or libraries.

## Ungrouped netlists

A netlist from a default `compile_ultra` run keeps operator names on only a
few clusters, usually the largest multipliers, and on only part of each.
Typical symptoms:

- label balance well below 0.5;
- the instance table shows large ratios where DC kept a partial `DP_OP_*`
  cluster, and `no DC DW` for most adders;
- the timing split shows a large positive `dw` delta cancelled by a large
  negative `logic` delta. DC's anonymous operator cells are being counted as
  logic.

None of this is a QoR finding. Rerun DC with `compile_ultra_ungroup_dw false`,
or use the microbench for the operator part. That is why the script prints
`INCONCLUSIVE` below a label balance of 0.5.

## Skill feedback (last step, every run)

Before reporting, fill in Skill feedback. List every step you took that this
skill did not prescribe: commands, scripts and experiments, each with the
reason the skill's own steps were not enough. Record a question the skill had
no method for, any step whose guidance failed or misled (with the error), and
any input or coverage the skill needed and did not get. Keep DC results out
of it: record coverage ratios and counts, not DC area or timing.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-dc-datapath-compare --question "<the user's question>"
python3 $F add off_script|missing_framework|wrong_guidance|missing_input --what "..." [--why "..."] [--error "..."]
python3 $F coverage --from-json split.json --pick label_balance,conclusive,provenance_coverage,timing.paired,timing.selected_failing_unpaired
python3 $F outcome yes|partly|no --iterations <compare runs>
python3 $F render
```

End the report with the rendered section, "none" lines included. Then offer
once to share it: `python3 $F share` (add `--map name_map.json` when a
`boson-netlist-debug` map exists) writes an anonymized copy and a `submit.tcl`
that sends it with boson's `report_feedback` when the user sources it. Never
send or source it without the user's explicit yes. See `feedback/README.md`.
