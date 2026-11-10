# Collection mismatches

Use this method when a cell, pin or net collection differs between runs, or a
timing constraint rejects objects the shell selected. A count difference alone
does not identify the missing or extra objects. Selection and timing binding
are separate checks.

## Preserve the query and inputs

Record the tool version, loaded netlist and library identities, top module,
current instance, naming settings and exact Tcl expression. Expand loop
variables before comparing queries. Use the same linked stage on both sides;
a synthesized netlist and an RTL hierarchy need not contain the same objects.

Keep full object names and reference-tool output on the user's machine. Do not
include them in shared feedback without the skill's anonymization and consent.

## Compare members, then counts

Evaluate the query once and retain its collection. Save sorted object names
and, for pin collections, direction and hierarchical status:

```tcl
set selected [get_pins -of_objects [get_cells u_block]]
puts [list count [sizeof_collection $selected]]
puts [lsort [get_object_name $selected]]
foreach_in_collection pin $selected {
    puts [list [get_object_name $pin] \
        [get_attribute $pin direction] \
        [get_attribute $pin is_hierarchical]]
}
```

Replace the example with the failing query. Compare name sets on the same
machine, preserving escaped identifiers and bus indices. Separate boundary
pins from leaf pins and inputs from outputs. Inspect representative missing
and extra objects in the netlist and Liberty, including whether their
connections are omitted, explicitly empty, scalar or buses. Do not normalize
hierarchy separators by blind string replacement: escaped names can contain
literal separators.

## Build the smallest matching case

Use public or invented cells and module names. Cover the observed shape with:

- A hierarchical module with its own input/output pins and internal leaf cells.
- Selection of the module alone, a leaf alone, both together, and all cells
  recursively. Retain exact member lists, not only collection sizes.
- Connected, explicitly empty and omitted leaf-pin connections, including a
  completely unconnected instance and bus pins where relevant.
- The original filter and current-instance scope, with positive controls for
  objects that must remain excluded.

The reduced case must reproduce the same discrepancy before changing code.
If it exposes another defect, label it separately; fixing it does not establish
parity for the original design.

## Check timing binding independently

If the selected collection becomes a `-through`, `-from` or `-to` constraint,
apply that constraint and update timing. Check both the binding diagnostics
and the affected paths. For a multicycle path, verify the intended period
shift and verify that a neighboring unconstrained path retains its timing.
Include individual bus bits and feedthrough boundaries when those occur in
the original case. A successful query alone does not prove the constraint
bound; a binding fix alone does not explain a collection-count mismatch.

## Unresolved clocks and timing-model differences

For unresolved register clocks, preserve the clock declarations and trace the
affected clock pins to input ports or internal clock-source nets. Group by the
actual root and count affected clock pins; separate forwarded ports, divided
clocks and disconnected nets. A concise root summary in STA-301 can identify
missing declarations without copying every register name into a report. Keep
the full attachment private. An unresolved clock is not proof of an engine
defect, and adding an invented clock only hides missing constraints.

Reduce a reported root-count problem to several distinct roots, including a
forwarded port and an internal source behind separate buffers. Verify the
counts before adding the intended clock declarations, then verify that those
declarations resolve the corresponding pins. Include a high-fanout root to
catch a diagnostic that repeatedly walks every sibling register.

When compile and a fresh session report different slack on the same written
netlist, capture `report_analysis_settings` in both sessions before attributing
the difference to stale timing. Compare the executed cell and net delay models,
SPEF coverage and explicit `timing_mode` settings. Written Verilog does not
carry session settings. A model difference is separate from an optimizer's
acceptance policy; changing the latter requires its own design-quality evidence.

## Report and coverage

Record exact missing/extra membership, the reproducer's before/after result,
unaffected controls, and whether the original query was replayed successfully.
Keep unavailable customer inputs explicit. Do not close a customer parity
issue solely because an invented case passes.

For the required skill feedback:

```sh
python3 $F coverage member_sets_compared=<yes|no> repro_reproduces=<yes|no> original_replayed=<yes|no> binding_checked=<yes|no>
```
