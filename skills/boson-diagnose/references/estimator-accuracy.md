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

For gate-vs-gate sequential checks, normalize state names on both netlist sides
and report the paired register-bit counts. Reading the reference netlist through
an RTL-only preparation path can leave its state unmatched and produce an
x-dependent inconclusive result even in a self-comparison. Require the identical
netlist control to pass before judging the candidate, then confirm a deliberate
output error is detected. A large topology change can also exhaust a monolithic
proof: a compositional proof must cover the word identity and both mapped links,
including payloads, fallback behavior and the one-hot premise of a selection SOP.

For sequential equivalence, inspect the proof method and depth as well as its
verdict. A bounded same-initial-state result is not an unbounded proof. A
single-clock AIGER flow cannot establish clock-gated behavior by silently treating
all state as edge-aligned. Use a clock-aware method, check every paired state
including internal gate latches, and require positive and deliberate negative
controls under the same clock semantics.

When both mapped netlists have identical sequential primitive instances, types,
parameters and pin shapes, a sufficient unbounded check can cut each matched
state output into a shared free input. Compare every original output and every
state-cell input, including clocks, enables, scan and asynchronous controls.
Equal input functions preserve identical primitive state trajectories from the
same per-instance initial state, including latches and clock gates. Refuse
changed state footprints or unhandled explicit initialization. This does not
establish an independent RTL initial-state contract. Require self-comparison,
an output-error control and a clock/enable-error control. If generating Yosys
JSON, keep ports and netnames consistent and audit serialization round trips
for disconnected or merged bit identities before crediting the proof. An
inconclusive checker or an exhausted resource budget is not an inequivalence.

State correspondence can sometimes normalize different drive strengths or Q/QN
variants, but verify their actual sequential models first. Derive an explicit
state relation and preserve every clock and data obligation; a matching cell-name
prefix is insufficient. If a physical register copy disappears, verify its repair
provenance and identical transition inputs before identifying it with its source.
Record the required initial equality and its inductive preservation. Do not
silently merge arbitrary registers or claim independent initial-state equivalence.

A loose clock lets mapping/repair spend slack; an impossible clock can make
repair give up. Use the first run to find each design's achieved delay, then
recompile near that value (for example at 90% of it). Repeat the largest misses
under several logic-neutral operand-order seeds, where the build supports them,
and report medians and ranges. Verify that each compiler pipeline actually reads
the perturbation knob: repeated identical maps from an unsupported setting are
repeatability checks, not independent operand orders. When comparing compile targets, retain the
candidate with the best measured timing and its own estimate; a tighter target
does not guarantee a faster result. Ensure a standalone diagnostic applies the
same operand-order transformation as the compiler. Do not infer a speed change from runtime on an
uncontrolled host.

When model code changes alongside optimizer code, serialize the settled word graph
and price those exact bytes with both models, without rerunning optimization.
Record the graph hash, objective and constraints; reproduce the original runner's
cost first. This separates model changes from new rewrite decisions, and avoids
overwriting concurrent source changes to reproduce an older experiment.

Fixed-graph repricing does not replace a fresh whole-flow baseline when pass
ordering, objective policy or lowering code has changed. Build the complete
current source, match its own final model cost, and rank its resulting netlists.
Keep older matched experiments as component evidence rather than treating their
word graphs as the current optimizer's output. Pin the node for a QoR A/B too:
if an identical binary produces a different AIG on another node, compare the
intermediate hashes and environment before attributing the mapped difference to
the candidate. A fixed word-graph hash alone does not fix downstream lowering.

A routing-aware model can improve aggregate error on fixed graphs while steering
word passes toward slower mapped results. Keep fixed-graph accuracy and new
whole-flow Fmax as separate acceptance gates. Even a whole-design modeled gain
check cannot guarantee that an identity-only cleanup preserves AIG ordering and
buffering. Test previously sensitive controls before widening the sweep. In
routing tests, distinguish a proven constant from an untimed source in one clock
context, preserve the final inverter of an odd inversion chain, and exercise
shared boundaries plus trial commit and rollback.

Distinguish a discarded-padding projection from an ordinary same-width alias.
A model can recognize the former without rewriting the word graph or making
all aliases and inversion chains transparent. Verify graph hashes, fresh model
costs and mapped netlist hashes separately; improved estimates on identical
hardware are an accuracy gain, not a physical timing gain. For clock-phase
controls, include a falling-edge launch so primary inputs excluded from that
context cannot accidentally mask a disappearing-gate error.

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

Width-changing routes can hide an exclusive case chain from an equal-width mux
matcher. Follow low-bit slices and zero extension while tracking exactly which
bits survive, then project every recovered arm and default to the root width.
Reuse the existing pairwise guard proof. Reject observed sign fill, nonzero fill,
shared interior values or unsupported routes unless their semantics are handled
explicitly. Check the IR's multi-hot semantics: a priority PMUX cannot become an
OR of masked arms without an exclusivity proof or priority-qualified masks.
Require a genuine projection rather than rerunning ordinary case recovery
through identity aliases late in the pipeline.

