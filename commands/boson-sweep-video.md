---
description: Run a boson design-space sweep and render it as an animated PPA video/GIF (terminal replay + Pareto scatter + placements).
argument-hint: [--rtl path --top name --axis NAME=v1,v2 ... --periods ns,ns] [--gif out.gif] [--mp4 out.mp4]
---

Run the `boson-sweep-video` skill end to end: `run_sweep.py` with the
arguments below (default to the bundled picorv32 example with a small
2×2×2 grid if none are given), then `render_video.py` to produce the
GIF/MP4/still. Confirm `boson`, a Liberty file and LEF files are available
first (env `$BOSON_BIN` / `$BOSON_LIBERTY`, or ask). Run the sweep in the
background and report progress; follow the skill's instructions for
choosing axes and for what to hand back.

Arguments: $ARGUMENTS
