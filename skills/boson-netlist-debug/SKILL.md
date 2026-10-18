---
name: boson-netlist-debug
description: Use when a customer wants to know what went wrong in a boson run of THEIR design, or wants to send partcl the evidence — "why is my netlist bad", "what did boson do wrong", "why did timing get worse after layout", "debug this timing report / QoR", "is this a boson problem or my constraints", "prepare a debug bundle for partcl", "send partcl our results without leaking IP". Reads the synthesized netlist, timing / QoR / check_timing reports, SDC, boson log and boson's decision journal; finds the bad choices boson made and the issues the netlist has now; and builds an anonymized, leak-checked report bundle the customer sends back to partcl.
---

# Netlist debug with boson

This runs on the customer's machine, against their design. The output
leaves their building, so the privacy rules come first and are not
negotiable.

## Rules

1. **Nothing customer-identifiable goes into the bundle.** No design,
   module, instance, net, port or clock names; no file paths, user names,
   hostnames, emails or dates; no RTL; no Liberty file or library name.
   The library may be described only by family / node ("a 7 nm library").
   `anonymize.py` enforces this for the files; you enforce it for what you
   write.
2. **Write REPORT.md from the anonymized copies only** (`<work>/anon/`,
   `<work>/digests/`). Name objects by their tokens (`u3/r12_reg[4]`,
   `clk0`, `add_o2`). To cite something you found in the raw files, convert
   it first: `anonymize.py --map name_map.json --encode '<raw name>'`.
   Never paste a raw name into REPORT.md or into a summary meant for
   partcl, even in a code block.
3. **`name_map.json` stays local.** It decodes every token. It is created
   with mode 600, outside the bundle; the scripts refuse to put it inside.
   Tell the customer to keep it: partcl's follow-up questions will use the
   tokens, and `anonymize.py --decode` turns them back.
4. **Run the leak check and believe it.** `make_bundle.py` runs
   `anonymize.py --check` on the directory and the tarball and writes no
   tarball if it fails. Fix the cause (add `--literal` for a project
   codename, `--lib-tag` for a library prefix it missed, reword REPORT.md);
   never hand-edit the check away. Read its "generic words" and WARN lines
   too: generic words are allowed only as prose, never as object names.
5. **The customer sees everything before it goes.** Show them MANIFEST.md
   (the file list) and REPORT.md in full, say whether the anonymized
   netlist is included and what that reveals, and let them decide.
6. **Never upload, email or attach anything yourself.** No
   `report_feedback`, no gh, no curl. The customer sends the tarball.
7. **Separate fact from inference.** Every finding cites journal seq
   numbers, path ids and numbers from the files. "Boson chose ripple at
   seq 412, the path through it fails by 84 ps" is a finding; "boson's
   adder selection is weak" is not.

## Inputs

Ask for, or discover with `--run-dir <dir>` (it prints what it found;
confirm with the customer):

| input | how it is produced in boson | needed for |
|---|---|---|
| decision journal | `set_app_var decision_log_file run/decisions.jsonl` before `compile` | what boson decided and why (the core) |
| timing JSON | `report_timing -max_paths 50 -format json -file run/timing.json` | path structure, numbers |
| timing text | `report_timing -max_paths 50 > run/timing.rpt` | cell types per stage, clocks, skew |
| QoR | `report_qor > run/qor.rpt` | design-wide WNS/TNS/violators |
| check_timing | `check_timing > run/check_timing.rpt` | unconstrained / missing-delay issues |
| netlist | `write_verilog run/netlist.v` | structure, fanout, buffering |
| SDC | the input SDC and `write_sdc run/out.sdc` | constraints review |
| boson log | stdout of the run | messages, repair summaries, version |
| Liberty (optional) | the `.lib` files they read | pin directions / area, read locally only |
| RTL (optional) | their sources | only to harvest names so they get scrubbed |

If they have boson but no journal yet, have them rerun the compile with it
on (their own compile line and effort, unchanged):

