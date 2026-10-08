# Native Boson timing traceback

Prefer native `report_timing -format json` when an agent is choosing RTL
edits or processing path data. Use `-format rtl` for a readable source
summary. These formats are available in Boson builds containing
[PR #12223](https://github.com/partcleda/boson/pull/12223).

## Discover and collect

Check the installed binary through the Boson shell:

```tcl
help report_timing
help report_timing rtl
help report_timing json
help search RTL traceback
```

`report_timing -format <Tab>` describes the format choices; the `rtl` and
`json` help sections also autocomplete. If these formats are unsupported,
use a newer Boson for native traceback or explicitly use the existing
text-report workflow. Do not assume an older binary emits this schema.

After compiling/analyzing the candidate's RTL in the session and running
its chosen flow:

```tcl
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
report_timing -format rtl -max_paths 10 -file timing.rtl
report_timing -format json -max_paths 10 -file timing.json
```

Use the existing `-from`, `-to`, `-through`, `-path_group`, `-nworst`,
`-max_paths` and `-delay_type min` selectors to focus a path or inspect
hold timing. `-delay_type min_max` includes both modes. `rtl`/`json` cannot
be combined with `-pba`; use `report_pba` separately when needed.

Generate the reports before changing the source again. Source locations
refer to **current files**, not compiler source snapshots. Retain each
report with the candidate revision and the constraints/flow/input hashes;
the JSON does not supply that experiment identity for you. A netlist-only
session may have no RTL source index.

## Interpret schema version 1

- Check `schema_version` before consuming fields. Check `timing_complete`,
  read `warnings` (a string) and `message` (a nullable string). Incomplete
  timing is not a usable score merely because the process returned zero.
- `rtl_available` means an RTL source index exists; individual matches may
  still be null. `source_lookup` identifies name matching in current files.
- `paths[]` carries `startpoint`, `endpoint`, `path_group`, `path_type`
  (`max`/`min`), `slack_ns`, `arrival_ns`, `required_ns`, `unconstrained`,
  `start_rtl`, `end_rtl` and `points`. Times are **ns**. Unavailable values
  are null; unconstrained paths have null slack and required time. Never
  coerce these values to zero or count an empty path sample as timing met.
- `points[]` contains `point`, `net`, `increment_ns`, `arrival_ns`,
  `fanout` and `rtl`. Follow large point delays and fanout to the associated
  source hints. Missing point values do not imply zero delay or fanout.
- `start_rtl`, `end_rtl` and each point's `rtl` are either null or a match
  with `kind`, `name`, `module`, `instance`, `file`, `line` (1-based), and
  `text` (the source snippet). Inspect the source and surrounding logic
  before editing; all matches are lookup hints rather than compiler spans.

| `kind` | How to use the match |
|---|---|
| `origin_signal` | Synthesis signal origin resolved to a source name. |
| `net_name` | A wire name matched in the resolved RTL module. |
| `cell_name` | A cell/register name matched in the resolved RTL module. |
| `origin_region` | Nearby synthesis region; inspect the surrounding module, not just the reported line. |
| `hierarchy` | Module-level hint; the exact signal is unknown. |

Use `groups[]` to find repeated bus-bit paths. Each group has
`start_rtl_name`, `end_rtl_name`, `path_group`, `path_type`, `path_count`,
`worst_slack_ns` and `best_slack_ns`. Group names use matched RTL signals
when available and original timing endpoints otherwise. Separate instances,
path groups and setup/hold modes stay separate. Counts and slack ranges
cover **only the reported sample**; they are not design-wide WNS, TNS or
violating-endpoint counts. Keep `report_qor` for those metrics and compare
samples with the same selectors and limits.

When a match is missing, preserve that uncertainty and inspect the reported
net/cell in its hierarchy. Do not invent a source location or infer that
unmapped logic is irrelevant. A source match suggests where to investigate;
it does not establish that an RTL rewrite is functionally equivalent.

The plugin's `timing_probe.py --json` produces a different, text-derived
probe schema. Its `--diff` expects that probe schema, not native Boson JSON.
