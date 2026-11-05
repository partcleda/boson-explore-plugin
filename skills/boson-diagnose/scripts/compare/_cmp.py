"""Shared helpers for the boson-diagnose compare scripts (stdlib only).

- Liberty reader: per cell its area, pin directions, output functions,
  clock pins and sequential / clock-gate / dont_use flags.
- Function classifier: every cell is classed by what its Liberty function
  computes (truth table), not by its name, so a clock NAND2 is a NAND2 and a
  full adder is a full adder in any library.
- Netlist reader: flattens a gate-level Verilog netlist (flat or
  hierarchical) into leaf instances and connected nets.
- DEF reader: component origins, and routed wire length per layer.
"""
from __future__ import annotations

import functools
import itertools
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "debug"))
from _bdlib import open_text, parse_cell, strip_escape, verilog_statements  # noqa: E402

# ---------------------------------------------------------------- categories

# Report order. "share of the gap" tables list categories in this order.
CATEGORIES = (
    "full_adder", "half_adder", "adder_sum", "adder_carry", "xor_xnor", "mux",
    "complex", "simple", "buffer", "inverter", "other_logic", "tie",
    "sequential", "clock_gate", "macro",
)
CATEGORY_NOTES = {
    "full_adder": "one cell with a 3-input sum and a carry output",
    "half_adder": "one cell with a 2-input sum and a carry output",
    "adder_sum": "single-output 3-input XOR (a full-adder sum built as its own cell)",
    "adder_carry": "single-output 3-input majority (a full-adder carry built as its own cell)",
    "xor_xnor": "2-input XOR / XNOR (and wider parity other than 3 inputs)",
    "mux": "multiplexers, inverting or not",
    "complex": "unate multi-level gates: AOI / OAI / AO / OA families",
    "simple": "single-level AND / OR / NAND / NOR (any input inversions)",
    "buffer": "non-inverting single-input cells, clock buffers and delay cells included",
    "inverter": "inverting single-input cells, clock inverters included",
    "other_logic": "binate functions that are not XOR, majority or mux",
    "tie": "constant outputs",
    "sequential": "flip-flops and latches (multibit included)",
    "clock_gate": "integrated clock gates",
    "macro": "no function in the Liberty files (macros, physical cells, unknown)",
}
# Categories rolled up into the mapping patterns a gap is usually explained by.
PATTERNS = {
    "adders": ("full_adder", "half_adder", "adder_sum", "adder_carry"),
    "xor/xnor": ("xor_xnor",),
    "mux and gate choice": ("mux", "complex", "simple", "other_logic"),
    "buffering": ("buffer", "inverter"),
    "registers and clock gates": ("sequential", "clock_gate"),
    "ties": ("tie",),
}
BUFFERING = frozenset({"buffer", "inverter"})

# ---------------------------------------------------------------- liberty

_GROUP = re.compile(r"(\w+)\s*\(\s*([^)]*?)\s*\)\s*\{")
_ATTR = re.compile(r"(\w+)\s*:\s*(\"(?:[^\"\\]|\\.)*\"|[^;{}\n]*?)\s*(?:;|(?=$|\}))")
_COMPLEX = re.compile(r"(\w+)\s*\(([^)]*)\)\s*;")
_TOKEN = re.compile(r"\{|\}|" + _GROUP.pattern + "|" + _ATTR.pattern + "|" + _COMPLEX.pattern)
_SKIP_GROUPS = {"test_cell", "pg_pin", "internal_power", "timing", "leakage_power", "dynamic_current",
                "receiver_capacitance", "output_current_rise", "output_current_fall", "ccsn_first_stage",
                "ccsn_last_stage"}


class LibCell:
    __slots__ = ("name", "area", "inputs", "outputs", "functions", "clock_pins", "kind", "dont_use", "category", "three_state")

    def __init__(self, name):
        self.name = name
        self.area = 0.0
        self.inputs: list[str] = []
        self.outputs: list[str] = []
        self.functions: dict[str, str] = {}
        self.clock_pins: set[str] = set()
        self.kind = None            # "sequential" | "clock_gate" | None
        self.dont_use = False
        self.category = "macro"
        self.three_state = False


