# Constraint and synthesis-engine iteration

Use this workflow when a design already has a flow, its SDC is suspect, or
the user wants synthesis fixes while preserving RTL. A passing timing number
is meaningful only for the intended operating mode and checked endpoints.

## Establish the timing contract

Record the source list and parameters, RTL and Boson revisions (including
local patches), binary hash, library/corner alias, SDC and sourced files,
thread count, and physical stage. Preserve the original artifacts. Keep
licensed library names and contents out of published issues and skill files.

For parameterized blocks, compare hard-coded SDC index bounds, last-row or
last-lane reference clocks, literal egress port indices and derived index
expressions with the elaborated port widths. Updating loop bounds alone can
leave a separate repair-egress constraint on the old final row. A supplied SDC can
belong to a larger configuration: out-of-range clocks and skipped I/O delay
checks do not establish coverage for the smaller block. Make a separate,
dimension-matched copy, preserve its delay budgets and clock relationships,
and rerun both arms under that same copy. Do not count removal of invalid
references as a retiming gain. Verify the diagnostics after mapping and final
STA; an early parse with no warnings does not prove all references resolve.

Read the delivered constraint bundle before inventing exceptions. Functional
mode settings may live in a separate DFT-disable file. Trace clock mux selects,
reset bypasses and test enables to establish the intended values. A false path
on a programming input does not make an internal configuration register static.

For functional mode, prefer the supplied `set_case_analysis` settings; keep
scan/JTAG analysis as separate scenarios. Verify selectors against the current
netlist and record the bound objects. Hierarchy separators, optimized-away
registers, clones, and Q-only versus QN-only mapping can change matches. A zero
on a logical Q becomes one on its complementary QN. Do not treat a nonempty
wildcard match as proof that every intended control was covered.

Inspect launch/capture edges as well as cell and net delays. An apparent
multi-nanosecond path can be a short mode-control path with an inappropriate
clock relationship. Audit `set_clock_groups -allow_paths`, cross-clock max/min
delays and multicycle start/end semantics. Preserve intentional functional
crossings; do not remove `-allow_paths` globally to improve WNS. Scope reset
exceptions to their justified domains and retain required recovery/removal
checks. An unexpected edge pair may also require a small STA-engine reproducer.

## Measure the constraint change separately

Replay timing on the same mapped netlist and binary with one justified
constraint change per scenario. Require complete timing and inspect unmatched
selectors, clock reachability and representative setup/hold paths. Record
exceptions added or removed and any newly unconstrained endpoints. Empty path
reports are not evidence of closure. Do not label a corrected mode's WNS delta
as a synthesis speedup or infer one fmax from mixed clock domains.

Once mode and exception coverage are established, freeze the corrected SDC for
engine comparisons. Recompile with the original flow and `-provenance`, keeping
the target period, I/O requirements, parameters and physical stage fixed.
Distinguish a mode-specific result from full functional-and-test signoff.

Inspect optimization stop reasons before attributing small differences between
independent runs. A wall-time-limited equivalence sweep can keep different
choices under the same nominal settings. Record the budget clock; for a
controlled ablation, use matched work budgets when the flow supports them, or
separate the internal baseline-versus-trial result from run-to-run variation.
Keep a product-default comparison identifiable if a follow-up changes budgets.

A run stopped before repair does not establish the full flow's peak memory.
When a run reaches its memory allocation, inspect resident and swapped memory
and page reclamation before attributing slow repair to the optimization under
test. Preserve incomplete attempts and rerun both arms with the measured
resource requirement when paging prevents a useful comparison.

Record when the mode constraints take effect. An overlay sourced after
`compile -retime` corrects the final timing report, but cannot correct a
candidate-selection decision already made inside `compile`. Likewise, repair
after candidate selection does not measure the repaired candidates against
each other. Inspect the selection log before interpreting a rollback as a
functional-mode retiming failure. Check selectors at the actual application
stage: a mapped Q/QN pin or net name need not exist during elaboration.

Boson's elaborated view can expose register cells before their mapped pins
exist. Resolve an explicit list of reviewed mode-register names at that stage;
a wildcard that finds three cells after optimization can find many more before
optimization. Deferred literal Q/QN selectors can carry their respective
constants into compile. Verify their binding after mapping, including polarity.
Check the installed version's handling of optional pins: versions affected by
[the deferred `-quiet` issue](https://github.com/partcleda/boson/issues/14374)
can retain a nonexistent alternate output as an unresolved strict-STA target.
For those versions, replace the constraints after mapping with the identical
base SDC and checked existing mode pins before repair and final STA. In Boson,
`remove_all` clears the SDC; reapply the complete timing contract immediately.
Verify this sequence on a small clock-mux example and by saved-netlist replay.

When testing an opt-in engine pass without an internal candidate comparison,
run the control and candidate through the same corrected constraints and repair
sequence, then compare their final reports. Include TNS and endpoint counts:
retiming can improve WNS while adding violating register endpoints. Preserve
the rejected points and state the area/hold tradeoff when choosing the winner.

For a WNS-focused pass with an internal acceptance guard, verify that comparison runs
under the corrected mode and includes the same compile repair in both arms.
A predicted stage-depth reduction is not acceptance evidence. Require a measured
WNS benefit, and retain the original on worse or tied WNS, failed timing, lost
coverage, or a failed trial. Exercise rejection as well as acceptance; check that
rollback restores the netlist, constraints, and provenance. Report any accepted
TNS or area tradeoff explicitly. Repairs invoked after `compile` remain outside
its guard and still require a matched final comparison.

Cross-check clock queries against STA. If `all_registers -clock` suddenly
returns empty after cell edits while timing still reports paths on that clock,
save the netlist and replay the same SDC and mode in a fresh session. Compare
clock coverage, representative paths and setup/hold metrics. Preserve live
provenance before replay, since reading a netlist does not restore it. A query
disagreement needs a small engine reproducer; it does not justify adding false
paths or accepting an empty timing report as closure.

## Investigate surviving synthesis failures

Use [boson-datapath-audit](../../boson-datapath-audit/SKILL.md) to collect timing
and cell stories in the live compile session. Check coverage and connectivity
before attributing a deep path to an arithmetic operator or rewrite pass.
Separate long arithmetic chains, pipeline placement, and high-fanout control
distribution; each needs a different engine change.

Run one hypothesis at a time: a controlled pass ablation or a minimal reproducer
with comparable interfaces can distinguish lowering, sharing, mapping,
retiming, and repair failures. Keep a candidate ledger with recipe, identity,
setup/hold WNS and TNS, area, cell count, elapsed time, memory, path changes and
validation status. Stop a sweep when its hypothesis is resolved; choose the
next experiment from the measured path rather than escalating every knob.

For engine retiming, preserve latency, enable behavior and reset/initial-state
semantics. Verify a focused equivalence test and directed simulation before a
full-design QoR confirmation; state whether the evidence is bounded or proven.
File confirmed engine issues with reproducer, expected versus actual behavior,
source/binary identity, timing contract, and supporting reports. Search existing
issues first. A local patch or pushed branch is not a fix on main.

When profiling SDC, measure Tcl parsing/binding separately from STA exception
construction and report generation. Compare the same netlist and constraints,
record host load and cache state, and avoid summing nested trace spans.
