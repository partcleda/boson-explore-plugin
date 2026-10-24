---
name: boson-datapath-audit
description: Use when the question is what boson built for the arithmetic on a critical path — "did it pick Han-Carlson or ripple for this adder", "is the multiplier's final adder log-depth", "did a logic rewrite undo the datapath architecture", "why is this adder path so deep". Compiles with -provenance and prints, per adder/subtractor/comparator on the worst paths, the architecture boson selected, the mapped cells it puts on each path against that architecture's depth, and the share of its cells each logic-optimization pass (dc2, dretime, prefix_scan) rewrote.
---

# Datapath architecture audit

Boson's datapath selector chooses an architecture per arithmetic operator
(ripple, carry-select, Sklansky, Brent-Kung, Han-Carlson, Kogge-Stone, ...).
Logic optimization then runs over the whole AIG, and a level-preserving rewrite
such as `dc2 -l` may re-serialize an adder that sits off the AIG's deepest
level. The selector's choice and the netlist's shape can therefore disagree.
This skill measures both on the paths that matter.

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
source <plugin>/skills/boson-datapath-audit/scripts/collect.tcl
```

This writes `prov_summary.txt` (passes that ran, netlist edits by pass),
`prov_paths.json` (`report_provenance -json` for every cell on the sampled
paths) and `timing.json` (native `report_timing -format json`).

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

## Audit

```sh
python3 <plugin>/skills/boson-datapath-audit/scripts/datapath_audit.py audit_synth [--json audit.json] [--coverage-json coverage.json] [--all-blocks] [--stages N]
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
- **ideal**: ceil(log2 w) + 2, a rough clean depth for a log-depth
  architecture. It is blank for comparators, whose width is the 1-bit result.
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
`boson-rtl-timing-closure`) maps registers and named nets, but often leaves
arithmetic unmapped. Measure provenance coverage on this sample instead of assuming a fixed
coverage percentage. Retain both forms of evidence.

For context-dependent failures, compile the implicated submodule with a
comparable interface constraint and inspect stage depths. A good isolated
result does not prove full-chip timing, but distinguishes a local lowering
problem from flattening, sharing or protection-boundary interactions. Do not
raise repair effort until the surviving structural chain is understood.
