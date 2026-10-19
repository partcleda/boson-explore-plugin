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
and ends. Provenance can.

## Collect

1. Compile with `-provenance` added to the flow's usual command (same SDC,
   effort and options; provenance does not change QoR).
2. After the stage you want to judge (synthesis, or after placement/repair),
   source the collector:

```tcl
compile -f design.f -top top -sdc top.sdc -effort medium -provenance
set audit_dir audit_synth      ;# default: datapath_audit
set audit_paths 200            ;# worst paths sampled, default 200
source <plugin>/skills/boson-datapath-audit/scripts/collect.tcl
```

This writes `prov_summary.txt` (passes that ran, netlist edits by pass),
`prov_paths.json` (`report_provenance -json` for every cell on the sampled
paths) and `timing.json` (native `report_timing -format json`).

## Audit

```sh
python3 <plugin>/skills/boson-datapath-audit/scripts/datapath_audit.py audit_synth [--json audit.json]
```

```
rtl                                op         w architecture       paths   slack cells/path ideal  rewritten by
FP32ParametricAdder.sv:645         AddTree   28 HanCarlson adder      51   -41.9    5/  2.7     7  dc2 14%
DPUMultiplier_RESIDUAL.sv:262      AddCarry   9 Sklansky adder        88   -41.6   16/ 10.5     6  dc2 69% dretime 14%  <-- deeper than its architecture
FP32ParametricAdder.sv:149         Add       23 HanCarlson adder      10   -41.3   12/ 11.4     7  dc2 39%  <-- deeper than its architecture
```

Columns:

- **architecture**: the selector's lowering for the block (`report_provenance`
  `blocks[].lowering`). A ripple here is the selector's choice, not a rewrite.
- **cells/path**: max/mean count of technology-mapped cells attributed to the
  block on each sampled path. Repair buffers and clones are excluded.
- **ideal**: ceil(log2 w) + 2, a rough clean depth for a log-depth
  architecture. It is blank for comparators, whose width is the 1-bit result.
- **rewritten by**: the share of the block's path cells that each AIG pass
  restructured. `&nf` (the mapper) is omitted because it touches every cell.

## Reading it

- **Architecture is ripple** and the block is critical: this is a selector
  decision. Check `adder_topology` / `adder_arrival_aware` in `report_app_var`
  before blaming a rewrite.
- **Log-depth architecture, cells/path well above ideal, mostly rewritten by
  `dc2`**: the rewrite re-serialized it. Confirm with a single
  `report_provenance <cell>` on the deepest cells: `aig_level` jumps of tens of
  levels inside one small block are the signature. Report it to boson with
  this table. Forcing `adder_topology` globally is no fix: it moves every
  adder at once and usually loses badly.
- **Cells/path near ideal, low rewritten share**: the structure survived as
  selected.
- Block attribution is shared. After a rewrite merges an adder with nearby
  logic, cells carry several blocks, so cells/path is an upper bound. Use it
  to rank blocks and not as an exact gate count.
- Compare runs only with the same SDC, effort and path sample. At a tight
  period, repair moves the worst paths between blocks from run to run.

The native `report_timing -format rtl|json` traceback (see
`boson-rtl-timing-closure`) maps registers and named nets, but often leaves
arithmetic unmapped. Provenance traces about 99% of cells to an RTL line, so
use it for datapath questions.
