# Source after a `compile ... -provenance` and the flow you want to judge.
# Writes into $audit_dir (default: ./datapath_audit):
#   prov_summary.txt  report_provenance summary (passes that ran, edits by pass)
#   prov_paths.json   report_provenance -json for every cell on the sampled paths
#   timing.json       native report_timing -format json for the same sample
# Optional: set audit_paths (default 200) before sourcing.
if {![info exists audit_dir]}   { set audit_dir datapath_audit }
if {![info exists audit_paths]} { set audit_paths 200 }
file mkdir $audit_dir
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
report_provenance > $audit_dir/prov_summary.txt
set audit_cells {}
foreach_in_collection p [get_timing_paths -max_paths $audit_paths -nworst 1] {
    foreach_in_collection pt [get_attribute $p points] {
        set c [get_cells -quiet -of_objects [get_attribute $pt object]]
        if {[sizeof_collection $c]} { lappend audit_cells [get_object_name $c] }
    }
}
set audit_cells [lsort -unique $audit_cells]
puts "datapath audit: [llength $audit_cells] cells on the $audit_paths worst paths -> $audit_dir"
report_provenance -json [get_cells $audit_cells] > $audit_dir/prov_paths.json
report_timing -format json -max_paths $audit_paths -nworst 1 -file $audit_dir/timing.json