def _liberty_lines(path):
    """Lines with comments removed and backslash continuations joined."""
    pending, in_comment = "", False
    with open_text(path) as f:
        for line in f:
            if in_comment:
                end = line.find("*/")
                if end < 0:
                    continue
                line, in_comment = line[end + 2:], False
            while "/*" in line:
                start = line.index("/*")
                end = line.find("*/", start + 2)
                if end < 0:
                    line, in_comment = line[:start], True
                    break
                line = line[:start] + " " + line[end + 2:]
            s = line.rstrip()
            if s.endswith("\\"):
                pending += s[:-1] + " "
                continue
            yield pending + s
            pending = ""
    if pending:
        yield pending


def read_liberty(paths) -> dict[str, LibCell]:
    """Cells of every Liberty file; a later file's cell of the same name wins."""
    cells: dict[str, LibCell] = {}
    for path in paths:
        stack: list[tuple[str, str]] = []
        cell = None
        pin = None
        for line in _liberty_lines(path):
            for m in _TOKEN.finditer(line):
                tok = m.group(0)
                if tok == "{":
                    stack.append(("", ""))
                    continue
                if tok == "}":
                    if stack:
                        kind, name = stack.pop()
                        if kind == "cell":
                            _finish(cell)
                            cells[cell.name] = cell
                            cell = None
                        elif kind in ("pin", "bus"):
                            pin = None
                    continue
                if m.group(1):           # group header
                    kind, name = m.group(1), m.group(2).strip().strip('"')
                    stack.append((kind, name))
                    skipping = any(k in _SKIP_GROUPS for k, _ in stack[:-1])
                    if kind == "cell" and not skipping:
                        cell = LibCell(name)
                    elif kind == "pin" and cell is not None and not skipping:
                        pin = name
                    elif cell is not None and not skipping and kind in ("ff", "latch", "ff_bank", "latch_bank",
                                                                        "statetable"):
                        cell.kind = "sequential"
                    continue
                if cell is None or any(k in _SKIP_GROUPS for k, _ in stack):
                    continue
                key = m.group(3) or m.group(5)
                val = (m.group(4) if m.group(3) else m.group(6) or "").strip().strip('"')
                if key == "area" and pin is None:
                    try:
                        cell.area = float(val)
                    except ValueError:
                        pass
                elif key == "dont_use" and val.lower() == "true":
                    cell.dont_use = True
                elif key == "clock_gating_integrated_cell":
                    cell.kind = "clock_gate"
                elif pin is not None and key == "direction":
                    if val in ("output", "inout"):
                        cell.outputs.append(pin)
                    elif val == "input":
                        cell.inputs.append(pin)
                elif pin is not None and key == "three_state":
                    cell.three_state = True
                elif pin is not None and key == "function":
                    cell.functions[pin] = val
                elif pin is not None and key == "clock" and val.lower() == "true":
                    cell.clock_pins.add(pin)
    return cells


def _finish(cell: LibCell) -> None:
    if cell.kind:
        cell.category = cell.kind
        return
    classes = []
    for out in cell.outputs:
        fn = cell.functions.get(out)
        if fn is None:
            continue
        try:
            tt, n = truth_table(fn, cell.inputs)
        except ValueError:
            continue
        classes.append(classify_function(tt, n))
    cell.category = combine_outputs(classes)


# ---------------------------------------------------------------- functions

class _Parser:
    """Liberty boolean expression -> bit-parallel truth table over the cell's inputs.

    Precedence, highest first: ' and !, ^, & * and juxtaposition, | and +.
    """
    _TOK = re.compile(r"\s*(?:([A-Za-z_][\w\[\]\.]*)|([01])|(.))")

    def __init__(self, text, var_tables, mask):
        self.toks = [t for t in self._TOK.findall(text) if any(t)]
        self.i = 0
        self.vars = var_tables
        self.mask = mask

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        v = self.or_expr()
        if self.peek() is not None:
            raise ValueError("trailing tokens")
        return v

    def or_expr(self):
        v = self.and_expr()
        while (t := self.peek()) and t[2] in ("+", "|"):
            self.take()
            v |= self.and_expr()
        return v

    def and_expr(self):
        v = self.xor_expr()
        while (t := self.peek()) and (t[2] in ("*", "&") or t[0] or t[1] or t[2] in ("(", "!")):
            if t[2] in ("*", "&"):
                self.take()
            v &= self.xor_expr()
        return v

    def xor_expr(self):
        v = self.unary()
        while (t := self.peek()) and t[2] == "^":
            self.take()
            v ^= self.unary()
        return v

    def unary(self):
        t = self.peek()
        if t and t[2] == "!":
            self.take()
            return ~self.unary() & self.mask
        v = self.primary()
        while (t := self.peek()) and t[2] == "'":
            self.take()
            v = ~v & self.mask
        return v

    def primary(self):
        t = self.take()
        if t is None:
            raise ValueError("unexpected end")
        if t[0]:
            if t[0] not in self.vars:
                raise ValueError(f"unknown pin {t[0]}")
            return self.vars[t[0]]
        if t[1]:
            return self.mask if t[1] == "1" else 0
        if t[2] == "(":
            v = self.or_expr()
            if self.take() != ("", "", ")"):
                raise ValueError("missing )")
            return v
        raise ValueError(f"unexpected {t[2]}")


