---
name: boson-rtl-evolve
description: Use when the user wants Claude to EVOLVE a design's RTL against a PPA objective with boson as the evaluator — "optimise this block's RTL for Fmax/area/power", "run an RTL optimisation loop", "rewrite this until it's faster, keep area within +15 %". A budgeted edit → equivalence gate → boson compile/place/repair/report loop that keeps the best candidate and ends with a signed-off final. The function at the ports never changes.
---

# Evolutionary RTL optimisation with boson

You rewrite the RTL; boson scores each rewrite. You keep the best one and
iterate within a fixed budget. Every candidate must be **provably the same
design** at its ports before it gets a score. A faster design that computes
something different is not a result.

## Set up before the first edit

- **Objective**, pick one: max Fmax, min area, or min power. Optionally add
  caps on the others (e.g. maximise Fmax with area ≤ baseline + 15 %).
  - Fmax = 1 / (T − WNS), with T the clock period and WNS the worst setup
    slack on the **placed** design, both in ns.
  - Tie-break: among candidates within ~0.5 % of the best objective, take
    the one that is best on the secondary metric.
- **Budget**: a fixed number of scored evaluations, plus a wall-clock cap.
  Gate-only runs (no boson) are free.
- **Freeze** the SDC, the clock, the Liberty/LEF set and the flow script.
  Record their hashes. Only the design's own RTL files are editable.
- **Pick the clock so the baseline clearly misses it** (tens of percent
  short). Repair stops once timing is met, so at a loose clock every good
  candidate saturates at 1/T and the loop ends up ranking noise.
- Work on a git branch with a clean tree. Score the unmodified RTL first
  (iteration 0) and score it twice: the two results should be identical.

## Never change the function

- Keep the same ports, the same latency, the same reset behaviour, and the
  same value on every output in every cycle from reset. That includes
  intermediate values that are observable, and the results the original
  gives for illegal or unused encodings. Retiming and re-encoding internal
  state are fine. Anything visible at the ports is not.
- **Every candidate passes the equivalence gate before it is scored**:
  1. **Lint.** Reject multiply-driven nets: two continuous drivers, or a
     continuous plus a procedural driver (Verilator `MULTIDRIVEN` as an
     error, or Yosys `check -assert` after `proc`). Reject
     use-before-declare (don't pass any "allow use before declare"
     option). Also reject preprocessor directives, synthesis pragmas, new
     X literals or `unique`/`priority` qualifiers, `initial`, `#` delays,
     and system tasks. The same text must mean the same hardware in
     simulation, formal and synthesis.
  2. **Formal sequential equivalence** against the original. Use a miter
     that compares the outputs every cycle from reset, with all inputs
     free. **Keep the miter sound.** Don't ignore X on the gold side
     (`-ignore_gold_x`) and then zero undefined values. Together they turn
     the X-mask into `gold == 0` and hide every 0→1 difference. If you
     zero undefined values (`setundef -zero`), do it on both copies before
     building the miter. Report PROVEN or BOUNDED(k) honestly: BOUNDED
     only means no difference was found within k cycles.
  3. **Lockstep co-simulation** against the original, comparing every
     output bit at every clock edge. Pulse every reset at time 0 and again
     mid-run. Random seeds aren't enough: add **directed configuration
     corners**, i.e. every mode, divider, clock ratio, format or CSR
     setting the block supports, plus back-pressure and error paths. Some
     non-equivalent candidates pass random stimulus and fail only on a
     corner.
- Test the gate itself first. It must PASS the original and FAIL a few
  hand-made mutants, including a 0→1 output flip.

## Anti-gaming

- Don't touch the SDC, the clock, I/O delays, case analysis, or the flow
  script. Only RTL edits count.
- Don't remove reachable logic. Remove a mode only when it is provably
  unreachable, for example because a configuration input is tied in the
  SDC or a parameter fixes it, and let formal confirm that.
- Never write RTL that detects the testbench or behaves differently off
  the tested paths.
- **Check that a gain is real, not a timing-model artifact.** If candidates
  bunch up just under 1/T, the period is saturating. Re-score the top
  candidates at a tighter clock: a separate diagnostic run that uses the
  same clock for all of them. Confirm a win of only a few percent with a
  rerun, or with a provably equivalent re-phrasing of the same RTL. The
  surface form of the RTL alone can move results by a few percent.

