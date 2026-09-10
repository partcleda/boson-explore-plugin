#!/usr/bin/env bash
# Exactly the command used to record demo/boson_dse.gif and the README's
# sample table. Needs a sky130_fd_sc_hd liberty file — not vendored here
# (13MB); point $BOSON_LIBERTY at your own copy
# (https://github.com/google/skywater-pdk) or any other Liberty file.
set -e
cd "$(dirname "$0")/.."
python3 skills/boson-timing-power-tradeoff/scripts/boson_dse.py \
  --rtl designs/picorv32/picorv32.v --top picorv32 \
  --liberty "${BOSON_LIBERTY:?set BOSON_LIBERTY to a sky130_fd_sc_hd .lib file}" \
  --periods 6,20 --presets min-area,balanced,max-perf
