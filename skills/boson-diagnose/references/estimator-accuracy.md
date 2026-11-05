# Compare an experimental datapath timing estimate with STA

Use this when the question is whether a word-level timing model predicts mapped
arrival times, rather than whether a rewrite improves the final netlist. Absolute
accuracy and decision quality are separate measurements.

## Establish the experiment

Record the source checkout and dirty state, binary hash, timing-library hash,
Liberty set and corner, backend, flow flags, thread count, clock, input/output
delays, input transition and output load. Confirm the experimental compiler
actually ran. On builds exposing it, `datapath_compiler true` selects the compiler;
`datapath_timing_library` supplies its characterized library and `DPC-006` reports
its final estimated WNS. Treat these as build-specific interfaces, not commands
available in every release. Prefer an existing matching binary to a different
version's standalone model runner.

Generate a small reproducible corpus using fixed random seeds. Include ordinary
mixed arithmetic/shift/mux datapaths and hypothesis-driven controls. Keep the
Verilog sizing explicit, preserve each generated RTL file and record the seeds.
Combinational tops with zero I/O delays make the first comparison easiest:

```tcl
# constraints.sdc: use the Liberty's own time/capacitance units
create_clock -name v -period <period>
set_input_delay 0 -clock v [all_inputs]
set_output_delay 0 -clock v [all_outputs]
set_input_transition <characterization transition> [all_inputs]
set_load <characterization load> [all_outputs]
```

Compile with the usual medium flow and `-provenance`. Collect the estimated WNS,
`report_qor`, native timing JSON, path provenance and high-precision arrivals at
all output ports. Exclude failures, timeouts, out-of-memory runs and logs reporting
that timing repair failed while keeping an incomplete netlist. Label the stage:
unplaced cell-delay STA does not establish placed or routed accuracy.

## Compare like quantities

For a combinational design with zero I/O delays and no clock margins:

```
estimated delay = model clock budget - estimated WNS
measured delay  = maximum STA output arrival
signed error    = (estimated delay - measured delay) / measured delay
```

Use high-precision arrivals or JSON rather than a rounded text WNS when the delay
is short. If the model subtracts uncertainty or latency, recover its actual
budget; do not assume it equals the SDC period. With registers or nonzero I/O
delays, match endpoint names and timing checks, including setup, launch delay and
external delay. Do not compare a model word's latest bit with an arbitrary STA
bit. At a register endpoint, trace the selected data or enable input and its
capture check: the register node's own arrival may be its clock-to-Q launch,
so subtracting that value from a data-input arrival gives a misleading negative
stage. Retain the full results, including cases that agree.

A loose clock lets mapping/repair spend slack; an impossible clock can make
repair give up. Use the first run to find each design's achieved delay, then
recompile near that value (for example at 90% of it). Repeat the largest misses
under several logic-neutral operand-order seeds, where the build supports them,
and report medians and ranges. Do not infer a speed change from runtime on an
uncontrolled host.

## Diagnose a large miss

Read the real worst path and its provenance before assigning a cause. Inspect
operator widths, bit slices, constants, fanout, the selected arithmetic
architecture and all model-specific caps. In particular, if a model caps arrivals
based only on the number of independent source bits, repeated nonlinear rounds
can keep that source count fixed while accumulating real logic depth. Compare
several depths. A control adding one independent input bit before the same logic
can expose a threshold discontinuity: describe it as a changed-input diagnostic,
not an equivalent rewrite or a performance fix. Establish causality with a model
ablation if a stronger claim is needed.

When a serial arithmetic/shift estimate greatly exceeds mapped delay, derive an
individual output bit's Boolean function before adjusting operator costs. For a
32-bit mask and a 5-bit unsigned selector, `((1 << (x + 1)) - 1)[j]` is `x >= j`;
combining two such masks as `~low & high` gives `(lo < j) && (j <= hi)`. The
increment, shift and subtract can disappear into constant-threshold decode logic.
Check the actual expression widths and signedness, including shift-by-width and
overflow cases; verify the identity exhaustively when the input space is small.
Compare the same output bit's estimate and STA arrival as well as each word's
worst bit. Read AIG counts/depths at successive stages and inspect mapped cell
fanins: provenance may retain an adder/subtractor label after its carry structure
has disappeared. Stage counts locate simplification but do not by themselves
attribute it to one optimization pass.

For a long chain of word muxes, inspect the corresponding bit in both arms.
A partial assignment may carry an unchanged bit through different versions of
the word. Follow routing and recursively prove equal-arm muxes redundant before
counting updates; comparing only the immediate source node IDs misses this.
Consecutive writes of the same value can merge their enables, for example
`s2 ? 1 : (s1 ? 1 : q)` equals `(s1 | s2) ? 1 : q`. Preserve the priority between
different values and any intervening variable write; do not assume enables are
exclusive. Check the new critical endpoint, because removing one false chain can
expose another bit's unchanged-data muxes.

Keep constant lookup tables and format selectors visible as word structures.
Decomposing every mux into per-bit logic can regress mapping even when each
identity is correct. Verify neighboring timing, area and constraint violations,
and preserve shared or adjacent fields when applying partial-update rewrites.

Report a compact table of estimated delay, measured median/range, error and clock
for each representative case. Attach the worst-case RTL, SDC, logs and rerun
command. A synthetic counterexample proves a limitation, not its prevalence in
customer designs. For decision quality, fix candidate choices and compare the
same rewritten graphs; rerunning a changing optimizer is a different experiment.

## Skill feedback

Record coverage with the skill's feedback helper:

```sh
python3 $F coverage synthetic_cases=<n> repeated_cases=<n> seeds=<n> valid_runs=<n>
```
