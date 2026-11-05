---
name: boson-diagnose
description: Use when a boson result is bad and the question is why, or when partcl should get the evidence — "what did boson do wrong", "why is my netlist bad", "why did timing get worse after layout", "is this my RTL, my constraints or boson", "why is this path 59 levels", "did it pick Han-Carlson or ripple", "why is boson's area bigger than the other tool's / Design Compiler's", "why did the new boson version regress", "boson can't parse my lib", "invalid constraint table", "does boson read every table in my Liberty correctly", "prepare a debug bundle for partcl without leaking IP". Reads boson's netlist, reports, log and decision journal, compares against a reference netlist, or tests every Liberty table shape against boson, and ends in evidence-backed findings.
---

# Diagnosing a boson result

Every method here ends in findings that cite numbers from files (path ids,
journal seq numbers, cell counts and areas on both sides), never impressions.

## Pick the method, then read its reference

| you have / the question is | method | read | scripts |
|---|---|---|---|
| a boson run of the user's design; "what did boson decide wrong on the failing paths"; a bundle for partcl | journal debug | [references/journal-debug.md](references/journal-debug.md) (+ [journal-schema.md](references/journal-schema.md), [privacy.md](references/privacy.md)) | `scripts/debug/` |
| "what did boson build for this adder / multiplier", "did a rewrite undo the architecture" | datapath audit | [references/datapath-audit.md](references/datapath-audit.md) | `scripts/datapath/` |
| a few paths far deeper than the clock allows; "is it the RTL or boson"; the full run is too slow to iterate | minimal repro | [references/minimal-repro.md](references/minimal-repro.md) | `scripts/repro/` |
| a learned repair misses a conventional repair; "policy, training or simulator?" | learned-repair audit | [references/learned-repair.md](references/learned-repair.md) (+ [compare-reference.md](references/compare-reference.md)) | controlled counterfactual replay |
| a reference netlist of the same RTL and library (another tool's, or an older boson version's); "why is the area / timing worse", "why did the new version regress" | reference compare | [references/compare-reference.md](references/compare-reference.md) | `scripts/compare/` |
| a Design Compiler netlist, and the question is how much of the gap is inside the datapath operators | DC datapath compare | [references/compare-dc.md](references/compare-dc.md) | `scripts/compare_dc/` |
| Liberty files boson rejects, warns about or may misread ("invalid constraint table", a 3-D or unusual table, a new library to trust) | Liberty table shapes | [references/liberty-shapes.md](references/liberty-shapes.md) | `scripts/liberty/` |

Read only the reference you need; the methods chain, and each reference
says when to hand over to another (a reference compare that lands in the
adders continues with the datapath audit; any finding that goes to partcl
goes through the journal debug's anonymizer).

## Rules for every method

1. **Fact before inference.** Each finding names its evidence: the file, the
   path or endpoint, the journal seq, the counts on both sides.
2. **Like for like.** Same RTL, Liberty files, SDC, corner, stage and wire
   model on both sides of any comparison, and one timer for both. A version
   A/B changes one thing.
3. **Boson's fault, or the design's?** Check logic depth against the period,
   the constraints and the clock model before calling something a boson
   defect.
4. **Nothing identifying leaves the user's machine.** Anything for partcl
   goes through `scripts/debug/anonymize.py` and its leak check; the name
   map stays local. Never upload, email or attach anything yourself; the
   user sends it.
5. **Third-party results stay under their license.** Design Compiler or any
   other reference tool's results are the user's to share or not; call it
   "the reference tool" in anything shared, and keep its numbers out of
   skill feedback.

All scripts are standard-library Python (or boson Tcl), stream large and
gzipped inputs, and have `--help`.

## Skill feedback (last step, every run)

Before reporting, record what this skill did not cover: every step you took
that it did not prescribe (with the reason), a question it had no method
for, guidance that failed or misled (with the error), and inputs or coverage
you needed and did not get. The reference you followed lists its coverage
keys.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-diagnose --question "<the user's question>"
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
