# Audit retiming through repair and sequential behavior

Use this method for a fixed RTL and clock contract when moving registers
predicts a better period but the mapped result loses timing, adds registers,
or takes too long. Read the available `report_app_var` descriptions before
choosing settings; a diagnostic switch from an older run may no longer exist.

## Locate the cost and the timing change

Freeze the RTL, libraries, SDC, corner, effort, placement stage and area
recovery policy. Save the baseline and candidate netlists and their hashes.
When word-level and mapped retiming both run, compare the baseline,
word-level only, and combined flows with the same executable. Record the
settings of every arm, including rejected candidates.

Record graph construction, period solving, control-conflict replay,
register reduction, rebuilding, validation and the second setup repair
separately. A candidate rejected after repair still incurs all earlier costs.
Compare runtime with repeated interleaved rounds on one node; do not treat
a cold first run or a shared-host slowdown as an algorithmic regression.

Read the real critical paths on both sides, including the cell and drive,
pin arc, slew, capacitance, fanout and wire delay. Follow changed stages back
to the word-level snapshots or register-move decisions. For a fixed-delay
retiming model, check whether the moved registers change the loads that
produced those delays. A lower model period alone does not establish a win.
Judge the repaired candidate against the repaired baseline under the same
constraints. Report area, WNS and TNS separately and use the user's objective
to rank their tradeoff.

## Preserve boundaries even when STA does not check them

Check clock edges, the clock-gate function and all its input bindings,
reset assertion polarity, reset values, and output polarity. Equal clock
and enable net names alone do not establish equal clock behavior.

Every load outside the movable graph must retain its cycle behavior. Include
clock-gate enables, asynchronous control pins, untimed outputs and inputs of
fixed cells. A missing STA required time removes a timing constraint; it
does not authorize changing latency or omitting the load from reconstruction.
Make a small fixture with an untimed control load when diagnosing this case.

## Validate the sequential result and the checker

Use formal sequential equivalence when available. Otherwise describe the
result as bounded simulation and record the actual compared cycles, seeds,
reset sequence, clock waveforms, input assumptions and output coverage.
Keep the original and candidate in lockstep and check outputs during reset
and after release. Exercise reset again during operation, gated-clock
enable changes, stalls and supported mode corners. If unknown reference
bits are masked, report the mask and check that output comparisons are not
vacuous. An unsupported clock, latch or cell is unavailable coverage.

Test the checker on the original and on deliberate mutants: an output flip,
a changed reset value, and a one-cycle latency change. Require these mutants
to fail. A simulator can return zero after `$finish` while its log contains
mismatches. Check both process completion and the comparison summary.

For a harness that emits exactly one `SIMEQ checked N cycles, M mismatches`
line per run, use the completion checker after the simulator succeeds:

```sh
python3 skills/boson-diagnose/scripts/repro/check_lockstep.py \
  --expected-cycles 2999 run-a.log run-b.log
```

Set the expected count from the harness's checked interval, excluding any
explicit warm-up cycles. Missing or duplicate summaries, a shorter run,
zero work, invalid UTF-8 and any mismatch fail. This script checks the
summary contract; the harness owns the clock/reset model and output coverage.
Passing it is bounded evidence, not an unbounded equivalence proof.

## Skill feedback

Use the skill's feedback workflow and record these coverage keys:

```sh
python3 "$F" coverage compared_arms=3 control_boundaries_checked=yes \
  simulator_supported=yes checked_cycles=2999 mutants_rejected=3
```

Use the actual counts and supported coverage from the run.
