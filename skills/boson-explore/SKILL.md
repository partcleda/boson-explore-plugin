---
name: boson-explore
description: Use when the user wants to explore an RTL block's area/power/timing design space with real boson runs — "sweep this design's parameters", "what does tightening the clock cost me in power", "which config is smallest / fastest / lowest-power", "show me the Pareto front" — or wants that sweep as an animated video or GIF ("make a sweep video", "animate the PPA space"). Every point is a real compile + STA + power run, not an estimate.
---

# Exploring a design space with boson

Each point of a sweep is one real boson session: `compile`, then QoR, area
and random-activity power reports, at one clock period and one setting of
the RTL parameters. N points cost N compiles; say so before a large sweep.

## Pick the mode, then read its reference

| the user wants | read | script |
|---|---|---|
| a table of area / power / timing over clock periods and parameter configs, and which config wins | [references/tradeoff-table.md](references/tradeoff-table.md) | `scripts/boson_dse.py` |
| the same sweep rendered as a GIF / MP4: terminal replay, Pareto scatter, placements | [references/sweep-video.md](references/sweep-video.md) | `scripts/video/run_sweep.py`, `render_video.py` |

Read only the reference for the chosen mode.

## Both modes

- A `boson` binary (`$BOSON_BIN`, `--boson-bin` or on `PATH`) and a Liberty
  file are required; the video also needs LEF, because placement is what it
  draws. boson is not shipped here; if it is missing, say so and stop.
- `designs/picorv32/picorv32.v` is a bundled example with real
  synthesis-affecting parameters, verified on sky130.
- One clock, or a sweep of one clock's period. A multi-clock flow is a
  `boson-close-timing` job.
- To close timing at one target, use `boson-close-timing`; to change the RTL,
  `boson-rtl-optimize`.

## Skill feedback (last step, every run)

Before reporting, record what this skill did not cover: every step you took
that it did not prescribe (with the reason), a question it had no method
for, guidance that failed or misled (with the error), and inputs or coverage
you needed and did not get. The reference you followed lists its coverage
keys.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-explore --question "<the user's question>"
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
