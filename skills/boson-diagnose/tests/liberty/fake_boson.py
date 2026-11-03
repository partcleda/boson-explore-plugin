#!/usr/bin/env python3
"""Stands in for boson in tests. FAKE_MODE:
  old    - reject 3-D constraint tables the way boson did before supporting them
  value  - answer every probe with FAKE_VALUE ns
  empty  - answer probes with no value (an older boson lacking a query)
"""
import os
import re
import sys
from pathlib import Path

mode = os.environ.get("FAKE_MODE", "value")
sys.stdin.read()
tcl = Path("run.tcl").read_text()
lib = Path("mini.lib").read_text()
cells = len(re.findall(r"^\s*cell\s*\(", lib, re.M))
body = lib.split("cell (", 1)[1] if "cell (" in lib else ""
if mode == "old" and re.search(r"cnst_rtin_ctin_rload_5x5x5\)\s*\{", body):
    print("Error: invalid constraint table: nochange fall_constraint table has 125 value(s), "
          "but its 5x5 index grid requires exactly 25 (LIB-130)")
    cells = 0
print(f"read_liberty: loaded mini.lib ({cells} cells)")
print("CHECKLIB_BEGIN")
print("CHECKLIB_END")
for m in re.finditer(r'timing_type : (\w+);', lib):
    print(f"ARC x/CK x/D {m.group(1)}")
points = [len(re.findall(r"\{[^{}]*\}", m)) for m in re.findall(r"set probe_points \[list (.*)\]", tcl)]
for i in range(tcl.count("PROBE_BEGIN")):
    print(f"PROBE_BEGIN {i}")
    v = "" if mode == "empty" else os.environ.get("FAKE_VALUE", "0.05")
    for pi in range(points[i] if i < len(points) else 1):
        for edge in ("rise", "fall"):
            print(f"PROBE comb {edge} {v or '-'} {v or '-'} {pi}")
    print(f"PROBE_END {i}")
