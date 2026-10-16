"""Shared helpers for the boson-netlist-debug scripts (stdlib only).

Cell-name parsing (function / drive / VT / class), a streaming Verilog
statement reader, metric-direction rules, and small markdown helpers.
"""
from __future__ import annotations

import gzip
import io
import re
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------- files

def open_text(path: str | Path):
    """Open a text file, transparently handling .gz."""
    p = str(path)
    if p.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(p, "rb"), encoding="utf-8", errors="replace")
    return open(p, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- cell names

# Library tag after anonymization (anonymize.py maps vendor prefixes/suffixes to LIBX, LIBX2, ...)
LIB_TOKEN = re.compile(r"_*LIBX\d*_*")
# raw vendor tags, for digests run on un-anonymized files
RAW_TAG = re.compile(r"^sky130_[a-z]+_sc_[a-z0-9]+__|^gf180mcu_[a-z]+_sc_[a-z0-9]+__|^sg13g2_|_ASAP7_\d+t(?=_)|(?<=[A-Z0-9])BWP[0-9A-Z]*?(?=ULVT|ELVT|LVT|SVT|HVT|$)")

_DRIVE_PATTERNS = [
    re.compile(r"^(?P<f>.+?)x(?P<d>p?\d+(?:p\d+)?)[a-z]?(?:_(?P<vt>[A-Z]{1,4}))?$"),   # ASAP7: OR5x1, AOI21xp33, ..._R
    re.compile(r"^(?P<f>.+?)_X(?P<d>\d+(?:P\d+)?)$"),                           # NanGate: NAND2_X4
    re.compile(r"^(?P<f>.+?)_(?P<d>\d+)$"),                                      # sky130: or4_1
    re.compile(r"^(?P<f>[A-Z0-9]+?)D(?P<d>\d+)(?:_?(?P<vt>ULVT|ELVT|LVT|SVT|HVT))?$"),  # TSMC-style: ND2D4 (after tag strip)
    re.compile(r"^(?P<f>.+?)X(?P<d>\d+)$"),                                      # BUFX4
]

_CLASSES = [
    ("delay", r"^(CLK)?DLY|^DEL|^DLYGATE|^BUFDLY|^DLYBUF|^DLYGAT"),
    ("clock_gate", r"ICG|CKGT|CLKGATE|^GCK|LATCHGATE|^CGL|CKLNQ|CKLHQ|PREICG|^SDLCLK|^DLCLK"),
    ("tie", r"^TIE|^CONB"),
    ("physical", r"FILL|DECAP|^TAP|ANTENNA|DCAP|ENDCAP|WELLTAP|^PHY"),
    ("clock_buffer", r"^CLKBUF|^CKB|^CKBUF|^CLKBUFF"),
    ("clock_inverter", r"^CLKINV|^CKND|^CKINV"),
    ("sequential", r"DFF|SDF|EDFF|^DF|LATCH|^LAT|^DLH|^DLL|^DHL|^DL[NP]|MBFF|^FF|^SDFF|^DLX|^SRFF"),
    ("buffer", r"^BUF|^HB|^BF$|^BUFH|^BUFZ"),
    ("inverter", r"^INV|^IN$|^INX|^INVERTER"),
    ("adder", r"^FA|^HA|^FADD|^HADD|^ADDF|^ADDH|^MAJ|FULLADD|HALFADD"),
    ("xor", r"XOR|XNOR|XNR|^XR|^XN"),
    ("mux", r"MUX|^MX|^MXI"),
    ("complex", r"^AOI|^OAI|^AO\d|^OA\d|^A\d+O|^O\d+A|^AOAI|^OAOI"),
    ("nand_nor", r"^NAND|^ND\d|^NOR|^NR\d|^IND|^INR"),
    ("and_or", r"^AND|^AN\d|^OR|^O\d$"),
]
_CLASS_RES = [(n, re.compile(p, re.I)) for n, p in _CLASSES]
_MULTIBIT = re.compile(r"MB\d|\dBIT|MBFF|DFF[24]|_2B|_4B", re.I)


def parse_cell(celltype: str) -> dict:
    """Split a (possibly anonymized) cell type into function, drive, vt and class.

    Heuristic and library-agnostic; unknown shapes return drive None and the
    whole name as the function.
    """
    base = LIB_TOKEN.sub("_", RAW_TAG.sub("_", celltype)).strip("_")
    base = re.sub(r"_+", "_", base)
    func, drive, vt = base, None, None
    for pat in _DRIVE_PATTERNS:
        m = pat.match(base)
        if m:
            func, drive = m.group("f"), m.group("d")
            vt = m.groupdict().get("vt")
            break
    up = func.upper()
    cls = "other"
    for name, rx in _CLASS_RES:
        if rx.search(up):
            cls = name
            break
    return {"function": func, "drive": drive, "vt": vt, "class": cls,
            "multibit": bool(_MULTIBIT.search(up)) and cls == "sequential"}


def drive_value(drive: str | None) -> float | None:
    """'4' -> 4.0, 'p33' -> 0.33, '0P5' -> 0.5."""
    if not drive:
        return None
    d = drive.lower().replace("p", ".")
    if d.startswith("."):
        d = "0" + d
    try:
        return float(d)
    except ValueError:
        return None


OUTPUT_PIN = re.compile(
    r"^(Y\d*|Z\d*|ZN|Q\d*|QN\d*|Q_N|QB|X|O\d*|OUT\d*|S|SN|SUM|CO|CON|COUT|GCLK|GCK|ECK|ENCLK|IQ|IQN|H|L|HI|LO)$")


def is_output_pin(pin: str, cell_outputs: dict | None = None, celltype: str | None = None) -> bool:
    if cell_outputs is not None and celltype in cell_outputs:
        return pin in cell_outputs[celltype]
    return bool(OUTPUT_PIN.match(pin))


# ---------------------------------------------------------------- verilog

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def verilog_statements(path: str | Path) -> Iterator[tuple[int, str]]:
    """Yield (first_line_no, statement) with comments removed.

    A statement ends at ';' or is a bare keyword line (endmodule).  Works on
    multi-GB flat netlists: only one statement is held at a time.  Escaped
    identifiers containing ';' are not supported (boson does not emit them).
    """
    buf: list[str] = []
    start = 0
    in_block = False
    with open_text(path) as f:
        for ln, line in enumerate(f, 1):
            if in_block:
                end = line.find("*/")
                if end < 0:
                    continue
                line = line[end + 2:]
                in_block = False
            if "/*" in line:
                line = _BLOCK_COMMENT.sub(" ", line)
                if "/*" in line:
                    line, in_block = line[: line.index("/*")], True
            if "//" in line:
                line = _strip_line_comment(line)
            s = line.strip()
            if not s:
                continue
            if not buf:
                start = ln
            if s in ("endmodule", "end", "endgenerate", "endfunction", "endtask") and not buf:
                yield ln, s
                continue
            parts = s.split(";")
            for i, part in enumerate(parts):
                last = i == len(parts) - 1
                if last:
                    if part.strip():
                        if not buf:
                            start = ln
                        buf.append(part.strip())
                    break
                buf.append(part.lstrip() + ";")   # keep the space that ends an escaped identifier
                st = " ".join(x for x in buf if x)
                if st.strip(" ;"):
                    yield start, st
                buf = []
                start = ln
        if buf:
            yield start, " ".join(buf)


def _strip_line_comment(line: str) -> str:
    # don't treat '//' inside an escaped identifier (\a//b ) as a comment
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            j = i
            while j < n and not line[j].isspace():
                j += 1
            out.append(line[i:j])
            i = j
            continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        out.append(c)
        i += 1
    return "".join(out) + "\n"


# identifiers inside a Verilog expression: escaped or simple
VID = re.compile(r"\\\S+|[A-Za-z_][\w$]*")


def strip_escape(name: str) -> str:
    return name[1:] if name.startswith("\\") else name


# ---------------------------------------------------------------- metrics

_LOWER_BETTER = re.compile(r"area|power|delay|cells|count|violat|leak|cap|tran|fanout|depth|arrival|runtime|elapsed|_s$|mem", re.I)
_HIGHER_BETTER = re.compile(r"wns|tns|slack|fmax|freq|margin|required", re.I)


def better_direction(metric: str) -> int:
    """+1 if a larger value is better, -1 if smaller is better, 0 unknown."""
    if _HIGHER_BETTER.search(metric):
        return 1
    if _LOWER_BETTER.search(metric):
        return -1
    return 0


def num(v):
    """Float or None; tolerates null / strings."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def fmt(v, nd=3):
    if v is None:
        return "–"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.1f}"
        return f"{v:.{nd}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def md_table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(fmt(c) if not isinstance(c, str) else c.replace("|", "\\|") for c in r) + " |")
    return "\n".join(out) + "\n"
