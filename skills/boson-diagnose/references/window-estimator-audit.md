# Audit a window timing estimator

Use this when buffering or sizing choices look good in a local timer but lose
when committed to the design. Separate prediction error from a poor search
choice before adjusting objective weights or running a design suite.

## Freeze the first discrepancy

Keep one design, one repair stage, one window and the exact edit prefix that
first disagrees. Save the library/corner, constraints, wire model, boundary
arrivals and required times, original cell types, sink partition and edits.
Replay that prefix alone on a fresh fork of the same design. A replay of a
resize must rebind its library pins/arcs before timing; an accepted edit
receipt is not proof that the new master was timed.

Compare on the same pin set. A window's cut pins can be internal pins in the
whole design; their minimum slack is not the whole design's WNS. Record both
and include whole-design TNS/area for edits that pass the local objective.

## Verify the quantity before interpreting the difference

For each compared pin, retain separate rise/fall arrival, slew, required time
and slack. Check the clock-domain basis as well as units. A scalar slack
propagated for repair ranking is not interchangeable with transition-specific
STA slack. Neither is `min(required) - max(arrival)` interchangeable with the
minimum of matched required-minus-arrival lanes.

A forced `-through` timing report follows a selected path. Its arrival at an
intermediate gate can be earlier than that gate's maximum arrival from another
fanin, even within one clock domain. Compare path-conditioned quantities with
the same path, and maximum pin quantities with maximum pin quantities. A large
improvement on the forced path can leave WNS almost unchanged when another
path takes over; it is not by itself evidence that the local timer is wrong.

In Boson's Rust repair harness, `RepairTiming::pin_slack_ps` reads
`view.slack_ps`; that column can carry scalar repair priorities. After a raw
timer call, internal `pin_lanes` slack lanes can be unavailable. Use the same
transition preparation as the starting measurement (the repair's
`Trials::measure`/`prepare_timing` path, where accessible), and compare matched
transition lanes. Do not treat missing lanes as measured zero slack. These
are internal APIs: inspect the checkout before depending on their names.

## Locate the first timing error

After each atomic choice, compare predicted and measured arrivals and slews
at the changed driver, inserted buffers, and downstream gates in topological
order. At the first divergence, inspect every input: arrival/slew per lane,
library arc and sense, evaluated rise/fall delay, and output load. Retain any
calibration offset explicitly; matching the starting measurement by an offset
does not prove predictions remain correct after changing the winning input.

Check window boundaries for reconvergence. A gate outside the core cannot be
held at a fixed arrival if an edited core driver reaches it and its output
feeds the core again. Include those connecting paths in the timed region, or
propagate their boundary response. Validate with the original edits replayed
through both window representations; running two searches alone confounds a
timer correction with different choices. Keep truly independent boundaries
outside to avoid turning every window into the entire design.

Check primary inputs with `set_driving_cell` before treating them as fixed
sources. Changing their fanout or sink capacitance changes the external driver's
NLDM delay and output slew. Boson can report the raw input-delay arrival and zero
slew on the port pin while applying the driving cell on its outgoing net arcs;
compare the first receiving pins as well. A local graph with zero-delay net edges
must represent the virtual driver's output, including during calibration. The
external-driver delay uses a zero-load reference: subtract that reference per
library arc before reducing alternatives, and retain the loaded output slew.
Validate both a load increase (such as an upsize) and side-sink buffering. A
frozen port can make an actually losing upsize appear beneficial and hide a
useful buffer even when incremental and full local recomputation agree.

If arrivals agree but slack differs, trace the required-time side separately:
receiver delay depends on changed input slew, downstream constraints or loads
may change, and grouped boundary sinks may hide different requirements.

Check objective invariance under sink grouping. Replacing several sinks by
their minimum requirement preserves WNS, but not their slack sum. Retain each
physical sink's rise/fall requirements, take its worst matched transition,
then sum its negative slack. Across clock domains, take the worst domain per
sink before summing; taking the worst domain's total is a different quantity.
Test grouped and ungrouped representations before and after an arrival change.
Boundary slack sums still approximate downstream endpoint TNS: label them as
such and retain whole-design validation.

