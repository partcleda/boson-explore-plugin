// boson-style flat netlist: equality compare from XNORs, a full-adder bit from
// separate sum and carry cells, a buffer chain, and a clock NAND2 in data logic
module top (clk, a, b, ci, eq, s, co, far);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input ci;
  output eq, s, co, far;
  wire [3:0] aq, bq, x;
  wire n1, n2, n3, nf1, nf2, nf3, ck, con, ainv;
  CLKBUF_X1 ckbuf (.I(clk), .Z(ck));
  DFF_X1 \aq_reg[0] (.D(a[0]), .CP(ck), .Q(aq[0]));
  DFF_X1 \aq_reg[1] (.D(a[1]), .CP(ck), .Q(aq[1]));
  DFF_X1 \aq_reg[2] (.D(a[2]), .CP(ck), .Q(aq[2]));
  DFF_X1 \aq_reg[3] (.D(a[3]), .CP(ck), .Q(aq[3]));
  DFF_X1 \bq_reg[0] (.D(b[0]), .CP(ck), .Q(bq[0]));
  DFF_X1 \bq_reg[1] (.D(b[1]), .CP(ck), .Q(bq[1]));
  DFF_X1 \bq_reg[2] (.D(b[2]), .CP(ck), .Q(bq[2]));
  DFF_X1 \bq_reg[3] (.D(b[3]), .CP(ck), .Q(bq[3]));
  XNOR2_X1 cmp0 (.A1(aq[0]), .A2(bq[0]), .ZN(x[0]));
  XNOR2_X1 cmp1 (.A1(aq[1]), .A2(bq[1]), .ZN(x[1]));
  XNOR2_X1 cmp2 (.A1(aq[2]), .A2(bq[2]), .ZN(x[2]));
  XNOR2_X1 cmp3 (.A1(aq[3]), .A2(bq[3]), .ZN(x[3]));
  NAND4_X1 red (.A1(x[0]), .A2(x[1]), .A3(x[2]), .A4(x[3]), .ZN(n1));
  INV_X1 inv_out (.I(n1), .ZN(eq));
  INV_X1 inv_side (.I(aq[0]), .ZN(ainv));
  CLKNAND2_X1 data_ck (.A1(ainv), .A2(bq[1]), .ZN(n2));
  SUM3_X1 sum0 (.A(aq[1]), .B(bq[1]), .CI(ci), .S(s));
  MAJI3_X1 car0 (.A(aq[1]), .B(bq[1]), .CI(ci), .CON(con));
  NOR2_X1 cnr (.A1(con), .A2(n2), .ZN(co));
  BUF_X1 fb1 (.I(aq[2]), .Z(nf1));
  BUF_X1 fb2 (.I(nf1), .Z(nf2));
  BUF_X1 fb3 (.I(nf2), .Z(nf3));
  AND2_X1 fsink (.A1(nf3), .A2(bq[2]), .Z(far));
endmodule