@functools.lru_cache(maxsize=None)
def var_table(i: int, n: int) -> int:
    """Truth table (bit m = value at minterm m) of input i among n inputs."""
    return sum(1 << m for m in range(1 << n) if m >> i & 1)


def truth_table(function: str, inputs: list[str]) -> tuple[int, int]:
    n = len(inputs)
    if n > 10:
        raise ValueError("too many inputs")
    mask = (1 << (1 << n)) - 1
    tables = {p: var_table(i, n) for i, p in enumerate(inputs)}
    return _Parser(function, tables, mask).parse(), n


def cofactor(tt: int, i: int, value: int, n: int) -> int:
    """tt with input i fixed to value, still over n inputs (independent of i)."""
    vi, shift, mask = var_table(i, n), 1 << i, (1 << (1 << n)) - 1
    if value:
        part = tt & vi
        return part | part >> shift
    part = tt & ~vi & mask
    return part | (part << shift) & mask


def support(tt: int, n: int) -> list[int]:
    return [i for i in range(n) if cofactor(tt, i, 0, n) != cofactor(tt, i, 1, n)]


def _literal(tt: int, n: int, mask: int):
    """(input, inverted) if tt is a single literal, else None."""
    for i in range(n):
        v = var_table(i, n)
        if tt == v:
            return i, False
        if tt == ~v & mask:
            return i, True
    return None


def classify_function(tt: int, n: int) -> str:
    mask = (1 << (1 << n)) - 1
    sup = support(tt, n)
    k = len(sup)
    if k == 0:
        return "tie"
    if k == 1:
        return "buffer" if tt == var_table(sup[0], n) else "inverter"
    parity = 0
    for i in sup:
        parity ^= var_table(i, n)
    if tt in (parity, ~parity & mask):
        return "adder_sum" if k == 3 else "xor_xnor"
    if k == 3 and _is_majority(tt, sup, n, mask):
        return "adder_carry"
    ones = bin(tt).count("1") >> (n - k)
    if ones in (1, (1 << k) - 1):
        return "simple"
    if _is_mux(tt, sup, n, mask):
        return "mux"
    for i in sup:
        c0, c1 = cofactor(tt, i, 0, n), cofactor(tt, i, 1, n)
        if c0 & ~c1 & mask and c1 & ~c0 & mask:
            return "other_logic"
    return "complex"


def _is_majority(tt, sup, n, mask) -> bool:
    for pol in itertools.product((False, True), repeat=3):
        lits = [(~var_table(i, n) & mask) if p else var_table(i, n) for i, p in zip(sup, pol)]
        a, b, c = lits
        maj = (a & b) | (a & c) | (b & c)
        if tt in (maj, ~maj & mask):
            return True
    return False


def _is_mux(tt, sup, n, mask) -> bool:
    """Some 1 or 2 select inputs split tt into cofactors that are each one data literal."""
    if not 3 <= len(sup) <= 7:
        return False
    for width in (1, 2):
        for sel in itertools.combinations(sup, width):
            data = set()
            ok = True
            for values in itertools.product((0, 1), repeat=width):
                f = tt
                for i, v in zip(sel, values):
                    f = cofactor(f, i, v, n)
                lit = _literal(f, n, mask)
                if lit is None or lit[0] in sel:
                    ok = False
                    break
                data.add(lit[0])
            if ok and len(data) >= 2 and set(sel) | data == set(sup):
                return True
    return False