## Check incrementality independently of search quality

For the same candidate mutations, compare incremental and full recomputation
of the window after resize, insertion, deletion and dependent edit sequences.
Check all live arrival/slew lanes, required lanes and active-edge slacks;
checking only WNS can miss a stale noncritical cone that becomes critical
later. Include an independent branch that should need no new table lookup.
Then check selected candidates against whole-design STA; agreement between two
local recomputations does not validate the window approximation.

Benchmark identical edits with both modes in one allocation, interleaving
order and repeating enough to see spread. Report window size, edits, table
work and time per replay. Separate timer/search time from synthesis, model
inference and whole-design validation. A faster local timer alone is not a
faster compile, and numbers within the interleaved spread are inconclusive.

Once fidelity is established, investigate missed choices: replay the
reference repair's exact sink partition and cell sizes in the window. Check
whether it was absent from candidates, pruned by a surrogate score, evaluated
incorrectly, or rejected by the whole-design guard. Change one cause at a time.

Check competition between windows separately from choices inside each window.
Record each plan's starting WNS, local gain, rank, and whole-design replay result.
A large local gain in a noncritical window can outrank an accurate improvement
of the design's bottleneck. If every rejected batch prefix contains the same
head window, shrinking prefixes cannot discover a useful plan below that head.
Replay the omitted plans individually before concluding that a new action or
better estimator is needed. Carry a plan's original criticality into selection;
compare any ranking correction on an identical frozen state with equal extra
work, then on fresh compiles. A frozen improvement does not establish that the
changed early repair trajectory improves the complete flow.

An accepted batch can also hide a better smaller batch. Measure the existing
batch sizes against one unchanged starting design, retaining the same native
acceptance checks for every alternative. Compare measured WNS and TNS before
choosing; stopping at the first acceptable large batch is a selection policy,
not evidence that it is the best available result. Check the selected batch
again with full STA, then compare fresh compiles and runtime overhead.

Audit action availability by stage as well as by name. Ownership flags can
suppress a reference action while the replacement enables it only in late
refinement. Test disabling the reference action and enabling the replacement
action earlier separately. These ablations measure different trajectories;
do not subtract them as independent causal contributions. A reference final
pin assignment or buffer removal may regress when transplanted alone, so
trace the accepted sequence before claiming a missing primitive is decisive.

Distinguish source loading from source-side timing coverage. A boundary source
can correctly model extra outside capacitance while missing the required times
of paths that source drives outside the window. Replay an exact bad plan and
its individual components. If an upsize speeds the window but slows another
branch through a shared launch flop, compare that source's arrival/slew and the
outside branch's slack in both timers. A source load model alone is insufficient.

Test immovable outside-path guards using existing required times and receiver
NLDM response, with zero added load and no duplicated endpoint TNS. Exclude
paths that return into editable logic: their requirements can improve with an
edit and must not be frozen. Keep graph shape stable across clock domains,
including untimed lanes. Virtual guard edges must not silently enable buffer
insertion by changing a physical fanout count. Compare the exact rejected
choice and alternative selected plan, then frozen and fresh flow results.
These guards remain an approximation; check their whole-design error and cost.
If many unchanged guards resample tables, test dependency-keyed receiver reuse
against an independent full recomputation and an uncached incremental control.
A cache with no measured leverage on an earlier window can matter after the
modeled boundary changes, but the new context needs its own evidence.

Compare candidate scoring and final acceptance independently. A local weighted
WNS/TNS score and a separate strict TNS veto can reject a WNS tradeoff that the
reference repair accepts. Replay both policies on the identical frozen input;
report TNS debt explicitly. When sharing the reference's acceptance policy,
retain its hold, electrical, area and preservation checks. An acceptance-only
ablation can be unchanged on one design and decisive on another.

