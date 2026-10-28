---
description: Show what boson built for the arithmetic on the critical paths — chosen adder architecture, depth on each path, and which logic rewrites restructured it.
argument-hint: <flow or compile command> [--paths N]
---

Run the `boson-datapath-audit` skill for the design and flow below. Add
`-provenance` to the compile and change nothing else. Source the collector
after the stage being judged, then run `datapath_audit.py`. Report the table
and name every block flagged deeper than its architecture, with the rewrite
that restructured it. Say whether each slow adder comes from the selector's
choice or from a rewrite.

Arguments: $ARGUMENTS
