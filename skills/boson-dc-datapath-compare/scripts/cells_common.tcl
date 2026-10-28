# Shared by collect_boson.tcl and score_netlist.tcl: one row per leaf cell,
#   cell <TAB> lib cell <TAB> area <TAB> output nets <TAB> input nets
# (nets space-separated), so the comparison can label cells by name and connectivity.
proc dw_write_cells {cells path} {
    set fh [open $path w]
    foreach_in_collection c $cells {
        set outs {}
        set ins {}
        foreach_in_collection p [get_pins -quiet -of_objects $c] {
            set n [get_nets -quiet -of_objects $p]
            if {![sizeof_collection $n]} { continue }
            if {[get_attribute $p direction] in {out output}} {
                lappend outs [get_object_name $n]
            } else {
                lappend ins [get_object_name $n]
            }
        }
        puts $fh "[get_object_name $c]\t[get_attribute $c ref_name]\t[get_attribute $c area]\t[join $outs { }]\t[join $ins { }]"
    }
    close $fh
}
proc dw_leaf_cells {} {
    set cells [get_cells -quiet -hierarchical * -filter "is_hierarchical == false"]
    if {![sizeof_collection $cells]} { set cells [get_cells *] }
    return $cells
}
# Worst setup path to each endpoint (up to $limit), compact:
#   P <TAB> startpoint <TAB> endpoint <TAB> slack <TAB> arrival <TAB> required
#   <TAB> pin <TAB> arrival            (one row per point, ns)
# Every endpoint, not just the failing ones: the other netlist's worst endpoints
# must find their partner here even when it has positive slack.
proc dw_write_paths {limit path} {
    set fh [open $path w]
    set n 0
    foreach_in_collection p [get_timing_paths -max_paths $limit -nworst 1] {
        set slack [get_attribute $p slack]
        if {$slack eq "" || $slack eq "INFINITY"} { continue }
        puts $fh "P\t[get_object_name [get_attribute $p startpoint]]\t[get_object_name [get_attribute $p endpoint]]\t$slack\t[get_attribute $p arrival]\t[get_attribute $p required]"
        foreach_in_collection pt [get_attribute $p points] {
            puts $fh "\t[get_object_name [get_attribute $pt object]]\t[get_attribute $pt arrival]"
        }
        incr n
    }
    close $fh
    return $n
}
