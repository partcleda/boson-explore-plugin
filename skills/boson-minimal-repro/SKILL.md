---
name: boson-minimal-repro
description: Use when a large design misses timing on a few deep paths and the question is WHY — "is this the RTL or boson", "why is this path 59 levels", "debug the critical path", "the full run takes hours / runs out of memory / repair dominates, what's actually going on". Rebuild the failing construct as a small module-level boson run, read the path against how the RTL is written, A/B equivalent rewrites of the same construct, and write the result up as a debug report. Every conclusion comes from a real boson run.
---

# Debug a deep path with a minimal repro

A full compile of a large block mixes three things: the structure synthesis
built for each construct, the repair ladder working on it, and constraint or
placement effects. When a few cones are far deeper than the clock allows,
separate the structure question from the rest. Compile the construct on its
own, in minutes, under the same clock. Then change how it is written,
without changing what it computes, and see whether boson's result follows the
coding style.

The outcome is one of three findings, and each has a different owner:

| Finding | Evidence | Who fixes it |
|---|---|---|
| **Coding-style sensitivity** | Equivalent rewrites of the construct differ a lot in depth or slack | boson (report it with the table), or the RTL in the meantime |
| **Architecture limit** | Every equivalent form is too deep for the clock | the RTL: restructure or pipeline (`boson-rtl-timing-closure`) |
| **Context** | The repro meets timing, the full design does not | constraints, fanout, placement or repair: go back to the full run |

## Rules

1. **The RTL stays where it is.** Work in the user's environment. What leaves
   it is the debug report (below): construct classes, widths, depths,
   slacks, boson version and flags. Include RTL text, names or paths only if
   the user says it may leave.
2. **Same yardstick everywhere.** Same Liberty set, `set_dont_use` list,
   clock period and uncertainty, boson version and effort for every variant.
   Record them once at the top of the report.
3. **One change per experiment.** A rewrite, a width, or an effort. Never two
   at once.
4. **Rewrites are experiments, not fixes.** A variant that is not proven
   equivalent tells you nothing. Use the equivalence gate of
   `boson-rtl-evolve` (formal, or lockstep simulation with directed corners).
   For a pure-arithmetic idiom, an exhaustive or random check of a small
   behavioural model is a useful first filter. Say which check was run.
5. **Confirm the repro reproduces.** Its worst path must look like the full
   design's: similar depth, similar cell mix, same endpoint family. If it
   doesn't, you are debugging something else.

## 1. Find the construct

From the full run (or the last one that finished):

```tcl
report_timing -format rtl  -max_paths 20 -file full.rtl
report_timing -format json -max_paths 20 -file full.json
report_timing -max_paths 20 > full.rpt
```

`full.json` maps path points to RTL file and line (`paths[].points[].rtl`).
Group the worst paths by endpoint family (bus bits of one register, replicated
instances of one module). Count levels so later runs can be compared:

```sh
python3 skills/boson-minimal-repro/scripts/path_levels.py full.rpt
```

A level is a cell that is not a buffer, inverter, delay cell, register or
clock gate. Repair adds and removes those, so they would hide the logic depth.
Check the printed cell mix: library naming differs, so pass `--exclude` if
the defaults miss your buffers. If no run finished (out of memory, timeout),
go straight to the module named by the failing endpoints, or the region the
user suspects.

Then read the RTL at those lines and name the construct. The patterns below
often produce more depth than their function needs. "Rewrite to test" is the
equivalent form to A/B against.

