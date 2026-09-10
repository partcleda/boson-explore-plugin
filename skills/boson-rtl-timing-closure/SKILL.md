---
name: boson-rtl-timing-closure
description: Use when timing can't be closed by tool settings alone and the user wants the RTL CHANGED to make it work — "fix the RTL so it meets X ns", "pipeline whatever's on the critical path", "get this block to N MHz, edit the design if you have to". An edit → boson probe → edit loop driven by real critical-path reports; every change is a reviewable diff with a before/after timing table. Behaviour-changing edits (pipelining) are flagged and need the user's OK.
---

# RTL timing closure with boson

You are going to change the design. That is different from every other
skill in this plugin, so the rules come first.

## Rules

1. **Exhaust the non-RTL levers first**, or confirm the user already has.
   A parameter (`-G TWO_CYCLE_ALU=1`, `-G BARREL_SHIFTER=0`), a higher
   effort, or `boson-ppa-optimize`'s ladder may close timing with zero
   behavioural risk. Say which you tried.
2. **One edit per iteration**, probed immediately. Never stack three
   changes and probe once — you won't know which one mattered, and neither
   will the reviewer.
3. **Prefer edits that keep cycle-level behaviour**, in this order:
   restructure logic (priority chain → parallel case, precompute a
   comparison a cycle early only if the operand is already registered,
   split a wide compare, one-hot a state test, isolate a rarely used
   operation off the main path) → move an existing register (retime) →
   **add a pipeline stage**. Adding a stage changes latency and any
   handshake around it; flag it explicitly as behaviour-changing and get
   the user's OK before you do it. Never present a latency change as a
   free fix.
4. **Work on a branch / clean tree.** `git status` before touching
   anything; if the tree is dirty, ask. Every iteration ends with a diff
   the user can read.
5. **Verify beyond timing.** If the project has a testbench, lint, or
   simulation command, run it after every accepted edit (ask for the
   command if you don't know it). boson checks timing, not function; say
   plainly that no equivalence check was run unless one was.
6. **Confirm at real effort.** Iterate at `--effort fast` (layout-blind,
   seconds to a minute) but the accepted fix must be re-probed at
   `--effort medium` with LEFs — placement-aware timing is what the user
   will actually see, and fast-tier slack can move by a lot.

## The loop

```
S=skills/boson-rtl-timing-closure/scripts
python3 $S/timing_probe.py --rtl <files> --top <top> --liberty <lib> \
    --period-ns <target> --paths 5 --json probe0.json          # baseline
# read the report: launching/capturing registers, logic depth, RTL-named nets
# find those registers/nets in the RTL, decide ONE edit (rules 1-3), make it
python3 $S/timing_probe.py ... --json probe1.json --diff probe0.json
# WNS better and no new worst endpoint? keep; else revert (git checkout) and try the next idea
# repeat until WNS >= 0 at fast, then:
python3 $S/timing_probe.py ... --effort medium --lef <tech.tlef> --lef <cells.lef> --diff probeN.json
```

`timing_probe.py` prints, per path: slack, number of combinational stages,
the launch and capture registers (their RTL names survive synthesis — that
is how you find the path in the source), the RTL-named nets along the path,
the slowest cells, and the highest-fanout net. Exit code 0 = timing met.

### Reading a path

- Launch `..._q_reg[3]/QN` → capture `..._result_q_reg[17]/D` with 30+
  stages: the combinational block between those two registers is the
  target. `grep` for both names (minus `_reg[..]`) in the RTL.
- Slowest cells are wide AOI/OAI or mux cells with an RTL-named net like
  `alu_out`/`mem_wordsize` next to them: usually a priority `if/else if`
  chain or a case with overlapping conditions → restructure to parallel.
- A high-fanout net (hundreds of loads) that is an enable/reset/state bit:
  duplicate the register driving it or register a decoded version.
- An adder/comparator chain (many XOR/NAND stages on a `..._add`/`_lt`
  net): boson already picks adder architecture; the RTL fix is narrowing
  the operation or splitting it across a cycle (behaviour-changing).
- If the path starts or ends at a port with `set_input_delay` /
  `set_output_delay` in the SDC, the fix may be a constraint, not RTL.

## Reporting back

Show: the baseline probe line, one line per iteration (edit → WNS delta →
kept/reverted), the final medium-effort confirmation, the full diff, and a
plain statement of what changed behaviourally (nothing / latency of X by N
cycles / interface Y) and what was and wasn't verified beyond timing.