def combine_outputs(classes: list[str]) -> str:
    if not classes:
        return "macro"
    s = set(classes)
    if "adder_sum" in s and "adder_carry" in s:
        return "full_adder"
    if "xor_xnor" in s and ("simple" in s or "adder_carry" in s):
        return "half_adder"
    if len(s) == 1:
        return classes[0]
    for c in CATEGORIES:          # several unrelated outputs: the most specific one names the cell
        if c in s:
            return c
    return classes[0]


def tied_function(cell: LibCell, ties: list[list[str]]) -> str | None:
    """Category of the cell's first output after joining each group of input pins to one input."""
    out = next((o for o in cell.outputs if o in cell.functions), None)
    if out is None:
        return None
    rename = {}
    for group in ties:
        for p in group[1:]:
            rename[p] = group[0]
    inputs = [p for p in cell.inputs if p not in rename]
    fn = re.sub(r"[A-Za-z_][\w\[\]\.]*", lambda m: rename.get(m.group(0), m.group(0)), cell.functions[out])
    try:
        tt, n = truth_table(fn, inputs)
    except ValueError:
        return None
    return classify_function(tt, n)


# ---------------------------------------------------------------- clock-class names

def clock_class(celltype: str) -> bool:
    """True for cells the library marks as clock cells by name (clock buffers, clock NAND2, ...)."""
    return parse_cell(celltype)["class"].startswith("clock_") and parse_cell(celltype)["class"] != "clock_gate"


def vt_of(celltype: str) -> str | None:
    return parse_cell(celltype)["vt"]


# ---------------------------------------------------------------- netlist

_INST = re.compile(r"^(\\\S+|[A-Za-z_][\w$]*)\s*(#\s*\(.*?\)\s*)?(\\\S+|[A-Za-z_][\w$]*)\s*(\[[^\]]*\])?\s*\((.*)\)\s*;?$",
                   re.S)
_CONN = re.compile(r"\.\s*(\\\S+|[A-Za-z_][\w$]*)\s*\(\s*((?:[^()]|\([^()]*\))*)\)")
_DECL = {"input", "output", "inout", "wire", "reg", "logic", "tri", "supply0", "supply1", "wand", "wor", "tri0", "tri1"}
_RANGE = re.compile(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]")
_CONST = re.compile(r"^(\d*)'[sS]?([bBoOdDhH])([0-9a-fA-FxXzZ_?]+)$")


class Module:
    __slots__ = ("name", "ports", "port_order", "widths", "instances", "assigns")

    def __init__(self, name):
        self.name = name
        self.ports: dict[str, str] = {}
        self.port_order: list[str] = []
        self.widths: dict[str, tuple[int, int]] = {}
        self.instances: list[tuple[str, str, list[tuple[str, str]]]] = []
        self.assigns: list[tuple[str, str]] = []


def _parse_modules(path) -> dict[str, Module]:
    mods: dict[str, Module] = {}
    cur = None
    for _, st in verilog_statements(path):
        st = re.sub(r"\(\*.*?\*\)", " ", st).strip().rstrip(";").strip()
        if not st:
            continue
        head = st.split(None, 1)[0]
        if head == "module":
            m = re.match(r"module\s+(\\\S+|[A-Za-z_][\w$]*)\s*(?:#\s*\(.*?\)\s*)?(?:\((.*)\))?", st, re.S)
            cur = Module(strip_escape(m.group(1)))
            mods[cur.name] = cur
            kind, rng = None, ""
            for part in _split_top(m.group(2) or ""):    # ANSI headers: "input [3:0] a, b"
                part = part.strip()
                words = part.split()
                if words and words[0] in ("input", "output", "inout"):
                    kind = words[0]
                    found = _RANGE.search(part)
                    rng = found.group(0) if found else ""
                    _declare(cur, kind, part[len(kind):])
                elif words and kind:
                    _declare(cur, kind, rng + " " + part)
                elif words:
                    cur.port_order.append(strip_escape(words[-1]))
            continue
        if cur is None:
            continue
        if head == "endmodule":
            cur = None
            continue
        if head in _DECL:
            _declare(cur, head, st[len(head):])
            continue
        if head == "assign":
            m = re.match(r"assign\s+(.+?)\s*=\s*(.+)$", st, re.S)
            if m:
                cur.assigns.append((m.group(1), m.group(2)))
            continue
        m = _INST.match(st + ";")
        if not m:
            continue
        conns = [(strip_escape(c.group(1)), c.group(2).strip()) for c in _CONN.finditer(m.group(5))]
        cur.instances.append((strip_escape(m.group(1)), strip_escape(m.group(3)), conns))
    return mods


