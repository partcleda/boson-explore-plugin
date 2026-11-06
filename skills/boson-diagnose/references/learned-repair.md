# Audit a learned repair against a conventional repair

Use this when a learned policy misses a local repair that a conventional
optimizer finds. A poor final netlist does not by itself distinguish a weak
policy from a bad simulator or a restricted search interface.

Start with [compare-reference.md](compare-reference.md): replay both saved
netlists with one binary, the same libraries, SDC, corner, wire model and
layout stage. Preserve the original input and both outputs.

## Isolate one choice

Trace one failing path's driver through its buffer tree to the first
non-buffer receiver pins in both outputs. Class buffers from their Liberty
function. Match receiver sets by stable instance and pin names; account for
aliases and polarity. An inverter is not a transparent buffer.

Record immediate fanout, rise/fall load, buffer strengths, topology, and
arrival/slew at the same critical receiver. For primary inputs inspect the
external driving-cell and transition constraints. Preserve sequential
launch clock latency and clock-to-Q behavior.

Create a counterfactual from the learned output changing only that driver's
buffering. Try the reference tree and a simpler move already legal in the
model's action space. Verify unchanged non-buffer connectivity after
collapsing transparent buffers. Catch writer/name-normalization errors
before interpreting timing.

Time each variant in the same full-design harness. Report whole-design
WNS/TNS/area and a path with fixed launch, receiver and transition semantics.
Report the worst path through the selected gate when reconvergence changes
the critical branch. A repair may improve the selected path substantially
but barely improve WNS because another path takes over. Do not attribute
the whole optimizer gap to that one repair.

## Separate visibility, proposals, scoring and acceptance

Audit the deployed repair code, not only an offline training evaluator.

1. **Visibility:** does a window include the driver and all needed receivers?
   Distinguish a core driver from a boundary source. Expand grouped sinks to
   actual pins. Record masks, area budget, cell vocabulary and edit budget.
   Trace attempted windows before construction and reachability checks, then
   count which actually reach policy evaluation. A missing proposal record
   can mean the entire window was rejected. Check unknown cell vocabulary
   entries and untimed branches from opaque blocks; an unrelated untimed
   branch must not silently erase the evidence about a timed repair.
   Verify the executed round and proposal limits in code or traces; a CLI
   argument alone does not establish the compute budget of a separate model path.
2. **Proposals:** record net rank, sink partition and cell-size proposals.
   Check whether search samples alternative partitions/strengths or merely
   different nets with one greedy move each. More playouts do not add an
   action absent from the proposal set.
   For factorized receiver probabilities, compare the greedy partition with
   the probability of an empty sample and the expected number of selected
   receivers. Every probability can be below one half while most sampled
   partitions are nonempty. An empty thresholded partition is not evidence
   that the policy usually samples no repair.
3. **Scoring:** force the legal counterfactual through the local simulator.
   Record before/after WNS, TNS, area and the exact acceptance potential.
   Compare its predicted timing change with full-design replay.
   Preserve raw timer units for acceptance checks. Rounded ns fields or text
   that divides a float32 ps value before formatting can lose precision
   even when many decimal digits are printed.
4. **Acceptance:** if local scoring predicts a benefit, follow expansion,
   pruning, replay conflicts, global acceptance and rollback. Record each
   root candidate's prior, visit count and state (unexpanded, rejected or
   evaluated), plus the selected edit sequence after every search batch.
   A useful generated proposal can remain unexpanded through repeated
   simulations: first-play urgency and concentrated priors can favor
   revisiting unhelpful branches. Distinguish that from a bad local score or
   a rejected global trial. Test proposal coverage at the same simulation
   budget before attributing the miss to action expressiveness or training.
   Identify the timer that actually judges a candidate: a full-design trial can still
   use an incremental estimator instead of STA. Trace the selected code path
   and settings rather than inferring accuracy from a helper's name.
   Replay the exact selected edit sequence with full STA before changing
   fallback or search policy when the outer judge rejects it. Preserve
   references to newly created buffers and verify unchanged logic connectivity.
   If local
   scoring predicts harm while full STA improves, better neural priors
   alone cannot make improving-only search accept that move.

