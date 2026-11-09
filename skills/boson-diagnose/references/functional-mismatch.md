# Trace a functional mismatch

Use this method when equivalence fails, or when a proof cannot finish after
state or graph structure changes. Retain the original failure and distinguish
an actual counterexample from a timeout, resource failure, or missing state
correspondence. A completed bounded check is not an unbounded proof.

## Freeze the failing pair

Record compiler and verifier revisions, binary hashes, RTL and parameters,
constraints, libraries, mapped netlist, reset assumptions, tool versions,
budgets, and the original verdict. Preserve all observed outputs, including
counts, intermediate flags, payload defaults and next-state behavior. A smaller
fixture is useful only if it retains the same failure.

Record word-level snapshots with `synth_graph_snapshot_dir`. Reproduce the
failure before changing the optimizer. Keep the reference and candidate under
the same input and state contract; do not impose a one-hot or reset invariant
merely because it makes the candidate pass.

## Follow the first incorrect value

For a real counterexample, replay its inputs and current state on the reference
and mapped candidate. Record the exact output bits that disagree. If it is a
register-cut counterexample, distinguish arbitrary cut state from a reachable
clocked trace; retain any unproved reachability obligation.

Replay that assignment through successive word graphs with the compiler's
existing evaluator or regression harness. Compare signal identities and widths,
not node numbers across snapshots. A custom evaluator must preserve width,
signedness, slicing, overflow and undefined-bit semantics, and agree with the
reference and mapped endpoints before its intermediate values count as evidence.
Find the first adjacent stages where a previously correct output becomes wrong.

Trace the changed cone and all its shared consumers. For care-condition
rewrites, check that the condition is valid at every affected live use. A node
can still exist in storage after it becomes unreachable; a worklist revisit of
an unused mux must not apply its arm condition to logic shared with live outputs.
Test both the original failing fixture and a small shared-consumer example.

A pass that reports zero accepted rewrites can still normalize wiring or remove
aliases. Compare the actual graph before and after a refusal. If normalization
changes downstream mapping, trace the first affected gates and timing path;
restore the graph on refusal while preserving any independently accepted work.
Add a regression that checks the refused graph as well as its functional outputs.

## Distinguish missing state from a miscompile

When RTL registers disappear from the mapped netlist, inspect their complete
output and retained-state fanout. Do not substitute constants or inferred state
relations without proof.

A possible strong check pairs every mapped register with its RTL counterpart,
leaves unmatched RTL current-state bits arbitrary, and proves every original
output and every paired next-state function for all inputs and cut-state values.
It must preserve clock, polarity, asynchronous-control and initialization
obligations. A claimed reset-based sequential proof still needs the relation's
reset base. Proving outputs alone is insufficient; omitted next-state errors
can become visible later. An overapproximation counterexample need not be a
reachable miscompile, while an incomplete check remains unverified.

Use the existing proof engine and its complete obligation accounting. Test
that unused state can prove and that changing either an output or a retained
next-state function fails. Test undefined values separately where the engine's
refinement contract allows them. Never convert a timeout into a proof, enlarge
a gate tolerance, or assume a state invariant to close the report.

## Close the diagnosis

Name the first incorrect stage or unresolved proof obligation, exact affected
bits and consumers, the regression that failed before the fix, and fresh
results after it. Remeasure the changed compiler under the original settings.
Reuse prior proof evidence only when all proof inputs and assumptions match,
with hashes binding the new compile to the audited donor. Keep historical
snapshots labeled with the revision that produced them.

Record skill feedback using these coverage keys:

```sh
python3 $F coverage verdict_class=<counterexample|unverified> replay_reproduces=<yes|no|not_applicable> first_bad_stage=<name|unresolved|not_applicable> shared_consumers_checked=<yes|no|not_applicable> negative_controls=<n> fresh_proof=<yes|no>
```
