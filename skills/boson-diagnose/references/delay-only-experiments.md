# Auditing a delay-only compiler experiment

Use this alongside [datapath-audit.md](datapath-audit.md) when comparing
compiler changes with a literal zero-period clock and area recovery disabled.
This is an experiment protocol, not a recipe guaranteed to work on a released
Boson build. A zero target and recovery flags can be accepted by the shell
while downstream optimization still uses different objectives.

## Establish support before the comparison

Record the exact source revision, dirty patch and binary hash for both arms.
Inspect that build's app variables, implementation and focused tests. If it
needs a common support patch, apply the identical patch to baseline and
candidate; the candidate should differ only by the optimization under test.
Do not attribute a support-patch change to the candidate.

In particular, verify that the logical timing target preserves `Some(0)`.
A helper that accepts only positive physical clock periods may legitimately
return no period for zero, but the synthesis objective must not silently
become `None` and select an area-only race. Preserve positive-period helpers
used for division or physical calculations. An unresolved clock whose period
field happens to contain zero is not an explicitly timed zero-period clock.

Run a small compile before launching the corpus. Native timing must report
constrained paths under the literal zero clock. Preserve the original input
and output delays on both arms; do not remove interface delay merely because
the clock period is zero. Check required and arrival times, not just the
presence of a clock name. For a simple zero-latency virtual-clock output with
output delay `d`, required time should be `-d`; register setup and clock-path
terms can change this relation for sequential endpoints. Use the report's
units, and distinguish Tcl/SDC units from stored timing units.

## Prove that recovery is disabled throughout the flow

A top-level flag is insufficient evidence. Save the app-variable values and
trace which stages actually execute, including probe/cone subcompiles and
operator characterization. Different policies need separate characterization
cache keys or identical fresh caches; otherwise a no-recovery run can reuse
area-optimized prices.

An experimental support patch may use this control set:

```tcl
set_app_var synth_no_recovery true
set_app_var repair_area_recovery false
set_app_var area_recovery_after_closure false
set_app_var area_recovery_restructure false
set_app_var loop_met_area_recovery false
```

Treat these names and their full-flow behavior as build-specific. Do not
claim this block disables all recovery on unpatched main or a released build.
In some versions, even explicitly setting a variable to `false` changes
recipe dispatch. Verify that the intended new-datapath recipe still runs.
Keep defaults unchanged outside the controlled experiment.

Inventory intrinsic mapper flow/area rounds, register-phase optimization,
postmapping resubstitution/remapping/area-flow recovery, mapped-netlist
recovery, design-rule buffer recovery, setup/post-closure recovery and loop
recovery. Disable the area objective at each applicable stage. Setup timing
repair remains a separate policy: buffering, resizing or removing a redundant
buffer for timing does not by itself demonstrate area recovery.

For a native NF mapper that explicitly supports a diagnostic initial-cover
mode, the intended effective schedule can be **F1/A0/R0 with register phase
choices frozen**. F0 may produce no cover rather than a delay-only cover.
Additional register-phase rounds can introduce area work even with A0, so
inspect them separately. Require an actual mapping test and a sequential
correctness test. This experimental execution policy must not be presented as
a newly certified reference-script shape or bypass normal script validation.
If the build lacks that policy, report the unsupported scope rather than
assuming an equivalent spelling exists.

Read profile markers with their scope. An `nf.exact` profiling scope can be entered
even when its exact-area loop has zero iterations; its presence or elapsed
time alone is not evidence of hidden recovery. Conversely, the absence of a stage name is not proof of
an absent algorithm. Reconcile effective round counts, source-level dispatch
and actual edits. Save enough evidence to distinguish inactive/no-op spans
from executed optimization work.

## Keep observations and controls comparable

Use the same RTL, library files, SDC, corner, timer, effort, wire model and
recovery policy for both arms. Record worker counts and cache policy; a single
shared-host runtime is not a speed comparison. Retain all corpus cases,
including unchanged and regressing cases.

For a pass ablation, first run the explicit full pass schedule and compare its
emitted netlist and native endpoint timing against the ordinary compile.
A byte-identical full control is strong protocol evidence; if it differs,
resolve the dispatch, initial design or cache difference before assigning
causality to an omitted pass. Then start each omitted-pass run from the same
fresh elaboration and change only that pass. Preserve provenance during this
process, and check that the final audit describes the final compile rather
than a cache-seeding compile.

Distinguish the snapshot surfaces in the manifest. Live compile snapshots may
contain only a few datapath boundaries plus downstream AIG/mapped stages.
They are not every-pass datapath dumps. For every-pass evidence, retain the
initial tape and each enabled pass occurrence, with sequence numbers and the
exact settings/order; see the datapath audit reference. Reusing old raw tapes
for a changed timing model is valid only when the word-pass decisions are
unchanged and that identity is established. Label model repricing separately
from rerunning optimization under the new target.

## Judge final native timing, then explain tradeoffs

Internal repair logs can report a judged WNS that differs from the final
native report, particularly under impossible zero-period constraints. The
scorer may omit interface shifts, filter paths or use another timing basis.
Compare the same final constrained endpoint set on both arms. A judged WNS
improvement alone does not prove an improvement in final worst slack. Record
the discrepancy and scoring scope rather than treating it as hidden recovery.

An overall worst-slack win can still regress an individual endpoint. Compare
worst paths and affected endpoints separately. For a regression, save exact
library-cell chains, input/output pins, incremental delays, arrival and
required times, fanin-cone sharing and consumer pin lists. When available,
probe native net capacitance and rise/fall transition in the same session.
An extra buffer can improve local slew while adding enough propagation delay
to hurt an endpoint; fanout count alone cannot explain that tradeoff.

Keep facts separate from causality: changed factoring, polarity, drive size,
loads and required time can all contribute. An unchanged cell count or cone
depth does not establish unchanged timing. A controlled local edit may test a
hypothesis, but its result is not automatically a universally good compiler
policy. Preserve the original experiment and label diagnostic edits.

## Skill feedback

Use the skill's feedback section. Suggested coverage keys:

```sh
python3 $F coverage cases=<n> timed_zero_verified=<0|1> recovery_policy_verified=<0|1> full_controls_matched=<matched>/<controls> endpoint_regressions_traced=<n>
```
