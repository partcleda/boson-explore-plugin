// Generated for acme_widget_core by jdoe on host buildbox7.acme-corp.com
// Written by boson write_verilog
module acme_widget_core (clk_core, rst_n, din_a, din_b, \dout_sum[0] , \dout_sum[1] , dout_valid);
  input clk_core;
  input rst_n;
  input din_a;
  input din_b;
  output \dout_sum[0] ;
  output \dout_sum[1] ;
  output dout_valid;
  wire \u_acme_dsp/secret_sauce_sum[0] ;
  wire \u_acme_dsp/secret_sauce_sum[1] ;
  wire n101;
  wire n102;
  wire n103;
  wire n104;
  wire hf_enable_net;
  wire \u_acme_dsp/acc_q[0]__qn_bsn ;
  wire _tielo_net_1;
  DFFHQNx1_ASAP7_75t_R \u_acme_dsp/acc_q_reg[0]  (.CLK(clk_core), .D(n104), .QN(\u_acme_dsp/acc_q[0]__qn_bsn ));
  DFFHQNx1_ASAP7_75t_R \u_acme_dsp/acc_q_reg[1]  (.CLK(clk_core), .D(n103), .QN(n105));
  FAx1_ASAP7_75t_R \u_acme_dsp/add_17_gs1  (.A(din_a), .B(din_b), .CI(\u_acme_dsp/acc_q[0]__qn_bsn ), .CON(n101), .SN(n102));
  BUFx2_ASAP7_75t_R gs10 (.A(n101), .Y(n106));
  BUFx2_ASAP7_75t_R gs11 (.A(n106), .Y(n107));
  BUFx2_ASAP7_75t_R gs12 (.A(n107), .Y(n108));
  INVx1_ASAP7_75t_R gs13 (.A(n108), .Y(n103));
  NAND2xp33_ASAP7_75t_R gs14 (.A(n102), .B(rst_n), .Y(n104));
  INVx1_ASAP7_75t_L gs15 (.A(rst_n), .Y(hf_enable_net));
  AND2x2_ASAP7_75t_R gs16 (.A(hf_enable_net), .B(n104), .Y(\u_acme_dsp/secret_sauce_sum[0] ));
  AND2x2_ASAP7_75t_R gs17 (.A(hf_enable_net), .B(n103), .Y(\u_acme_dsp/secret_sauce_sum[1] ));
  OR2x2_ASAP7_75t_R gs18 (.A(hf_enable_net), .B(n105), .Y(dout_valid));
  AND2x2_ASAP7_75t_R gs19 (.A(hf_enable_net), .B(n102), .Y());
  TIELOx1_ASAP7_75t_R gs20 (.L(_tielo_net_1));
  assign \dout_sum[0]  = \u_acme_dsp/secret_sauce_sum[0] ;
  assign \dout_sum[1]  = \u_acme_dsp/secret_sauce_sum[1] ;
endmodule
