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

Record units per interface and verify them against a nonzero pin in a trusted
report. `report_units` describes the loaded library metadata; it does not prove
that every diagnostic attribute uses those units. Current Boson timing attributes
such as `max_rise_arrival`, `max_fall_arrival` and `actual_rise_transition` convert
stored picoseconds to nanoseconds. Inspect the implementation and cross-check a
pin before converting; check capacitance units separately.

For a small measured gain, run an untouched control through the exact same
input, edit/serialization, timing, emit and reload pipeline, including executable
options. Reusing an earlier audit from a different pipeline does not establish
its zero-edit baseline. Report the gain relative to that control; a small WNS
variation within the audit tolerance does not establish an optimization gain or
certify the accompanying TNS difference.

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

Include interactions between load-dependent cut sources, not only paths from an
editable gate back into the editable core. Removing a buffer can load one cut
source more heavily while another cut source lies downstream of it. Freezing
the second source hides arrival changes even when the first source's NLDM
response is accurate. Close the connecting paths among the edit roots and their
immediate cut sources. Keep added timing observations separate from cell-edit
permissions: changing an observed gate's input caps would require additional
upstream timing coverage. Its side exits can constrain WNS without adding new
terms to the original window's TNS objective. Test a dependent cut-source chain
and a side exit against native STA before and after the exact buffer deletion.

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

Check explicit SDC loads independently of library pin capacitance. An output
port can carry `set_load` while its design pin's intrinsic capacitance is zero.
Include that external load in both rise/fall totals, grouped sinks, source
responses and replacement gates, using the native electrical resolver where
available. Starting calibration can hide an omitted load: a newly factored
gate loses the old calibration offset and is then timed at zero load. Compare
the new gate's input arrivals, evaluated arc delays, output slew and actual
load before blaming its Boolean binding. Replay an equivalent loaded-output
replacement against native STA, and check that buffering the port carries its
external load onto the new branch exactly once.

If arrivals agree but slack differs, trace the required-time side separately:
receiver delay depends on changed input slew, downstream constraints or loads
may change, and grouped boundary sinks may hide different requirements.

Check setup/recovery requirements at sequential boundaries even when both
arrival lanes are accurate. Changing data slew changes the library check, so
freezing endpoint required time can reverse the predicted value of a resize or
sink split. Compare each lane's required-time delta against full STA; retain
clock slew, check derates/annotations and competing capture checks. Reuse the
native check model where available. Apply the response per physical sink before
grouping and before summing negative slacks, including zero-load outside guards
without charging their TNS twice. Filter checks by the same launch/capture key
as each timing plane. Cache an immutable check response only while its data
slew and plane key match, and compare with uncached recomputation.

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

Attribute a whole-process profile to callers and phases before changing the
simulator's storage. Memory copies can come from loading or constraint-name
matching. Check whether call chains unwind completely; truncated stacks cannot
establish a phase percentage. If useful markers exist, gate counters after
window construction and through the repair round, recording any native commit
included. Verify first/last sample bounds and retain final STA, connectivity and
netlist-identity checks. An instrumented shared-node profile attributes costs;
it is not a controlled runtime comparison.

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

Individually accurate plans can still interfere when replayed together. If
several leading plans improve the same worst path but expose a second bottleneck,
ranked prefixes can include many overlapping alternatives before reaching a plan
for that next path. Test a representative combination across bottlenecks as well
as prefixes and singletons. Starting slack levels can shortlist such combinations;
equal or different slack does not prove either endpoint identity or independence.
Bound the extra trials and retain native acceptance against the unchanged source.
A synthetic regression should replay overlapping alternatives on two independent
critical paths and measure the installed circuit, not only assert chosen indices.

Saved candidate netlists can isolate the missing combination before an optimizer
change. Merge only verified changes relative to the same source; check changed
instances, aliases, retired nets and generated-name collisions. Reproduce each
single candidate with native STA, then check the merged result with emission,
reload, connectivity and library audits. Such a merge is a selection
counterfactual, not an actual optimizer result or a full RTL equivalence proof.
The eventual optimizer must reproduce the gain through its own replay and
acceptance, then be tested for complete-flow quality and extra timing work.

