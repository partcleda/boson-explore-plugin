# Time one library arc of one cell at one table point and print what boson computes.
# Sourced by shape_probe.py in a session that has read only the mini library; it links
# a one-cell probe design (each call replaces the previous one). Set before sourcing:
#   probe_cell  lib cell             probe_mode  comb | edge | setup | hold
#   probe_clock_edge  rise (default) or fall: the clock edge the arc or check uses
#   probe_from  related pin          probe_to    the pin the table belongs to
#   probe_slew  transition at the related pin (clock pin for edge/setup/hold)
#   probe_dslew transition at the constrained (data) pin; setup/hold only
#   probe_load  load on probe_to (comb/edge) in library units
#   probe_unit_ns  ns per library time unit (0.001 for a ps library)
#   probe_points  optional list of {slew dslew load} triples: one link, every point timed
# Prints one line per point and edge:
#   PROBE <mode> <rise|fall> <delay|constraint> <transition> <point index>   (ns)
set lc [get_lib_cells $probe_cell]
set ins {}
set outs {}
foreach_in_collection p [get_lib_pins -quiet "[get_attribute $lc full_name]/*"] {
    set n [get_attribute $p base_name]
    switch [get_attribute $p direction] {
        input  { lappend ins $n }
        output { lappend outs $n }
        inout  { lappend outs $n }
    }
}
# only the pins under test are connected: an undriven input contributes no arrival and
# no slew, so the measured pin's transition is this arc's own, not the worst over all
# inputs that static timing would merge at the pin
set used [lsort -unique [list $probe_from $probe_to]]
set ins [lmap n $ins {expr {$n in $used ? $n : [continue]}}]
set outs [lmap n $outs {expr {$n in $used ? $n : [continue]}}]
set decl {}
set conns {}
foreach n $ins  { lappend decl "  input p_${n};";  lappend conns ".${n}(p_${n})" }
foreach n $outs { lappend decl "  output p_${n};"; lappend conns ".${n}(p_${n})" }
set fh [open probe_table.v w]
puts $fh "module probe ([join [lmap n [concat $ins $outs] {string cat p_ $n}] {, }]);"
puts $fh [join $decl \n]
puts $fh "  $probe_cell u0 ([join $conns {, }]);"
puts $fh "endmodule"
close $fh
read_verilog probe_table.v
link_design probe
# small enough that float rounding at the period cannot hide a constraint value
set period [expr {2.0 / $probe_unit_ns}]
if {![info exists probe_clock_edge]} { set probe_clock_edge rise }
set edge_ns [expr {$probe_clock_edge eq "fall" ? $period * $probe_unit_ns / 2.0 : 0.0}]
if {$probe_mode eq "comb"} {
    create_clock -name vclk -period $period
    set_input_delay 0 -clock vclk [all_inputs]
    set_output_delay 0 -clock vclk [all_outputs]
} else {
    # the falling edge sits at half the period; checks and delays are read relative to it
    set half [expr {$period / 2.0}]
    create_clock -name ck -period $period -waveform [list 0 $half] [get_ports p_$probe_from]
    set data [remove_from_collection [all_inputs] [get_ports p_$probe_from]]
    if {[sizeof_collection $data]} { set_input_delay 0 -clock ck $data }
    set_output_delay 0 -clock ck [all_outputs]
}
if {![info exists probe_points]} {
    set probe_points [list [list $probe_slew [expr {[info exists probe_dslew] ? $probe_dslew : 0}] $probe_load]]
}
set pi 0
foreach pt_spec $probe_points {
lassign $pt_spec slew dslew load
if {$probe_mode eq "comb"} {
    set_input_transition $slew [all_inputs]
} else {
    set_clock_transition $slew [get_clocks ck]
    if {[sizeof_collection $data]} { set_input_transition $dslew $data }
}
if {$probe_mode in {comb edge}} { set_load $load [get_ports p_$probe_to] }
update_timing
foreach edge {rise fall} {
    set v ""
    set tr ""
    switch $probe_mode {
        comb - edge {
            set from [expr {$probe_mode eq "comb" ? [get_ports p_$probe_from] : [get_pins u0/$probe_from]}]
            set p [get_timing_paths -from $from -${edge}_to [get_ports p_$probe_to]]
            if {[sizeof_collection $p]} {
                foreach_in_collection pt [get_attribute $p points] {
                    if {[get_object_name [get_attribute $pt object]] eq "u0/$probe_to"} {
                        set arr [get_attribute -quiet $pt arrival]
                        if {$arr ne ""} { set v [expr {$arr - ($probe_mode eq "edge" ? $edge_ns : 0.0)}] }
                        # this path's transition at the pin, not the pin's worst over all events
                        set tr [get_attribute -quiet $pt transition]
                    }
                }
            }
        }
        setup {
            set p [get_timing_paths -to [get_pins u0/$probe_to] -${edge}_to [get_pins u0/$probe_to]]
            # the check's capture edge: the next rising edge, or the falling edge
            set cap [expr {$probe_clock_edge eq "fall" ? $edge_ns : $period * $probe_unit_ns}]
            # a check may exist on one data edge only (recovery: the rising release)
            set req [expr {[sizeof_collection $p] ? [get_attribute -quiet $p required] : ""}]
            if {$req ne ""} { set v [expr {$cap - $req}] }
        }
        hold {
            set p [get_timing_paths -delay_type min -to [get_pins u0/$probe_to] -${edge}_to [get_pins u0/$probe_to]]
            # a hold check on the falling edge is against the falling edge before the
            # launch, half a period before time 0
            set req [expr {[sizeof_collection $p] ? [get_attribute -quiet $p required] : ""}]
            if {$req ne ""} { set v [expr {$req + $edge_ns}] }
        }
    }
    # "-" keeps the columns fixed when a value is missing
    puts "PROBE $probe_mode $edge [expr {$v eq {} ? {-} : $v}] [expr {$tr eq {} ? {-} : $tr}] $pi"
}
incr pi
}
unset probe_points
