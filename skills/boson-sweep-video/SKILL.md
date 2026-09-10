---
name: boson-sweep-video
description: Use when the user wants a design-space-exploration VIDEO or GIF from boson — an animated PPA sweep showing a boson terminal replaying each compile, a Pareto scatter of area vs achieved clock filling in point by point, and the real placement of each design point. Runs the sweep (RTL parameter axes × clock periods, one real compile+place+STA+power per point) and renders it. Triggers on "make a sweep video/gif", "animate the PPA space", "show the design space filling in", "Pareto animation".
---

# boson design-space sweep video

Three scripts, run in order, all under `scripts/` in this skill's directory:

1. `run_sweep.py` — runs the cartesian product of `--axis NAME=v1,v2` RTL
   parameter axes and `--periods` clock periods through boson. Each point is
   one real session: `compile` (synthesis + timing-driven placement),
   `report_qor`, `report_area`, `write_def`, random-activity `report_power`.
   Writes `<runs>/<tag>/` (logs, reports, DEF) plus `<runs>/space.json`.
   Restart-safe — re-running skips points whose `rc.txt` is `0`.
2. `collect.py` — parses every run dir into `<runs>/summary.json`. Called by
   step 3 automatically; run it alone to inspect a sweep in progress.
3. `render_video.py` — assembles the GIF and/or MP4 (and a final-frame PNG
   with `--still`). Left pane: boson terminal replaying the point's real
   progress lines against a time-lapse elapsed timer. Right pane: the
   parameter grid with evaluated points lit, the PPA scatter (x = std-cell
   area, y = achieved clock = 1/(period − WNS), marker size = power, colour =
   `--color-by` axis, shape = `--marker-by` axis), and the placement thumbnail
   of the point that just finished. Closes on the Pareto front.

```
S=skills/boson-sweep-video/scripts
python3 $S/run_sweep.py --rtl designs/picorv32/picorv32.v --top picorv32 \
  --liberty <cells.lib> --lef <tech.tlef> --lef <cells.lef> \
  --axis ENABLE_MUL=0,1 --axis BARREL_SHIFTER=0,1 --periods 8,20 \
  --color-by ENABLE_MUL --marker-by BARREL_SHIFTER \
  --label "ENABLE_MUL:1=hardware MUL" --title "picorv32 · sky130 · design space" \
  --runs runs
python3 $S/render_video.py --runs runs --gif demo/sweep.gif --mp4 demo/sweep.mp4 --still demo/sweep.png
```

## Prerequisites (check before running)

- A `boson` binary (`$BOSON_BIN` / `--boson-bin` / on PATH) — partcl's
  product, not shipped here (https://partcl.com).
- Liberty **and LEF** files for the target library. LEF is what makes
  placement real: boson's `place_design` refuses to run without a footprint
  for every cell, and the placement thumbnails are drawn from the DEF using
  the LEF `SIZE` of each cell. Pass the tech LEF first, then the cell LEF.
  The bundled picorv32 example is verified on SkyWater sky130
  (`sky130_fd_sc_hd__nom.tlef` + `sky130_fd_sc_hd.lef` + `..._tt_025C_1v80.lib`).
- Python: `numpy pillow matplotlib`, plus `imageio-ffmpeg` for MP4
  (`pip install -r requirements.txt` at the plugin root). DejaVu fonts
  (Sans + Sans Mono) — present on most Linux installs; set
  `BOSON_VIZ_FONT_DIR` otherwise.
- If boson runs through a container-based host wrapper, every path (RTL,
  libs, LEFs, `--runs`) must live **under the current working directory**.
  The scripts default `--runs runs` for that reason; copy or symlink PDK
  files into the working tree if boson can't see them.

## Choosing the sweep

- Pick axes that genuinely move PPA. picorv32: `ENABLE_MUL`, `ENABLE_FAST_MUL`,
  `BARREL_SHIFTER`, `TWO_CYCLE_ALU`, `COMPRESSED_ISA`, `ENABLE_IRQ`,
  `ENABLE_REGS_DUALPORT`. For another design, any top-module parameter works
  (they go straight to `compile -G NAME=VALUE`).
- Keep the grid small enough to finish: every point is a full compile. A
  2×2×2 grid is ~8 × (minutes to an hour, by design size). Ask the user
  before launching anything that will take more than an hour, and run the
  sweep in the background (`nohup`/background task) rather than blocking.
- `--color-by` should have ≤ 3 values (the first three palette slots are
  validated all-pairs on a scatter); put a 2-value axis on `--marker-by`.
  Include at least one period that violates and one that meets so the
  achieved-clock axis has spread.
- `--label AXIS:VALUE=text` turns raw parameter values into readable
  captions ("hardware MUL" instead of `ENABLE_MUL=1`); worth doing for the
  final video.
- Extra library setup (e.g. a `set_layer_rc` deck) goes in `--extra-tcl`;
  extra SDC (IO delays, false paths) in `--sdc-extra`; extra compile flags
  (`-blackbox`, `-compat vcs`) in `--compile-extra`.

## Rendering notes

- `render_video.py` orders points by cell count ascending (small → large)
  by default; pass `--order tag1 tag2 …` for a narrative order.
- `--supersample 2` (default) renders at 3200×1800 then downsamples: GIF at
  `--gif-scale 0.5` (1600×900), MP4 at `--mp4-scale 0.6` (1920×1080). A
  quick preview: `--supersample 1 --gif-scale 1 --secs-per-point 1.5`.
- `--compute-note` replaces the closing "N GPU-hours total" line when the
  user wants to name the hardware; otherwise it's derived from wall time.
- Everything on screen is real: the terminal lines are the point's own
  `[compile]`/`[layout-loop]` progress lines, the numbers are from the
  reports, the thumbnails are the written DEFs. Don't hand-edit the frames
  to make a point look better.

## Reporting back

Hand back the GIF/MP4 paths and the final-frame PNG, plus the `collect.py`
table (tag / cells / area / WNS / fmax / power / wall). Say which points
sit on the Pareto front and what the sweep actually showed — e.g. an axis
that everyone expected to help fmax but didn't. If any point failed
(`rc.txt` ≠ 0), say so and point at its `boson.err`.
