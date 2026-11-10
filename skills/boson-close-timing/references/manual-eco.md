# Manual cell and buffering closure

Use this workflow when the user authorizes mapped-cell edits. Keep the same
libraries, corner, SDC, layout stage and timing model. Follow the user's VT
restriction for every replacement, inserted buffer and clock cell.

1. Save the mapped netlist and collect several critical paths with input pins,
   nets, capacitance and transition time. Read the path's side inputs and
   fanout before choosing a drive change, buffer removal or pin swap.
2. Check replacement behavior from Liberty. `size_cell` checks signal-pin
   compatibility; that alone does not establish Boolean equivalence. Match
   pin names and directions, every output's `function` and `three_state`, and
   any sequential state, clock, enable, reset or preset equations. Reject an
   unsupported cell form rather than assigning it an empty signature. Exact
   expression matching is conservative: different expressions need a Boolean
   proof before they can be treated as equivalent.
3. Parse Liberty attribute names exactly. `function` and
   `power_down_function` are different attributes; substring matching can put
   NAND and NOR cells in the same alleged family. Quoted directions and
   nested groups also need proper parsing. The Liberty shape census has a
   group parser in `scripts/liberty/shape_census.py` under `boson-diagnose`.
4. Change one candidate, run `update_timing`, and compare design-wide WNS,
   TNS, hold and design-rule violations. Restore rejected candidates. A
   smaller drive can help by reducing the load on its predecessor. Removing
   a buffer can hurt when it exposes that predecessor to the full fanout.
5. Refresh the path sample after accepted edits. Fixing one bus bit can move
   the worst path to another bit or a different cone. A tied WNS can hide
   useful TNS improvement; record both instead of treating an unchanged
   displayed WNS as proof that nothing moved.
6. Use exact slack from timing JSON or `get_attribute` on timing paths.
   Three-decimal reports can print a tiny violation or negligible positive
   margin as `0.000`. State the actual margin and the timing model when
   reporting closure. A tighter repair margin is separate from changing SDC.
7. Re-read the saved mapped netlist in a fresh process, load the same SDC,
   and confirm the reported result. Replay from the selected RTL and pinned
   binary through the same checkpoint boundaries and ECO commands. Save
   the netlist, source hashes, exact commands and checks; verify the resulting
   function with equivalence checking or the available gate-level tests.

Preserve instance names exactly as returned by the loaded design. A Verilog
reload can expose escaped names, and Tcl double quotes evaluate bracketed bus
indices. Use collection objects where supported and Tcl-safe words or
brace-quoted `format` strings when generating edit commands and receipts.

Before relying on `write_changes` for replay, inspect its output: not every
internal repair is necessarily present in the ECO journal. Keep the actual
repair command and the resulting checkpoint when the journal is empty.

Before a large gate-level simulation, exercise the library's flop, latch and
clock-gate models in a small test with reset and data transitions. A simulator
can accept a sequential UDP model yet simulate its edges incorrectly. Isolate
such a failure and check it in an independent simulator before attributing it
to synthesis. Four-state checks must also account for state the RTL does not
reset: compare defined outputs against the RTL oracle and preserve a separate
check of the original and candidate unknown states.
