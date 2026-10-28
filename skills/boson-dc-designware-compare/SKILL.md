---
name: boson-dc-designware-compare
description: Use when a boson netlist is being compared with a Synopsys Design Compiler netlist of the same RTL and the question is how much of the QoR gap (area, WNS/TNS, per-endpoint slack) sits inside DesignWare / datapath operators versus everything else, or how much worse boson's adders, multipliers, comparators and shifters are than DesignWare's — "is the gap in the DW blocks", "how far behind DC should we expect to be", "calibrate boson against DC". Times both netlists in one engine, labels DC cells by their DW names and boson cells by provenance, splits area and each endpoint's slack gap by class, and benchmarks isolated operators in both tools.
---

# Boson vs DC: how much of the gap is DesignWare

DC builds adders, multipliers, comparators and shifters from DesignWare
(`DW01_add`, `DW02_mult`, synthetic `DP_OP_*` datapath clusters, ...). boson
builds the same operators with its own datapath selector. When a boson netlist
is worse than DC's, the useful question is *where*: inside those operators (the
architecture and its mapping) or outside them (control logic, muxing, sizing,
buffering, registers, clock gating). This skill answers that in two ways:

1. **In-design split** (`dw_compare.py`): label every cell of both netlists as
   DW-equivalent or not, time both netlists with one engine, and split the area
   gap and each endpoint's slack gap by the class of the cells involved.
2. **Operator calibration** (`dw_microbench.py`): the same isolated operators
   (registered in and out) synthesized by both tools on the same library at a
   tight and a relaxed clock. This gives boson/DW delay and area ratios per
   operator and width, with no surrounding logic to confound them.

Use the split to say "X% of this design's gap is in DW". Use the calibration to
say "on this library, boson's 32-bit adders are 1.1× DW's delay". Report both
together when quoting how far behind DC we expect to be.

## What boson already reports natively

For boson's own netlist, no script is needed:

- `report_provenance [get_timing_paths ...]` traces each stage of a path to its
  RTL origin and totals the path's delay by RTL source and by the pass that
  inserted cells.
- `report_resources` lists every word-level operator it lowered, with widths
  and the architecture it chose. It is the counterpart of DC's
  `report_resources`.
- `boson-datapath-audit` turns these into a per-operator depth audit.

boson cannot attribute a *DC* netlist this way, because a foreign netlist has
no provenance. It also has no side-by-side comparison command. The scripts here
supply both: DW labels from DC's names, and one timer for both netlists.

## Prerequisites

