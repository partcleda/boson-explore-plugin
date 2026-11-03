---
description: Explain why a boson netlist is worse than a reference netlist of the same RTL and library (another tool's, or an earlier boson version's) by mapping pattern, buffer tree and failing-path family, and write ranked findings partcl can act on.
argument-hint: <boson netlist [+DEF, timing, log, journal]> <reference netlist [+DEF, timing]> --liberty <files> [--old-boson <log/journal>]
---

Run the `boson-reference-compare` skill on the inputs below. Check first
that the runs are comparable (`run_ab.py`: version, wire model calibration,
app variables, stage checkpoints); time both netlists in boson with the
same libraries, SDC and corner. Then split the area gap by mapping pattern
with `cell_mix.py`, explain XOR/XNOR use and one concrete cone with
`logic_patterns.py`, compare buffer trees with `buffer_trees.py` (DEF for
distances), and group failing paths with `path_families.py`. Class cells by
Liberty function only, count exclusive cone cells, and define every
measurement next to its number. Report with the skill's template: the
headline table, findings ranked by share of the area gap and by TNS, each
with both sides' numbers, one example and the next experiment. Keep
reference-tool results on the user's machine unless they say they may share
them.

Arguments: $ARGUMENTS
