# What the bundle keeps, maps and drops

`anonymize.py` builds one mapping across every input, so a register in the
netlist, the timing report, the SDC and a journal subject gets the same
token everywhere. The mapping is `name_map.json` (mode 600). It never goes
in the bundle; `--check` fails if it, or anything that looks like it, does.

## Kept as is

- Numbers and units: slacks, delays, arrival/required times, clock periods,
  uncertainties, capacitances, fanouts, areas, counts, run times.
- Path structure: the order of points, pins, rise/fall, stage counts.
- Cell function and drive: `NAND2xp33`, `NAND2_X4`, `or4_1`, `ND2D4`, and
  the VT / track variant (`_R`, `_L`, `LVT`), because these are the
  analysis signal.
- Library pin names (`A1`, `Y`, `QN`, `CLK`).
- boson vocabulary: message IDs (`SYN-301`), journal `kind`, `domain`,
  `action`, `verdict`, `severity`, metric names, command and option names,
  SDC unit values (`-time ns`). Free-text journal fields (`chosen`,
  `option`, `stage`, `reason`, ...) are anonymized like prose.
- boson's own name suffixes on design names (`_reg`, `__qn_bsn`, `_bsn`,
  `_gs<N>`), so a register and its output net share a token.
- Tool-generated names with no design information (`n1234`, `gs56`,
  `U78`, `_12_`, `_tielo_net_3`).
- boson version, OS family and release, CPU count, RAM size, GPU model.

## Mapped to tokens

| original | token | notes |
|---|---|---|
| top module | `top` | |
| clocks (SDC `-name`, clock ports) | `clk<N>` | role kept: clock vs data |
| top-level ports | `in<N>` / `out<N>` / `io<N>` (`p<N>` if direction unknown) | bus index kept: `in3[7]` |
| modules | `m<N>` | |
| hierarchy instances | `u<N>` | each `/` segment separately, so depth stays visible: `u3/u9/r12_reg[4]` |
| registers | `r<N>` | `_reg`, index kept |
| other cell instances | `c<N>` | |
| nets / signals | `w<N>` | |
| operator-like names (`add_17`, `mul_3`) | `add_o<N>`, `mul_o<N>` | operator kind kept |
| other names (SDC patterns, RTL-only names, parameters, macros) | `x<N>` | |
| vendor library tag in cell names (`sky130_fd_sc_hd__`, `_ASAP7_75t`, `BWP16P90`) | `LIBX` (`LIBX2`, ...) | detected from known patterns, then by common prefix/suffix; add `--lib-tag REGEX` if one is missed |
| file paths (absolute, or relative with a known extension) | `<path<N>>.ext` | extension kept |
| Liberty library names, `--literal` strings, user name, hostname | `<redacted<N>>` | case-insensitive |
| emails, non-allowlisted hostnames/URLs, IP addresses | `<email>`, `<host>`, `<url>`, `<ip>` | partcl.com / github.com URLs kept |
| dates and timestamps | `<date>` | |

Tokens are numbered in HMAC-SHA256(random salt, name) order, so neither the
numbering nor a dictionary of likely names reveals the original without
the salt, which lives only in the map. A token never equals any original
name. Rerunning with the same map keeps every token stable and adds new
ones.

## Dropped

- Comments in the netlist and SDC.
- RTL source: read only to collect identifiers (so they get scrubbed
  wherever they appear); never copied. RTL snippets in the timing JSON
  (`rtl.text`) are replaced by `<rtl snippet dropped>`; file and line
  stay as `<path>` + line number.
- Liberty files: read locally for names, pin directions and areas; never
  copied.
- The netlist, unless `--include-netlist` (then the anonymized one only).

## Limits — tell the customer

- A design name that appears only in free text (a log line, a `reason`)
  and nowhere structured is unknown to the anonymizer. Give it the RTL and
  the full log so it learns the names, and pass project or company names
  with `--literal`.
- Names that are ordinary words (`data`, `valid`, `clk`, `debug`,
  `running`) are mapped in structured positions but left alone in prose, so
  report text stays readable. `--check` has two levels: in structured
  positions (netlist, SDC objects, report start/end/point columns, journal
  subjects and object fields) any original name fails, generic or not; in
  prose a whole-word match on generic vocabulary (the built-in word list,
  the words of the scripts' own report templates, boson's static journal
  vocabulary, library pins, single letters) is listed but allowed. Every
  distinctive name (with `_`, digits, or not in those lists) fails anywhere.
- RTL names that are English words are mapped in prose too (safe side), so
  a log sentence may read oddly.
- Structure is information. The anonymized netlist, path shapes and cell
  histograms reveal architecture (how many multipliers, how deep the
  pipeline) even without names. That is why the netlist is opt-in.
- `--check` scans for every original name, path, literal and library tag,
  and for email/path/host/IP patterns. It cannot know names it was never
  shown. Read the WARN lines and REPORT.md yourself.
