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

Hold the allowed threshold-voltage set fixed across isolated-operator
characterization, composition calibration and mapped STA. For a single-VT
experiment, load only that VT's Liberty files, explicitly disable any VT-swapping
repair, and audit every mapped cell reference against the loaded libraries.
A single-VT netlist does not make a model calibrated with mixed-VT cells
comparable: regenerate both the operator tables and composition parameters.
Record the allowed-library hashes and use a fresh cache identity. Drive-strength
sizing within the allowed VT is a separate choice; keep its policy fixed too.

Hold the optimization objective fixed too. For an Fmax-only comparison, disable
explicit area recovery and VT swapping in every stage, select arithmetic
topologies by their measured delays, and retain timing improvements even after
the clock is met. Inspect mapper-internal area rounds separately: disabling a
post-mapping recovery pass does not disable those rounds. A stage named for area
recovery may also contain timing-improving resynthesis; preserve that work as
timing-ranked alternatives while removing area-only trades. Recharacterize after
changing the mapping policy rather than pricing the fastest isolated topology
while shipping another implementation.

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

Where an experimental model reports an explicit minimum-period estimate, use
that field for Fmax comparisons and keep WNS as the actual capture-window slack.
Match the standalone runner to the compiler's objective as well as its period:
a target-meeting policy and a maximum-frequency policy can choose different
word graphs. Compare each estimate with the implementation compiled under that
same target, rather than another target's faster result.

For Fmax, measure the minimum feasible period of each frozen mapped netlist by
changing only its clock period and rerunning STA. Bracket a feasible period and
bisect with a stated tolerance; keep waveform relationships, clock constraints
and external timing intent consistent. `period - WNS` is not a general minimum
period formula for paths spanning opposite clock edges. Recheck the worst path
after changing the period. A clock-gating enable check is not automatically a
half-cycle path; inspect its launch/capture edges and setup requirement.


An unsupported generated clock or latch in one domain must not erase independently
known opposite-edge checks in another. Keep the existing fallback for unknown
launch/capture relationships while checking paths whose shared primary root and
static inversion are established. Test mixed known/opaque domains, independent
primary clocks, and incremental trial commit/rollback. An estimate correction can
change rewrite selection: compare mapped timing across operand-order seeds, and
trace accepted ties to distinguish worst-slack progress from TNS-only changes.

For sequential equivalence, inspect the proof method and depth as well as its
verdict. A bounded same-initial-state result is not an unbounded proof. A
single-clock AIGER flow cannot establish clock-gated behavior by silently treating
all state as edge-aligned. Use a clock-aware method, check every paired state
including internal gate latches, and require positive and deliberate negative
controls under the same clock semantics.

A loose clock lets mapping/repair spend slack; an impossible clock can make
repair give up. Use the first run to find each design's achieved delay, then
recompile near that value (for example at 90% of it). Repeat the largest misses
under several logic-neutral operand-order seeds, where the build supports them,
and report medians and ranges. When comparing compile targets, retain the
candidate with the best measured timing and its own estimate; a tighter target
does not guarantee a faster result. Ensure a standalone diagnostic applies the
same operand-order transformation as the compiler. Do not infer a speed change from runtime on an
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

A masked nonzero test also has useful word forms. For an unsigned count and a
same-width shift/subtract mask, `|(x & ((1 << n) - 1))` equals
`(x != 0) && (ctz(x) < n)`. Keep the zero guard; the index of a zero word is not
a valid set-bit position. A second form precomputes data prefix ORs and selects
from `[0, x[0], |x[1:0], ...]` with the count, selecting the full OR for counts
beyond the table. This moves data reduction ahead of a late count. Preserve
shift saturation, count-increment wrapping, truncation and extension semantics;
zero- and sign-extension preserve the lowest set-bit position of a nonzero
word. Check both forms against actual Fmax: an encoder/comparison can add a
consumer to shared arithmetic even when the prefix lookup does not. When a new
worst endpoint appears, compare the same output bits and pin arcs on both
netlists, including fanout, load, input transition and drive strength. A smaller
estimate alone does not justify keeping a slower implementation.

Check when a proposed word identity becomes visible. Earlier passes can turn an
equality-guarded mux into an AND/NE expression after its matcher has already run.
Compare the IR at that pass boundary; where a final-pass override exists, run the
same matcher late as a diagnostic. If only the late invocation activates, schedule
the normalization after the pass that reveals it and before lowering. Use a
known positive activation marker to distinguish no eligible expression from a
disabled pass or missing logging. Recheck the corpus when moving the pass, and
avoid rerunning an unrelated pass family merely to reach one helper.

A profiler label is not proof that the similarly named command ran. Generic
rewrite/refactor routines can emit shared internal labels when called from
other optimizers. Check callers and distinct command-stage markers before
attributing an error to a disabled pass; retain the shared diagnostics in the
record rather than silently ignoring every similarly named stage.

For a variable shift, inspect each count bit's arrival and the high-bit overshift
predicate. Charging the count's latest bit followed by an entire barrel can hide
which mux stages actually follow that bit. Expose constant-routing shifts and
count-bit muxes late, after identities needing the original word shift have run.
For right shifts, retain the larger of the input and result widths before final
truncation; preserve signed extension and the operator's exact fill semantics.
Reduce the count to its proven unsigned significant width before building the
overshift check, keeping repeated sign bits when they may be one. Test sliced
selectors, padding, saturation, widening and truncation. Compare frozen mapped
netlist bytes and STA: unchanged implementations with better estimates establish
a representation correction, not a hardware speedup.
Preserve explicitly selected architectures and the specialized handling of
indexed single-bit reads. Test the full corpus as well as the motivating pilot:
equivalent shift forms can map differently and worsen Fmax elsewhere. If only
carry-dependent counts need normalization, distinguish them structurally and
validate both the positive cases and excluded forms.

For an adder tree, record both the result width and the widths and signedness of
its terms. The same result width and term count can describe a population count
or a sum of full words, with different compressor depths. Do not substitute the
input width for the result width in a table whose probes truncate at that width:
a one-bit output loses the carries a population count needs. Check whether the
term count lies beyond the characterized range, and whether the probe fixes a
compressor topology different from the emitted implementation. Use generic
paired-width controls before adding a cost dimension, and compare mapped
netlist hashes and timing to distinguish a pricing correction from a QoR gain.

For a scalar control driving wide muxes, compare the standalone operator with
several mux widths and optional intervening Boolean logic. Inspect measured
pin capacitance, fanout and buffer stages on the real path before changing a
composition constant. A load sweep of one frozen netlist answers a different
question from a fresh Fmax compile at each load: sizing and remapping can change
the preferred implementation. Retiming each candidate across the complete load
grid reveals the fastest measured alternative at each point without an area
trade. If adding an incremental drive cost, subtract the same operator's
reference-load delay to avoid counting its intrinsic delay twice. Sum the loads
of shared consumers, remove redundant mux bits, and verify that incremental
trial commit and rollback agree with rebuilding timing from scratch. Validate
on held-out compositions and the full corpus; a more accurate estimate does
not itself demonstrate faster mapped timing.

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
