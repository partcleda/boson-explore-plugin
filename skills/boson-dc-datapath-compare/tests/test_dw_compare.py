"""dw_compare on a hand-built pair of netlists: one 2-cell adder path in each tool.

DC: launch reg r0 -> \\u_alu/add_x_12/U1 (named DW) -> U2 (enclosed by the region)
    -> \\u_alu/add_x_12/U3 -> U9 (random logic) -> r1/D
boson: r0 -> g1, g2 (provenance: Add32 in u_alu) -> g9 (Mux) -> g8 (Add in u_ctl,
    where DC has no DW) -> r1/D
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dw_compare as dw  # noqa: E402


def write(d: Path, cells, paths, stories=None):
    d.mkdir(parents=True, exist_ok=True)
    (d / "cells.tsv").write_text("".join(f"{n}\t{r}\t{a}\t{' '.join(o)}\t{' '.join(i)}\n" for n, r, a, o, i in cells))
    lines = []
    for start, end, slack, req, pts in paths:
        lines.append(f"P\t{start}\t{end}\t{slack}\t{pts[-1][1]}\t{req}")
        lines += [f"\t{p}\t{t}" for p, t in pts]
    (d / "paths.tsv").write_text("\n".join(lines) + "\n")
    if stories is not None:
        (d / "prov_cells.0000.json").write_text(json.dumps(stories))


def story(cell, op=None, inst="u_alu", exact=1):
    blocks = [] if op is None else [{"block": 1, "share": 2, "exact": exact, "op": op, "width": 32,
                                     "lowering": "KoggeStone adder",
                                     "origins": [{"file": "a.sv", "line": 12, "instance": inst, "operator": True}]}]
    return {"cell": cell, "blocks": blocks}


class DwCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        dc = [("\\r0", "DFFHQNx1", 1.0, ["q0"], ["d0", "clk"]),
              ("\\u_alu/add_x_12/U1", "XOR2xp5", 0.2, ["u_alu/add_x_12/n1"], ["q0"]),
              ("U2", "NAND2xp5", 0.1, ["n2"], ["u_alu/add_x_12/n1"]),
              ("\\u_alu/add_x_12/U3", "XOR2xp5", 0.2, ["u_alu/add_x_12/n3"], ["n2"]),
              ("U9", "AO21x1", 0.3, ["n9"], ["u_alu/add_x_12/n3"]),
              ("\\r1", "DFFHQNx1", 1.0, ["q1"], ["n9", "clk"])]
        write(self.tmp / "dc", dc, [("\\r0/CLK", "\\r1/D", 0.010, 0.310,
              [("\\r0/CLK", 0), ("\\r0/QN", 0.040), ("\\u_alu/add_x_12/U1/A", 0.040), ("\\u_alu/add_x_12/U1/Y", 0.100),
               ("U2/A", 0.100), ("U2/Y", 0.150), ("\\u_alu/add_x_12/U3/A", 0.150), ("\\u_alu/add_x_12/U3/Y", 0.200),
               ("U9/A", 0.200), ("U9/Y", 0.300), ("\\r1/D", 0.300)])])
        bo = [("r0", "DFFHQNx1", 1.0, ["q0"], ["d0", "clk"]),
              ("g1", "XOR2xp5", 0.3, ["n1"], ["q0"]),
              ("g2", "XOR2xp5", 0.3, ["n2"], ["n1"]),
              ("g9", "AO21x1", 0.3, ["n9"], ["n2"]),
              ("g8", "XOR2xp5", 0.2, ["n8"], ["n9"]),
              ("r1", "DFFHQNx1", 1.0, ["q1"], ["n8", "clk"])]
        write(self.tmp / "bo", bo, [("r0/CLK", "r1/D", -0.090, 0.470,
              [("r0/CLK", 0), ("r0/QN", 0.050), ("g1/A", 0.050), ("g1/Y", 0.200), ("g2/A", 0.200), ("g2/Y", 0.330),
               ("g9/A", 0.330), ("g9/Y", 0.400), ("g8/A", 0.400), ("g8/Y", 0.560), ("r1/D", 0.560)])],
              [story("r0"), story("g1", "Add"), story("g2", "Add", exact=0), story("g9", "Mux"),
               story("g8", "Add", inst="u_ctl"), story("r1")])

    def test_dc_labels_name_net_and_enclosed(self):
        lab = dw.label_dc(dw.read_cells(self.tmp / "dc" / "cells.tsv"))
        self.assertEqual(lab["\\u_alu/add_x_12/U1"]["how"], "name")
        self.assertEqual(lab["U2"]["how"], "enclosed")
        self.assertEqual(lab["U2"]["region"], "u_alu/add_x_12")
        self.assertEqual(lab["U9"]["cls"], "logic")
        self.assertEqual(lab["\\r0"]["cls"], "register")

    def test_split_sums_to_gap_and_scopes_unlabeled_arith(self):
        r = dw.compare(self.tmp / "bo", self.tmp / "dc")
        t = r["timing"]
        self.assertEqual(t["paired_exact"], 1)
        self.assertAlmostEqual(t["gap_sum_ps"], 100.0, places=3)
        self.assertAlmostEqual(sum(t["delta_by_class_ps"].values()), t["gap_sum_ps"], places=3)
        # DC adder (U1,U2,U3) = 160 ps; boson adder g1,g2 = 280 ps
        self.assertAlmostEqual(t["delta_by_class_ps"]["dw"], 120.0, places=3)
        # g8 is an adder in u_ctl, where DC shows no DW: random logic in the default scope
        self.assertEqual(r["boson_datapath_outside_dc_dw_instances"], 0.2)
        self.assertAlmostEqual(t["delta_by_class_ps"]["logic"], 130.0, places=3)
        self.assertAlmostEqual(t["delta_by_class_ps"]["required/setup"], -160.0, places=3)
        self.assertAlmostEqual(r["area"]["delta_dw"], 0.6 - 0.5, places=6)
        alldw = dw.compare(self.tmp / "bo", self.tmp / "dc", scope="all")
        self.assertAlmostEqual(alldw["timing"]["delta_by_class_ps"]["dw"], 280.0, places=3)

    def test_dw_name_patterns(self):
        for part in ("DP_OP_12J3_45_678", "add_x_12", "mult_45", "gte_x_7", "DW01_add_0", "DW_mult_tc_1", "sub_123_2"):
            self.assertTrue(dw.DW_PART.match(part), part)
        for part in ("mult_unit", "alu_core", "adder", "U123", "add_x", "DWELL"):
            self.assertFalse(dw.DW_PART.match(part), part)
        self.assertEqual(dw.dc_family("DW02_mult_2"), "multiply")
        self.assertEqual(dw.dc_family("gte_x_7"), "compare")

    def test_endpoint_group_key(self):
        self.assertEqual(dw.endpoint_keys("u_top.u_regs.\\regs_q[3][5]/D")[1],
                         dw.endpoint_keys("u_top.u_regs.regs_q[29]/D")[1])

    def test_parse_resources(self):
        text = """
Resource Report for this hierarchy in file ./alu.sv
=============================================================================
| Cell           | Module         | Parameters | Contained Operations       |
=============================================================================
| add_x_12       | DW01_add       | width=32   | add_12                     |
| DP_OP_7J1_1_2  | DP_OP_7J1_1_2  |            | mult_20 add_21             |
=============================================================================

Implementation Report
===============================================================================
|                    |                  | Current            | Set            |
| Cell               | Module           | Implementation     | Implementation |
===============================================================================
| add_x_12           | DW01_add         | pparch (area,speed)|                |
===============================================================================
"""
        res = dw.parse_resources(text)
        self.assertEqual(res["add_x_12"]["impl"], "pparch (area,speed)")
        self.assertEqual(res["DP_OP_7J1_1_2"]["ops"], [("mult", 20), ("add", 21)])


if __name__ == "__main__":
    unittest.main()