| Construct | What to look for in the RTL | Rewrite to test |
|---|---|---|
| First-match scan with a found flag | `for` loop, `if (!found && c[i]) begin found = 1; idx = i; end` | last-assignment-wins loop (`for i = N-1 downto 0: if (c[i]) idx = i`); a balanced priority encoder |
| Scan from a rotating pointer | index `(ptr + i) % N`, or the request vector rotated before the scan | double-width vector and a plain scan; two masked scans (above / below `ptr`) |
| Encode then decode | a scan's binary index immediately decoded: `occ[idx] <= 1`, `grant[idx]`, `1 << idx` | drive the decode from the one-hot "first" vector (`c & ~(c - 1)`) |
| Chained scans in one cycle | allocate k entries: mask the winner, scan again | parallel scans on disjoint halves, or a k-hot prefix count |
| Accumulation folded each step | `s = s + w; s = s[W-1:0] + s[W];` in a loop (ones'-complement checksum) | one wide sum, folded twice at the end |
| Serial reduction loop | `acc = acc OP x[i]` across a wide vector | the same reduction as a balanced tree |
| Long `if / else if` chain | many overlapping conditions writing one variable | `case` / one-hot form only where the conditions are proven exclusive |
| Compare-then-subtract / saturate | `a >= b ? a - b : ...`, saturation in the same cycle | compute `a - b` once and use its borrow as the compare |
| Hand-instantiated arithmetic | gates spelling an adder or counter (boson may rebuild these: check the log) | the plain `+` / `-` operator |
| Wide operand broadcast | one register feeding many multiplier or compare inputs | a registered duplicate per consumer group (changes nothing at the ports) |

## 2. Build the repro

Compile the enclosing module alone: the real RTL, the same parameters as the
instance on the path, the same libraries. Keep the SDC to the clock unless the
path starts or ends at a port:

```tcl
foreach l $LIBS { read_liberty $l }
set_dont_use <the flow's dont_use list>
# repro.sdc
#   create_clock -name clk -period <T> [get_ports <clk port>]
#   set_clock_uncertainty <U> [all_clocks]
#   set_input_delay 0 -clock clk [remove_from_collection [all_inputs] [get_ports <clk port>]]
#   set_output_delay 0 -clock clk [all_outputs]
compile -f design.f -top <module> -G <PARAM>=<instance value> -sdc repro.sdc -effort fast -provenance
report_timing -max_paths 10 > fast.rpt
```

If the module has too much else in it, wrap only the construct: put registers
on its inputs and outputs, so its own logic is the register-to-register path.

Run it twice: `-effort fast` (one map and a short repair: the structure as
built) and the flow's effort (usually `medium`). `-fast` reports a zero-wire
WNS, so compare it by depth, not slack. If medium is much shallower than fast,
optimization is doing the work. If both are as deep as the full design, the
structure is set at mapping. Then run `boson-datapath-audit` on the medium
compile. It shows, per arithmetic or priority block, the architecture boson
chose and which logic passes rewrote it.

Check rule 5 now: does the repro's worst path match the full design's?

## 3. A/B the construct

Write one to three equivalent variants of the same construct, from the table
or from what the path suggests. Put each one in its own module with the same
ports, prove it equivalent (rule 4), and compile each one exactly like the
baseline. Useful experiment types:

- **Coding-style variants**: the same function written another way.
- **Width sweep**: compile the original at several widths (`-G N=128, 256,
  257, 512, 1024`). A depth that jumps at one width, rather than growing like
  log N, points at a size limit in a synthesis optimization. Report the
  width where it jumps.
- **Clock sweep**: compile at the target period and at a much tighter one.
  Repair stops once timing is met, so a loose clock can hide how far boson
  can actually push a structure.

Fill one table, one row per run:

| variant | equivalence check | effort | period (ns) | levels | WNS (ns) | cells | notes |
|---|---|---|---|---|---|---|---|

Read it against the three findings at the top. For example: a ones'-complement
checksum over 16 words, written with the end-around carry folded after every
add, took 91 levels and missed a 606 ps clock by 1.0 ns. The same function as
one wide sum folded twice took 16 levels and met it. That is coding-style
sensitivity: report it to Partcl with both variants' rows, and use the
faster form in the RTL until boson handles the first.

## 4. Write the debug report

This is what goes back to the design team and to Partcl. Keep it free of IP
unless the user allows otherwise.

```
boson <version>, <flags>, libraries <corner>, clock <T> ns, uncertainty <U> ns
Full design: worst endpoint family <description>, <levels> levels, WNS <x> ns
Construct: <class from the table>, width <N>, coding style <one line, generic>
Repro: module-level compile, reproduces full path (yes/no: depth a vs b)
Experiments: <the table>
Datapath audit: <block, chosen architecture, rewritten-by> for the worst rows
Finding: coding-style sensitivity | architecture limit | context
Next step: <boson issue / RTL change / back to full-run constraints>
```

With the user's consent, `report_feedback -category bug -message "..."`
sends that text to Partcl from the boson session. Show the user the exact
message first; it must not contain anything they have not cleared.

## Related skills

- `boson-datapath-audit`: what architecture boson chose per operator and
  whether a rewrite undid it. Run it on the repro.
- `boson-rtl-timing-closure`: when the finding is an architecture limit and
  the RTL has to change.
- `boson-rtl-evolve`: the equivalence gate used in step 3.