Keep a reference tree outside the model's vocabulary/action space separate
from a legal simpler move's result.

Audit WNS and TNS separately. Match endpoint identities and reconcile their
negative-slack sum with the reported TNS before ranking where the gap lives.
A window selected using a reference endpoint's deficit is an audit with
extra information; it does not establish a general window-selection fix.
Test a selector using only the candidate design's information before making
that claim. Likewise compare a proxy correction against retaining several
candidates under the unchanged full-STA gate: retention alone may recover
a feasible repair. Count the added full-STA evaluations separately.

For a multi-edit tree, replay every primitive prefix with full STA and the
local simulator. Record WNS, TNS, potential, area and step budget at each
prefix. A completed tree can improve while its early prefixes regress; a
shallow label-generating teacher may never select that route. A demonstrated
barrier for one route does not prove every improving route needs that depth.
If sampled rollouts find a better local potential, replay the exact winner
before changing search: its WNS/TNS tradeoff may still fail the actual gate.
Preserve the nondominated WNS/TNS candidates from the same proposals when
testing whether winner retention loses a valid repair. Record the additional
full-STA evaluations separately from the proposal budget. After correcting a
simulator response, rerun the unchanged policy and search: the correction can
change later observations and proposals as well as their scores. A better
forced-prefix estimate alone does not establish an optimization gain.

## Test the timing response, not just the starting value

A baseline match can conceal a wrong response to edits. Calibration may
fold omitted delay into a fixed arrival, slew or per-cell offset.

Trace boundary timing and what retiming recomputes after loads change.
Preserve rise/fall capacitances when compacting receiver groups. Pair each
arrival with the required time of the same transition and clock domain;
independently collapsed scalar values cannot be recombined into a valid slack.
A primary input with an external driving cell is not a fixed waveform:
isolating receivers changes driver delay and transition. Likewise inspect
clock-to-Q launch loads and outside-window gate sources. Verify these
dependencies, not just the initial arrival/slew.

An outside-load term preserves capacitance without preserving timing demand.
After a boundary driver's load changes, inspect every other fanout branch,
including paths that leave the window and later reenter it at a frozen input.
Replay primitive prefixes and identify the first changed critical launch,
endpoint or branch. A present driver model does not establish that those
paths participate in the score. Test read-only timing endpoints for omitted
fanouts while preserving the original edit set; transfer their capacitance
out of the outside-load term so it is counted once. Compare the predicted
loss with full STA, then rerun the unchanged policy and search. These guards
still approximate downstream delay and reconvergence; measuring part of a
loss does not establish exact response or a feasible optimization gain.

Inspect training separately. Training and native inference may use
different boundary representations despite feature/network-output parity.
A shared frozen-boundary assumption can bias teacher labels; a native-only
mismatch is a deployment-harness defect.

Regression cases should compare predicted and full-STA edit deltas,
including a useful edit, a harmful edit and rejection. Forward-pass parity
and baseline-window timing do not establish counterfactual parity.

## Findings and feedback

State which failure is demonstrated: visibility, expressiveness, proposals,
scoring, or global application/acceptance. Treat other layers as unresolved
unless tested. Quote an exact forced move, its predicted/measured change,
and the new bottleneck.

Keep instrumentation isolated from production benchmarks. Restore temporary
source changes after saving diagnostic binaries, patches and records.
Follow the host's build and experiment scheduling rules.

Use the parent skill's feedback workflow. Coverage keys:

    python3 $F coverage wire_model_matched=yes placed=no receiver_sets_matched=yes legal_counterfactual=yes local_delta_checked=yes full_sta_delta_checked=yes training_boundary_checked=yes native_boundary_checked=yes actual_acceptance_timer_checked=yes

Replace values with actual coverage. Missing simulator access or decision
traces are coverage gaps, not evidence that the policy is at fault.