Distinguish a harness round cap from a genuine search stall. Continue an
independently reloaded compile-stage artifact to natural stagnation using the
production ceiling, retaining the same candidate and acceptance settings.
Record rounds and final artifact checks. Label this a late-only continuation;
it does not establish a fresh full-flow improvement when earlier choices also
change. Preserve short-run or early-stage regressions even if longer repair
later beats the reference.

Compare stage invocation counts before attributing an early-flow gap to choice
quality. A native-stagnation gate can skip an enabled window-search turn even
when that search can still improve the same state. Verify the boundary netlist
bytes and independently audit the productive turn. Test native continuation,
window-search invocation and the no-model path separately, then verify a fresh
flow; the scheduling defect alone does not attribute the whole quality gap.
For a partial checkpoint, also audit the next existing rounds before adding a
primitive: an admitted candidate can lose to other useful choices while repair
is still progressing.

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

Trace the chosen candidate's value and the final plan threshold together. A
preferred candidate can fall below that threshold while a discarded alternative
would pass, leaving no emitted plan despite useful candidates being timed. Test
whether retaining the best qualified alternative fixes this loss without extra
timing trials; preserve subthreshold steps when they are needed to accumulate a
useful plan. Verify the disabled control exactly and measure the full trajectory
before enabling the change. Widening an earlier shortlist cannot repair a loss
that occurs after candidate evaluation.

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

When comparing separately compiled results, verify identity before matching
cell names. Generated factor, buffer and clone counters can assign the same
name to different functions in different repair trajectories. Compare preserved
original cells, connectivity and Boolean function, or use provenance to establish
a correspondence. Retain matched-endpoint reports and maximum rise/fall pin
measurements separately; a coincident generated name is not a timing comparison.

When a path comes from a reloaded emitted design, its labels may retain a
Verilog escape marker that a netlist parser already removed. Normalize only the
recognized lexical escape when looking up a cell; retain the raw report label.
Keep bus indices and hierarchy separators intact and verify actual bindings
before treating normalized names as matching circuit points.

For exploratory correspondence, deterministic bit-parallel simulation can shortlist
candidate matching signals across netlists. It is not an equivalence proof:
rarely asserted functions can coincide on every sampled vector, and buffers or
reconvergent logic can create repeated matches on either side. Preserve ambiguous
matches explicitly. Prove the proposed local rewrite against the actual Liberty
functions on every assignment of its cut leaves before timing it. Distinguish
path-conditioned arrivals from maximum rise/fall pin arrivals, and force the same
branch when a worst path changes input at a shared gate.

When a reference uses one compound cell where the candidate has a network, inspect
whether the search can absorb that cone or only replace one gate over its current
inputs. Test the complete cone replacement on a frozen netlist before implementing
a new action. A local endpoint gain can leave whole-design WNS unchanged because
another endpoint is tied; report both. For differing sizes and pin assignments,
test their individual families and their joint choice with Boolean checking.
These experiments do not establish benefit from untransplanted buffer trees.

A newly available choice can change an entire greedy repair trajectory. Use
controlled option ablations on the same input, then replay complete choices on
a frozen netlist; transplanting only a size or pin assignment can lose when its
benefit depends on a buffer-tree change. Report the original and final worst
path, whole-design WNS and TNS, and a control with equal extra refinement work.
If enabling the new action early regresses, test a separate late refinement
from the identical frozen state rather than claiming the action always helps.
Do not add option-ablation deltas as if they were independent contributions.

## Deferring timing work during candidate scoring

If trial scoring uses only physical boundary arrival/slew and endpoint WNS/TNS,
internal backward required-time propagation may be deferred for losing trials.
Keep dynamic receiver and setup responses, grouped endpoint terms, timing-domain
planes and outside-path guards current. Complete internal requirements before
reusing any selected state for critical-node ranking, sink partitioning or
private-path extension. A locally selected clone can be reused before the global
winner is chosen; completing only the global winner leaves this path stale.

Retain an independent uncached full-retime reference. Compare candidate boundary
slacks and grouped TNS against it before completion, then compare every live
rise/fall arrival, slew, requirement and active-edge slack after completion,
including all domain planes. Exercise resize, pin permutation, insert/delete,
clone and equivalent logic-replacement sequences. Exact selected-edit replay
alone cannot validate the losing candidates or measure work saved on them.
Check an entire candidate search against the reference, and require unchanged
emitted netlist identity and native reload/connectivity results when claiming
that an optimization preserves choices. Use interleaved candidate-search runs
on one controlled allocation for speed evidence; profiler phase shares and
shared-machine wall times establish costs, not an end-to-end speedup.

