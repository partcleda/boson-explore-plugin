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

Path limits can apply separately to each clock group. Rank the complete
reported sample by constrained slack before choosing a global worst path;
the first path in the file need not be the worst. The audit's `--stages N`
does this ranking and excludes unconstrained paths. Preserve report order
when slacks tie, and retain the endpoint, transition, arrival and setup
requirement: a WNS difference can come from the endpoint check even when
the data arrival barely changes.

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

First establish which optimizer ran. On builds that expose
`datapath_compiler`, its default is `false`: a plain medium compile uses the
legacy word-level passes. Set `datapath_compiler true` before the plain
`compile -effort medium` command to investigate the `datapath/` crate. Keep
the command on that recipe; other compile modes may refuse this setting.
The `DPC-002` messages name the passes that actually ran.

Do not assume `synth_graph_snapshot_dir` captures those passes. Check the
snapshot index against the compiler's enabled pass list, including repeated
passes. Some builds record only the graph stamped after the datapath
compiler finishes. Likewise, `report_elaborated -full` may read the original
elaboration tape even after `dp_<pass>` commands changed the working design.
An unchanged report is then missing observation, not evidence of a no-op.

When snapshots are allowed but the shell lacks intermediate snapshots, use the matching checkout's
Rust API. `compile_datapath` with `DatapathOptSettings.take_snapshots = true`
returns a tape after each enabled pass. Alternatively, run the enabled pass
list over `Design` and dump `design.to_tape()` after each pass with
`boson_elab_tape::dump_tape_text`. Add a sequence number to every filename:
pass names can repeat. Retain the initial tape, complete intermediate tapes,
operator widths and fanins, live-node counts by kind, and the final tape.
Validate every tape. The runner must match the checkout and API under test;
record the commit, dirty diff, binary identity, seed, constraints, library
and enabled pass order beside its output.

When snapshots must remain off, keep that constraint in diagnostic runs too.
Use timing, provenance, pass counters and a matching source checkout for
targeted read-only model inspection. For a register's modeled capture path,
rank arrivals at its capture inputs, including an enable or other control,
rather than at its Q output. Preserve clock-gating enable endpoints and
their setup checks in mapped comparisons: data-pin paths alone can miss the
worst path. Trace routed bit identities through slices, concatenations and
extensions, and distinguish
ordinary tree rebalancing from duplication across a shared producer. A
local delay improvement need not improve a timed endpoint. Confirm both the
retained graph and repaired STA before keeping a rewrite.

A source-level harness must reproduce raw elaboration, production pass settings
and order, the run's characterization library, and every clock and port
constraint. A unit-test fixture library is not evidence of the production
model's decision. Compare the ordered `DPC-002` pass names and before/after
node counts through the stage under inspection, including repeated passes.
An earlier mismatch means the harness has not reproduced that decision;
resolve it before attributing the production result to the inspected graph.

When a candidate moves the worst path to another block, compare both the
original and new launch/capture pairs in both repaired designs with one timer.
Also compare the worst path over the original output group. A different worst
endpoint alone does not establish that the intended path improved. Keep an
absent or unconstrained pair explicit instead of assigning it a zero delay.

Use the model's critical-path reporter for the global estimate. A manual
global ranking needs each capture clock relationship and setup term, not
just the largest data arrival.

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

For archived `synth_graph_snapshot_dir` output, trace recorded node properties
across word-level stages with
`python3 scripts/datapath/snapshot_trace.py <snapshot-dir> --origin 'file.sv:123'`.
Repeat `--origin` for additional locations. The JSON retains stage sequence,
node IDs, kinds, widths, details and origin labels, and emits a row when the
matching properties change or disappear. These are recorded properties, not
an equivalence check; verify connectivity and timing before attributing a gain.

A word-level graph can contain a cycle even when its bit-level circuit is
acyclic: a wide routing or select node can read a disjoint slice of its own
result. A whole-node topological walk can therefore loop or exhaust memory
on a valid graph. Track visited states and report a cycle explicitly. For
structural comparison, resolve the requested output bits through edge ranges,
Gather maps, concatenations and extensions; do not replace an unresolved
cycle with a constant or an unrelated symbolic input. Compare the implicated
cones first, with measured memory, before expanding to the whole design.

Register names can change when aliases are retained differently. Establish
register identity from its RTL declaration, instance and bit range, checking
that the match is unique and that reset and enable semantics agree. A name
mismatch alone is not a different register. Exact structural signatures also
need operand extension, constant routing and commutativity normalization;
unequal signatures do not prove functional inequivalence or explain a timing
regression. Confirm the candidate difference in connectivity and mapped STA.
A provenance block's width alone does not establish word-level register
grouping. Resolve the named state bits to register nodes and inspect their
widths, data operands, clocks, enables and resets before attributing a split
to a pass.

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