A valid normalization can still slow a short chain's mapped implementation.
Try it as a timed candidate, check local gain and the whole-design objective,
and exercise rollback. Retain a pilot with previously sensitive controls before
starting the full sweep. A modeled improvement is only a hypothesis until mapped
Fmax passes; a tied critical delay with better TNS deserves the same check.

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

For validity-guarded min/max trees, inspect the selector's Boolean function and
all payloads sharing it. A selector equivalent to `valid_b && (!valid_a || beats)`
can support a parallel winner matrix, but preserve strict/inclusive tie order,
signedness, and the original fallback payload when every input is invalid.
Do not infer activation from direct-graph tests alone: packed slices may hide
child muxes, and elaboration can allocate parents before children. Normalize
only proven contiguous routes and test both allocation orders. Recognize the
largest complete tree before claiming its descendants. Compare grouped and
parallel matrices using actual mapped timing; the faster form can use many more
cells, and a lower word estimate alone does not establish a gain. Prove every
changed mapped implementation with positive and deliberate negative controls.

Before changing a carry-delay curve, inspect which operand bits are provably
constant through muxes, parallel selects and inversion. A bit shared by the default
and every parallel-select arm stays constant even with multiple active selectors;
do not assume one-hot behavior to infer more. Preserve signed extension and input
widths. Constant bits must not become transition sources in carry timing. Bound
the total traversal work across shared branches, test inferred constants against
selector assignments, and check incremental commit and rollback against a fresh
timing rebuild. Reprice identical saved graphs first, then check whether the new
facts change rewrite selection or mapped Fmax. Report any other estimates that
become less accurate as well as the motivating improvement.

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

For decode cofactoring, make the forward reader walk and the operand membership
test use the same edge representation. A reader API that skips wire aliases can
discover a consumer while omitting the alias node named by its operands, splitting
an otherwise valid region. Test the identity with named intermediate wires, then
check real mapped timing. Separate multi-bit decoded values from single-bit
Boolean predicates: broad expansion may help one operand order and regress
others. Scope eligibility by structural evidence and validate both compiler
pipelines across the corpus. A lower estimate after scalar-control expansion can
hide a newly critical output flag; inspect all consumers before retaining it. Restricting replacement to the data
root can still change shared mapping and buffer loads; verify the same input and
output pins before concluding that leaving the flag graph intact preserves timing.

When a decoded word is also arithmetic data, specializing only its comparisons
misses the correlation. Substitute the tested value into every exact data read
for each explicit case, while leaving unmatched data symbolic. A fully constant
set of case results and default can become a bounded word lookup. Preserve
slices, wrapping and overlapping-guard priority; do not assume that two compilers
share the same multi-hot PMUX contract. Include independent arithmetic siblings
in discovery, since the comparison's reader cone alone may miss them. Compare
balanced selectors, parallel guards, indexed constant tables and bounded Boolean
composition using mapped timing: any of them can change a different shared
control cone's buffering. An indexed table must cover the full bounded domain of
the original decoded word, including every unmatched value; do not turn an
explicit-case table into a don't-care assumption. Bound the packed table size
before multiplication, and reject unsupported domains without silently falling
back to a previously regressing materialization.
Retain improvements per pipeline only after validating that pipeline; a successful
counterpart does not justify shipping a regressing implementation.

For a conditional increment `x + enable`, test early and late enables across
several widths before expanding it into prefix ANDs and XORs. The identity can
shorten an isolated carry path yet deepen surrounding overflow or zero-detection
logic after mapping. Compare the same startpoint and endpoint as well as the new
worst path; audit fanout, buffer stages and consumers of the rounded word. Reject
a real Fmax regression even when the estimate becomes much closer. Preserve
arithmetic recognizers by scheduling expansion after them, and test that one
pass invocation reaches a fixed point after accepted timing changes.

For a long chain of word muxes, inspect the corresponding bit in both arms.
A partial assignment may carry an unchanged bit through different versions of
the word. Follow routing and recursively prove equal-arm muxes redundant before
counting updates; comparing only the immediate source node IDs misses this.
Consecutive writes of the same value can merge their enables, for example
`s2 ? 1 : (s1 ? 1 : q)` equals `(s1 | s2) ? 1 : q`. Preserve the priority between
different values and any intervening variable write; do not assume enables are
exclusive. Check the new critical endpoint, because removing one false chain can
expose another bit's unchanged-data muxes.

Packed constant tables can hide address arithmetic such as `constant - index`
behind muxes, sign extension and an overshift guard. Inspect the graph after
width cleanup. For a bounded selector domain, absorb its arithmetic into the
constant entries and retain word muxes over the original selector; preserve
wrapping, slices, extension and the chosen out-of-range values. Test arithmetic
and data consumers separately from predicate consumers: a correct reindexing
can improve a comparison cone while making a variable-shift implementation
slower. Retain the measured incumbent when narrowing eligibility.

When a table matcher misses a real case, inspect selector wrappers and internal
readers before changing its schedule again. Reducing one bit with AND or OR is
wiring; reducing several bits is not. Earlier bit analysis may also leave
predicate readers on an internal constant-table subtree. Preserve those
observations, either by keeping that subtree or by rewriting each observed
constant function. Bounded copying is valid when area is secondary, but still
compare actual Fmax and audit the full corpus. An improved implementation can
offset much of a lower estimate, so report both changes and the remaining error.

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
