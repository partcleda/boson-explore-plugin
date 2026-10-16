`define ACME_SECRET_WIDTH 2
// proprietary: acme
module acme_dsp #(parameter int SAUCE_W = `ACME_SECRET_WIDTH) (input logic clk_core, input logic din_a, din_b, output logic [1:0] secret_sauce_sum);
  logic [1:0] acc_q;
  assign secret_sauce_sum = din_a + din_b + acc_q;
  always_ff @(posedge clk_core) acc_q <= secret_sauce_sum;
endmodule