```tcl
set_app_var decision_log_file run/decisions.jsonl
compile ...                      ;# their usual compile
update_timing
report_qor > run/qor.rpt
report_timing -max_paths 50 -format json -file run/timing.json
report_timing -max_paths 50 > run/timing.rpt
check_timing > run/check_timing.rpt
write_verilog run/netlist.v
write_sdc run/out.sdc
```

Confirm the spellings in the installed boson before handing this over:
`report_app_var decision_log_file`, `help report_timing`, `help report_timing json`,
`help check_timing`. An older boson may lack the journal or the JSON format;
then work from what exists and say what was missing. For hold problems also
collect `report_timing -delay_type min -max_paths 20 -format json -file run/hold.json`.
A killed run still leaves a journal up to the point it reached (no
`compile_end` record) — that is useful, not broken.

## Workflow

```sh
S=skills/boson-netlist-debug/scripts
ARGS="--map name_map.json --work boson-debug-work --run-dir run \
      [--rtl src/*.sv] [--liberty libs/*.lib] [--literal <company>] [--literal <codename>] --pdk-node '7 nm'"
python3 $S/make_bundle.py $ARGS                        # 1. anonymize + digests -> boson-debug-work/
# 2. read boson-debug-work/digests/*.md and anon/*; analyse (playbook below); write REPORT.md
python3 $S/make_bundle.py $ARGS --report REPORT.md     # 3. bundle + leak check -> boson-debug-bundle.tar.gz
```

