# Liberty table shapes: does boson read every table in the library?

Liberty tables vary in shape: the number of axes (1-D, 2-D, 3-D), which
variable each axis is (input transition, output load, related pin
transition, ...), the axis order, sizes, per-table `index_N` overrides, scalar
tables. A reader that assumes "constraint tables have two axes" or "axis 1 is
always the input transition" fails on a shape it has not seen. It can fail
loudly with a load error, or silently by reading the numbers in the wrong
order. This method tests every shape the library actually uses, not a sample:

1. **Census** (`shape_census.py`) groups every table in the files into
   *shape classes*. A class is one combination of table (`cell_rise`,
   `fall_constraint`, `rise_power`, ...), timing_type, template variables in
   order, dimensions and overrides. The census only measures shapes and does
   not interpret any values. It also flags any table whose value count does
   not match its own index grid.
2. **Probe** (`shape_probe.py`) checks each class in a fresh boson session.
   It builds a mini library from the file's own header (verbatim) and the
   first cell that uses the class (verbatim). Only that table's `timing` or
   `internal_power` group is kept, so every message and value belongs to that
   one shape. It records:
   - whether the class loads, and every message boson prints for it;
   - whether boson made an arc of that timing_type;
   - for delay, transition, clock-to-Q, setup, hold, recovery and removal
     tables: boson's own timing of the arc at **two exact, off-diagonal
     index points**, compared with the table's entries there. No
     interpolation is involved, and an off-diagonal point catches swapped
     axes that a diagonal point would hide.

Runs take about a minute for a full standard-cell library. Everything runs on
your machine, and the library text never leaves it.

## Run it

```sh
P=<plugin>/skills/boson-diagnose/scripts/liberty
python3 $P/shape_census.py my_lib_a.lib my_lib_b.lib --json shapes.json
python3 $P/shape_probe.py shapes.json --boson $(which boson) --out shape_probe --jobs 8
```

Give the census the same files the flow passes to `read_liberty`.
`shape_probe.py` exits non-zero when any class has a LOAD ERROR, MISMATCH or
NO ARC.

Outputs in `shape_probe/`:

| file | contents | shareable |
|---|---|---|
| `report.md` | one row per shape class: verdict, table count, an example cell and line, messages, probe values | no: names your cells |
| `results.json` | the same, machine-readable | no |
| `class_NNNN/` | per class: `mini.lib`, `run.tcl`, `boson.log` | no |
| `shapes_summary.json` | per class: Liberty keywords (table, timing_type, variables), dimensions, counts, verdicts, message IDs | **yes**: no library, cell, pin or template names, no values |
| `submit.tcl` | sends `shapes_summary.json` to partcl with boson's `report_feedback` | source it only if you agree |

## Read the report

The header line gives coverage: how many tables are in classes that were
timed, and how many of those boson timed exactly. Messages printed by the
header alone (units, templates, missing defaults) are listed once per file.

| verdict | meaning | what to do |
|---|---|---|
| **LOAD ERROR** | boson rejected the class: the cell does not load | Read the class's `boson.log` and the example lines. If the census also lists the table under "value count does not match", the file is inconsistent; otherwise boson does not support this shape. Report it. |
| **MISMATCH** | boson loaded it but returns a different number than the table at an exact index point | The detail column gives both numbers. Read the table in the file at the example line, check the template's `variable_N` order, and rerun the class's `run.tcl` by hand to see the timing report. Report it. |
| **NO ARC** | the class loaded but boson made no arc of its timing_type | The group was dropped. Report it. |
| **WARNING** | loads and times, but boson printed a message for this group | Read the message. Messages that state an assumption matter most, e.g. LIB-303: "that axis is evaluated at 0 fF" for a 3-D constraint with a `related_out_*` axis and no `related_output_pin`. |
| **PROBE FAILED** | the probe got no number back | Not a finding about the library. The boson build may predate a query the probe uses, or the arc (an async recovery check, for example) cannot be timed by this probe. Update boson and rerun; read `boson.log`. |
| loaded, not probed | loads cleanly; this kind of table is not timed by the probe | The reason is listed: power tables, `min_pulse_width`, `clear`/`preset`, `non_seq_*`, arcs from an output pin or through a clock gate's clock pin, tables outside a timing group. |
| OK (timed exactly) | boson returns the table's own value at both points | Nothing to do. One example covers every table of the class. |

The mini libraries are verbatim cuts of your file, so a class can be
reproduced in one command: `cd shape_probe/class_NNNN && boson < run.tcl`.

## Known results on public libraries (boson 1.896)

- ASAP7 (RVT TT, 5 files, 41 classes) and sky130_fd_sc_hd (51 classes): every
  probed delay, transition, clock-to-Q, setup, hold, recovery and removal
  class times exactly, **except output transitions of `falling_edge` arcs**.
  Their clock-to-Q *delays* match exactly, and the same transition tables on
  `rising_edge` arcs match exactly, but the falling-edge output transition is
  0.3–1% off at some table points (largest at high clock slew and low load).
  Treat these MISMATCH rows as a known open issue rather than a problem with
  your library.
- The 3-D `nochange` constraint shape (`related_pin_transition`,
  `constrained_pin_transition`, `related_out_total_output_net_capacitance`)
  loads. Without a `related_output_pin` boson warns LIB-303 and evaluates
  the third axis at 0 fF.

## Report and feedback

Report each LOAD ERROR, MISMATCH, NO ARC and assumption-stating WARNING. For
each, give its shape (table, timing_type, variables, dimensions), the number
of tables affected, and the example line. Give the coverage line. To tell
partcl which shapes boson does not support, offer to send
`shapes_summary.json`: `source shape_probe/submit.tcl` in boson calls
`report_feedback`, which prints the payload and asks before sending. Never
send it, or paste library text anywhere, without the user's explicit yes.

## Skill feedback

Fill in the skill's feedback section (see SKILL.md). Coverage for this method:

```sh
python3 $F coverage --from-json shape_probe/shapes_summary.json --pick tables.total,tables.in_probed_classes,tables.in_exact_classes,verdicts
```

Never include library text, cell names or values.
