"""Parse a boson-written DEF plus the LEF cell footprints into numpy arrays.
Only the COMPONENTS section (placed instance -> lib cell, x, y) and DIEAREA
are read; the LEF gives each lib cell's `SIZE w BY h` so cells are drawn as
their real rectangles rather than points."""
import re
import numpy as np


def lef_sizes(paths):
    """{lib_cell: (w_um, h_um)} across every LEF given (tech LEFs contribute nothing)."""
    sizes = {}
    for p in paths:
        name = None
        with open(p) as fh:
            for line in fh:
                if line.startswith("MACRO "):
                    name = line.split()[1]
                elif name and line.strip().startswith("SIZE "):
                    f = line.split()
                    sizes[name] = (float(f[1]), float(f[3]))
    return sizes


def parse_def(path):
    units = 1000.0
    die = None
    names, cells, xs, ys = [], [], [], []
    rx = re.compile(r"^\s*-\s+(\S+)\s+(\S+)\s+\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    in_comp = False
    with open(path) as fh:
        for line in fh:
            if line.startswith("UNITS"):
                units = float(line.split()[3])
            elif line.startswith("DIEAREA"):
                n = [int(t) for t in re.findall(r"-?\d+", line)]
                die = (n[0] / units, n[1] / units, n[2] / units, n[3] / units)
            elif line.startswith("COMPONENTS"):
                in_comp = True
            elif line.startswith("END COMPONENTS"):
                in_comp = False
            elif in_comp:
                m = rx.match(line)
                if m:
                    names.append(m.group(1)); cells.append(m.group(2))
                    xs.append(int(m.group(3))); ys.append(int(m.group(4)))
    if die is None and xs:
        die = (min(xs) / units, min(ys) / units, max(xs) / units, max(ys) / units)
    return dict(die=die, names=names, cells=cells, x=np.array(xs, float) / units, y=np.array(ys, float) / units)
