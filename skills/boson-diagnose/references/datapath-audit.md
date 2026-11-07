# Datapath architecture audit

Boson's datapath selector chooses an architecture per arithmetic operator
(ripple, carry-select, Sklansky, Brent-Kung, Han-Carlson, Kogge-Stone, ...).
Logic optimization then runs over the whole AIG, and a level-preserving rewrite
such as `dc2 -l` may re-serialize an adder that sits off the AIG's deepest
level. The selector's choice and the netlist's shape can therefore disagree.
This method measures both on the paths that matter.

Do not answer this question by counting MAJ/AOI/OAI chains in the netlist.
The mapper uses full-adder carry cells as generic majority gates. Compressor
trees and carry chains share one pipeline stage. Rewrites also merge an adder
into the logic around it, so a chain count cannot tell where the adder starts
and ends. Provenance helps locate candidate operators, but inferred or shared attribution must be checked against connectivity.

## Collect

1. Compile with `-provenance` added to the flow's usual command (same SDC,
   effort and options; provenance does not change QoR).
2. After the stage you want to judge (synthesis, or after placement/repair),
   source the collector:

```tcl
compile -f design.f -top top -sdc top.sdc -provenance
set audit_dir audit_synth      ;# default: datapath_audit
set audit_paths 200            ;# worst paths sampled, default 200
source <plugin>/skills/boson-diagnose/scripts/datapath/collect.tcl
```

This writes `prov_summary.txt` (passes that ran, netlist edits by pass),
`prov_paths.json` (`report_provenance -json` for every cell on the sampled
paths), `timing.json` (native `report_timing -format json`), and
`path_trace.txt` / `path_trace.json` (native path provenance with stage delays
and RTL origins). The text trace ranks delay by source; a `~` origin is
propagated attribution, not an exact match. Inspect it before ranking arithmetic.

The collector requires timing-point attributes and path provenance support.
It writes timing first so an unsupported provenance API leaves diagnostic
evidence. A zero-cell collection or a failed command means the audit failed;
a timing report or provenance summary alone is not a completed netlist audit.
Cell stories use literal names from timing points, avoiding hierarchical glob
queries that can silently drop nested cells or names containing brackets.

Collect in the live compile session: a saved session can restore the netlist
without detailed provenance. After loading a checkpoint, run `update_timing`
and check completion. To join archived cell stories to restored timing, verify
the checkpoint identity and ordered data-pin paths first; native JSON also
contains net rows and may omit the launch clock pin. Record source, binary,
constraints and flow identities beside the reports.

When runtime is part of the question, separate elaboration, probe mapping,
final mapping and repair using the build's stage profiler. `-fast` can still
run many repair rounds. Record cold/warm characterization caches and thread
counts; do not attribute a cache speedup to a netlist setting or sum nested
profile spans as independent work.

## Auditing the datapath compiler pass by pass

First establish which optimizer ran. Inspect `report_app_var datapath_compiler`
and the effort's compile settings: an `auto` default can select different
optimizers by effort. Set `datapath_compiler false` for the legacy reference
and `true` for the `datapath/` candidate before `compile -effort medium`.
Keep the command on that recipe; other compile modes may refuse this setting.
The `DPC-002` messages name the passes that actually ran.

Do not assume `synth_graph_snapshot_dir` captures those passes. Check the
snapshot index against the compiler's enabled pass list, including repeated
passes. Some builds record only the graph stamped after the datapath
compiler finishes. Likewise, `report_elaborated -full` may read the original
elaboration tape even after `dp_<pass>` commands changed the working design.
An unchanged report is then missing observation, not evidence of a no-op.

When the shell lacks intermediate snapshots, use the matching checkout's
Rust API. `compile_datapath` with `DatapathOptSettings.take_snapshots = true`
returns a tape after each enabled pass. Alternatively, run the enabled pass
list over `Design` and dump `design.to_tape()` after each pass with
`boson_elab_tape::dump_tape_text`. Add a sequence number to every filename:
pass names can repeat. Retain the initial tape, complete intermediate tapes,
operator widths and fanins, live-node counts by kind, and the final tape.
Validate every tape. The runner must match the checkout and API under test;
record the commit, dirty diff, binary identity, seed, constraints, library
and enabled pass order beside its output.

