#!/usr/bin/env python3
"""Anonymize a boson run (netlist, SDC, timing/QoR/check_timing reports, log,
decision journal) with ONE consistent name mapping, so cross-references
between files still work after the customer's names are gone.

    # anonymize everything into anon/, keep the mapping locally
    anonymize.py --out anon --map name_map.json \\
        --netlist run/netlist.v --sdc run/out.sdc --timing run/timing.rpt \\
        --timing-json run/timing.json --qor run/qor.rpt --check-timing run/check_timing.rpt \\
        --log run/boson.log --journal run/decisions.jsonl \\
        [--rtl src/*.sv] [--liberty libs/*.lib] [--top NAME] [--literal ACME --literal projectX]
    anonymize.py --run-dir run --out anon --map name_map.json      # auto-discover inputs

    anonymize.py --map name_map.json --encode 'u_core/alu/add_17'   # raw -> token (for REPORT.md)
    anonymize.py --map name_map.json --decode 'u3/u9/add_o2'        # token -> raw (LOCAL use only)
    anonymize.py --map name_map.json --check boson-debug-bundle[.tar.gz]   # leak scan; exit 1 on leak

Names become stable tokens: each hierarchy segment separately (u3/u9/r12[4]),
bus indices and boson's own suffixes (_reg, __qn_bsn) kept; role prefixes:
top, clk<N> (clock), in<N>/out<N>/io<N>/p<N> (ports), m<N> (module), u<N>
(hierarchy instance), r<N> (register), c<N> (cell instance), w<N> (net),
x<N> (other), <op>_o<N> (operator-like names such as add_17).  Tokens are
numbered in HMAC(salt, name) order, so neither order nor a dictionary attack
reveals the original.  Vendor cell-library prefixes/suffixes become LIBX;
function and drive (NAND2_X4, OR5x1) are kept.  Paths, emails, hostnames,
dates, usernames and --literal strings are replaced.  name_map.json never
goes in a bundle.  See ../references/privacy.md for the exact rules.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bdlib import _strip_line_comment, open_text, strip_escape, verilog_statements  # noqa: E402

MAP_SCHEMA = 1

ROLES = ["top", "clock", "in", "out", "io", "port", "module", "reg", "hier", "cell", "net", "other"]
RANK = {r: i for i, r in enumerate(ROLES)}
PREFIX = {"clock": "clk", "in": "in", "out": "out", "io": "io", "port": "p", "module": "m",
          "hier": "u", "reg": "r", "cell": "c", "net": "w", "other": "x"}
TOKEN_RE = re.compile(r"^(?:top|clk\d+|in\d+|out\d+|io\d+|p\d+|m\d+|u\d+|r\d+|c\d+|w\d+|x\d+|[a-z]+_o\d+)$")

# Tool-generated anonymous names carry no customer information: passed through unchanged.
TOOL_ANON = re.compile(r"^(?:n|g|gs|gn|N|U|net|_)\d+_?$|^_tie(?:lo|hi)_net_\d+$|^_\d+_$")
# boson's own suffixes on RTL names: kept, so a register and its Q net share one token.
ROLE_SUFFIX = re.compile(r"(?:__qn_bsn|__bsn\w*|_bsn\d*|_reg|_gs\d+|_gn\d+|_g\d+)$")
OP_KIND = re.compile(r"^(add|sub|mul|mult|div|mod|rem|cmp|eq|ne|lt|le|gt|ge|shl|shr|sra|sll|srl|sh|mux|pmux|neg|abs|min|max|inc|dec|csa|fma|mac|alu|sum|prod)_\w*?\d+$", re.I)

VERILOG_KW = set("""
module endmodule macromodule input output inout wire reg logic tri tri0 tri1 triand trior wand wor supply0 supply1
assign always always_ff always_comb always_latch initial begin end if else case casex casez endcase default for while
repeat forever generate endgenerate genvar parameter localparam defparam function endfunction task endtask integer real
time realtime signed unsigned posedge negedge or and nand nor xor xnor not buf bufif0 bufif1 notif0 notif1 specify
endspecify primitive endprimitive table endtable package endpackage import export typedef enum struct union packed
interface endinterface modport bit byte shortint int longint void return break continue unique priority automatic
static const var string class endclass extends virtual pure extern this super new null type parameter_override
include define ifdef ifndef elsif endif undef timescale default_nettype celldefine endcelldefine resetall
pullup pulldown small medium large scalared vectored highz0 highz1 strong0 strong1 weak0 weak1 pull0 pull1
assert assume cover property endproperty sequence endsequence disable iff inside with foreach do final
""".split())

SDC_WORDS = set("""
create_clock create_generated_clock set_clock_latency set_clock_uncertainty set_clock_transition set_clock_groups
set_input_delay set_output_delay set_max_delay set_min_delay set_false_path set_multicycle_path set_load set_driving_cell
set_input_transition set_max_transition set_max_capacitance set_max_fanout set_case_analysis set_disable_timing
set_dont_touch set_dont_use set_size_only set_ideal_network set_propagated_clock set_units set_operating_conditions
set_wire_load_model set_timing_derate set_max_area set_clock_gating_check set_sense set_data_check set_min_pulse_width
set_load set_fanout_load set_port_fanout_number set_resistance set_logic_zero set_logic_one set_logic_dc group_path
get_ports get_pins get_cells get_nets get_clocks get_lib_cells get_libs get_designs all_inputs all_outputs all_clocks
all_registers current_design current_instance set expr list foreach if else puts source proc return lappend lindex llength
concat join incr upvar global namespace info string format regexp regsub true false
""".split())

# Generic English / EDA words: a customer object with one of these names is still mapped in
# structured positions (netlist, SDC objects, report point columns) but not in free text.
VOCAB = set("""
a an the of to in on at by for from with without and or not no yes is are was were be been has have had it its this that
these those as into than then so if else all any each per via over under after before up down out off only also more less
data clock clk_period time arrival required slack path paths point points net nets cell cells pin pins port ports input
output inputs outputs inout wire wires reg regs register registers module modules design top instance instances hierarchy
library lib setup hold max min rise fall edge rising falling ideal propagated network delay delays latency uncertainty
skew transition trans cap capacitance fanout load loads drive driver drivers area power leakage dynamic internal switching
total wns tns endpoint endpoints startpoint startpoints group groups type types report reports summary status met violated
violation violations violating unconstrained constrained constraint constraints check checks warning warnings error errors
info information note notes message messages compile synthesis synthesized map mapping mapped optimize optimized
optimization effort fast low medium high ultra done begin end start stop stage stages pass passes round rounds iteration
loop layout place placement placed route routing cts tree buffer buffers inverter inverters size sizing upsize upsizes
downsize downsizes clone clones repair repaired timing hold_repair setup_repair recipe candidate candidates option options
default value values count counts number total true false none null on off enable enabled disable disabled reset set clear
mode modes corner corners scenario scenarios voltage temperature process temp vt lvt hvt svt rvt slvt ulvt ff ss tt
gate gates gating clock_gating bank banking banked mbff multibit flop flops flip latch latches sequential combinational
logic depth level levels adder adders multiplier multipliers mux muxes comparator shifter carry sum product operator
operators architecture topology ripple kogge stone brent kung sklansky han carlson booth wallace dadda csa prefix
x y z q d clk_gate in_port out_port seconds second ms ns ps um mw uw nw fs pf ff kb mb gb cpu gpu thread threads memory
result results file files line lines column name names object objects kind domain action chosen reason inputs impact
before after delta metrics probe shipped rejected rolled_back skipped alternative alternatives verdict why
read write written wrote loaded load loading saved save keep kept drop dropped removed remove merged merge added add
new old other unknown generic real ok fail failed pass passed success incomplete complete partial
""".split())

KNOWN_EXT = ["v.gz", "sv.gz", "lib.gz", "def.gz", "spef.gz", "jsonl.gz", "json.gz", "v", "sv", "svh", "vh", "vhd",
             "vhdl", "vg", "lib", "db", "lef", "tlef", "def", "sdc", "tcl", "json", "jsonl", "rpt", "log", "gz", "vcd",
             "saif", "fsdb", "spef", "sdf", "upf", "cpf", "f", "txt", "csv", "yaml", "yml", "py", "sh", "md", "tar",
             "tgz", "zip", "out"]
_EXT_ALT = "|".join(re.escape(e) for e in sorted(KNOWN_EXT, key=len, reverse=True))
ABS_PATH = re.compile(r"(?<![\w\]\)\[:/.$\\<>*?-])(?:~/?|/)[\w.+@%~-]+(?:/[\w.+@%~-]*)*")
REL_PATH = re.compile(rf"(?<![\w/.\\$<>-])(?:[\w.+-]+/)*[A-Za-z0-9_+-][\w.+-]*\.(?:{_EXT_ALT})(?![\w])")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>)\]]+", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
HOST = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+(?:com|net|org|io|ai|dev|local|lan|corp|internal|intra|edu|gov|cloud|co|us|uk|de|cn|jp|kr|tw|in)\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}"
    r"(?:\s+\d{2}:\d{2}(?::\d{2})?)?(?:\s+[A-Z]{3,4})?(?:\s+\d{4})?\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b")
GENERIC_FILE_WORDS = set("""
netlist boson decisions decision constraints constraint timing qor rpt log logs run runs out sdc json jsonl final synth syn
post pre place placed cts route routed report reports work tmp scratch flow script scripts check_timing check summary
journal anon bundle debug opt eco signoff golden baseline candidate rtl src hdl lib libs liberty lef def spef sdf vcd saif
gate gates mapped compile compiled result results v1 v2 v3 old new latest
""".split())
ALLOW_HOSTS = ("partcl.com", "github.com", "anthropic.com", "claude.ai", "claude.com")

MASTER = re.compile(r"(?P<esc>\\[^\s\\]+)|(?P<lit>\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+)|(?P<num>\d[\w.]*)|(?P<id>[A-Za-z_][\w$]*)")
WORD = re.compile(r"[A-Za-z_][\w$]*")
QUOTED = re.compile(r"(['`\"])([^'`\"\s]{1,400})\1")
# a quoted string is harvested as a design object only when it looks like one
OBJ_QUOTED = re.compile(r"(?i)\b(?:nets?|pins?|ports?|cells?|instances?|insts?|modules?|registers?|regs?|clocks?|objects?|"
                        r"signals?|designs?|endpoints?|startpoints?|hierarch(?:y|ies)|subjects?|drivers?|loads?|flops?)\s+"
                        r"(['`\"])([^'`\"\s]{1,400})\1")

# Vendor-library tags in cell names (prefix or suffix); group 'tag' is replaced, the rest kept.
KNOWN_TAGS = [
    re.compile(r"^(?P<tag>sky130_[a-z]+_sc_[a-z0-9]+__)"),
    re.compile(r"^(?P<tag>gf180mcu_[a-z]+_sc_[a-z0-9]+__)"),
    re.compile(r"^(?P<tag>sg13g2_)"),
    re.compile(r"^(?P<tag>ihp_[a-z0-9]+_)"),
    re.compile(r"(?P<tag>_ASAP7_\d+t)(?:_(?:R|L|SL|SRAM))?$"),
    re.compile(r"[A-Z0-9](?P<tag>BWP[0-9A-Z]*?)(?:ULVT|ELVT|LVT|SVT|HVT|ULL|LL)?$"),
    re.compile(r"(?P<tag>_[0-9]{1,2}T[0-9A-Z]*(?:_[A-Z0-9]+)?)$"),  # e.g. _9T_A or _12TH
]
SEQ_HINT = re.compile(r"(?i)dff|sdf|latch|dlh|dll|^df|__df|__sdf|__dl|__edf|lat[a-z]?\d|mbff")


def split_suffix(word: str) -> tuple[str, str]:
    m = ROLE_SUFFIX.search(word)
    if m:
        if m.start() == 0:
            return "", word          # the word is only a boson suffix (e.g. '__qn_bsn' after a bus index)
        return word[: m.start()], word[m.start():]
    return word, ""


def _hm(salt: str, s: str) -> str:
    return hmac.new(salt.encode(), s.encode(), hashlib.sha256).hexdigest()


class Mapper:
    def __init__(self, salt: str | None = None):
        self.salt = salt or secrets.token_hex(16)
        self.roles: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.paths: dict[str, str] = {}
        self.literals: dict[str, str] = {}
        self.celltypes_raw: set[str] = set()
        self.celltypes: dict[str, str] = {}
        self.lib_tags: dict[str, str] = {}
        self.pins: set[str] = set()
        self.counters: dict[str, int] = {}
        self.top: str | None = None
        self.user_tag_res: list[re.Pattern] = []
        self.path_stems: set[str] = set()
        # netlist bookkeeping for port roles
        self._modules: set[str] = set()
        self._instantiated: set[str] = set()
        self._ports: dict[str, list[tuple[str, str]]] = {}
        self._lit_res: list[tuple[re.Pattern, str]] = []
        self._tag_re: re.Pattern | None = None

    # ------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: Path) -> "Mapper":
        d = json.loads(path.read_text())
        m = cls(d["salt"])
        m.names, m.roles, m.paths = d.get("names", {}), d.get("roles", {}), d.get("paths", {})
        m.literals, m.celltypes, m.lib_tags = d.get("literals", {}), d.get("celltypes", {}), d.get("lib_tags", {})
        m.pins, m.counters, m.top = set(d.get("pins", [])), d.get("counters", {}), d.get("top")
        m.path_stems = set(d.get("path_stems", []))
        m.celltypes_raw = set(m.celltypes)
        m._compile_literals()
        return m

    def save(self, path: Path) -> None:
        d = {"schema": MAP_SCHEMA, "note": "LOCAL ONLY - never send this file. It decodes every token in the bundle.",
             "created": time.strftime("%Y-%m-%d"), "salt": self.salt, "top": self.top, "names": self.names,
             "roles": self.roles, "paths": self.paths, "literals": self.literals, "celltypes": self.celltypes,
             "lib_tags": self.lib_tags, "pins": sorted(self.pins), "counters": self.counters,
             "path_stems": sorted(self.path_stems)}
        path.write_text(json.dumps(d, indent=1, sort_keys=True))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------ harvesting
    def add_word(self, base: str, role: str) -> None:
        if not base or TOOL_ANON.match(base) or base in VERILOG_KW or base.isdigit() or not base.strip("_"):
            return
        cur = self.roles.get(base)
        if cur is None or RANK[role] < RANK[cur]:
            self.roles[base] = role

    def add_seg(self, seg: str, role: str) -> None:
        for w in WORD.findall(strip_escape(seg.strip())):
            base, _ = split_suffix(w)
            self.add_word(base, role)

    def add_name(self, name: str, role: str) -> None:
        name = strip_escape(name.strip())
        segs = [s for s in name.split("/") if s]
        for s in segs[:-1]:
            self.add_seg(s, "hier")
        if segs:
            self.add_seg(segs[-1], role)

    def add_literal(self, s: str) -> None:
        s = s.strip()
        if len(s) >= 3 and s not in self.literals:
            self.literals[s] = f"<redacted{len(self.literals) + 1}>"

    def add_path_stem(self, p: str) -> None:
        stem = Path(p).name
        for e in sorted(KNOWN_EXT, key=len, reverse=True):
            if stem.endswith("." + e):
                stem = stem[: -len(e) - 1]
                break
        parts = [w for w in re.split(r"[_.\-]+", stem.lower()) if w]
        if len(stem) >= 4 and not all(w in VOCAB or w in GENERIC_FILE_WORDS or w.isdigit() for w in parts):
            self.path_stems.add(stem)

    def harvest_netlist(self, path: Path) -> None:
        mod_re = re.compile(r"^\s*(?:module|macromodule)\s+(\\\S+|[A-Za-z_][\w$]*)")
        with open_text(path) as f:
            for line in f:
                m = mod_re.match(line)
                if m:
                    self._modules.add(strip_escape(m.group(1)))
        inst_re = re.compile(r"^(\\\S+|[A-Za-z_][\w$]*)\s*(#\s*\(.*?\)\s*)?(\\\S+|[A-Za-z_][\w$]*)\s*(\[[^\]]*\])?\s*\((.*)\)\s*;$", re.S)
        conn_re = re.compile(r"\.\s*(\\\S+|[A-Za-z_][\w$]*)\s*\(")
        cur = None
        for _, st in verilog_statements(path):
            head = st.split(None, 1)[0] if st.split() else ""
            if head in ("module", "macromodule"):
                m = mod_re.match(st)
                cur = strip_escape(m.group(1)) if m else None
                if cur:
                    self.add_word(cur, "module")
                    hdr = st[m.end():]
                    for dm in re.finditer(r"\b(input|output|inout)\b([^,;()]*)", hdr):
                        for w in self._decl_names(dm.group(2)):
                            self._ports.setdefault(cur, []).append((dm.group(1), w))
                    for w in WORD.findall(re.sub(r"\[[^\]]*\]", " ", hdr)):
                        if w not in VERILOG_KW:
                            self.add_name(w, "net")
                continue
            if head in ("endmodule", "end"):
                continue
            if head in ("input", "output", "inout"):
                for w in self._decl_names(st[len(head):]):
                    if cur:
                        self._ports.setdefault(cur, []).append((head, w))
                    self.add_name(w, "net")
                continue
            if head in ("wire", "reg", "logic", "tri", "supply0", "supply1", "wand", "wor", "tri0", "tri1", "assign",
                        "parameter", "localparam", "defparam", "genvar", "integer"):
                body = re.sub(r"\[[^\]]*\]", " ", st[len(head):])
                body = re.sub(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+", " ", body)
                for w in re.findall(r"\\\S+|[A-Za-z_][\w$]*", body):
                    if w not in VERILOG_KW:
                        self.add_name(w, "other" if head in ("parameter", "localparam", "defparam") else "net")
                continue
            if st.startswith("(*") or head.startswith("`"):
                continue
            m = inst_re.match(st)
            if not m:
                continue
            typ, inst, conns = strip_escape(m.group(1)), m.group(3), m.group(5)
            if typ in self._modules:
                self._instantiated.add(typ)
                self.add_name(inst, "hier")
                pins_are_lib = False
            else:
                self.celltypes_raw.add(typ)
                base = strip_escape(inst)
                self.add_name(base, "reg" if SEQ_HINT.search(typ) else "cell")
                pins_are_lib = True
            for cm in conn_re.finditer(conns):
                if pins_are_lib:
                    self.pins.add(strip_escape(cm.group(1)))
            body = conn_re.sub(" ( ", conns)
            body = re.sub(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+", " ", body)
            for w in re.findall(r"\\\S+|[A-Za-z_][\w$]*", body):
                if w not in VERILOG_KW:
                    self.add_name(w, "net")

    @staticmethod
    def _decl_names(s: str) -> list[str]:
        s = re.sub(r"\[[^\]]*\]", " ", s)
        return [w for w in re.findall(r"\\\S+|[A-Za-z_][\w$]*", s) if w not in VERILOG_KW]

    def harvest_sdc(self, path: Path) -> None:
        with open_text(path) as f:
            for line in f:
                line = _sdc_strip_comment(line)
                for m in re.finditer(r"\[\s*get_(ports|clocks|pins|cells|nets)\s+(?:-\w+\s+)*(\{[^}]*\}|[^\]]+)\]", line):
                    kind, objs = m.group(1), m.group(2).strip("{} ")
                    role = {"ports": "port", "clocks": "clock", "pins": "other", "cells": "other", "nets": "net"}[kind]
                    for o in objs.split():
                        if not o.startswith("-"):
                            self.add_name(o.replace("*", " ").replace("?", " "), role)
                for m in re.finditer(r"-(?:name|clock|source_clock|master_clock)\s+(\{[^}]*\}|\S+)", line):
                    for o in m.group(1).strip("{}").split():
                        if not o.startswith("[") and not o.startswith("-"):
                            self.add_name(o, "clock")
                if re.match(r"\s*create_clock\b", line):
                    for m in re.finditer(r"\[\s*get_ports\s+(\{[^}]*\}|[^\]]+)\]", line):
                        for o in m.group(1).strip("{} ").split():
                            self.add_name(o, "clock")
                for m in re.finditer(r"-(?:from|to|through|rise_from|fall_from|rise_to|fall_to)\s+(\{[^}]*\}|[A-Za-z_\\][^\s\]]*)", line):
                    for o in m.group(1).strip("{}").split():
                        if not o.startswith(("[", "-", "$")):
                            self.add_name(o.replace("*", " ").replace("?", " "), "other")

    def harvest_timing_text(self, path: Path) -> None:
        pt = re.compile(r"^\s+(\S+)\s+\(([^)\s]+)\)")
        with open_text(path) as f:
            for line in f:
                m = re.match(r"\s*(Startpoint|Endpoint):\s+(\S+)", line)
                if m:
                    self.add_name(m.group(2), "other")
                for cm in re.finditer(r"clocked by (\S+?)\)?(?:\s|$)", line):
                    self.add_name(cm.group(1).rstrip(")"), "clock")
                m = re.match(r"\s*clock (\S+) \((?:rise|fall) edge\)", line)
                if m:
                    self.add_name(m.group(1), "clock")
                m = re.match(r"\s*Path Group:\s+(\S+)", line)
                if m:
                    self.add_name(m.group(1), "clock")
                m = re.match(r"\s*Design\s*:\s*(\S+)", line)
                if m:
                    self.top = self.top or m.group(1)
                m = pt.match(line)
                if m:
                    obj, cell = m.group(1), m.group(2)
                    if cell == "net":
                        self.add_name(obj, "net")
                    elif obj.lower() in VOCAB or cell in ("MET", "VIOLATED", "UNCONSTRAINED"):
                        pass
                    elif cell not in ("rise", "fall", "ideal", "propagated", "in", "out", "inout"):
                        if "/" in obj:
                            inst, pin = obj.rsplit("/", 1)
                            self.add_name(inst, "cell")
                            self.pins.add(pin)
                        else:
                            self.add_name(obj, "port")
                        if re.match(r"^[A-Za-z_][\w$]*$", cell):
                            self.celltypes_raw.add(cell)
                    elif "/" not in obj:
                        self.add_name(obj, "port")

    def harvest_timing_json(self, path: Path) -> None:
        with open_text(path) as f:
            try:
                d = json.load(f)
            except json.JSONDecodeError:
                return
        def walk(o, key=None):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, k)
            elif isinstance(o, list):
                for v in o:
                    walk(v, key)
            elif isinstance(o, str):
                if key in ("startpoint", "endpoint", "point", "net", "pin", "instance", "name", "start_rtl_name",
                           "end_rtl_name", "module", "cell_name", "object"):
                    m = re.match(r"^(\S+)\s+\(([^)]+)\)$", o)
                    if m:
                        obj, cell = m.groups()
                        if re.match(r"^[A-Za-z_][\w$]*$", cell) and cell not in ("net", "rise", "fall"):
                            self.celltypes_raw.add(cell)
                        o = obj
                    if "/" in o and key in ("point", "startpoint", "endpoint", "pin"):
                        inst, pin = o.rsplit("/", 1)
                        self.add_name(inst, "cell")
                        self.pins.add(pin)
                    else:
                        self.add_name(o, "module" if key == "module" else "other")
                elif key in ("clock", "path_group", "launch_clock", "capture_clock"):
                    self.add_name(o, "clock")
                elif key in ("design", "top"):
                    self.top = self.top or o
                elif key in ("cell", "lib_cell", "ref_name") and re.match(r"^[A-Za-z_][\w$]*$", o):
                    self.celltypes_raw.add(o)
                elif key == "file":
                    self.add_path_stem(o)
        walk(d)

    def harvest_text(self, path: Path) -> None:
        """Log / QoR / check_timing: quoted names, Design: lines, -top, slash names."""
        with open_text(path) as f:
            for line in f:
                self._harvest_line(line)

    def _harvest_line(self, line: str) -> None:
        cands = [m.group(2) for m in OBJ_QUOTED.finditer(line)]
        cands += [m.group(2) for m in QUOTED.finditer(line) if re.search(r"[/\[]", m.group(2))]
        for inner in cands:
            if not ABS_PATH.fullmatch(inner) and not REL_PATH.fullmatch(inner) and not URL.match(inner):
                self.add_name(inner, "other")
        m = re.search(r"\bDesign\s*:\s*(\S+)", line)
        if m:
            self.top = self.top or m.group(1)
        m = re.search(r"-top\s+(\S+)", line)
        if m and not m.group(1).startswith("-"):
            self.top = self.top or m.group(1)
        for tok in line.split():
            if "/" in tok and not tok.startswith(("/", "~", "http")) and not REL_PATH.search(tok):
                t = tok.strip(",;:()'\"`")
                if re.match(r"^[\\A-Za-z_][\w$\[\]/.\\]*$", t):
                    self.add_name(t, "other")

    def harvest_journal(self, path: Path) -> None:
        with open_text(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    self._harvest_line(line)
                    continue
                if not isinstance(r, dict):
                    continue
                for s in r.get("subjects") or []:
                    if isinstance(s, str):
                        self.add_name(s, "other")
                for k in ("text", "reason"):
                    if isinstance(r.get(k), str):
                        self._harvest_line(r[k])
                for a in r.get("alternatives") or []:
                    if isinstance(a, dict) and isinstance(a.get("why"), str):
                        self._harvest_line(a["why"])
                if r.get("kind") == "header":
                    for v in (r.get("app_vars") or {}).values():
                        if isinstance(v, str):
                            for p in ABS_PATH.findall(v) + REL_PATH.findall(v):
                                self.add_path_stem(p)

    def harvest_rtl(self, path: Path) -> None:
        text_re = re.compile(r'"(?:\\.|[^"\\])*"')
        for _, st in verilog_statements(path):
            st = text_re.sub(" ", st)
            m = re.match(r"^(?:module|macromodule|interface|package|program)\s+(?:automatic\s+)?(\\\S+|[A-Za-z_][\w$]*)", st)
            if m:
                self.add_word(strip_escape(m.group(1)), "module")
            st = re.sub(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+", " ", st)
            for w in re.findall(r"(?<![$\w'])`?(\\\S+|[A-Za-z_][\w$]*)", st):
                if w not in VERILOG_KW:
                    self.add_name(w, "other")

    def harvest_liberty(self, path: Path) -> None:
        self.add_path_stem(str(path))
        with open_text(path) as f:
            for line in f:
                m = re.match(r"\s*library\s*\(\s*\"?([^\")\s]+)", line)
                if m:
                    self.add_literal(m.group(1))
                m = re.match(r"\s*cell\s*\(\s*\"?([^\")\s]+)", line)
                if m:
                    self.celltypes_raw.add(m.group(1))

    # ------------------------------------------------------------ finalize
    def finalize(self, top: str | None = None) -> None:
        if top:
            self.top = top
        if not self.top:
            roots = self._modules - self._instantiated
            if len(roots) == 1:
                self.top = next(iter(roots))
        tops = self.top
        if tops and tops in self._ports:
            for d, w in self._ports[tops]:
                self.add_name(w, {"input": "in", "output": "out"}.get(d, "io"))
        if self.top:
            self.roles[self.top] = "top"
            self.names[self.top] = "top"
            self.add_path_stem(self.top)
        # environment literals
        for lit in _env_literals():
            self.add_literal(lit)
        self._build_celltypes()
        for p in self.pins:      # library pin names seen as the last segment of a subject are not design names
            if self.roles.get(p) == "other" and p not in self.names:
                del self.roles[p]
        originals = set(self.roles) | set(self.names)
        pending: dict[str, list[str]] = {}
        for base, role in self.roles.items():
            if base in self.names:
                continue
            key = role
            if role in ("cell", "net", "other") and OP_KIND.match(base):
                key = "op"
            pending.setdefault(key, []).append(base)
        for key, bases in pending.items():
            bases.sort(key=lambda b: _hm(self.salt, b))
            for b in bases:
                while True:
                    if key == "op":
                        n = self.counters["op"] = self.counters.get("op", 0) + 1
                        tok = f"{OP_KIND.match(b).group(1).lower()}_o{n}"
                    elif key == "top":
                        tok = "top"
                    else:
                        p = PREFIX[key]
                        n = self.counters[p] = self.counters.get(p, -1 if key == "clock" else 0) + 1
                        tok = f"{p}{n}"
                    if tok not in originals or key == "top":
                        break
                self.names[b] = tok
        self._compile_literals()

    def _build_celltypes(self) -> None:
        raw = sorted(self.celltypes_raw)
        tags: list[str] = []
        for c in raw:
            for rx in self.user_tag_res + KNOWN_TAGS:
                m = rx.search(c)
                if m:
                    t = m.group("tag") if "tag" in rx.groupindex else m.group(0)
                    if t and t not in tags:
                        tags.append(t)
                    break
        if len(raw) >= 5 and not tags:
            pre = os.path.commonprefix(raw)
            pre = pre[: pre.rfind("_") + 1] if "_" in pre else ""
            if len(pre) >= 3:
                tags.append(pre)
            suf = os.path.commonprefix([c[::-1] for c in raw])[::-1]
            suf = suf[suf.find("_"):] if "_" in suf else ""
            if len(suf) >= 3:
                tags.append(suf)
        for t in tags:
            if t not in self.lib_tags:
                n = len(self.lib_tags) + 1
                tok = "LIBX" if n == 1 else f"LIBX{n}"
                if t.startswith("_"):
                    tok = "_" + tok
                if t.endswith("__"):
                    tok += "__"
                elif t.endswith("_"):
                    tok += "_"
                self.lib_tags[t] = tok
        for c in raw:
            if c in self.celltypes:
                continue
            out = c
            for t, tok in sorted(self.lib_tags.items(), key=lambda kv: -len(kv[0])):
                if t in out:
                    out = out.replace(t, tok)
                    break
            self.celltypes[c] = out
            self.roles.pop(c, None)

    def _tag_sub(self, w: str) -> str:
        if self._tag_re is None:
            return w
        return self._tag_re.sub(lambda m: self.lib_tags[m.group(0)], w)

    def _compile_literals(self) -> None:
        tags = sorted(self.lib_tags, key=len, reverse=True)
        self._tag_re = re.compile("|".join(re.escape(t) for t in tags)) if tags else None
        self._lit_res = [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(l) + r"(?![A-Za-z0-9])", re.I), t)
                         for l, t in sorted(self.literals.items(), key=lambda kv: -len(kv[0]))]

    # ------------------------------------------------------------ rewriting
    def path_token(self, p: str) -> str:
        if p not in self.paths:
            self.add_path_stem(p)
            ext = ""
            for e in sorted(KNOWN_EXT, key=len, reverse=True):
                if p.endswith("." + e):
                    ext = "." + e
                    break
            self.paths[p] = f"<path{len(self.paths) + 1}>{ext}"
        return self.paths[p]

    def anon_text(self, s: str, strict: bool = False) -> str:
        prot: list[str] = []

        def protect(rep: str) -> str:
            prot.append(rep)
            return f"\x00{len(prot) - 1}\x00"

        def url(m):
            u = m.group(0)
            host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u, flags=re.I).split("/")[0].split(":")[0].lower()
            return protect(u) if host.endswith(ALLOW_HOSTS) else protect("<url>")

        def host(m):
            h = m.group(0)
            return protect(h) if h.lower().endswith(ALLOW_HOSTS) else protect("<host>")

        def path(m):
            p = m.group(0)
            trail = ""
            while p and p[-1] in ".,:":
                trail, p = p[-1] + trail, p[:-1]
            if len(p) < 2:
                return m.group(0)
            return protect(self.path_token(p)) + trail

        s = URL.sub(url, s)
        s = EMAIL.sub(lambda m: protect("<email>"), s)
        s = ABS_PATH.sub(path, s)
        s = REL_PATH.sub(path, s)
        s = HOST.sub(host, s)
        s = IPV4.sub(lambda m: protect("<ip>"), s)
        s = DATE.sub(lambda m: protect("<date>"), s)
        if not strict:
            s = QUOTED.sub(lambda m: m.group(1) + protect(self._lits(self._ids(m.group(2), True))) + m.group(1), s)
        s = self._lits(self._ids(s, strict))
        while "\x00" in s:
            s = re.sub("\x00(\\d+)\x00", lambda m: prot[int(m.group(1))], s)
        return s

    def _lits(self, s: str) -> str:
        for rx, tok in self._lit_res:
            s = rx.sub(tok, s)
        return s

    def _ids(self, s: str, strict: bool) -> str:
        def repl(m):
            g = m.lastgroup
            if g in ("lit", "num"):
                return m.group(0)
            if g == "esc":   # Verilog escaped identifier; in prose a backslash is just a character
                return "\\" + self._ids(m.group(0)[1:], strict)
            w = m.group(0)
            ct = self.celltypes.get(w)
            if ct is not None:
                return ct
            prev = s[m.start() - 1] if m.start() else ""
            if prev == "-":
                return w
            if prev in "/." and w in self.pins:
                return w
            if not strict and (len(w) < 2 or w in VOCAB or w.lower() in VOCAB):
                return w
            base, suf = split_suffix(w)
            tok = self.names.get(base)
            if tok is None and suf == "":
                tok = self.names.get(w)
            if tok is not None:
                return tok + suf
            return self._tag_sub(w)
        return MASTER.sub(repl, s)

    # file writers -------------------------------------------------------
    def write_netlist(self, src: Path, dst: Path) -> None:
        in_block = False
        with open_text(src) as f, open(dst, "w") as o:
            o.write("// anonymized\n")
            for line in f:
                if in_block:
                    if "*/" not in line:
                        continue
                    line, in_block = line[line.index("*/") + 2:], False
                line = re.sub(r"/\*(?!\s*\)).*?\*/", " ", line)
                if "/*" in line and "(*" not in line:
                    line, in_block = line[: line.index("/*")] + "\n", True
                if "//" in line:
                    line = _strip_line_comment(line)
                if line.strip() == "":
                    continue
                o.write(self.anon_text(line, strict=True))

    def write_sdc(self, src: Path, dst: Path) -> None:
        with open_text(src) as f, open(dst, "w") as o:
            o.write("# anonymized\n")
            for line in f:
                line = _sdc_strip_comment(line)
                if line.strip():
                    # unit values (-time ns) are SDC vocabulary, never design names
                    units: list[str] = []
                    line = SDC_UNIT_OPT.sub(lambda m: units.append(m.group(2)) or m.group(1) + f"\x01{len(units) - 1}\x01", line)
                    line = self.anon_text(line, strict=True)
                    o.write(re.sub("\x01(\\d+)\x01", lambda m: units[int(m.group(1))], line))

    def write_timing_text(self, src: Path, dst: Path) -> None:
        pt = re.compile(r"^(\s+)(\S+)(\s+\()([^)\s]+)(\).*)$", re.S)
        se = re.compile(r"^(\s*(?:Startpoint|Endpoint|Path Group|Design)\s*:\s*)(\S+)(.*)$", re.S)
        with open_text(src) as f, open(dst, "w") as o:
            for line in f:
                m = se.match(line)
                if m:
                    o.write(m.group(1) + self.anon_text(m.group(2), True) + self.anon_text(m.group(3)))
                    continue
                m = pt.match(line)
                if m and m.group(4) not in ("rise", "fall", "ideal", "propagated"):
                    o.write(m.group(1) + self.anon_text(m.group(2), True) + m.group(3)
                            + self.celltypes.get(m.group(4), self.anon_text(m.group(4), True)) + self.anon_text(m.group(5)))
                    continue
                o.write(self.anon_text(line))

    def write_text(self, src: Path, dst: Path) -> None:
        with open_text(src) as f, open(dst, "w") as o:
            for line in f:
                o.write(self.anon_text(line))

    # boson's static vocabulary: compile-time strings that never carry design names.  `chosen`, `option`,
    # `stage`, `label`, `pass` are NOT here: real journals put names in them ("merged into decoded_imm_j[20]").
    JSON_KEEP = {"kind", "domain", "action", "verdict", "id", "severity", "tool", "schema", "schema_version",
                 "path_type", "unit", "units", "version", "source_lookup", "timing_complete"}
    JSON_STRICT = {"subjects", "startpoint", "endpoint", "point", "net", "pin", "instance", "name", "module",
                   "start_rtl_name", "end_rtl_name", "cell_name", "object", "clock", "path_group", "launch_clock",
                   "capture_clock", "design", "top"}

    def anon_json(self, o, key=None):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "text" and isinstance(v, str) and key == "rtl":
                    out[k] = "<rtl snippet dropped>"
                    continue
                out[k] = self.anon_json(v, "rtl" if k in ("rtl", "start_rtl", "end_rtl") else k)
            return out
        if isinstance(o, list):
            return [self.anon_json(v, key) for v in o]
        if isinstance(o, str):
            if key in self.JSON_KEEP:
                return self.celltypes.get(o) or self._tag_sub(o)
            if key in self.JSON_STRICT:
                m = re.match(r"^(\S+)(\s+)\(([^)]+)\)$", o)
                if m:
                    return self.anon_text(m.group(1), True) + m.group(2) + "(" + self.celltypes.get(m.group(3), m.group(3)) + ")"
                return self.anon_text(o, True)
            if key in ("cell", "lib_cell", "ref_name"):
                return self.celltypes.get(o, self.anon_text(o, True))
            if key == "file":
                return self.path_token(o)
            return self.anon_text(o)
        return o

    def write_json(self, src: Path, dst: Path) -> None:
        with open_text(src) as f:
            d = json.load(f)
        r = self.anon_json(d)
        dst.write_text(json.dumps(r, indent=1))

    def write_journal(self, src: Path, dst: Path) -> None:
        with open_text(src) as f, open(dst, "w") as o:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    o.write(json.dumps({"kind": "unparsed", "text": self.anon_text(line.rstrip("\n"))}) + "\n")
                    continue
                if isinstance(r, dict) and r.get("kind") == "header" and isinstance(r.get("app_vars"), dict):
                    r["app_vars"] = {k: (self.anon_text(v) if isinstance(v, str) else v) for k, v in r["app_vars"].items()}
                    rest = {k: v for k, v in r.items() if k != "app_vars"}
                    rest = self.anon_json(rest)
                    rest["app_vars"] = r["app_vars"]
                    r = rest
                else:
                    r = self.anon_json(r)
                o.write(json.dumps(r, separators=(",", ":")) + "\n")

    # ------------------------------------------------------------ check
    def forbidden(self) -> tuple[set[str], list[str]]:
        words = set(self.names) | set(self.roles) | self.path_stems
        words -= set(self.names.values())  # our own tokens are never originals (finalize guarantees it)
        subs = [p for p in self.paths if "/" in p or Path(p).stem in self.path_stems] + list(self.literals) + [t.strip("_") for t in self.lib_tags if len(t.strip("_")) >= 3]
        return words, [s for s in subs if len(s) >= 3]


def _sdc_strip_comment(line: str) -> str:
    if re.match(r"^\s*#", line):
        return ""
    return re.sub(r";\s*#.*$", "", line)


def _env_literals() -> list[str]:
    out = []
    try:
        out.append(getpass.getuser())
    except Exception:
        pass
    for fn in (socket.gethostname, socket.getfqdn):
        try:
            h = fn()
            out.append(h)
            out.append(h.split(".")[0])
        except Exception:
            pass
    home = os.path.expanduser("~")
    if home not in ("/", "~"):
        out.append(Path(home).name)
    return [o for o in out if o and len(o) >= 3 and o.lower() not in VOCAB and o not in ("localhost", "root")]


# ---------------------------------------------------------------- discovery

def discover(run_dir: Path) -> dict:
    found: dict = {"netlist": None, "sdc": [], "timing": [], "timing_json": [], "qor": [], "check_timing": [],
                   "log": [], "journal": None, "rtl": []}
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.stat().st_size == 0:
            continue
        name = p.name.lower()
        try:
            with open_text(p) as f:
                head = "".join(f.readline() for _ in range(60))
        except OSError:
            continue
        if name.endswith((".jsonl", ".jsonl.gz")) and '"kind"' in head and '"header"' in head:
            found["journal"] = found["journal"] or p
        elif name.endswith(".json") and ("schema_version" in head or '"paths"' in head):
            found["timing_json"].append(p)
        elif name.endswith((".v", ".vg", ".v.gz", ".sv")):
            with open_text(p) as f:
                sample = "".join(f.readline() for _ in range(3000))
            if re.search(r"\balways\b|\bbegin\b|\bgenerate\b", sample) or name.endswith(".sv"):
                found["rtl"].append(p)
            else:
                found["netlist"] = found["netlist"] or p
        elif name.endswith(".sdc"):
            found["sdc"].append(p)
        elif not name.endswith((".rpt", ".txt", ".log", ".out", ".gz")):
            continue
        elif "Startpoint:" in head or "Report : timing" in head:
            found["timing"].append(p)
        elif re.search(r"^WNS:", head, re.M) and "TNS" in head:
            found["qor"].append(p)
        elif "check_timing" in head or "Checking '" in head:
            found["check_timing"].append(p)
        elif name.endswith(".log") or "boson v" in head:
            found["log"].append(p)
    return found


# ---------------------------------------------------------------- check

def _iter_bundle(target: Path):
    if target.is_dir():
        for p in sorted(target.rglob("*")):
            if p.is_file():
                yield str(p.relative_to(target)), p.read_bytes()
    else:
        with tarfile.open(target) as t:
            for m in t.getmembers():
                if m.isfile():
                    yield m.name, t.extractfile(m).read()


_SCRIPT_WORDS: set[str] | None = None
BUNDLE_DIRS = ("digests", "reports", "constraints", "logs", "journal", "netlist", "boson-debug-bundle")
SDC_UNIT_OPT = re.compile(r"(-(?:time|capacitance|resistance|current|voltage|power|unit)\s+)(\S+)")
JSON_STATIC = ("domain", "action", "verdict", "kind", "severity", "id", "tool")


def script_words() -> set[str]:
    """Every word in a string literal of this skill's own scripts.

    The digests, MANIFEST.md and environment.json are generated from fixed
    templates in these scripts; their template text ("still running",
    "boson debug bundle", "clk<N>") is tool vocabulary, never customer data,
    so a customer identifier that happens to equal one of these words is not
    identifying in prose.  Only exact whole words count: a distinctive
    identifier never appears in the templates.
    """
    global _SCRIPT_WORDS
    if _SCRIPT_WORDS is None:
        import ast
        ws: set[str] = set()
        for f in Path(__file__).resolve().parent.glob("*.py"):
            try:
                tree = ast.parse(f.read_text())
            except (OSError, SyntaxError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    ws.update(WORD.findall(n.value))
        _SCRIPT_WORDS = ws
    return _SCRIPT_WORDS


def _words_of(m) -> list[str]:
    if m.lastgroup == "esc":
        return WORD.findall(m.group(0))
    if m.lastgroup == "id":
        return [m.group(0)]
    return []


def run_check(mapper: Mapper, target: Path, verbose: int = 20) -> int:
    """Leak scan of a bundle directory or tarball.

    Two strictness levels.  STRUCTURED positions (netlist, SDC object names,
    report point / start / end columns, journal subjects and object fields)
    must contain no original name at all.  PROSE (everything else: digests,
    REPORT.md, logs, free-text journal fields) must contain no original name
    either, except whole-word matches on generic vocabulary (VOCAB, the
    scripts' own template words, boson's static journal vocabulary, library
    pin names, single letters) - those are listed, not failed.
    """
    words, subs = mapper.forbidden()
    pins = mapper.pins
    files = list(_iter_bundle(target))
    static_vocab: set[str] = set()       # boson's static strings: domain/action names, metric and app-var names
    for name, data in files:
        if name.endswith(".jsonl"):
            for line in data.decode("utf-8", "replace").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(r, dict):
                    continue
                for k in ("domain", "action"):
                    if isinstance(r.get(k), str):
                        static_vocab.update(WORD.findall(r[k]))
                for k in ("metrics", "inputs", "impact", "counts", "app_vars"):
                    if isinstance(r.get(k), dict):
                        for kk in r[k]:
                            static_vocab.update(WORD.findall(kk))
    sw = script_words()
    generic = {w for w in words if w in VOCAB or w.lower() in VOCAB or len(w) < 2 or w in pins
               or w in sw or w in static_vocab}
    hard_struct = words - {w for w in words if len(w) < 2 and w in pins}
    hard_prose = words - generic
    own_paths = set()
    for name, _ in files:
        rel = name.split("/", 1)[1] if name.startswith("boson-debug-bundle/") else name
        own_paths.add(rel)
        own_paths.add(re.sub(r"\.[A-Za-z]+$", "", rel))
    leaks, warns = [], []
    unmapped_hier = re.compile(r"(?<![\w<$/])([A-Za-z_][\w$]*(?:\[\d+\])*(?:/[A-Za-z_][\w$]*(?:\[\d+\])*)+)")

    def scan(text: str, where: tuple, structured: bool, sdc: bool = False):
        hard = hard_struct if structured else hard_prose
        if sdc:
            text = SDC_UNIT_OPT.sub(lambda m: m.group(1) + " " * len(m.group(2)), text)
        for m in MASTER.finditer(text):
            for w in _words_of(m):
                prev = text[m.start() - 1] if m.start() else ""
                if structured and (prev == "-" or (sdc and w in SDC_WORDS) or (prev in "/." and w in pins)):
                    continue
                base, _ = split_suffix(w)
                if base in hard or w in hard:
                    leaks.append((*where, f"original identifier {w!r}" + (" (structured position)" if structured else "")))

    for name, data in files:
        low = name.lower()
        if "name_map" in low:
            leaks.append((name, 0, "name map file is in the bundle"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            leaks.append((name, 0, "binary file - cannot be scanned; remove it"))
            continue
        if '"salt"' in text and '"names"' in text:
            leaks.append((name, 0, "looks like a name map (salt+names)"))
        if any(s in name for s in subs):
            leaks.append((name, 0, "original path/literal in the file name"))
        scan(name.replace("/", " "), (name, 0), False)
        is_v, is_sdc = low.endswith((".v", ".vg", ".sv")), low.endswith(".sdc")
        is_json, is_jsonl, is_rpt = low.endswith(".json"), low.endswith(".jsonl"), low.endswith(".rpt")
        if is_json:
            try:
                scan_json(json.loads(text), name, scan)
            except json.JSONDecodeError:
                is_json = False
        for ln, line in enumerate(text.splitlines(), 1):
            for s in subs:
                if s.lower() in line.lower():
                    leaks.append((name, ln, f"literal/path/library tag: {s!r}"))
            for m in EMAIL.finditer(line):
                leaks.append((name, ln, f"email {m.group(0)!r}"))
            for m in ABS_PATH.finditer(line):
                if len(m.group(0)) > 2:
                    leaks.append((name, ln, f"absolute path {m.group(0)!r}"))
            for m in HOST.finditer(line):
                if not m.group(0).lower().endswith(ALLOW_HOSTS):
                    leaks.append((name, ln, f"hostname {m.group(0)!r}"))
            for m in IPV4.finditer(line):
                leaks.append((name, ln, f"IP address {m.group(0)!r}"))
            for m in DATE.finditer(line):
                warns.append((name, ln, f"date/timestamp {m.group(0)!r}"))
            if is_json:
                pass                                   # scanned field by field above
            elif is_jsonl:
                try:
                    scan_json(json.loads(line), name, scan, ln)
                except json.JSONDecodeError:
                    scan(line, (name, ln), False)
            elif is_v or is_sdc:
                scan(line, (name, ln), True, sdc=is_sdc)
            elif is_rpt:
                mm = re.match(r"^(\s*(?:Startpoint|Endpoint|Path Group|Design)\s*:\s*)(\S+)(.*)$", line) or \
                    re.match(r"^(\s+)(\S+)(\s+\(.*)$", line)
                if mm and not re.match(r"\s*(?:clock|data|library|slack|input|output)\b", line):
                    scan(mm.group(2), (name, ln), True)
                    scan(mm.group(1) + mm.group(3), (name, ln), False)
                else:
                    scan(line, (name, ln), False)
            else:
                scan(line, (name, ln), False)
            for m in unmapped_hier.finditer(line):
                cand = m.group(1)
                if cand in own_paths or cand.split("/", 1)[0] in BUNDLE_DIRS:
                    continue                           # the bundle's own file names
                segs = cand.split("/")
                bad = [x for x in segs[:-1] if not (TOKEN_RE.match(split_suffix(re.sub(r"\[\d+\]", "", x))[0])
                       or TOOL_ANON.match(re.sub(r"\[\d+\]", "", x)) or x.lower() in VOCAB or x in static_vocab or x in sw)]
                if bad and not all(len(x) <= 4 and x.isalpha() for x in segs):
                    warns.append((name, ln, f"unmapped-looking hierarchical name {cand!r}"))
    print(f"check: scanned {len(files)} file(s) in {target}; {len(hard_struct)} original identifiers "
          f"({len(hard_prose)} distinctive), {len(subs)} literals/paths/tags")
    coll = sorted(words & generic)
    if coll:
        print(f"check: {len(coll)} original names are generic words; they must not appear in structured positions "
              f"(checked) and are allowed as whole words in prose: {', '.join(coll[:30])}{' ...' if len(coll) > 30 else ''}")
    for n, ln, msg in warns[:verbose]:
        print(f"  WARN {n}:{ln}: {msg}")
    if len(warns) > verbose:
        print(f"  WARN ... {len(warns) - verbose} more")
    if leaks:
        for n, ln, msg in leaks[: max(verbose, 50)]:
            print(f"  LEAK {n}:{ln}: {msg}")
        if len(leaks) > max(verbose, 50):
            print(f"  LEAK ... {len(leaks) - max(verbose, 50)} more")
        print(f"check: FAILED - {len(leaks)} leak(s). The bundle is NOT shareable. Fix (re-run anonymize with --literal/"
              f"--lib-tag, or edit REPORT.md) and re-check.")
        return 1
    print(f"check: PASSED - no original identifiers, paths, literals or library tags found ({len(warns)} warning(s) to eyeball)")
    return 0


def scan_json(o, name: str, scan, ln: int = 0, key: str | None = None) -> None:
    """Scan JSON string values: object fields strictly, free text as prose, boson's static fields not at all."""
    if isinstance(o, dict):
        for k, v in o.items():
            scan(str(k), (name, ln), False)
            scan_json(v, name, scan, ln, k)
    elif isinstance(o, list):
        for v in o:
            scan_json(v, name, scan, ln, key)
    elif isinstance(o, str):
        if key in JSON_STATIC:
            return
        scan(o, (name, ln), key in Mapper.JSON_STRICT)


