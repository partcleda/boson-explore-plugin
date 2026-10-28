---
name: boson-rtl-timing-closure
description: Use when timing can't be closed by tool settings alone and the user wants the RTL CHANGED to make it work — "fix the RTL so it meets X ns", "pipeline whatever's on the critical path", "get this block to N MHz, edit the design if you have to". An edit → boson probe → edit loop driven by native RTL traceback and JSON timing reports; every change is a reviewable diff with a before/after timing table. Behaviour-changing edits (pipelining) are flagged and need the user's OK.
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
   restructure logic (balanced first-match tree, split a wide compare,
   one-hot a state test, isolate a rarely used operation) → move an
   existing register (retime) →
   **add a pipeline stage**. Adding a stage changes latency and any
   handshake around it; flag it explicitly as behaviour-changing and get
   the user's OK before you do it. Never present a latency change as a
   free fix. Preserve priority for overlapping conditions; a parallel case
   is safe only when exclusivity is established.
4. **Work on a branch / clean tree.** `git status` before touching
   anything; if the tree is dirty, ask. Every iteration ends with a diff
   the user can read.
5. **Verify beyond timing.** If the project has a testbench, lint, or
   simulation command, run it after every accepted edit (ask for the
   command if you don't know it). boson checks timing, not function; say
   plainly that no equivalence check was run unless one was.
6. **Confirm in the target flow.** Use `compile -fast` for a short probe
   when appropriate, then re-run the accepted change at the baseline effort
   and layout mode. Effort alone does not enable placement: `-physical`
   needs the appropriate LEF/RC inputs. Report unplaced results as unplaced,
   and check the installed command help before changing the recipe.

## The loop

Prefer Boson's native RTL traceback over manually stripping register
suffixes or scraping the text report. Before the first probe, read the
[native timing traceback guide](references/rtl-traceback.md). Check
`help report_timing rtl` and `help report_timing json` in the installed
Boson; they describe source matching and the JSON schema.

After compiling the candidate in the same session and running the chosen
flow, collect these reports before editing its source files:

```tcl
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
puts [report_qor]
report_timing -format rtl -max_paths 10 -file timing.rtl
report_timing -format json -max_paths 10 -file timing.json
```

Save outputs in a separate directory for each candidate. Read
`timing.json`: validate `schema_version`, `timing_complete` and `warnings`,
then inspect `paths[].start_rtl`, `end_rtl` and `points[].rtl`. Follow the
matched file/line and snippet in the matching candidate revision. Use
`groups` to recognize repeated bus-bit paths, then inspect the individual
path points to decide ONE edit (rules 1–3). Recompile and re-probe under
the same constraints; compare design-wide WNS from `report_qor`, path
slacks and endpoint changes before keeping or reverting the edit.
Repeat until the target is met, then perform the final confirmation in
rule 6. An empty path sample or null slack is not evidence that timing met.

### Existing Python probe

`timing_probe.py` remains available for its text-derived stage summaries
and `--diff` workflow, or an older Boson without native traceback:

```sh
S=skills/boson-rtl-timing-closure/scripts
python3 $S/timing_probe.py --rtl <files> --top <top> --liberty <lib> \
    --period-ns <target> --paths 5 --json probe0.json          # baseline
# inspect the text-derived path summary, decide ONE edit (rules 1-3), make it
python3 $S/timing_probe.py ... --json probe1.json --diff probe0.json
# WNS better and no new worst endpoint? keep; else revert (git checkout) and try the next idea
# repeat until WNS >= 0 at fast, then:
python3 $S/timing_probe.py ... --effort medium --lef <tech.tlef> --lef <cells.lef> --diff probeN.json
```

Its `--json probe.json` is the helper's own schema, parsed from
`report_timing -format pt`; it is **not** Boson's native `-format json` and
does not contain native file/line matches. Do not pass native
`timing.json` to the helper's `--diff`. Its stage counts and retained net
names are heuristics; it may not recover a source signal after synthesis.

### Reading a path

- Start with the native launch/capture matches and source snippets. Use
  `kind` to distinguish a signal match from a nearby region or module
  hint. If a point is unmapped, search the reported net/cell names in the
  correct hierarchy; do not invent a source line by stripping a suffix.
- Slowest cells are wide AOI/OAI or mux cells with an RTL-named net like
  `alu_out`/`mem_wordsize` next to them: usually a priority `if/else if`
  chain or a case with overlapping conditions → inspect a balanced
  priority-preserving implementation; do not discard overlap semantics.
- A high-fanout net (hundreds of loads) that is an enable/reset/state bit:
  duplicate the register driving it or register a decoded version.
- An adder/comparator chain (many XOR/NAND/AOI stages on a `..._add`/`_lt`
  net): first run `boson-datapath-audit` to see which architecture boson
  chose and whether a logic rewrite re-serialized it. That is a tool issue to
  report, not an RTL fix. If the structure is clean, the RTL fix is narrowing
  the operation or splitting it across a cycle (behaviour-changing).
- If the path starts or ends at a port with `set_input_delay` /
  `set_output_delay` in the SDC, the fix may be a constraint, not RTL.
- If it is unclear whether the depth comes from the RTL or from boson (a
  scan or accumulation far deeper than its function needs, or a full run too
  slow to iterate on), use `boson-minimal-repro` first: compile the construct
  alone and A/B equivalent rewrites of it. A coding-style sensitivity is a
  tool issue to report, not only an RTL fix.

## Reporting back

Show: the baseline probe line, one line per iteration (edit → WNS delta →
kept/reverted), the final target-flow confirmation, the full diff, and a
plain statement of what changed behaviourally (nothing / latency of X by N
cycles / interface Y) and what was and wasn't verified beyond timing.

## Skill feedback (last step, every run)

Before reporting, fill in Skill feedback. List every step you took that this
skill did not prescribe: commands, scripts and experiments, each with the
reason the skill's own steps were not enough. Record a question the skill had
no method for, any step whose guidance failed or misled (with the error), and
any input or coverage the skill needed and did not get.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-rtl-timing-closure --question "<the user's question>"
python3 $F add off_script|missing_framework|wrong_guidance|missing_input --what "..." [--why "..."] [--error "..."]
python3 $F coverage probes=<n> kept_edits=<n> rtl_mapped_points=<mapped>/<total> wns_ps_start=<x> wns_ps_end=<y>
python3 $F outcome yes|partly|no --iterations <probe/edit iterations>
python3 $F render
```

End the report with the rendered section, "none" lines included. Then offer
once to share it: `python3 $F share` (add `--map name_map.json` when a
`boson-netlist-debug` map exists) writes an anonymized copy and a `submit.tcl`
that sends it with boson's `report_feedback` when the user sources it. Never
send or source it without the user's explicit yes. See `feedback/README.md`.
