# Time a gate netlist (DC's, or boson's written one) in a fresh boson session with the
# libraries and SDC used for the other netlist. Set before sourcing:
#   dw_netlist  path to the gate-level Verilog      dw_top  top module
#   dw_sdc      the SDC (same file for both netlists)
#   dw_dir      output directory (default: dw_dc)   dw_paths  endpoint cap (default all)
# and read_liberty every library first (the same set, in the same order, as the
# boson compile). Writes cells.tsv and paths.tsv in the collect_boson.tcl formats.
foreach v {dw_netlist dw_top dw_sdc} {
    if {![info exists $v]} { error "set $v before sourcing score_netlist.tcl" }
}
if {![info exists dw_dir]}   { set dw_dir dw_dc }
if {![info exists dw_paths]} { set dw_paths 1000000 }
file mkdir $dw_dir
read_verilog $dw_netlist
link_design $dw_top
read_sdc $dw_sdc
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
source [file join [file dirname [info script]] cells_common.tcl]
set cells [dw_leaf_cells]
dw_write_cells $cells $dw_dir/cells.tsv
set npaths [dw_write_paths $dw_paths $dw_dir/paths.tsv]
report_qor > $dw_dir/qor.rpt
puts "dw score: [sizeof_collection $cells] cells, $npaths endpoint paths -> $dw_dir"