# ---------------------------------------------------------------- main

def anonymize_inputs(a, mapper: Mapper, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    files = {"netlist": a.netlist, "sdc": a.sdc or [], "timing": a.timing or [], "timing_json": a.timing_json or [],
             "qor": a.qor or [], "check_timing": a.check_timing or [], "log": a.log or [], "journal": a.journal,
             "rtl": a.rtl or [], "liberty": a.liberty or []}
    for lit in a.literal or []:
        mapper.add_literal(lit)
    mapper.user_tag_res = [re.compile(r) for r in (a.lib_tag or [])]
    # pass 1: harvest
    for p in files["liberty"]:
        mapper.harvest_liberty(Path(p))
    for p in files["rtl"]:
        mapper.harvest_rtl(Path(p))
    if files["netlist"]:
        mapper.harvest_netlist(Path(files["netlist"]))
    for p in files["sdc"]:
        mapper.harvest_sdc(Path(p))
    for p in files["timing"]:
        mapper.harvest_timing_text(Path(p))
    for p in files["timing_json"]:
        mapper.harvest_timing_json(Path(p))
    for k in ("qor", "check_timing", "log"):
        for p in files[k]:
            mapper.harvest_text(Path(p))
    if files["journal"]:
        mapper.harvest_journal(Path(files["journal"]))
    for p in [files["netlist"], files["journal"], *files["sdc"], *files["timing"], *files["timing_json"], *files["qor"],
              *files["check_timing"], *files["log"], *files["rtl"], *files["liberty"]]:
        if p:
            mapper.path_token(str(Path(p)))
            mapper.path_token(str(Path(p).resolve()))
    mapper.finalize(a.top)
    # pass 2: rewrite
    manifest: dict = {}

    def put(kind, src, dst, fn):
        fn(Path(src), out / dst)
        manifest.setdefault(kind, []).append(dst)
        print(f"anonymize: {kind:13s} -> {out / dst}", file=sys.stderr)

    if files["netlist"]:
        put("netlist", files["netlist"], "netlist.v", mapper.write_netlist)
    for i, p in enumerate(files["sdc"], 1):
        put("sdc", p, f"constraints_{i}.sdc", mapper.write_sdc)
    for i, p in enumerate(files["timing"], 1):
        put("timing", p, f"timing_{i}.rpt", mapper.write_timing_text)
    for i, p in enumerate(files["timing_json"], 1):
        put("timing_json", p, f"timing_{i}.json", mapper.write_json)
    for i, p in enumerate(files["qor"], 1):
        put("qor", p, f"qor_{i}.rpt", mapper.write_text)
    for i, p in enumerate(files["check_timing"], 1):
        put("check_timing", p, f"check_timing_{i}.rpt", mapper.write_text)
    for i, p in enumerate(files["log"], 1):
        put("log", p, f"boson_{i}.log", mapper.write_text)
    if files["journal"]:
        put("journal", files["journal"], "decisions.jsonl", mapper.write_journal)
    if files["rtl"]:
        manifest["rtl_harvested_only"] = len(files["rtl"])
    if files["liberty"]:
        manifest["liberty_harvested_only"] = len(files["liberty"])
    manifest["top"] = "top" if mapper.top else None
    manifest["lib_tags"] = sorted(set(mapper.lib_tags.values()))
    (out / "inputs.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", type=Path, default=Path("name_map.json"), help="name map (created or extended; LOCAL ONLY)")
    ap.add_argument("--out", type=Path, help="directory for anonymized copies")
    ap.add_argument("--run-dir", type=Path, help="auto-discover inputs in this directory (prints what it found)")
    ap.add_argument("--netlist"); ap.add_argument("--journal")
    for k in ("sdc", "timing", "timing-json", "qor", "check-timing", "log", "rtl", "liberty"):
        ap.add_argument(f"--{k}", action="append")
    ap.add_argument("--top", help="top module name (else inferred)")
    ap.add_argument("--literal", action="append", help="extra string to scrub everywhere (company, project codename, ...)")
    ap.add_argument("--lib-tag", action="append", help="regex for a vendor tag in cell names (group 'tag' or whole match)")
    ap.add_argument("--encode", help="map raw names in this text to tokens ('-' = stdin)")
    ap.add_argument("--decode", help="map tokens in this text back to raw names ('-' = stdin). LOCAL use only")
    ap.add_argument("--check", type=Path, help="scan a bundle dir or tarball for leaks; exit 1 on any")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.check or a.encode is not None or a.decode is not None:
        if not a.map.exists():
            print(f"anonymize: no map at {a.map}", file=sys.stderr)
            return 2
        m = Mapper.load(a.map)
        if a.check:
            return run_check(m, a.check)
        txt = sys.stdin.read() if (a.encode or a.decode) == "-" else (a.encode if a.encode is not None else a.decode)
        if a.encode is not None:
            n_paths = len(m.paths)
            print(m.anon_text(txt, strict=True))
            if len(m.paths) != n_paths:
                m.save(a.map)      # a new path token must stay stable for the next call
        else:
            rev = {v: k for k, v in m.names.items()}
            rev.update({v: k for k, v in m.paths.items()})
            rev.update({v: k for k, v in m.literals.items()})
            def dec(mm):
                w = mm.group(0)
                base, suf = split_suffix(w)
                return rev[base] + suf if base in rev else rev.get(w, w)
            txt = re.sub(r"<(?:path|redacted)\d+>", lambda mm: rev.get(mm.group(0), mm.group(0)), txt)
            print(WORD.sub(dec, txt))
        return 0
    if a.run_dir:
        f = discover(a.run_dir)
        print("discovered inputs (confirm these with the user):", file=sys.stderr)
        for k, v in f.items():
            print(f"  {k:13s} {v}", file=sys.stderr)
        a.netlist = a.netlist or (str(f["netlist"]) if f["netlist"] else None)
        a.journal = a.journal or (str(f["journal"]) if f["journal"] else None)
        for k in ("sdc", "timing", "timing_json", "qor", "check_timing", "log", "rtl"):
            if not getattr(a, k):
                setattr(a, k, [str(p) for p in f[k]] or None)
    if not a.out:
        print("anonymize: --out is required", file=sys.stderr)
        return 2
    if a.map.resolve().parent == a.out.resolve() or a.out.resolve() in a.map.resolve().parents:
        print("anonymize: refusing to put the name map inside the output directory", file=sys.stderr)
        return 2
    mapper = Mapper.load(a.map) if a.map.exists() else Mapper()
    anonymize_inputs(a, mapper, a.out)
    mapper.save(a.map)
    print(f"anonymize: {len(mapper.names)} names, {len(mapper.paths)} paths, {len(mapper.literals)} literals, "
          f"{len(mapper.lib_tags)} library tag(s) -> map {a.map} (LOCAL ONLY, never send)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
