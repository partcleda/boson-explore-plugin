// reference-style hierarchical netlist of the same function
module eqcmp (p, q, eq);
  input [3:0] p;
  input [3:0] q;
  output eq;
  wire [3:0] x;
  wire n1;
  AO2N2_X1 e0 (.A1(p[0]), .B1(p[0]), .A2(q[0]), .B2(q[0]), .ZN(x[0]));
  AO2N2_X1 e1 (.A1(p[1]), .B1(p[1]), .A2(q[1]), .B2(q[1]), .ZN(x[1]));
  AO2N2_X1 e2 (.A1(p[2]), .B1(p[2]), .A2(q[2]), .B2(q[2]), .ZN(x[2]));
  AO2N2_X1 e3 (.A1(p[3]), .B1(p[3]), .A2(q[3]), .B2(q[3]), .ZN(x[3]));
  NAND4_X1 red (.A1(x[0]), .A2(x[1]), .A3(x[2]), .A4(x[3]), .ZN(n1));
  INV_X1 o (.I(n1), .ZN(eq));
endmodule
module top (clk, a, b, ci, eq, s, co, far);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input ci;
  output eq, s, co, far;
  wire [3:0] aq, bq;
  wire ck, n2, cot, ainv;
  CLKBUF_X1 ckbuf (.I(clk), .Z(ck));
  DFF_X1 \aq_reg[0] (.D(a[0]), .CP(ck), .Q(aq[0]));
  DFF_X1 \aq_reg[1] (.D(a[1]), .CP(ck), .Q(aq[1]));
  DFF_X1 \aq_reg[2] (.D(a[2]), .CP(ck), .Q(aq[2]));
  DFF_X1 \aq_reg[3] (.D(a[3]), .CP(ck), .Q(aq[3]));
  DFF_X1 \bq_reg[0] (.D(b[0]), .CP(ck), .Q(bq[0]));
  DFF_X1 \bq_reg[1] (.D(b[1]), .CP(ck), .Q(bq[1]));
  DFF_X1 \bq_reg[2] (.D(b[2]), .CP(ck), .Q(bq[2]));
  DFF_X1 \bq_reg[3] (.D(b[3]), .CP(ck), .Q(bq[3]));
  eqcmp u_eq (.p(aq), .q(bq), .eq(eq));
  INV_X1 inv_side (.I(aq[0]), .ZN(ainv));
  NAND2_X1 d2 (.A1(ainv), .A2(bq[1]), .ZN(n2));
  FA_X1 fa0 (.A(aq[1]), .B(bq[1]), .CI(ci), .S(s), .CO(cot));
  AOI22_X1 cmb (.A1(cot), .A2(n2), .B1(cot), .B2(cot), .ZN(co));
  AND2_X1 fsink (.A1(aq[2]), .A2(bq[2]), .Z(far));
endmodule
