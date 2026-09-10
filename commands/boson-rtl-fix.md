---
description: Edit the RTL until boson meets timing — probe critical paths, make one reviewable change at a time, re-probe, confirm at real effort.
argument-hint: --rtl files --top name --period-ns T [--liberty lib] [-G NAME=VALUE]
---

Run the `boson-rtl-timing-closure` skill on the arguments below. Follow its
rules exactly: non-RTL levers first, one edit per probe, restructuring
before pipelining, ask before any latency-changing edit, clean git tree,
run the project's tests after each accepted edit if there are any, and
confirm the final fix at `--effort medium`. Report the iteration table,
the diff, and what changed behaviourally.

Arguments: $ARGUMENTS