## Reusing exact arc responses

A dirty combinational node can need new arrivals while some or all of its table
arguments are unchanged. Measure evaluator calls and exact-key reuse separately
from dirty-node counts. A table-response key must include the immutable library
arc and every dynamic argument the evaluator reads, including both rise/fall
input slews and output loads. Using only the largest lane, a gate name, or a
previous topology's edge position is insufficient. Keep measured calibration
offsets outside the raw-response cache when that is how the timer applies them.

An immutable baseline snapshot shared by candidate clones can avoid copying a
large mutable cache for every losing trial. Misses evaluate normally, including
new edges, changed arcs, resizes, permutations and changed loads. Re-anchoring
must not reuse a response under mismatched arguments. The independent full path
must bypass cached responses even when their keys match; poison cached delays
and slews in a regression to verify that bypass. Compare all-candidate results
against that reference, then require identical emitted choices and native timing.
Benchmark interleaved search runs rather than inferring speed from cache hits.
A wider-window correctness/resource pilot is not a controlled scaling benchmark.

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
and reload, and incremental/full timing agreement in every timing domain.
Replay overlapping windows in both orders as well: a staged cloned input can read
a buffer net another window retires in the same rewrite batch. Track shared reads
separately from removed nets. Allow several copies to share an input, while
rejecting a copy after its input net was retired or a deletion after that net was
borrowed. An isolated one-window truth test cannot expose this conflict. Keep
virtual outside-path guards out of physical load and endpoint-count totals.

Compare an equal-work frozen control, fresh compile with the operator throughout,
and identical compile followed by late operator availability. Attribute the matched
operator delta separately from cumulative improvements made earlier. Preserve the
early-enabled negative result if a better late result exists. Count surviving
copies and trace the new critical path; closing one control cone can expose an
address-decode or another path as the next worst case. STA reload and local Boolean
checks do not constitute a full RTL-versus-netlist equivalence proof. Independently
check that every loaded net has a driver: a floating cloned input can leave WNS
and TNS unchanged when another input controls arrival. Keep typed net collections
when querying `driver_pins` and `load_pins`; ordinary Tcl `foreach` can discard
collection type and resolve a net named like a port as that port. Use
`foreach_in_collection` for this check. Invalidate failed outputs and every derived
experiment; preserve their logs rather than silently re-ranking the STA-only score.

## Long-run checkpoints and option availability

For long searches, save changed completed rounds as well as phase boundaries.
Publish the complete netlist before its metadata, using temporary files followed
by atomic renames. Label snapshots partial, record the timing source and round,
and independently reload under the same constraints, audit connectivity and library
restrictions before using a snapshot as a frozen experiment source. Keep raw
metadata unchanged and store audit outcomes separately. A scheduling offset alone
is not complete serialized optimizer state. An audit-launch failure before load
does not invalidate a separately successful optimizer artifact; fix the launcher
and audit that same artifact instead of rerunning the optimization.

Hash initial mapped checkpoints when comparing changed compile trajectories.
Identical RTL and constraints do not prove identical mapped starts. Compare phase
checkpoints to locate divergence, retaining intermediate scores as partial evidence.
An improved early phase can lead to a worse later topology; do not attribute that
move to a cache or a specific operator without a controlled intervention.

Trace operator ownership filters as well as candidate generators: a sizing filter
may also suppress native pin permutations while the replacement search enables
them only late. Test equal-work frozen availability before changing the default.
If that subset shows no gain, preserve it and use a native proposal-family ablation
to test whole-flow leverage. Verify that its unmodified control reproduces the
original final metrics and netlist bytes. An option's existence or a large count
of accepted proposals does not establish that it explains the measured gap.

## Skill feedback

Record: `same_edits`, `matched_slack_basis`, `boundary_response_checked`,
`incremental_full_checked`, and `whole_design_checked` as yes/no. Explain any
missing candidate-replay or internal timing-column access instead of claiming
that an unavailable check passed.

For a batch of native counterfactuals, measure a small session-reuse pilot before
assuming library reuse saves time. Reset all design state, reread constraints,
and compare unchanged controls at both ends plus an independently measured
variant. Enforce an explicit process wall bound as well as the allocation
request. A cancelled batch without its final control is incomplete; independently
audit selected completed frames before relying on their scores.
