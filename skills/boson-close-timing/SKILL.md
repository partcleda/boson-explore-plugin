---
name: boson-close-timing
description: Use when timing has to close, or fmax has to be found, without changing the design's RTL — "close timing at X ns", "what's the fmax", "which effort should I use", "clean up the SDC before optimizing", "synthesis fails / boson crashes on this design", "timing got worse after resizing or buffering". Fixes constraints first, then climbs the cheapest boson recipe ladder (effort, placement draws, candidate race, datapath search, ECO) and stops at the first rung that closes.
---

# Closing timing without touching the RTL

The design's RTL and latency are fixed here. Constraints, synthesis settings
and boson's own engine are what may change. Changing the RTL is
`boson-rtl-optimize`; comparing RTL variants is `boson-explore`.

## Pick the workflow, then read its reference

| situation | read |
|---|---|
| a target clock to close, or fmax to find, on a single-clock design | [references/ladder.md](references/ladder.md) (`scripts/ppa_optimize.py`) |
| an existing flow with suspect SDC, a synthesis failure, or a request to fix boson's engine | [references/constraint-engine-loop.md](references/constraint-engine-loop.md), before any ladder |
| QoR moved after buffer insertion, resizing or another placement | [references/placement-continuity.md](references/placement-continuity.md) |

## Always

- Keep the user's clock contract, sources, parameters and layout stage. For
  a multi-clock or mode-specific flow, iterate their Tcl directly.
- Say whether every number is placed or unplaced, and which rung or setting
  produced it.
- When no setting closes timing, the path is usually architectural: hand
  over to `boson-rtl-optimize`. When the question becomes "why is boson's
  result bad", hand over to `boson-diagnose`.

## Skill feedback (last step, every run)

Before reporting, record what this skill did not cover: every step you took
that it did not prescribe (with the reason), a question it had no method
for, guidance that failed or misled (with the error), and inputs or coverage
you needed and did not get. The reference you followed lists its coverage
keys.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-close-timing --question "<the user's question>"
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
