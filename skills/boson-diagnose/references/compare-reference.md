# Explaining a QoR gap against a reference netlist

A gap between two netlists of the same RTL is useful to partcl only when it
is pinned to patterns: "boson builds every full-adder bit from two cells",
"boson spaces buffers on long nets much closer than the reference", "this
stage undid that stage's gain". This method gets from two netlists to that
kind of finding, with numbers on both sides and one small concrete example
per finding.

Two other methods of this skill complement it:

- the DC datapath compare ([compare-dc.md](compare-dc.md)) splits the gap into inside and outside the
  datapath operators, and benchmarks operators in isolation. Use it when the
  question is the operators themselves.
- the journal debug ([journal-debug.md](journal-debug.md)) follows boson's decision journal on the failing paths
  and builds an anonymized bundle. Use it to package what this method found.

## Rules

1. **One variable at a time.** Same RTL, same Liberty files in the same
   order, same SDC verbatim, same corner, same stage (a compile against a
   compile, a placed design against a placed design, both before clock-tree
   synthesis or both after). When comparing boson versions or decks, change
   one thing and say "same deck otherwise".
2. **One timer.** Time both netlists in boson with the same session
   settings: `score_netlist.tcl` from the DC datapath compare ([compare-dc.md](compare-dc.md)) times any
   gate netlist. Report GBA numbers at one corner. A reference tool's own
   report is a cross-check, not a column.
3. **Class cells by function, never by name.** The scripts read every cell's
   Liberty `function`, so a clock NAND2 is a NAND2, a sum-only cell and a
   carry-only cell are the two halves of a full adder, and an AND-OR-invert
   gate with two pins tied together is whatever function remains. A
   name-based count is the classic way to report a regression that does not
   exist.
4. **Count what the function costs, not what the cone touches.** When
   comparing how two tools built one output (a compare, a mux), count the
   cells exclusive to its fanin cone. Shared cells (an inverted register bit
   used by many cones) belong to no single function.
5. **Define every measurement next to its number**: levels, spacing, cell
   origins or centers, which nets were excluded, which stage, which corner.
6. **Measure runtime on an idle host or a dedicated job.** A loaded host
   turns a runtime comparison into noise; give the load next to any
   runtime.
7. **Reference-tool results are subject to that tool's license.** Keep them
   on the user's machine unless the user has checked they may share them.
   In anything shared, call the reference "the reference tool" and never
   name the design, the library vendor or the customer (see Sharing).

## Inputs

| input | from | for |
|---|---|---|
| boson netlist + DEF | `write_verilog`, `write_def` at the stage compared | everything; DEF for distances |
| reference netlist + DEF | the reference flow at the same stage | everything; DEF for distances |
| reference routed DEF (optional) | the reference flow after routing | which layers long nets use |
| Liberty files | the same set both tools read | cell functions, areas, clock pins |
| timing of both netlists | boson: `report_timing -max_paths N -nworst 1 -format json`, or `paths.tsv` from `collect_boson.tcl` / `score_netlist.tcl` | failing-path families |
| boson logs, journals, `report_qor` | each boson run (`set_app_var decision_log_file run/decisions.jsonl` before `compile`) | run A/B |

Every script reads gzipped files too, streams large inputs, and flattens
hierarchical netlists. Each has `--help`.

## Step 0: are the runs comparable?

When either side is a boson run (always, when comparing boson versions):

```sh
S=<plugin>/skills/boson-diagnose/scripts/compare
python3 $S/run_ab.py old=old.log new=new.log --journal old=old.jsonl --journal new=new.jsonl \
    --qor old=old_qor.rpt --qor new=new_qor.rpt
```

When journals are supplied for multiple runs, `run_ab.py` also reports the first different non-probe decision against the first journal, including its original sequence number and line. It ignores timestamps and sequence numbers when comparing decisions. Use that first difference to locate the producing stage before comparing later edits; probe decisions may be interleaved differently.

Read, in this order:

