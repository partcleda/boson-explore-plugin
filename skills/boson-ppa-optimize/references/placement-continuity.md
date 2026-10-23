# Placement continuity after netlist edits

Use this workflow when a small repair or restructure appears to disturb the
whole placement. Warm initialization, global optimization, legalization, and
routing can each change the outcome; measure them separately.

## Preserve the experiment inputs

Start from the user's mapped netlist, LEF, Liberty corner, SDC, floorplan and
wire-RC settings. Record the binary revision/hash, effective app variables,
seeds and hardware. Follow the workspace's scheduler and resource rules. Budget
one checkpoint placement and six replay arms before starting a large design.
Keep the user's RTL and constraints unchanged.

Inspect RC warnings. Missing layer RC can make the tool use one wire model
instead of the routed layers. Preserve that model in the first comparison,
record the fallback, and investigate RC calibration as a separate experiment.
Likewise, do not repair constraint coverage by silently changing clock modes or
adding exceptions between arms.

## Replay the same edit

1. Place and check the baseline. Run `update_timing`, record `report_qor`,
   `report_wns`, `report_tns` and representative `report_timing` paths. Export
   cell coordinates with `write_design_tables <dir> -format csv -tables {cells}`
   and retain the session with `save_session <path>`.
2. Apply one edit batch once and save another session before legalization.
   Record exactly which instances were added, removed or resized. A small
   resize tests local continuity; a repair-sized buffer batch tests capacity
   pressure. For a repeater/DRV diagnostic, supported builds expose
   `repair_design -placement_checkpoint` with `placement_checkpoint_stages drc`.
   This intentionally keeps the edits without the normal timing acceptance
   gate. Its overlapping, as-planned result is a diagnostic, not a legal final
   implementation. Check the installed command help before using this path.
3. In fresh sessions restored with `load_session`, run both the unchanged and
   edited checkpoints through `place_design -incremental warm`,
   `place_design -incremental off`, and `legalize_place`. This gives six arms.
   Set overrides after loading, because the checkpoint restores app variables.
4. Prevent additional netlist edits during the replay. For a wirelength-only
   continuity study, set `place_timing_driven false`,
   `place_repair_timing false`, and `place_global_route false`, and disable any
   other embedded repair enabled by the installed version. Keep those settings
   identical in the baseline and replays. Label this as an isolated placement
   study. A production timing-driven comparison is a separate arm: automatic
   repair can otherwise give warm and cold different netlists.
5. Check legality and re-extract the same RC model before each final timing
   measurement. Save final cell tables and netlists. Verify cell/master identity,
   connectivity, counts and area across the warm/cold/legalization-only arms of
   each edit. If they differ, resolve that mismatch before attributing a timing
   difference to placement.

## Interpret the results

Report final setup WNS, TNS, cell area, timing coverage and legality, with deltas
against both the original checkpoint and the cold arm. If negative-only WNS is
zero in every arm, also show the unclipped worst setup slack. Distinguish cell
area from core/bounding-box area. For an identical netlist without sizing, cell
area should be equal even when the coordinates differ.

Compare survivor coordinates by instance name, not tensor index. Include mean,
p95 and maximum movement, and compare each edited result with its own no-edit
control. Large no-edit drift is not sensitivity caused by the inserted cell.
When useful, compare consecutive cell locations on the worst timing path to
identify newly introduced detours.

Warm starts may retain coordinates while rebuilding optimizer state, filler
positions, density weights and stopping targets. Check the implementation and
logs before calling them a continuation of the same solve. Use a controlled
ablation before attributing drift to any one setting. An incremental global
start also does not imply local legalization: the repair path may still submit
every movable cell to the legalizer.

If legalization alone loses slack, investigate insertion locality and packing.
If warm no-edit refinement changes slack, investigate optimizer restart and its
objective. If placed timing is stable but rerouting loses slack, retain those
legalized layouts and compare routing separately with the same layer and RC
settings. Do not label placement-estimated timing as routed signoff.

Keep failed and rejected arms alongside successful ones. Record all qualifying
baseline and candidate results in the workspace's experiment ledger, if one is
required, and retain scripts, constraints, per-stage reports and checkpoints for
replay. Do not weaken locality tests just because timing remains acceptable;
report continuity and QoR as separate measured properties.
