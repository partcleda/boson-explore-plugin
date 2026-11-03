# Source after read_liberty, in a session that read the libraries exactly as the flow
# does. Writes into $lib_dir (default ./lib_model) what boson holds, for
# lib_inventory.py to compare with the Liberty text:
#   model.txt       pdb_query lib cell "" -tables: boson's internal model, every cell's
#                   pins and arcs (timing_type, sense, when) and its constraint tables
#                   as stored (shape, axes, values in ns)
#   libs.txt        get_libs, report_units
#   report_lib.txt  report_lib: every cell, area, pin count, s/c/d/t/p flags
#   check_library.txt  check_library: what the timer can and cannot time, per cell
#   cells.tsv       lib cell attributes
#   pins.tsv        lib pin attributes (direction, function, capacitances, limits)
#   arcs.tsv        lib timing arcs as get_lib_timing_arcs reports them (from, to,
#                   timing_type, sense, when): compared with model.txt to catch a query
#                   that collapses arcs the model keeps
#   census.tsv      per cell: pins by direction, arcs by type (the quick comparison)
# Keep read_liberty's own messages (LIB-*): run boson under `tee lib_read.log`.
if {![info exists lib_dir]} { set lib_dir lib_model }
file mkdir $lib_dir
proc lib_attr {obj name} {
    if {[catch {get_attribute -quiet $obj $name} v]} { return "?" }
    return [string map {"\t" " " "\n" " "} $v]
}
set fh [open $lib_dir/libs.txt w]
foreach_in_collection l [get_libs *] { puts $fh [get_object_name $l] }
close $fh
catch {report_units >> $lib_dir/libs.txt}
pdb_query lib cell "" -tables > $lib_dir/model.txt
report_lib > $lib_dir/report_lib.txt
check_library > $lib_dir/check_library.txt

set cell_attrs {area dont_use dont_touch is_sequential is_latch is_combinational is_inverter
    is_macro_cell is_memory_cell is_pad_cell is_isolation_cell is_level_shifter
    level_shifter_type retention_cell switch_cell_type always_on leakage_power
    has_multi_input_switching_data}
set pin_attrs {direction function capacitance rise_capacitance fall_capacitance
    max_capacitance max_transition max_fanout is_clock_pin}
set cf [open $lib_dir/cells.tsv w]
set pf [open $lib_dir/pins.tsv w]
set af [open $lib_dir/arcs.tsv w]
set nf [open $lib_dir/census.tsv w]
puts $cf "cell\t[join $cell_attrs \t]"
puts $pf "pin\t[join $pin_attrs \t]"
puts $af "arc\tfrom\tto\ttiming_type\tsense\twhen"
puts $nf "cell\tinputs\toutputs\tinouts\tinternal\tarcs\tarc_types"
set ncell 0
foreach_in_collection c [get_lib_cells *] {
    set cn [get_attribute $c full_name]
    set row [list $cn]
    foreach a $cell_attrs { lappend row [lib_attr $c $a] }
    puts $cf [join $row \t]
    set dirs [dict create input 0 output 0 inout 0 internal 0]
    # by full name: in boson 1.896 a foreach_in_collection loop variable is not
    # accepted by get_lib_pins -of_objects (it returns no pins)
    set pins [get_lib_pins -quiet "[get_attribute $c full_name]/*"]
    foreach_in_collection p $pins {
        set row [list [get_object_name $p]]
        foreach a $pin_attrs { lappend row [lib_attr $p $a] }
        puts $pf [join $row \t]
        set d [lib_attr $p direction]
        if {[dict exists $dirs $d]} { dict incr dirs $d }
    }
    set types [dict create]
    set narcs 0
    foreach_in_collection t [get_lib_timing_arcs -quiet -of_objects $pins] {
        set tt [lib_attr $t timing_type]
        puts $af "[get_object_name $t]\t[lib_attr $t from_pin]\t[lib_attr $t to_pin]\t$tt\t[lib_attr $t sense]\t[lib_attr $t when]"
        dict incr types $tt
        incr narcs
    }
    set tl {}
    dict for {k v} $types { lappend tl "$k=$v" }
    puts $nf "$cn\t[dict get $dirs input]\t[dict get $dirs output]\t[dict get $dirs inout]\t[dict get $dirs internal]\t$narcs\t[join [lsort $tl] { }]"
    incr ncell
}
foreach f [list $cf $pf $af $nf] { close $f }
puts "lib model dump: $ncell lib cells -> $lib_dir"