- **Wire model.** PAR-252 means boson recalibrated the wire model from its
  own global route during the run, replacing the `set_wire_rc` the deck
  gave; "at the 2x/0.5x hold" means the fit hit its limit. A run that
  recalibrated and a run that did not time every wire differently, which
  moves TNS on its own. For like for like, rerun with the same
  `wire_price_route_calibration` in both (`off` keeps the deck's model) and
  confirm with `report_layer_rc`. Never attribute a TNS change to mapping or
  buffering before this is settled.
- **App variables that differ** (journal headers): each is a candidate cause.
- **Stage checkpoints**: the stage that lost the most TNS. A later stage
  that undoes an earlier stage's gain (e.g. register banking after
  timing-driven placement) is a finding in itself; the A/B for it is that
  stage's own settings (for banking, the `multibit_banking_*` app
  variables; `report_app_var multibit_banking*` lists them).
- Messages whose counts differ, and the boson versions.

## Step 1: the headline

One table, both netlists timed by boson at one corner:

| netlist | WNS (ns) | TNS (ns) | setup violators | std-cell area (um2) |
|---|---|---|---|---|
| boson <version> | | | | |
| reference | | | | |

Std-cell area excludes macros (`cell_mix.py` reports both). When several
boson runs are compared, one row each, with what differs in the row label.

For a residual of a few ps after repair, a small paired clock-target perturbation
can test whether the ranking is stable. Keep each binary fixed; vary only the
clock period by the same small offsets for both arms, holding absolute I/O
delays fixed. Re-run synthesis and repair: retiming an unchanged netlist does
not exercise target-dependent choices. Report every target's paired WNS, TNS
and violating-endpoint count, together with pre-repair WNS. Rank reversals show
target sensitivity; use the pre/post evidence to determine whether repair
introduced the reversal, since lowering and mapping can also respond to the
clock. This check does not explain an unresolved pre-repair gap or replace a
gate/graph diagnosis.

## Step 2: area by mapping pattern

```sh
python3 $S/cell_mix.py --liberty lib1.lib --liberty lib2.lib boson=boson.v ref=reference.v \
    --out-md mix.md --out-json mix.json
```

It prints the std-area gap split by mapping pattern (adders, XOR/XNOR, mux
and gate choice, buffering, registers) with each one's share of the gap,
the per-category table, the cell functions that differ most, adder
accounting, cells with tied inputs, clock-class cells on data nets, and the
VT mix by area. Rank findings by share of the gap. Then, per pattern:

