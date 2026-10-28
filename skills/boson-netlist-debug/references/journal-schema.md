# boson decision journal (schema 1)

Enable with `set_app_var decision_log_file <path>` before `compile`;
`set_app_var decision_log_file ""` closes it. Check the installed binary with
`report_app_var decision_log_file` and `help set_app_var`. The journal is
JSONL: one object per line, appended as the run goes, so a killed run keeps
everything up to the point it reached (it then has no `compile_end` and no
`summary`). Journals can have millions of lines: stream or grep them.

Every record has `kind`. All records except `header` have `seq` (increasing
per file) and `t_s` (seconds since process start). Any record may carry
`stage` (the innermost stage label in force, e.g. `"medium: alternate map"`),
`pass` (the pass path, e.g. `["map", "resize 3"]`) and `probe: true`.

## Kinds

| kind | fields | meaning |
|---|---|---|
| `header` | `schema` (1), `tool` ("boson"), `version` ("1.824.1 (build abc1234)"), `pid`, `t_s`, `app_vars` {name: value} | written when the file is opened; `app_vars` are the overrides in force — values may contain file paths |
| `compile_begin` | — | a `compile` started |
| `compile_end` | `counts` {"<domain>/<action>": N}, `elapsed_s` | the compile finished; counts are decisions so far |
| `summary` | `counts` | written when the journal is closed (file switched/cleared or process end); may be missing if the process just exited |
| `decision` | see below | one choice boson made |
| `checkpoint` | `label`, `metrics` {wns_ns, tns_ns, area_um2, cells, violating_endpoints, ...} | QoR at a stage boundary |
| `progress` | `text` (may start with `[stage] `) | the compile's progress lines |
| `message` | `id` ("SYN-123"), `severity` ("Error" / "Warning" / "Information"), `text` | every catalogued diagnostic boson printed; texts name design objects (`net 'a/b'`) |

Unknown kinds: count them, otherwise ignore.

## decision

```json
{"kind":"decision","seq":12,"t_s":3.21,"stage":"medium: alternate map","pass":["map","resize 3"],
 "domain":"datapath","action":"adder_topology","subjects":["u_core/add_17"],"chosen":"kogge_stone",
 "alternatives":[{"option":"ripple","verdict":"rejected","why":"misses required time by 0.12 ns",
                  "metrics":{"delay_ns":0.41,"area_um2":12.3}}],
 "reason":"free text","inputs":{"slack_ns":-0.12,"fanout":34},
 "impact":{"wns_ns":{"before":-0.2,"after":-0.05,"delta":0.15},"area_um2":{"before":100.0,"after":112.0,"delta":12.0}}}
```

Only `kind`, `seq`, `t_s`, `domain` and `action` are guaranteed.

- `domain`: recipe, elaboration, constraints, datapath, mapping,
  resynthesis, sequential, clock_gating, banking, placement, sizing,
  buffering, vt, setup_repair, hold_repair, ccd, drv, layout.
- `action`: free-form snake_case (`adder_topology`, `upsize`,
  `insert_buffer_chain`, ...). Handle unknown actions generically.
- `subjects`: design objects the decision acted on — instances, nets,
  pins, operators (`u_core/add_17`; the cells built for it carry the
  operator name as a prefix), or patterns from the SDC.
- `chosen`: the option taken (boson vocabulary or a cell type).
- `alternatives[]`: `option`, `verdict` (`chosen` | `rejected` |
  `rolled_back` | `skipped`), optional `why` and `metrics`. The chosen
  option may also appear here with `verdict: "chosen"` and its metrics.
- `reason`: free text.
- `inputs`: what boson knew when deciding (slack, fanout, setup margin...).
- `impact`: {metric: {before, after, delta}}, `delta = after − before`.
  Whether a positive delta is good depends on the metric: for wns/tns/slack
  higher is better; for area/power/delay/cells/violators lower is better.
- `applied`: present on keep/reject/rollback judgements. `true` = the
  change is in the design afterwards; `false` = it was tried and rejected
  or undone, so its `impact` is what the trial *would* have done (a trial's
  negative impact is not damage to the shipped netlist — but a rejected
  trial with a positive impact is a missed opportunity worth reporting).
  Absent = the decision is not a trial (a structure pick, a gate verdict).
- `probe: true`: the decision happened inside an internal what-if
  evaluation. It is **not** in the shipped netlist; compare it with the
  shipped decision on the same subject.

Metric values (in `metrics`, `inputs`, `impact`) can be `null` when the
value was non-finite or unknown. Treat null as unknown, never as 0.

## checkpoint

```json
{"kind":"checkpoint","seq":40,"t_s":12.5,"stage":"layout","label":"after layout",
 "metrics":{"wns_ns":-0.09,"tns_ns":-0.16,"area_um2":39.1,"cells":16,"violating_endpoints":2}}
```

Consecutive checkpoints bracket the decisions between them: a stage whose
checkpoint lost WNS owns the decisions with seq between the two.

## After anonymization

`anonymize.py` keeps `kind`, `domain`, `action`, `verdict`, `id`,
`severity`, numbers and metric / app-var names raw — boson's static
vocabulary. `chosen`, `option`, `stage`, `label`, `pass`, `reason`, `why`,
`text`, `inputs` strings and `app_vars` values go through the text
anonymizer, because real journals carry design names there
(`"chosen":"merged into decoded_imm_j[20]"`); cell types in them get the
library tag replaced. `subjects` are tokenized like every other design
name.