The anonymized netlist is left out unless the customer opts in with
`--include-netlist`. It is the most useful thing partcl can get (every cell
and connection, so the problem can be reproduced structurally) and also the
most revealing (the design's architecture, under tokens). Explain that
trade-off and let them choose. A large journal is cut to
`--journal-max-lines` (default 200k): structural records and messages stay,
decisions are kept by relevance, and `journal/truncation.json` says what was
dropped.

Ask the customer for company and project/codename strings to pass as
`--literal` (they appear in paths, comments and names). Their user name and
hostname are added automatically. The scripts are also usable one by one:
`anonymize.py`, `journal_digest.py`, `timing_digest.py`, `netlist_stats.py`
(each has `--help`; run the digests on the anonymized copies). Read
[the journal schema](references/journal-schema.md) before interpreting
records and [the privacy rules](references/privacy.md) before promising the
customer anything about what is kept.

The digests are a starting point. Open `anon/decisions.jsonl` and
`anon/timing_1.*` directly (grep by token) to follow a chain; the journal can
be millions of lines, so grep or stream it, never read it whole.

## Analysis playbook

### 1. Establish the facts first

- From `report_qor`: setup WNS/TNS, hold WNS/TNS, violating endpoints,
  MPW/DRV counts. Path samples are only what `-max_paths` printed; never
  quote a sample as design-wide.
- From the timing JSON: `timing_complete` and `warnings`. Incomplete timing
  is a finding in itself, not a score.
- Period sanity: `timing_digest` prints capture edge − launch edge per
  path. If that differs from the SDC period (e.g. 0.001 ns against a 0.6
  "ns" clock), the SDC time unit was read differently from what the
  customer intended — check `set_units` and the log's "SDC time unit" line
  before analysing anything else; every slack downstream is meaningless.

### 2. Tie each critical path to the decisions that shaped it

For the worst paths (P1.. in the timing digest, ordered by slack):

1. List its objects: launch/capture registers, every cell instance and net
   (the digest's `objects`), plus operator prefixes — cells boson built for
   an operator carry the operator's token as a prefix (`u3/add_o2_gs41`
   belongs to subject `u3/add_o2`).
2. `journal_digest.py` already lists decisions whose subjects hit those
   objects ("Decisions on reported critical paths"). Extend by hand:
   `grep -n '"u3/add_o2' anon/decisions.jsonl`, and the registers'
   `_reg` and `__qn_bsn` forms.
3. Order the hits by seq; that is the decision chain for the path: recipe →
   datapath architecture → mapping → sizing/VT → buffering → repair. Note
   for each its `stage`, `chosen`, rejected alternatives with their metrics,
   `inputs` (the slack/fanout boson believed at the time) and `impact`.
4. Compare what boson believed (`inputs.slack_ns`, alternative metrics) with
   the final path. A large gap means the estimate was wrong at decision time
   — a mis-estimation finding, distinct from a bad trade-off.

### 3. Journal patterns that indicate a bad choice

| pattern in the journal | what it suggests | evidence to cite |
|---|---|---|
| datapath decision chose an area-leaning architecture (ripple, serial, array) whose subject's cells sit on a failing path; a rejected faster alternative had better delay | architecture chosen against timing | seq, chosen vs alternative `delay_ns`/`area_um2`, path id + slack |
| recipe/candidate chose better area with worse WNS (digest: "A rejected alternative was better on timing") while the design fails | recipe selection traded timing for area on a failing design | seq, both candidates' `wns_ns`/`area_um2`, final WNS |
| the same subject sized up, up, down, up (digest "flip-flopping") with net timing gain ≈ 0 | sizing oscillation; area or runtime wasted | seqs, choices chain, summed impact |
| many `sizing/upsize` on one path, WNS unchanged at the next checkpoint | upsizing the wrong stage (load or wire bound, not drive bound) | seqs, checkpoint ΔWNS, slowest stages on the path |
| hold_repair inserted delay where setup margin was small or negative (digest "Hold repair on tight setup") | hold fixing that cost setup | seq, `inputs` setup slack, `impact.wns_ns`, the path's final setup slack |
| setup repair rolled back / "kept the design as it was" (also in the log's repair_timing line) | repair rejected — find why (`why`: hold regression, DRV, no gain) | seq, alternative verdicts and metrics |
| a checkpoint shows WNS/TNS loss or area growth with no WNS gain (stage table) | that stage made QoR worse; look at its decisions | checkpoint seqs, deltas, decisions between them |
| `applied: false` trials whose impact improved WNS/TNS (e.g. a `recipe/judge_candidate` rejected for area budget, a repair round rolled back) | boson declined a fix it had in hand; check whether the rejecting rule (area cap, hold guard, credit) was right | seq, `inputs.verdict`/rule, impact, the threshold it lost on |
| probe decisions that improved timing but nothing equivalent shipped | a what-if found a better answer that was not applied | probe seq, impact, the shipped decision on the same subject |
| buffering decisions on a net that remains slow, or a buffer/inverter chain ≥3 on a critical path | over-buffering / chain instead of sizing the driver | seq, chain from netlist_stats, the stages' delays |
| a high-fanout net on a critical path with no buffering decision and a non-buffer or weak driver (netlist_stats "unbuffered" / "weak driver") | high-fanout net left unbuffered | net token, fanout, driver cell, path id |
| clock_gating / banking decisions on registers that start or end failing paths | CG or MBFF banking hurt timing (gated-clock latency, merged flop's worse D/CK→Q) | seq, register tokens, skew/latency on the path |
| sequential decisions removing or merging a register (constant, duplicate, unloaded) | register removed/merged — confirm it was truly redundant | seq, `reason`, the register token |
| constraints-domain decisions / SDC-* messages showing an ignored, unsupported or partially applied command | a constraint was dropped or misread | message id + text, seq, the SDC line |
| VT swaps to a faster VT that did not change the path, or leakage-driven swaps onto failing paths | VT used against timing | seqs, VT mix on the path |
| a cell type dominates the slowest stages (e.g. a weak `xp33` complex gate or OR5 chain) | mapping chose slow cells for a timing-critical cone | path slowest stages, cell histogram on the path |

Domains or actions not listed here: read the `reason`, `alternatives` and
`impact`, and apply the same tests — did the choice move the metric it
claimed, and did it touch a failing object?

### 4. Current issues in the netlist (independent of the journal)

From the digests: setup and hold violations (count, worst, endpoint
groups — a whole bus failing is one issue, not 32), DRV and MPW counts,
unconstrained endpoints and missing I/O delays (check_timing), undriven /
multi-driven nets, unconnected input pins, dangling outputs, tie cells on
functional nets, long buffer/inverter chains, back-to-back inverter pairs,
unbuffered high-fanout nets, weak drivers on large loads, clock skew on the
failing paths, VT mix, clock-class cells used in data logic (e.g. `CKND2`
clock NAND2s on data nets) and data buffers on the clock. On a placed run the
timing digest gives every driver->load wire length from the report's
Location column: a long wire behind a weak driver, or a chain of buffers
each driving tens of um, is the placement-side explanation of a slow path.

### 5. Boson's fault, or the design / constraints?

Before blaming boson, check these and say which apply:

- **Logic depth vs period.** stages × a typical stage delay of this library
  (take the median stage delay on the reported paths) against the period.
  If even good cells cannot fit, the RTL needs restructuring or pipelining —
  that is `boson-rtl-timing-closure`'s job, not a boson defect.
- **Constraints.** Missing `set_input_delay`/`set_output_delay` (I/O paths
  unconstrained or over-constrained), missing multicycle or false paths on
  known slow paths (dividers, config registers, CDC), clocks missing or
  merged, generated clocks absent, unrealistic uncertainty. Read the
  anonymized SDC next to check_timing.
- **Clock model.** Ideal vs propagated clocks — slack moves when the tree
  is real. Compare launch/capture latency in the digest.
- **A real boson problem** looks like: a decision chain that made the path
  worse, an estimate far from the result, a repair that gave up while a
  probe found improvement, a constraint ignored, a stage checkpoint that
  regressed with no compensating gain. Only these go under "Suspected bad
  decisions".

### 6. Severity and confidence

- **High** — on a failing path (or the worst endpoint group) and the
  journal shows the decision made it worse, or a constraint was misread.
- **Medium** — on a failing path, the decision is plausibly wrong but the
  impact was not measured (null `impact`) or other factors contribute.
- **Low** — area/runtime waste, or a pattern on paths that meet timing.

Confidence: *confirmed* (journal impact + final path agree), *likely*
(pattern matches, numbers consistent), *speculative* (pattern only).

## REPORT.md template

```markdown
# boson debug report — <one-line verdict>

## Summary
3–6 bullets: the state (WNS/TNS/hold/violators), the top suspected boson
issues with severity, and whether the design/constraints also limit timing.

## Environment (anonymized)
boson version, effort/app var overrides from the journal header, library
family/node only, OS family, CPU count, GPU model class, run time.

## Current issues
Table: issue | count / worst | where (tokens, endpoint groups) | source file.

## Suspected bad decisions
### D1: <short title> — severity, confidence
- Evidence: path P<n> (slack, stages, slowest stages), journal seq <a>,<b>,<c>
  (stage, domain/action, chosen vs alternatives with metrics), checkpoint deltas.
- Impact: measured deltas (WNS/TNS/area) and what share of the miss it explains.
- Why we think it was the wrong choice.
- Suggested boson-side fix area (e.g. datapath architecture selection under
  negative slack, hold repair setup-margin guard, sizing oscillation damping).
(repeat per finding, most severe first)

## Stage-by-stage QoR
The checkpoint table with deltas and one line per regressing stage.

## Constraints review
What the SDC does and does not constrain; check_timing findings; any
ignored/misread command (message id).

## What we could not determine
Missing inputs, null impacts, probe-only data, anything you inferred.

## Appendix
Digest file names in the bundle, path list, decision counts by domain.
```

## Reporting back

To the customer, in chat: the summary, the top findings with severity, the
bundle path, MANIFEST.md's file list, whether the anonymized netlist is in
(and that it reveals structure), the leak-check result, and that
`name_map.json` must stay with them. Then show REPORT.md in full and let
them decide whether to send it. Speak about their design with real names
in chat if that helps them — just never in the bundle.