Even correctly aggregated boundary slacks are not whole-design endpoint TNS.
Replay the exact competing choices, such as a resize and a buffered sink
partition, and compare their local and global WNS/TNS ordering. Agreement on
WNS can coexist with a reversed TNS ordering. When the user's target is WNS,
test making WNS primary and using the approximate secondary score only among
equivalent primary outcomes, with the existing numerical resolution and
whole-design hold, electrical, area and preservation checks. Report actual
TNS debt. An objective ablation establishes a mechanism; it is not a license
to tune a multiplier or infer that the new greedy trajectory always wins.

If the reference factors a compound gate, test the complete equivalent network
with the same output load. Test output-buffer removal separately and together:
the factorization can help while removing its buffer loses. Validate generated
networks against the original truth table for every input assignment, then
check simulator mutation, applied connectivity and incremental/full timing.
Keep the output identity traceable when replacement retires its original pin.
Competing windows can skip an earlier mutation but retain its dependent later
edits. Check replay against the live cell interface and input bindings: a resize
for a replacement gate must not reach the unreplaced cell. Test skipped ancestors
explicitly. Reload the final emitted netlist, link it, and compare its WNS and TNS
before treating a promising in-memory result as valid QoR evidence.

When reload introduces a loop absent from the in-memory graph, inspect output
ports and emitted aliases as well as replacement cells. Moving a cell-driven
output port off the net named for it can leave that port name upstream of a
new buffer; the writer's continuity assignment then joins its input and output.
Keep the output port on its named net and move the original driver and
unselected side loads upstream, following the native buffering convention.
Test a vector port, an unselected side branch, a buffer chain and deletion.
Compare pin-to-pin connectivity after emit/reload independently of net spelling;
a matching WNS alone can hide the new loop while TNS changes.

A newly available choice can change an entire greedy repair trajectory. Use
controlled option ablations on the same input, then replay complete choices on
a frozen netlist; transplanting only a size or pin assignment can lose when its
benefit depends on a buffer-tree change. Report the original and final worst
path, whole-design WNS and TNS, and a control with equal extra refinement work.
If enabling the new action early regresses, test a separate late refinement
from the identical frozen state rather than claiming the action always helps.
Do not add option-ablation deltas as if they were independent contributions.

## Cloning as a missing window choice

A clone intervention must distinguish combinational copies, register copies,
and structural private-path sweeps. A per-net Clone filter may leave a separate
private-path stage active. Verify which proposal families and stages a diagnostic
flag actually covers in the binary used; a flag absent from that binary is a null
intervention, not negative evidence about the operator.

Test cloning as a complete connectivity mutation: copy the function, move selected
sinks, retain the other branch, and account for every new input capacitance at its
upstream driver. Include upstream paths outside the editable window. A cut source
with only a launch-response model is not a complete gate and cannot be copied
faithfully without bringing its fanins into the window. Preserve clock, sequential,
macro, multi-output and guarded-cell restrictions independently of timing gain.

Offer joint topology choices when a copy alone loses: buffer-tree removal plus
sink redistribution, independent sizing/buffering of the branches, and a short
private path copied atomically. Give copied input pins stable replay identities;
later upstream isolation must reconnect the intended copied input, even when graph
and library pin order differ. Verify exhaustive Boolean behavior through emission
and reload, and incremental/full timing agreement in every timing domain. Keep
virtual outside-path guards out of physical load and endpoint-count totals.

Compare an equal-work frozen control, fresh compile with the operator throughout,
and identical compile followed by late operator availability. Attribute the matched
operator delta separately from cumulative improvements made earlier. Preserve the
early-enabled negative result if a better late result exists. Count surviving
copies and trace the new critical path; closing one control cone can expose an
address-decode or another path as the next worst case. STA reload and local Boolean
checks do not constitute a full RTL-versus-netlist equivalence proof.

## Skill feedback

Record: `same_edits`, `matched_slack_basis`, `boundary_response_checked`,
`incremental_full_checked`, and `whole_design_checked` as yes/no. Explain any
missing candidate-replay or internal timing-column access instead of claiming
that an unavailable check passed.