- The **same** Liberty files, SDC (the customer's real SDC, verbatim) and RTL
  for both tools, with the same operating condition and wire model. If one
  netlist is placed and the other is not, the comparison is meaningless.
- A DC netlist **that kept its DesignWare names**. By default `compile_ultra`
  ungroups DW. Cells of the ungrouped operators become anonymous `U1234` and
  the labels are lost. For an attribution study, ask for (or run) DC with:

  ```tcl
  set_app_var compile_ultra_ungroup_dw false   ;# keep each DW instance as hierarchy
  compile_ultra ...                             ;# the production options otherwise
  report_resources -hierarchy > dc_resources.rpt
  report_qor > dc_qor_dwkept.rpt
  write -format verilog -hierarchy -output dc_dwkept.v
  ```

  Keeping DW boundaries blocks some of DC's cross-boundary optimization.
  Compare `dc_qor_dwkept.rpt` with the production DC QoR and quote the
  difference. The split is exact only for the DW-kept run.
- With only an ungrouped netlist, the script still runs. It counts boson
  datapath as DW only in the hierarchy instances where DC's DW names survived,
  and prints a `label balance` warning. Treat the whole-design percentages as
  **inconclusive** in that case (see the worked example).

## Step 1: collect from the boson session

```tcl
read_liberty ...                               ;# the same libs DC used
compile rtl.f -top top -sdc top.sdc -provenance  ;# production flow + -provenance
# ... place / repair if that is the stage being compared ...
set dw_dir dw_boson
source <plugin>/skills/boson-dc-designware-compare/scripts/collect_boson.tcl
```

This writes `netlist.v`, `resources.rpt` (boson's `report_resources`),
`cells.tsv` (cell, lib cell, area, output nets, input nets),
`prov_cells.NNNN.json` (provenance per cell, in 5000-cell chunks) and
`paths.tsv`, the worst setup path to **every** endpoint. Every endpoint is
needed, not only the failing ones: each of boson's failing endpoints must find
its DC counterpart even where DC has positive slack. `-provenance` does not
change QoR. Provenance JSON is about 8 KB per cell, so budget disk for large
designs.

## Step 2: time the DC netlist in a fresh boson session

```tcl
read_liberty ...                               ;# same set, same order
set dw_netlist dc_dwkept.v ; set dw_top top ; set dw_sdc top.sdc ; set dw_dir dw_dc
source <plugin>/skills/boson-dc-designware-compare/scripts/score_netlist.tcl
```

Both netlists are now timed by one engine, so a timer difference cannot pass
for a QoR difference. Check that this session's WNS for the DC netlist is close
to DC's own report. If a PrimeTime sign-off number is the reference, also
re-score boson's `netlist.v` here and confirm it matches the in-session WNS.

## Step 3: split

```sh
python3 <plugin>/skills/boson-dc-designware-compare/scripts/dw_compare.py dw_boson dw_dc \
    [--dc-resources dc_resources.rpt] [--scope labeled|all] [--top N] [--json split.json]
```

### Labels

- **DC**: a cell is DW if its instance path has a DW-named level
  (`DP_OP_*`, `DW01_*`, `add_x_12`, `mult_45`, `gte_x_7`, ...), or if it
  drives a net under one (`how=net`), or if every driver and load around it
  is in one such region (`how=enclosed`). Hierarchical (DW-kept) netlists
  label by instance; ungrouped ones label by whatever names survived.
- **boson**: the datapath block the cell's provenance traces to, exact match
  first, then the largest share. Families: add (add/sub/inc/neg),
  multiply (Mul and its AddTree compressor), compare (<, >=), shift, divide.
  `==`/`!=` is reported as `equality` outside DW, because DC usually leaves it
  as random logic.
- **Both**: registers, clock gates and ties are separate classes. Buffers and
  inverters stay with the region they sit in; their area is shown per class.
- `--scope labeled` (the default) counts boson datapath as DW only in instances
  where DC shows DW cells. The rest is reported as `arith, no DC DW`.
  `--scope all` counts it everywhere. That is valid only when the DC netlist
  kept every DW instance, i.e. `label balance` is near 1.

### Output

- **label balance**: DC DW area divided by boson datapath area. Below about
  0.5, DC's names did not survive for most operators, and the script warns.
  The split then covers only `dc_dw_instances`.
- **AREA by class**: cells and area per family on each side, delta and ratio.
  The headline line gives the area gap inside DW and outside it.
- **DW AREA by hierarchy instance**: DC resource cells against boson datapath
  blocks traced to the same instance. This is the most robust area comparison
  because it does not depend on matching individual operators. `no DC DW` marks
  instances where boson has datapath but DC kept no DW names.
- **TIMING**: endpoints are paired by name, or by register group when arrays
  were flattened differently (DC `mem_reg[22][20]`, boson `mem_reg[727]`).
  For each paired boson-failing endpoint, the gap `slack_dc - slack_boson` is
  split exactly into: `launch` (clock-to-Q, input delay), `dw`, `logic`,
  `buffer/inverter` (outside DW), `register` (net into D), and
  `required/setup` (setup time and clock differences). The class deltas sum to
  the gap. A negative class means DC spent more there.
- `median DW-segment delay boson/DC`: computed over paths that pass through DW
  in both netlists. It is the in-context counterpart of the microbench delay
  ratio.

When the split says the gap is inside DW, use `boson-datapath-audit` on the
worst blocks to see which architecture boson chose and how deep it mapped.
`--dc-resources` adds DC's implementation (`pparch`, `apparch`, `rpl`) per
resource, so the two architectures can be compared directly.

## Step 4: operator calibration

```sh
python3 <plugin>/skills/boson-dc-designware-compare/scripts/dw_microbench.py gen mb \
    [--ops add:32,mult:16,cmp:32,shr:32,...] --tight 100 --relaxed 2000 --lib-time-unit-ns 0.001
# boson:     read_liberty ...;           source mb/run_boson.tcl   -> mb/boson.tsv
# dc_shell:  set target/link_library;    source mb/run_dc.tcl      -> mb/dc.tsv
python3 <plugin>/skills/boson-dc-designware-compare/scripts/dw_microbench.py compare mb
```

Periods are in the library's time unit. `--tight` should fail in both tools,
so that the delay corner reads the operator's best delay
(`period - slack`, including clock-to-Q and setup, which are the same cells in
both). `--relaxed` should pass in both, so that it reads minimum area.
`compare` prints per-operator boson/DC delay and area ratios and their
geomeans. Run it on the design's library and the widths its critical operators
use (from `report_resources`).

`run_dc.tcl` is plain `compile_ultra`, with DesignWare available as in any
licensed DC. Add the customer's `compile_ultra` options when they use non-default
ones. The DC half has to run where a DC license is available, usually the
customer's machine.

## Reporting the calibration

Quote these:

1. The in-design area gap: total, the part inside DW (and the boson/DC DW area
   ratio), and the part outside DW.
2. The timing gap: WNS/TNS on each side, failing endpoints, and the share of
   the summed endpoint gap that sits in DW, logic, buffering and setup. Give
   the label balance and the number of paired endpoints beside it.
3. The operator geomeans from the microbench (delay at tight, area at relaxed)
   by family.
4. What it implies: "on this design X% of the slack gap is inside
   DW-equivalent operators, where boson is Y× DW's delay. The rest is
   control/buffering. Closing the datapath gap alone would recover about Z ps."

Never quote a DW share when label balance is low; say it is inconclusive and
why. Never compare a placed boson netlist with an unplaced DC netlist (or the
other way round), or runs with different SDC or libraries.

## Worked example: cv32e40p, ASAP7 TT, 500 ps (ETHZ bundle 20260814)

The DC netlist was ungrouped (production `compile_ultra`), which makes this
example a cautionary one:

```
DC DesignWare labels: {'name': 183, 'net': 722, 'enclosed': 84, 'dw_cells': 989}
label balance: DC DW area 119.0 vs boson datapath area 725.7 (DC/boson 0.164)
WARNING: DC's DesignWare names survive on a small part of the datapath ...
  instance                    dc area   boson  ratio
  ex_stage_i/mult_i             114.1   429.3   3.76  DP_OP_105_140_3039,DP_OP_97J6_122_4453
  ex_stage_i/alu_i                5.0    80.6  16.21  DP_OP_391J5_123_6951
  id_stage_i                      0.0    55.3 no DC DW   2x Add32 KoggeStone
  cs_registers_i                  0.0    46.1 no DC DW   Add64 HanCarlson
TIMING: WNS boson -72.9 ps, dc 0.0 ps; failing boson 1214/2332, dc 0/2243
```

cvfpu (`cvfpu_full_synth`, 1.5 ns) gives the same picture: label balance
0.164, 834 µm² of DC DW against 5090 µm² of boson datapath, with boson -37 ps
WNS and DC meeting timing. Its timing split reads `dw +48460 ps, logic
-40669 ps` for a 2163 ps summed gap.

In cv32e40p, DC's names survived only on two `DP_OP` clusters, and only partly there: the
ALU shows 5 µm² of DC DW against 81 µm² of boson datapath. Without the scope
rule, the script reported 227% of the area gap as "inside DW". With it, the
report still puts most of the timing gap in `dw` and cancels it with negative
`logic`. That pattern is DC's anonymous adder cells being counted as logic. The
right conclusion from this netlist is **inconclusive**: rerun DC with
`compile_ultra_ungroup_dw false`, or use the microbench for the operator part.
The "label balance" line exists to catch exactly this case: below 0.5 the
script prints `INCONCLUSIVE` in place of every share.