def _declare(mod: Module, kind: str, rest: str) -> None:
    rng = _RANGE.search(rest)
    body = _RANGE.sub(" ", rest)
    for w in re.findall(r"\\\S+|[A-Za-z_][\w$]*", body):
        if w in _DECL or w == "signed":
            continue
        name = strip_escape(w)
        if rng:
            mod.widths[name] = (int(rng.group(1)), int(rng.group(2)))
        if kind in ("input", "output", "inout"):
            mod.ports[name] = kind
            if name not in mod.port_order:
                mod.port_order.append(name)


def _bits(expr: str, widths: dict) -> list[str]:
    """MSB-first bit names of a connection expression; constants become '1'b0' / '1'b1'."""
    expr = expr.strip()
    if not expr:
        return []
    if expr.startswith("{") and expr.endswith("}"):
        inner = expr[1:-1]
        rep = re.match(r"^\s*(\d+)\s*\{(.*)\}\s*$", inner, re.S)
        if rep:
            return _bits("{" + rep.group(2) + "}", widths) * int(rep.group(1))
        out = []
        for part in _split_top(inner):
            out += _bits(part, widths)
        return out
    c = _CONST.match(expr)
    if c:
        size, base, digits = c.groups()
        value = int(digits.replace("_", "").replace("x", "0").replace("X", "0").replace("z", "0").replace("Z", "0")
                    .replace("?", "0"), {"b": 2, "o": 8, "d": 10, "h": 16}[base.lower()])
        size = int(size) if size else 32
        return [f"1'b{value >> i & 1}" for i in reversed(range(size))]
    if re.fullmatch(r"\d+", expr):
        return [f"1'b{int(expr) & 1}"]
    m = re.fullmatch(r"(\\\S+\s|[A-Za-z_][\w$]*)\s*(?:\[\s*(-?\d+)\s*(?::\s*(-?\d+)\s*)?\])?", expr)
    if not m:
        return [strip_escape(expr)]
    name = strip_escape(m.group(1).strip())
    if m.group(2) is not None and m.group(3) is None:
        return [f"{name}[{m.group(2)}]"]
    if m.group(2) is not None:
        hi, lo = int(m.group(2)), int(m.group(3))
    elif name in widths:
        hi, lo = widths[name]
    else:
        return [name]
    step = -1 if hi >= lo else 1
    return [f"{name}[{i}]" for i in range(hi, lo + step, step)]


def _split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


class Netlist:
    """Flattened leaf instances and the nets that join them.

    inst_type[i] / inst_name[i]: leaf cell type and full hierarchical name.
    pins[i]: list of (pin, net id).  net_name[n]: one name for each net
    (the highest-level name it has).  Constant nets are '1'b0' and '1'b1'.
    """

    def __init__(self):
        self.inst_name: list[str] = []
        self.inst_type: list[str] = []
        self.pins: list[list[tuple[str, int]]] = []
        self.net_name: list[str] = []
        self.top = None

    def __len__(self):
        return len(self.inst_name)


