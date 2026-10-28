# Skill feedback

Every customer-facing skill (ppa-optimize, rtl-timing-closure, datapath-audit,
minimal-repro, netlist-debug, timing-power-tradeoff, dc-datapath-compare)
ends its report with a fixed **Skill feedback** section. The agent writes it
into `skill_feedback.json` with `skill_feedback.py`. The customer does not have
to do anything.

| # | section | what goes in it |
|---|---|---|
| 1 | Off-script actions | every command, script or experiment the agent ran that the skill did not prescribe, and why it was needed |
| 2 | Missing framework | a question the skill had no method for ("the DC netlist was ungrouped, so the skill could not label DW cells") |
| 3 | Guidance that was wrong or misleading | a step that failed or led to a bad conclusion, with the error |
| 4 | Missing inputs or coverage gaps | data the skill needed but could not get; the coverage numbers the scripts print (`coverage --from-json ... --pick ...` copies them) |
| 5 | Outcome | answered yes / partly / no, the number of probe or edit iterations, one line of note |

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill <skill> --question "<the user's question>"
python3 $F add off_script --what "..." --why "..."
python3 $F add missing_framework --what "..."
python3 $F add wrong_guidance --what "..." --error "..."
python3 $F add missing_input --what "..."
python3 $F coverage key=value ... [--from-json out.json --pick a,b.c]
python3 $F outcome yes|partly|no --iterations N --note "..."
python3 $F render            # markdown for the end of the report
python3 $F share [--map name_map.json]
```

## Privacy and sending

- `skill_feedback.json` stays on the customer's machine.
- `share` writes `skill_feedback.share/skill_feedback.anon.json` and
  `skill_feedback.share/submit.tcl`.
  - With `boson-netlist-debug` installed and its `name_map.json` passed as
    `--map`, free text is encoded with the same salted tokens as a debug
    bundle, and that skill's leak check must pass.
  - Without it, or in addition to it, a basic scrub replaces paths, emails,
    hosts and every identifier the plugin itself does not use with salted
    tokens. Its map, `skill_feedback.map.json` (mode 600), never leaves the
    machine.
  - Coverage keeps only numbers, flags and short tokens.
- Nothing is sent by the script. The customer sources `submit.tcl` in boson,
  which calls `report_feedback -category docs` with the anonymized JSON
  (tagged with the skill and plugin version). `report_feedback` sanitizes
  again, prints the payload and asks before sending. The agent offers this
  once and never sources it without an explicit yes.

## On partcl's side

Group received feedback by `skill`. Treat a recurring off-script action as a
missing step, a recurring missing framework as a missing method, and wrong
guidance as a bug. Each becomes a skill update and a PR on this repo, the same
rule we follow internally: when a skill falls short, extend it and PR it.
