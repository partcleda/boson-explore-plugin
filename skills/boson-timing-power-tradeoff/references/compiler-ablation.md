# Paired compiler-pass measurements

A request such as “measure this corpus with dc2 disabled” needs a paired
compiler experiment with unchanged RTL, SDC, libraries, effort and physical
flow. The clock/RTL parameter sweep is not a substitute for this comparison.

## Define the intervention

Read the compiler's actual schedule before choosing a control. A supplied
`-abc` script can also alter controller eligibility, mapping defaults, or
retry behavior. Verify that a setting changes only the intended pass; if
there is no suitable setting, use a small diagnostic source patch on an
isolated branch and preserve its diff.

For dc2, check both `dc2` and `&dc2`, including calls made during calibration
and controller retries. A no-op should bypass the pass's protection wrapper
too: cutting and stitching an AIG can itself change representation. Keep
execution evidence that the disabled command was skipped. Do not change
other rewriting, mapping, timing repair, effort or optimization budgets to
make the result favorable.

Distinguish two questions:

- **Full-flow ablation:** the pass is disabled throughout compilation,
  including structure characterization. This measures the resulting product
  flow and may change selector rankings as well as gate rewriting.
- **Post-selection ablation:** preserve identical characterized tables and
  selected structures, then disable the downstream pass. This measures a
  narrower intervention and needs explicit instrumentation to establish
  that selection remained identical.

Do not interpret the first as proof that the selected structure alone was
destroyed by the pass. Use separate caches when characterization differs.

## Execution and evidence

Build both arms from the same recorded base. Record fetched main, each
working source revision, actual binary source and binary hash. A binary
named `latest` is insufficient. Save input, library and constraint hashes,
backend, effort, placement stage, CPU/GPU allocation and cache condition.

Use the environment's scheduler and resource rules. Review existing jobs
before adding work. Batch compatible short cases sequentially, keep
concurrency bounded, and size requests from measured peaks. Keep each pair
on the same host and allocation; preserve per-case failures and resume
completed cases without silently overwriting them. Distinguish cold-start
runtime from subsequent warm-cache measurements.

Compile with `-provenance` when the question includes where timing changed.
In the same session, save `report_qor`, `report_area`, the final netlist,
native JSON timing paths, and provenance for cells on those paths. Follow
the [native traceback guide](../../boson-rtl-timing-closure/references/rtl-traceback.md)
for schema validation, incomplete timing, unconstrained paths and source
match limits. Keep warnings attached to their result. Reports from a fresh
netlist-only session can lose compiler provenance and black-box semantics.

Report design-wide WNS/TNS and area, plus endpoint changes and representative
path details. Label unplaced synthesis, placed timing and routed signoff
separately. A changed worst endpoint can hide a different limiting cone;
compare targeted paths as well as the new global worst when attributing a
cause. A bounded top-path sample is not the entire violating population.

Keep QoR completion and functional validation as separate fields. Skipping
an equivalence-preserving optimization does not itself constitute an RTL
equivalence proof of the final netlist. Report failures, timeouts and
unverified cases alongside successful measurements.
