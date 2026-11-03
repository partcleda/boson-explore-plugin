# acme_widget_core constraints, owner jdoe@acme-corp.com, 2026-10-01
set_units -time ns
create_clock -name core_clk -period 0.5 [get_ports clk_core]
set_input_delay 0.1 -clock core_clk [get_ports {din_a din_b}]
set_output_delay 0.1 -clock core_clk [all_outputs]
set_false_path -from [get_ports rst_n]
set_multicycle_path 2 -setup -to [get_pins u_acme_dsp/acc_q_reg*/D]
