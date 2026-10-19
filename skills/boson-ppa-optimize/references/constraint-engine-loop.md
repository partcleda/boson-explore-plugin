# Constraint and synthesis-engine iteration

Use this workflow when a design already has a flow, its SDC is suspect, or
the user wants synthesis fixes while preserving RTL. A passing timing number
is meaningful only for the intended operating mode and checked endpoints.

## Establish the timing contract

Record the source list and parameters, RTL and Boson revisions (including
local patches), binary hash, library/corner alias, SDC and sourced files,
thread count, and physical stage. Preserve the original artifacts. Keep
licensed library names and contents out of published issues and skill files.

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
