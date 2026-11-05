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

Compare candidate scoring and final acceptance independently. A local weighted
WNS/TNS score and a separate strict TNS veto can reject a WNS tradeoff that the
reference repair accepts. Replay both policies on the identical frozen input;
report TNS debt explicitly. When sharing the reference's acceptance policy,
retain its hold, electrical, area and preservation checks. An acceptance-only
ablation can be unchanged on one design and decisive on another.

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

A newly available choice can change an entire greedy repair trajectory. Use
controlled option ablations on the same input, then replay complete choices on
a frozen netlist; transplanting only a size or pin assignment can lose when its
benefit depends on a buffer-tree change. Report the original and final worst
path, whole-design WNS and TNS, and a control with equal extra refinement work.
If enabling the new action early regresses, test a separate late refinement
from the identical frozen state rather than claiming the action always helps.
Do not add option-ablation deltas as if they were independent contributions.

## Skill feedback

Record: `same_edits`, `matched_slack_basis`, `boundary_response_checked`,
`incremental_full_checked`, and `whole_design_checked` as yes/no. Explain any
missing candidate-replay or internal timing-column access instead of claiming
that an unavailable check passed.
