# Source after a `compile ... -provenance` and the flow you want to judge.
# Writes into $audit_dir (default: ./datapath_audit):
#   prov_summary.txt  report_provenance summary (passes that ran, edits by pass)
#   prov_paths.json   report_provenance -json for every cell on the sampled paths
#   timing.json       native report_timing -format json for the same sample
#   path_trace.*      native path provenance, including delay by RTL source
# Optional: set audit_paths (default 200) before sourcing.
if {![info exists audit_dir]}   { set audit_dir datapath_audit }
if {![info exists audit_paths]} { set audit_paths 200 }
if {![info exists audit_path_args]} { set audit_path_args {} }
file mkdir $audit_dir
update_timing
if {[report_timing_status -quiet] ne "complete"} { error "Timing did not complete" }
report_timing -format json -max_paths $audit_paths -nworst 1 {*}$audit_path_args -file $audit_dir/timing.json
report_provenance > $audit_dir/prov_summary.txt
set audit_timing_paths [get_timing_paths -max_paths $audit_paths -nworst 1 {*}$audit_path_args]
report_provenance $audit_timing_paths > $audit_dir/path_trace.txt
report_provenance -json $audit_timing_paths > $audit_dir/path_trace.json
set audit_cells {}
foreach_in_collection p $audit_timing_paths {
    foreach_in_collection pt [get_attribute $p points] {
        set pin [get_attribute $pt object]
        set slash [string last / $pin]
        if {$slash >= 0} { lappend audit_cells [string range $pin 0 [expr {$slash - 1}]] }
    }
}
set audit_cells [lsort -unique $audit_cells]
puts "datapath audit: [llength $audit_cells] cells on the $audit_paths worst paths -> $audit_dir"
if {![llength $audit_cells]} { error "No path cells collected; inspect timing paths before auditing provenance" }
report_provenance -json $audit_cells > $audit_dir/prov_paths.json
