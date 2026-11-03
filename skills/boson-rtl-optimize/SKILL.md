---
name: boson-rtl-optimize
description: Use when the RTL itself should change, with boson as the judge — "fix the RTL so it meets X ns", "pipeline whatever is on the critical path", "get this block to N MHz, edit the design if you have to", "optimise this block's RTL for Fmax / area / power", "run an RTL optimisation loop", "rewrite it until it's faster, area within +15 %". Edit → check → boson probe loops where every change is a reviewable diff with a before/after table.
---

# Changing the RTL with boson as the judge

## Pick the mode, then read its reference

| the user wants | read |
|---|---|
| meet one timing target with the fewest, smallest edits; every edit reviewed | [references/meet-timing.md](references/meet-timing.md) (`scripts/timing_probe.py`) |
| a budgeted search for the best RTL against an objective (max Fmax, min area or min power, with caps), each candidate equivalence-checked | [references/evolve.md](references/evolve.md) |

Both read paths back to source with boson's native RTL traceback:
[references/rtl-traceback.md](references/rtl-traceback.md).

## Rules for both modes

1. **Try the non-RTL levers first** (parameters, effort, `boson-close-timing`'s
   ladder), or confirm the user already has.
2. **Work on a branch with a clean tree.** Every iteration ends in a diff the
   user can read.
3. **Never change behaviour silently.** A pipeline stage or any latency,
   port or reset change needs the user's explicit OK. Say plainly what was
   verified (tests, lint, equivalence) and what was not.
4. **One change per scored run**, so each result is attributable.
5. **Confirm the winner in the target flow** (baseline effort and layout
   mode), and report unplaced numbers as unplaced.
6. When the question is whether a deep path is the RTL's fault or boson's,
   run `boson-diagnose` (minimal repro) before editing.

## Skill feedback (last step, every run)

Before reporting, record what this skill did not cover: every step you took
that it did not prescribe (with the reason), a question it had no method
for, guidance that failed or misled (with the error), and inputs or coverage
you needed and did not get. The reference you followed lists its coverage
keys.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-rtl-optimize --question "<the user's question>"
python3 $F add off_script|missing_framework|wrong_guidance|missing_input --what "..." [--why "..."] [--error "..."]
python3 $F coverage <the reference's keys>
python3 $F outcome yes|partly|no --iterations <n>
python3 $F render
```

End the report with the rendered section, "none" lines included. Then offer
once to share it: `python3 $F share` (add `--map name_map.json` when a debug
bundle's map exists) writes an anonymized copy and a `submit.tcl` that sends
it with boson's `report_feedback` when the user sources it. Never send or
source it without the user's explicit yes. See `feedback/README.md`.