When a transform changes operator widths, check the eligibility rules of
later proofs on the resulting representation. A word proof can silently stop
applying after a packed field becomes a scalar. Reduce the case to both
representations, preserve a live-dependency negative case and shared outputs,
and check equivalence as well as whether the false dependency disappeared.

Before moving a pass, inspect the representation available at its current
position and the first stage that exposes the missing fields or operators.
Compare register widths, field counts and operand shapes at those stages.
A diagnostic rerun at the end does not establish that a second invocation
is needed. Compare that exact final placement with and without the earlier
invocation, keeping sharing and cleanup at the same positions in the control.
Test the placement against the same real endpoint, record work spent inside
the pass, and require fresh post-repair timing before promoting it.

An operator in the frozen word graph may have been formed by the shared
selector after the native passes finished. Find its first appearance before
editing its apparent producer. After a trial, verify the predicted operand,
width or guard change in the saved graph; an unchanged target is a failed
intervention even when unrelated final metrics move.

For every generated RTL case, inspect the stages that change the implicated
cone, then compile it through mapping and collect timing and provenance as
above. Include negative controls for width extension, signed operands,
overflow, shared producers and out-of-range shifts. Test equivalence across
the changed pass; fewer word-level nodes alone does not establish a gain in
mapped area or timing. A pass ablation must use the same RTL and constraints
and start from a fresh design.

If an experimental word-level timing model is used, label its delays and
areas as estimates and identify its source tree and library. Keep its pass
decisions distinct from those of the production compiler. Match input and
output delays as well as the clock period before comparing against mapped
STA. Snapshot instrumentation must not change optimization decisions: use a
separate observer or verify its final graph and estimates against a run
without observation. Flag disagreements for model calibration instead of
treating estimated improvements as measured timing gains.

## Comparing word-level graphs

A word-level graph can contain a cycle even when its bit-level circuit is
acyclic: a wide routing or select node can read a disjoint slice of its own
result. A whole-node topological walk can therefore loop or exhaust memory
on a valid graph. Track visited states and report a cycle explicitly. For
structural comparison, resolve the requested output bits through edge ranges,
Gather maps, concatenations and extensions; do not replace an unresolved
cycle with a constant or an unrelated symbolic input. Compare the implicated
cones first, with measured memory, before expanding to the whole design.

When the native compiler refuses a word cycle, compare its normalization
stage with the legacy bit-lowering scheduler. The latter can build ready bits
and carries before the rest of a word is ready. A legacy refusal mentioning a
whole-only multiply or variable shift does not establish a real bit cycle.
Build a small independent acyclic reference, enumerate its operator truth table
to find actual bit dependencies, and check arithmetic prefixes, correlated shift
amounts, replicated or independent lane guards, and mutually exclusive mux
feedback. Keep register values unconstrained and include genuine-loop refusal
cases. Free cycle-cut inputs are useful in a proof, but substitution is valid
only after proving that no output can depend on any of their values.

Register names can change when aliases are retained differently. Establish
register identity from its RTL declaration, instance and bit range, checking
that the match is unique and that reset and enable semantics agree. A name
mismatch alone is not a different register. Recheck coverage of every implicated
endpoint after cleanup: a smaller maximum error is not an improvement if the
target lost its alias and disappeared from the comparison. Retain the old
endpoint set and fail the diagnostic when a required match is missing.
Exact structural signatures also
need operand extension, constant routing and commutativity normalization;
unequal signatures do not prove functional inequivalence or explain a timing
regression. Confirm the candidate difference in connectivity and mapped STA.

For an addition with a late one-bit operand, measure that operand's own path
through the carry network. Compare it with the equivalent carry-in form of
the same addition, including overflow and truncation checks. A shorter path
in lowering can be serialized again by AIG optimization or mapping: compare
the stage snapshots and final mapped timing before claiming an improvement.

## Audit

```sh
python3 <plugin>/skills/boson-diagnose/scripts/datapath/datapath_audit.py audit_synth [--json audit.json] [--coverage-json coverage.json] [--all-blocks] [--stages N]
```

