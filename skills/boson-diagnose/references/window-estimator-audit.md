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

If arrivals agree but slack differs, trace the required-time side separately:
receiver delay depends on changed input slew, downstream constraints or loads
may change, and grouped boundary sinks may hide different requirements.

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

## Skill feedback

Record: `same_edits`, `matched_slack_basis`, `boundary_response_checked`,
`incremental_full_checked`, and `whole_design_checked` as yes/no. Explain any
missing candidate-replay or internal timing-column access instead of claiming
that an unavailable check passed.
