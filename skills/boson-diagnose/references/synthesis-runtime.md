# Diagnose synthesis runtime

Find the expensive production stage before changing an effort or a timeout.
Keep the original command, binary revision, RTL, libraries and constraints.
Follow the user's execution and resource limits for every run.

## Locate the cost

Enable `synth_profile` and `timing_profile` before the original compile and
retain its complete log. Read the caller too: a benchmark timeout may cover
cold compilation, warm repetitions, netlist writing and external scoring.
Distinguish its budget from the time for one `compile`.

Track the last completed stage and the advancing `worked` counters. A walk's
printed time can be the interval since its preceding progress message; use
the enclosing stage's completed total when attributing runtime. Its work
counter can count candidate checks rather than every graph node.

Account separately for structure-library calibration, word-level passes,
lowering, AIG optimization, mapping and timing repair. A warmup using a small
adder does not cover widths or operand shapes a larger design prices on demand.
The library's fill receipt reports the tables, real-flow measurements and
timing runs it performed. Concurrent compiles can wait on the same cache lock;
attribute that wait once instead of calling it a second expensive algorithm.

Check warnings before interpreting profiles. A licensing failure can leave
default arithmetic architectures and skip timing repair. Such a run locates
costs in that incomplete flow; it cannot establish the original flow's total
or the effect of removing a stage. Resolve the failure within the user's
authorized environment and repeat the affected comparison.

## Explain the circuit's cost

Compare elaborated nodes, AIG ANDs and depth, arithmetic widths and shapes,
and final mapped cells. Similar final cell counts can conceal very different
depth and reconvergence. Use a design near the same instance count with the
same binary, library, constraints, thread budget and cache state. If only a
replicated synthetic comparison is available, identify it as such.

For FRAIG, read proved merges, undecided checks, wasted conflicts and capped
calls. A conflict limit bounds each SAT call, not the whole sweep. For `dc2`,
read its individual rewrite/refactor stages and their internal cut, search,
replacement and level-update times. Many zero-cost substitutions can spend
most of their time maintaining reverse levels and fanouts, even when finding
replacement candidates is cheap. Use a short CPU profile or stack sample to
connect the dominant time to the production function.

## Confirm a proposed cause

When an ablation is warranted, change only the suspected stage and retain the
remaining schedule, including context-derived arguments. Confirm the same
AIG hash at the seam before the schedules diverge. Keep the selector and its
calibration active in both arms.

Complete both arms through netlist writing. Record downstream stage times:
removing FRAIG can make `dc2` and timing repair more expensive, so time saved
inside the removed stage is not the end-to-end result. A concurrent pair
establishes mechanism, not a stable speed ratio; use repeated, interleaved
rounds when the decision depends on that ratio.

Keep failed and incomplete runs distinct from completed results. State which
timeout was reproduced and which host or runner differences remain untested.

Coverage: `runtime_stage_identified`, `completed_arms`,
`matching_input_aig`, `cold_calibration_accounted`, `matched_cell_comparison`.