```
rtl                                op         w architecture       paths   slack cells/path ideal  rewritten by
FP32ParametricAdder.sv:645         AddTree   28 HanCarlson adder      51   -41.9    5/  2.7     7  dc2 14%
DPUMultiplier_RESIDUAL.sv:262      AddCarry   9 Sklansky adder        88   -41.6   16/ 10.5     6  dc2 69% dretime 14%  <-- deeper than its architecture
FP32ParametricAdder.sv:149         Add       23 HanCarlson adder      10   -41.3   12/ 11.4     7  dc2 39%  <-- deeper than its architecture
```

The audit prints per-path coverage before the arithmetic table. Missing cells,
blocks or timing values are not evidence that logic is absent. `--all-blocks`
includes mux/priority/Boolean logic; the default arithmetic view can miss the
actual bottleneck. JSON rows retain block IDs, full source paths and instances
so repeated instances at the same source line stay separate. A cell is counted
once per block per path, even when its block record is repeated.

Columns:

- **architecture**: the selector's lowering for the block (`report_provenance`
  `blocks[].lowering`). A ripple here is the selector's choice, not a rewrite.
- **cells/path**: max/mean count of technology-mapped cells attributed to the
  block on each sampled path. Repair buffers and clones, registers, and
  buffer/inverter cells are excluded.