def read_netlist(path, top: str | None = None) -> Netlist:
    mods = _parse_modules(path)
    if not mods:
        raise ValueError(f"{path}: no module found")
    used = {t for m in mods.values() for _, t, _ in m.instances}
    if top is None:
        roots = [m for m in mods if m not in used]
        top = roots[0] if len(roots) == 1 else max(roots or mods, key=lambda m: _size(mods, m, {}))
    parent = []

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    names: list[str] = []
    ids: dict[str, int] = {}

    def net(name):
        i = ids.get(name)
        if i is None:
            i = ids[name] = len(names)
            names.append(name)
            parent.append(i)
        return i
    for c in ("1'b0", "1'b1"):
        net(c)
    nl = Netlist()
    nl.top = top
    raw_pins: list[list[tuple[str, int]]] = []

    def flatten(mod: Module, prefix: str, bind: dict[str, int]):
        def local(bit):
            if bit.startswith("1'b"):
                return net(bit)
            if bit in bind:
                return bind[bit]
            return net(prefix + bit)
        for lhs, rhs in mod.assigns:
            for a, b in zip(_bits(lhs, mod.widths), _bits(rhs, mod.widths)):
                ra, rb = find(local(a)), find(local(b))
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)     # keep the earlier (higher-level) name
        for typ, inst, conns in mod.instances:
            child = mods.get(typ)
            if child is None:
                nl.inst_name.append(prefix + inst)
                nl.inst_type.append(typ)
                row = []
                for pin, expr in conns:
                    bits = _bits(expr, mod.widths)
                    if len(bits) == 1:
                        row.append((pin, local(bits[0])))
                    else:                               # a bus pin of a leaf cell: pin[k], LSB last
                        row += [(f"{pin}[{k}]", local(b)) for k, b in zip(range(len(bits) - 1, -1, -1), bits)]
                raw_pins.append(row)
                continue
            child_bind = {}
            for pin, expr in conns:
                pbits = _bits(pin, child.widths)
                for pb, b in zip(reversed(pbits), reversed(_bits(expr, mod.widths))):
                    child_bind[pb] = local(b)
            flatten(child, prefix + inst + "/", child_bind)
    top_mod = mods[top]
    for port in top_mod.ports:
        for bit in _bits(port, top_mod.widths):
            net(bit)
    flatten(top_mod, "", {})
    nl.pins = [[(p, find(n)) for p, n in row] for row in raw_pins]
    nl.net_name = [names[find(i)] for i in range(len(names))]
    nl.top_ports = {b: (d, find(ids[b])) for p, d in top_mod.ports.items() for b in _bits(p, top_mod.widths)
                    if b in ids}
    return nl


def _size(mods, m, memo):
    if m in memo:
        return memo[m]
    memo[m] = 0
    memo[m] = sum(1 + _size(mods, t, memo) if t in mods else 1 for _, t, _ in mods[m].instances)
    return memo[m]


class Graph:
    """Driver / load view of a Netlist, with each instance's Liberty category."""

    def __init__(self, nl: Netlist, lib: dict[str, LibCell]):
        self.nl = nl
        self.lib = lib
        n = len(nl)
        self.category = [lib[t].category if t in lib else "macro" for t in nl.inst_type]
        self.area = [lib[t].area if t in lib else 0.0 for t in nl.inst_type]
        self.driver: dict[int, tuple[int, str]] = {}
        self.loads: dict[int, list[tuple[int, str]]] = defaultdict(list)
        self.inputs: list[list[tuple[str, int]]] = [[] for _ in range(n)]
        self.outputs: list[list[tuple[str, int]]] = [[] for _ in range(n)]
        self.unknown_types = set()
        for i, (t, row) in enumerate(zip(nl.inst_type, nl.pins)):
            cell = lib.get(t)
            if cell is None:
                self.unknown_types.add(t)
            outs = set(cell.outputs) if cell else None
            for pin, net in row:
                base = pin.split("[")[0]
                is_out = base in outs if outs is not None else bool(
                    re.match(r"^(Y\d*|Z\d*|ZN|Q\d*|QN\d*|X|O\d*|S|CO|CON|SUM|COUT)$", base))
                if is_out:
                    self.driver[net] = (i, pin)
                    self.outputs[i].append((pin, net))
                else:
                    self.loads[net].append((i, pin))
                    self.inputs[i].append((pin, net))
        ports = getattr(nl, "top_ports", {}).values()
        self.output_port_nets = {net for d, net in ports if d != "input"}
        self.clock_nets = self._trace_clock()

    def is_clock_pin(self, i: int, pin: str) -> bool:
        cell = self.lib.get(self.nl.inst_type[i])
        return bool(cell and pin.split("[")[0] in cell.clock_pins)

    def _trace_clock(self) -> set[int]:
        """Nets on a clock network: from sequential/ICG clock pins back through buffers, inverters and gates."""
        work = [net for i, row in enumerate(self.inputs) for pin, net in row if self.is_clock_pin(i, pin)]
        seen = set(work)
        while work:
            n = work.pop()
            d = self.driver.get(n)
            if d is None:
                continue
            i = d[0]
            cat = self.category[i]
            if cat in ("sequential", "macro"):
                continue
            if cat not in ("buffer", "inverter", "clock_gate") and not clock_class(self.nl.inst_type[i]):
                continue
            for pin, m in self.inputs[i]:
                if m not in seen:
                    seen.add(m)
                    work.append(m)
        return seen


# ---------------------------------------------------------------- DEF

