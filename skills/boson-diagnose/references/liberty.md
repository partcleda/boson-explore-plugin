# Liberty check: did boson read the whole library, and read it right?

`read_liberty` prints one line, the number of cells it loaded. It does not show:

- a pin, attribute or timing group that was dropped;
- several groups merged into one;
- a table stored with fewer axes or values than the file gives;
- a table whose axis order was misread;
- a construct boson ignores.

This method checks each of these against the Liberty text, exhaustively where
boson exposes the data and by probing where it does not. Every check names
the file line it compares against.

| check | script | covers | how |
|---|---|---|---|
| inventory | `lib_inventory.py` | every cell, pin, field, timing group, and every constraint table value | the file against boson's own library model (`pdb_query lib cell "" -tables`) and its query attributes |
| shapes | `shape_census.py` + `shape_probe.py` | every distinct table shape | one example of each shape, isolated in a fresh session, timed at exact index points |
| every arc | `shape_probe.py --scope all` | every delay and transition table of every cell, and how boson combines several groups on one pin pair | each cell loaded verbatim; each arc timed at exact index points against each group's table |

Everything runs on the user's machine. Reports name cells and stay local.
The `summary.json` / `shapes_summary.json` files hold only counts, verdicts
and standard Liberty keywords. Attributes declared with `define()`, and all
names and values, are left out. The user can choose to send these files to
partcl.

## Run it

Give every script the same files, in the same order, as the flow passes to
`read_liberty`.

```sh
P=<plugin>/skills/boson-diagnose/scripts/liberty
# 1. boson's model, read exactly as the flow reads it (fresh cache)
boson 2>&1 <<'EOF' | tee lib_read.log
set_app_var libcache_dir ./libcache_check
read_liberty a.lib b.lib
set lib_dir lib_model
source $P/dump_model.tcl
EOF
# 2. inventory: fields, pins, arcs, every constraint table
python3 $P/lib_inventory.py lib_model a.lib b.lib --out lib_inventory
# 3. shapes, then every arc
python3 $P/shape_census.py a.lib b.lib --all --json shapes.json
python3 $P/shape_probe.py shapes.json --boson $(which boson) --out shape_probe --jobs 8 --scope all
```

`--grid full` probes every index point instead of two off-diagonal ones. Use
it on a class or library under suspicion: a table that boson stores at a lower
resolution, or smooths, cannot hide between probe points.

Runtimes on a 20-core host: a 400-cell library takes about 2 minutes
for every arc at two points per table; the inventory takes seconds.

## What the inventory reports (`lib_inventory/report.md`)

| finding | meaning |
|---|---|
| cell / pin missing in boson | in the file, not in boson's model |
| timing groups dropped | a pin pair and timing_type has groups in the file and no arc in boson |
| timing groups merged | more groups in the file than arcs in boson for one pin pair and timing_type |
| when condition lost | a group's `when` has no boson arc with that condition |
| sense differs | a group's `timing_sense` is not on any matching boson arc |
| constraint table missing / smaller / reshaped / axes differ / values differ | boson's stored table (shape, axis variables and values, every value in ns) against the file. A 3-D table with a `related_out_*` axis is stored with that axis outermost and is compared in that order |
| field differs | area, dont_use/dont_touch, leakage, always_on, sequential/latch, and pin direction, function, capacitances, limits and clock, compared on every cell and pin |
| internal pin not kept as internal | `direction : internal` reads back as `other` |
| query collapses arcs | boson's model keeps N arcs for a pin pair but `get_lib_timing_arcs` reports fewer. The data is there; scripts that query arcs see less of it |
| arcs / pins only in boson | boson created something the file does not state |

The "not visible to any boson query" table lists every attribute in the files
that no query exposes (power pins, `power_down_function`, ff/latch next-state,
three-state, user-defined attributes, ...), with counts. Nothing on that list
counts as checked; it says what this method cannot see. Delay, transition and
power tables are not in boson's model dump. Delay and transition tables are
checked by the probes below; power tables are not checked.

## What the probes report

Shapes (`shape_probe/report.md`), one row per shape class:

| verdict | meaning |
|---|---|
| LOAD ERROR | boson rejected the class (e.g. "invalid constraint table ... 125 value(s), but its 5x5 index grid requires exactly 25") |
| MISMATCH | boson's timing at an exact index point is not the table's entry |
| NO ARC | loaded, but no arc of that timing_type |
| WARNING | a message for this group alone, e.g. LIB-303: a 3-D constraint whose output-capacitance axis "is evaluated at 0 fF" because the group names no `related_output_pin` |
| PROBE FAILED | the probe got no number back. This is not a finding about the library: update boson and read the class's `boson.log` |
| loaded, not probed | the reason is given (power tables, min_pulse_width, clear/preset, latch transparency, arcs from outputs or clock-gate clock pins) |
| OK (timed exactly) | boson returns the table's own values |

Every arc (`--scope all`, the second section of the same report and
`arcs.json`):

- `exact`: one group on the pin pair, and boson returns its values.
- `combined: max of groups`: several groups share the pin pair (`when`
  conditions, or both senses on a non-unate cell), and boson's value equals
  the largest of their tables at every point. That is boson's aggregation
  rule for late (max) timing. The early (min) side is not probed.
- `combined: min of groups` / `one group`: a different rule. Report it with
  the cell and arc.
- `MISMATCH`: matches none of the groups' tables. The detail column gives the
  point and both numbers.

A mismatch is a lead. Read the table at the given line, check the template's
`variable_N` order, then rerun the class's `run.tcl` in boson by hand and read
`report_timing`. For the probe itself, keep in mind:

- it connects only the probed pins, so static timing does not merge other
  inputs' slews into the measured pin;
- it reads the transition of the probed path, not the pin's worst;
- constraint values are read from the required time.

## Known results (boson 1.896)

On ASAP7 (RVT TT) and sky130_fd_sc_hd:

- no cell, pin, field or timing group is lost;
- every constraint table equals the file, value for value: 646 on ASAP7, 778
  on sky130;
- every probed shape and arc times exactly or as the max of its groups,
  except **output transitions of falling-edge (negative-edge flop and latch)
  arcs**: 8 tables on ASAP7, 34 on sky130, up to about 1% off, mostly at high
  clock slew. Their delays, and the same tables on rising-edge arcs, are
  exact. Treat these MISMATCH rows as a known open boson issue;
- internal pins read back as `other`;
- `get_lib_timing_arcs` reports one arc where the model keeps two for pin
  pairs with both a positive- and a negative-unate group (sky130 xor/xnor,
  mux, fa/ha: 67 pin pairs). Timing uses both.

## Report and feedback

For each finding give the check, the cell and arc, the file line, and both
numbers. Give the coverage: cells, pins and fields compared, constraint
tables compared, arcs probed, and the share of tables in timed classes. To
tell partcl what boson does not support, offer to send `summary.json` and
`shapes_summary.json`. `source shape_probe/submit.tcl` in boson calls
`report_feedback`, which prints the payload and asks first. Never send them,
or paste library text anywhere, without the user's explicit yes.

## Skill feedback

Fill in the skill's feedback section (see SKILL.md). Coverage for this method:

```sh
python3 $F coverage --from-json shape_probe/shapes_summary.json --pick tables.total,tables.in_probed_classes,tables.in_exact_classes,verdicts,arcs
python3 $F coverage --from-json lib_inventory/summary.json --pick cells.file,cells.boson,constraint_tables_compared,findings
```

Never include library text, cell names or values.