- **own**: the most cells on one path that implement this block alone. When
  a rewrite merges a structure into the logic around it, its cells also carry
  the neighbours' blocks and `own` drops toward 0. When the structure is kept
  intact (for example under boson's `synth_preserve_datapath`), `own` is its
  mapped depth and should sit near **ideal**.
- **exact**: the most cells on one path whose provenance matches this block
  exactly. The rest of **cells/path** carries the block only by inference
  (`~` in `report_provenance`: no node of the cell's cone matched, so the label
  is the logic it feeds or is fed by). When cells/path is deep and exact is
  not, the row is marked `deeper only through inferred labels`: the depth
  belongs to whatever sits around the block, not to its architecture.
- **ideal**: ceil(log2 w) + 2, a rough clean depth for a single log-depth
  adder/subtractor. It is blank for comparators, whose width is the 1-bit
  result, and for multipliers and multioperand trees: a final-adder label
  does not describe their complete depth.
- **rewritten by**: the share of attributed path cells listing each AIG
  pass in `aig_passes`. This is reported pass membership, not proof that the
  pass created the measured depth. `&nf` (mapping) is omitted.

## Stage by stage

`--stages N` prints the N worst sampled paths cell by cell (arrival, delay
including the input net, library cell, and the block the cell most belongs
to: an exact match first, then the largest share; `~` marks an inferred
label), then folds consecutive cells of one block into segments with their
total delay. Read where a path's delay goes from the segments, and treat a
segment made only of inferred cells as a pointer to check against the
netlist, not as the block's own depth: a 10-bit subtractor label stretched
over twenty cells usually is the compressor tree and final adder it feeds.

## Reading it

- **The estimated path is much faster, but arithmetic depth looks right**:
  separate structure from electrical delay before changing word-level costs.
  For the same repaired path, collect each cell's input/output pins, both
  transition edges, arc delay, input slew, output load, fanout and wire delay.
  Re-evaluate the exact Liberty arcs at the measured coordinates first;
  resolve any discrepancy before using the replay as evidence. Match timing
  sense, clock edge and conditional arcs, rather than taking the fastest arc
  of the cell. An ideal launch clock uses its constrained clock transition;
  a transition propagated as data on the physical clock net can differ.
  Then evaluate those same arcs at the estimator's reference slew and load.
  Report nominal path delay, electrical excess and estimator error separately.
  Changing load first and slew second is an order-dependent decomposition,
  not two independent effects. This reference-point replay does not show what
  repair could achieve, establish an operator boundary, or justify fitting an
  endpoint-specific correction. Use the matched endpoint, transition and
  setup check throughout: the worst-slack path may differ from the path with
  the latest data arrival. If the remaining gap is electrical, report it as
  downstream sensitivity and continue looking for structural discrepancies.
- **Shared provenance suggests a serial arithmetic dependency**: first inspect
  the selected word graph's actual edges. A mapped cell can inherit an adder
  label while computing part of a comparator or leading-zero counter. Locate
  candidate boundaries by simulating the extracted gate cone with the Liberty
  Boolean functions, including the register's `next_state` and output
  function; register pin names do not establish polarity. Random signatures
  only suggest matches: rare carry boundaries can make different functions
  appear equal. Prove candidate matches against the word expressions with
  SAT, stating any nonzero, reachable-state or mode assumptions. Compare
  cumulative mapped and estimated arrivals only at confirmed boundaries.
  Snapshot numeric identifiers require their epoch; use names and origins to
  follow an operator across snapshots that renumber the graph.
- **Nominal replay is still slower after removing slew/load excess**: identify
  identity buffers by Liberty function, then find their first appearance in
  mapping and repair snapshots. Report their measured and reference-coordinate
  delays separately. Removing those stages from a diagnostic reference is not
  a measured improvement, a new post-repair accuracy result, or proof that the
  estimator has not already charged some buffering cost. Keep the original
  post-repair error visible and avoid counting buffer electrical excess twice.
- **Retiming predicts a large gain but mapped timing barely improves**: report
  input-to-register and register-to-register paths separately. Compare the
  actual stage arrivals, register count and endpoint identities, not just the
  printed estimated stage delay. Check whether the candidate was retained;
  reports after a rejected candidate describe the restored baseline.
  Check timing-model coverage separately from architecture-selection coverage:
  shifts, negation and normalization logic may use depth estimates even when
  the selected adders are all priced. A controlled `datapath_selector_all_ops`
  comparison changes both modeling and selection; isolate those effects
  before recommending it as a retiming fix.
- **Wide arithmetic is absent from selector decisions or survival groups**:
  enable `datapath_selection_trace` and inspect the `unpriced` count. A
  provenance architecture label does not establish that the cost model priced
  the operator or registered its protection. Check the build's table widths
  and extrapolation limit. As a controlled diagnostic, compare
  `datapath_selection_exact_widths true` with the normal setting; missing
  prices can affect both retiming cuts and arithmetic preservation. Use
  separate fresh caches or identical cache snapshots: exact-width probes can
  persist extra tables and change subsequent control runs.
- **Architecture is ripple** and the block is critical: this is a selector
  decision. Check `adder_topology` / `adder_arrival_aware` in `report_app_var`
  before blaming a rewrite.
- **Log-depth architecture, cells/path well above ideal, mostly rewritten by
  `dc2`**: investigate a possible rewrite regression. Pass membership and
  AIG level do not establish causation; levels are absolute and may include
  upstream logic. Verify the deepest cells against netlist fanins, then use
  before/after stage snapshots or a controlled pass ablation. Keep the
  constraints, effort, libraries and thread count fixed.
- **Cells/path near ideal, low rewritten share**: the structure survived as
  selected, subject to attribution and coverage checks.
- Block attribution is shared. After a rewrite merges an adder with nearby
  logic, cells carry several blocks, so cells/path is an upper bound. Use it
  to rank blocks and not as an exact gate count. Some engine versions infer
  labels by propagation into neighboring cones and do not expose that
  confidence in block stories. If a small arbiter comparison is attributed
  a long chain whose fanins are decoder table data, report the conflict and
  follow connectivity; do not call it a comparator carry chain.
- Compare runs only with the same SDC, effort and path sample. At a tight
  period, repair moves the worst paths between blocks from run to run.

The native `report_timing -format rtl|json` traceback (see
`boson-rtl-optimize`, meet-timing mode) maps registers and named nets, but often leaves
arithmetic unmapped. Measure provenance coverage on this sample instead of assuming a fixed
coverage percentage. Retain both forms of evidence.

For context-dependent failures, compile the implicated submodule with a
comparable interface constraint and inspect stage depths. A good isolated
result does not prove full-chip timing, but distinguishes a local lowering
problem from flattening, sharing or protection-boundary interactions. Do not
raise repair effort until the surviving structural chain is understood.

## Skill feedback

Fill in the skill's feedback section (see SKILL.md). Coverage for this method:

```sh
python3 $F coverage paths=<n> path_cells_matched=<matched>/<candidates> arithmetic_attributed=<a>/<mapped>
```