**Adders.** Compare library full-adder cells with "bits from separate sum +
carry cells" (a sum cell and a carry cell on the same three nets): a split
bit is roughly twice the area of a library full adder. Count half adders
too: a change that brings in full adders can bring in half adders the
reference does not use. The A/B is `structural_adders` (`true` / `false` /
`auto`); to keep a cell class out, use `set_dont_use` on those cells
(boson's adder construction honours dont_use). When the user asks for "dont
touch" on a cell class, ask whether they mean `set_dont_use` (never use it)
or `set_dont_touch` (keep instances that exist): they are different
experiments.

**XOR/XNOR excess.**

```sh
python3 $S/logic_patterns.py xor --liberty lib.lib boson.v
python3 $S/logic_patterns.py xor --liberty lib.lib reference.v
```

It classes each XOR by use: `compare` (equality bits feeding an AND/NOR
reduction), `adder`, `conditional invert` (one control inverting a word)
or `other`. A large `compare` share on boson's side, with
`complex -> xor_xnor` tied-input cells on the reference side, means the
reference builds each equality bit in one AND-OR-invert cell with paired
inputs and boson uses XOR plus inverters. Prove it on one instance:

```sh
python3 $S/logic_patterns.py cone --liberty lib.lib boson.v --net <compare output>
python3 $S/logic_patterns.py cone --liberty lib.lib reference.v --net <same output>
```

Quote exclusive cells per side, list their functions, and give the shared
cells separately (Rule 4).

**Muxes against complex gates.** Discrete MUX2/3/4 on boson's side against
AOI/OAI/MAOI/MOAI families on the reference side means the reference folds
mux logic into complex gates. Also compare the counts of simple
NAND/NOR/AOI22: twice the simple gates usually goes with the missing
complex ones.

**Clock-class cells in data logic.** Clock buffers or clock NAND/NOR cells
whose outputs reach no clock pin. Report them by function; ask whether they
are intended (clock cells are usually sized for balanced edges, not data).

**VT mix.** Share of std area per VT flavour. A VT recovery that does not
run shows as almost all area in the fastest VT.

## Step 3: buffer trees

```sh
python3 $S/buffer_trees.py --liberty lib.lib boson=boson.v ref=reference.v \
    --def boson=boson.def --def ref=reference.def --out-md trees.md
```

Compare both netlists before clock-tree synthesis (clock nets are excluded
either way). Two tables, side by side: by driver-to-farthest-sink distance
(trees, buffered, average and maximum levels, spacing) and by sink count
(trees, buffered, buffer/inverter area, levels). Read:

- **Spacing on long nets.** Buffers much closer together than the
  reference's on nets over a few hundred um point at a wire model with more
  resistance than the reference assumed. Check which layers the reference
  routed those nets on (`route_layers.py` on its routed DEF) against the
  layer and model boson priced them on (`report_layer_rc`, and the Step 0
  calibration).
- **Single-sink and 2-3-sink trees that are buffered.** Buffering with no
  fanout to split is delay or distance repair; compare counts and area.
- **Levels on high-fanout trees** against the reference's at the same sink
  count.

```sh
python3 $S/route_layers.py reference_routed.def --long-um 200
```

A compile has no routing, so layer usage always comes from a routed design;
say which tool and stage it came from.

## Step 4: failing-path families

```sh
python3 $S/path_families.py --liberty lib.lib \
    boson=boson_timing.json:boson.v ref=ref_paths.tsv:reference.v [--depth 3]
```

Families are startpoint and endpoint names with numbers replaced, so a
register that fans out to every copy of a block is one family. Per family: failing
endpoints and TNS, the mean violation, buffer/inverter stages and their
delay per path, logic stages per path, and "closable" (failing paths whose
buffer delay is at least their violation, an upper bound). The reference
columns cover the same family's paths whether or not they fail.

The finding to look for: logic stages as few as the reference's or fewer,
buffer stages several times the reference's, and buffer delay per failing
path larger than the mean violation. That says the timing gap is buffering,
not logic depth. For the worst path of each top family, give the chain from
the timing report: the buffers in series, their delay, the distance they
span, and the logic after them.

## Step 5: write it up

Lead with the headline table, then the findings ranked by share of the area
gap and by TNS. Per finding:

1. One sentence that names the pattern, with its share of the area gap
   and/or the TNS it explains.
2. Numbers on both sides (cells, area, ratio), from the script outputs.
3. One concrete instance: a cone (cells on each side) or a path (buffers,
   delay, distance).
4. What the reference does instead, in cell functions, not vendor cell names.
5. The next experiment, or a direct question when intent is unclear ("is
   this override intended? is there a switch to keep our model?").

Close with the corrections: if an earlier message classified something
wrongly (a name-based count, a cone that swept in shared cells), say what
was wrong and give the corrected numbers. Answer each question the user
asked, in order, before adding new findings.

Template:

```markdown
## <boson run> against <reference> — same RTL, library, SDC and corner

|                  | WNS (ns) | TNS (ns) | setup viol | std area (um2) |
| boson <version>  |          |          |            |                |
| reference        |          |          |            |                |

1. <pattern> (~N% of the area gap)
   <both-side counts and areas>. Example: <cone or path>. The reference
   <does instead>. Next: <A/B or question>.
2. ...

Measurement notes: <levels, spacing, origins, excluded nets, stage, host load>.
Corrections to earlier numbers: <what changed and why>.
```

## Sharing with partcl

What partcl can act on is the pattern and its size, not the design. Before
anything leaves the user's machine:

- run the outputs through the anonymizer of the journal debug ([journal-debug.md](journal-debug.md))
  (`anonymize.py --map name_map.json --encode '<name>'` for every design
  object a finding cites), or describe objects generically ("a register
  fanning out to many blocks", "an 8-bit equality compare");
- call the other tool "the reference tool" and the library by node only;
- the user decides whether reference-tool numbers may be shared under that
  tool's license. Ratios and shares ("1.4x the reference's adder area")
  reveal less than absolute values; offer them as the default.

Never send anything yourself; the user sends it.

## Skill feedback

Fill in the skill's feedback section (see SKILL.md). Coverage for this method:

```sh
python3 $F coverage wire_model_matched=<yes|no> placed=<yes|no> unknown_cell_types=<n> paired_families=<n>
```
