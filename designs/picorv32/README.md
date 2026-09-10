# picorv32 (vendored)

`picorv32.v` is vendored verbatim from [YosysHQ/picorv32](https://github.com/YosysHQ/picorv32)
(ISC license, see `LICENSE` in this directory) as the example RTL for the
`boson-timing-power-tradeoff` skill.

It was picked for its ~19 real top-module parameters (`BARREL_SHIFTER`,
`ENABLE_FAST_MUL`, `TWO_CYCLE_ALU`, `COMPRESSED_ISA`, `ENABLE_IRQ`,
`ENABLE_REGS_DUALPORT`, ...) — a genuine area/power/timing design space
from a single RTL file, with no testbench or PDK license required beyond an
open standard-cell library (the skill was verified against SkyWater
sky130's `sky130_fd_sc_hd`).