## The loop

1. **Read the critical path first.** It is in `report_timing` of the last
   run: startpoint, endpoint, logic depth and the dominant cells. Map it
   back to the RTL. Register and RTL net names survive synthesis.
2. **One hypothesis per candidate.** Make one change (or one small
   coherent set) that targets that path. Run the free gate if the change
   is not trivial.
3. **Commit, gate, then score.** Every candidate is a commit, including
   failures and reverts. Never rewrite history.
4. **Log a ledger row** for each candidate, for example in `results.csv`:
   iteration, sha, gate verdict (lint / formal / sim), Fmax, WNS, area,
   power, Δ vs best, Δ vs baseline, and a one-line note. The note says
   which path you targeted and whether it moved.
5. **Keep or revert.** If the candidate didn't help, restore the best RTL
   (`git checkout <best_sha> -- rtl/`) before you try the next idea.
6. **Respect the budget.** Use all of it: when ideas run out, re-read the
   paths, combine partial wins, or trade unused area for speed.
7. **Declare the final as an explicit commit** (`final: <sha>`). Rerun the
   flow on it and confirm the numbers reproduce. Then sign it off with a
   much longer run than the in-loop gate: a long or unbounded formal proof
   plus long random and directed simulation. Report the verdict as is.

## What tends to pay off with boson as the evaluator

- **Algorithmic and architectural rewrites** of the block on the critical
  path. Local gate tweaks pay off much less.
- **Retiming**: move an existing register forward or back across logic.
  Keep the post-reset outputs identical.
- **Late select / Shannon expansion** on a late-arriving signal: compute
  both outcomes in parallel and let the late signal pick at the end.
- **One-hot encodings** of states and selects. Flatten priority chains
  into parallel sum-of-products.
- **Precompute into flops**: register a decode, a compare or a next value
  one cycle early, from operands that are already registered.
- **Remove unreachable modes** (see Anti-gaming).
- **Keep arithmetic behavioural.** boson already builds fast adders and
  multipliers from `+` and `*`. Hand-built adder, compressor and Booth
  trees usually cost area and buy nothing. Hand-build one only when the
  critical path proves it's needed. If you do, and want it kept as
  written, mark it with `(* keep_hierarchy *)` / `(* dont_touch *)`, or
  `set_dont_touch <module or instance>` before `compile`. Check that
  `help set_dont_touch` mentions RTL hierarchy, because older boson
  releases ignore these. Allow those attributes explicitly in your lint.

## Running boson

Verify flags with `help <cmd>` in the boson shell. Run the same script for
every candidate (`boson --no-color -f eval.tcl > boson.log`):

```tcl
foreach lib $LIBS { read_liberty $lib }
read_lef tech.lef ; read_lef cells.lef         ;# placement needs footprints
# set_wire_rc ...                              ;# calibrate RC for your PDK
compile rtl/a.sv rtl/b.sv -top TOP -sdc design.sdc -effort medium
create_floorplan -utilization 50
place_design -density 0.6
repair_design -max_fanout 32
repair_timing -setup
update_timing
puts [report_qor]                ;# setup WNS / TNS -> Fmax
puts [report_timing -max_paths 5] ;# critical paths for the next hypothesis
puts [report_area]               ;# total cell area
puts [report_power -vcd sim.vcd] ;# add -vcd_rtl if the VCD names RTL signals
write_verilog placed.v
```

- `compile` maps and runs setup repair. It does not place, so
  `place_design` follows. Without `-effort` it does a one-shot fast map.
- Power without activity is leakage only. For a power objective, use a
  VCD (or SAIF) from the **same workload** for every candidate, and
  regenerate it from that candidate's own simulation.

## Optional: cross-check the final

If a second synthesis and place-and-route flow is available, run the
baseline and the final through it too. RTL tuned against one evaluator
doesn't always transfer to another. Report both, and don't claim a
general win from one flow.

## Reporting back

Report the objective and constraints, the baseline and final metrics,
and the ledger. List the 3–5 changes that mattered and the dead ends.
Give the final sha and its rerun, the sign-off verdict (PROVEN / BOUNDED /
FAIL, with the simulation volume), and the full diff.
