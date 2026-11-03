# Source in the boson session right after `compile ... -provenance` (and after the
# flow stage you want to compare, e.g. place/repair). Writes into $dw_dir
# (default: ./dw_boson):
#   netlist.v       the netlist as boson holds it now
#   cells.tsv       cell, lib cell, area, output nets, input nets for every leaf cell
#   prov_cells.NNNN.json  report_provenance -json for every leaf cell, in chunks (block, op, width,
#                   lowering, exact/inferred, repair-inserted)
#   resources.rpt   report_resources: each lowered operator and its construction
#   paths.tsv       worst setup path to every timed endpoint (cap: $dw_paths)
# Then score the DC netlist with score_netlist.tcl in a fresh session using the SAME
# libraries and SDC, so both netlists are timed by one engine.
if {![info exists dw_dir]}   { set dw_dir dw_boson }
if {![info exists dw_paths]} { set dw_paths 1000000 }
file mkdir $dw_dir
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
write_verilog $dw_dir/netlist.v
# boson's own operator inventory (architecture per adder/multiplier/shifter), the
# counterpart of DC's report_resources
report_resources > $dw_dir/resources.rpt
source [file join [file dirname [info script]] cells_common.tcl]
set cells [dw_leaf_cells]
dw_write_cells $cells $dw_dir/cells.tsv
# provenance in chunks: one JSON array per $dw_chunk cells keeps each file loadable
if {![info exists dw_chunk]} { set dw_chunk 5000 }
foreach f [glob -nocomplain $dw_dir/prov_cells.*.json] { file delete $f }
set names {}
foreach_in_collection c $cells { lappend names [get_object_name $c] }
for {set i 0} {$i < [llength $names]} {incr i $dw_chunk} {
    set chunk [lrange $names $i [expr {$i + $dw_chunk - 1}]]
    report_provenance -json [get_cells $chunk] > [format "%s/prov_cells.%04d.json" $dw_dir [expr {$i / $dw_chunk}]]
}
set npaths [dw_write_paths $dw_paths $dw_dir/paths.tsv]
puts "dw collect: [sizeof_collection $cells] cells, $npaths endpoint paths -> $dw_dir"