def _def_statements(path, section):
    """Yield (statement tokens) of one DEF section (COMPONENTS, NETS, ...) and the DBU per micron first."""
    dbu = 1000.0
    inside = False
    buf: list[str] = []
    with open_text(path) as f:
        for line in f:
            s = line.strip()
            if not inside:
                m = re.match(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", s)
                if m:
                    dbu = float(m.group(1))
                    yield ("__DBU__", dbu)
                if re.match(rf"{section}\s+\d+", s):
                    inside = True
                continue
            if s.startswith(f"END {section}"):
                break
            buf.append(s)
            if s.endswith(";"):
                st = " ".join(buf)
                buf = []
                yield st.rstrip(";").split()


def def_name(name: str) -> str:
    return name.replace("\\", "")


def read_def_locations(path) -> dict[str, tuple[float, float]]:
    """Component origin (um) by instance name (escapes removed)."""
    loc = {}
    dbu = 1000.0
    for st in _def_statements(path, "COMPONENTS"):
        if st[0] == "__DBU__":
            dbu = st[1]
            continue
        if not st or st[0] != "-":
            continue
        for k, tok in enumerate(st):
            if tok in ("PLACED", "FIXED", "COVER") and k + 4 < len(st) and st[k + 1] == "(":
                loc[def_name(st[1])] = (float(st[k + 2]) / dbu, float(st[k + 3]) / dbu)
                break
    return loc


def read_def_routing(path, special=False):
    """Yield (net name, USE (SIGNAL, CLOCK, ...), {layer: wire length um}, via count) for every routed net."""
    dbu = 1000.0
    for st in _def_statements(path, "SPECIALNETS" if special else "NETS"):
        if st[0] == "__DBU__":
            dbu = st[1]
            continue
        if not st or st[0] != "-":
            continue
        lengths: dict[str, float] = defaultdict(float)
        vias = 0
        layer = None
        prev = None
        k = 2
        while k < len(st):
            tok = st[k]
            if tok in ("ROUTED", "NEW", "FIXED", "COVER", "NOSHIELD") and k + 1 < len(st):
                layer, prev = st[k + 1], None
                k += 2
                continue
            if tok == "+" or tok in ("USE", "SOURCE", "WEIGHT", "PROPERTY", "SHAPE"):
                if tok == "+" and k + 1 < len(st) and st[k + 1] not in ("ROUTED", "FIXED", "COVER", "NOSHIELD"):
                    layer = None
                k += 1
                continue
            if tok in ("RECT", "VIRTUAL"):
                k += 6 if tok == "RECT" else 4
                continue
            if tok in ("TAPER", ):
                k += 1
                continue
            if tok in ("TAPERRULE", "STYLE", "MASK"):
                k += 2
                continue
            if tok == "(" and layer is not None and k + 2 < len(st):
                x, y = st[k + 1], st[k + 2]
                px = prev[0] if prev and x == "*" else (float(x) if x != "*" else 0.0)
                py = prev[1] if prev and y == "*" else (float(y) if y != "*" else 0.0)
                if prev is not None:
                    lengths[layer] += (abs(px - prev[0]) + abs(py - prev[1])) / dbu
                prev = (px, py)
                k += 3
                while k < len(st) and st[k] != ")":
                    k += 1
                k += 1
                continue
            if layer is not None and prev is not None and re.match(r"^[A-Za-z]", tok):
                vias += 1          # a via name after a point
            k += 1
        if lengths:
            use = st[st.index("USE") + 1] if "USE" in st[:-1] else "SIGNAL"
            yield def_name(st[1]), use, dict(lengths), vias


# ---------------------------------------------------------------- formatting

def fmt_num(v, nd=1):
    if v is None:
        return "–"
    if isinstance(v, int):
        return f"{v:,}"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.{nd}f}"
    return f"{v:.3f}".rstrip("0").rstrip(".") if v else "0"


def md_table(headers, rows) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(c if isinstance(c, str) else fmt_num(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def load(netlist, liberty, top=None, quiet=False) -> Graph:
    lib = read_liberty(liberty)
    g = Graph(read_netlist(netlist, top), lib)
    if g.unknown_types and not quiet:
        print(f"note: {netlist}: {len(g.unknown_types)} cell types not in the Liberty files "
              f"(counted as macro): {sorted(g.unknown_types)[:8]}", file=sys.stderr)
    return g
