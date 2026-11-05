"""Positive, planted-negative and unsupported cases for the affine checker."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "compare"))
from linear_equiv import main

LIB = Path(__file__).resolve().parent / "fixtures" / "lib.lib"
HEADER = "module top(input clk, input a, input b, output y); wire q, d, x;\n"
REGISTER = "DFF_X1 state (.D(d), .CP(clk), .Q(q));\n"
GOLD = HEADER + REGISTER + """
XOR2_X1 first (.A1(q), .A2(b), .Z(x));
XOR2_X1 second (.A1(x), .A2(b), .Z(y));
BUF_X1 capture (.I(a), .Z(d));
endmodule
"""
GOOD = HEADER + REGISTER + """
BUF_X1 out (.I(q), .Z(y));
BUF_X1 capture (.I(a), .Z(d));
endmodule
"""


class LinearEquivalenceTest(unittest.TestCase):
    def check(self, gold, gate):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("gold.v", "gate.v")]
            for path, text in zip(paths, (gold, gate)):
                path.write_text(text)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--liberty", str(LIB), "--top", "top", *map(str, paths)])
            return result, output.getvalue()

    def test_cancellation_across_register_cut_points(self):
        code, output = self.check(GOLD, GOOD)
        self.assertEqual(code, 0, output)
        self.assertIn("0 mismatches", output)

    def test_output_mutation_is_rejected(self):
        code, output = self.check(GOLD, GOOD.replace(".I(q)", ".I(b)"))
        self.assertEqual(code, 1, output)
        self.assertIn("first mismatch", output)

    def test_capture_mutation_is_rejected(self):
        self.assertEqual(self.check(GOLD, GOOD.replace(".I(a)", ".I(b)"))[0], 1)

    def test_nonlinear_cone_is_inconclusive(self):
        gate = GOOD.replace("BUF_X1 out (.I(q), .Z(y));",
                            "NAND2_X1 out (.A1(q), .A2(b), .ZN(y));")
        self.assertEqual(self.check(GOLD, gate)[0], 2)

    def test_unmatched_cut_point_is_inconclusive(self):
        self.assertEqual(self.check(GOLD, GOOD.replace("state (", "renamed ("))[0], 2)

    def test_cycle_is_inconclusive(self):
        self.assertEqual(self.check(GOLD, GOOD.replace(".I(q)", ".I(y)"))[0], 2)

    def test_multiple_drivers_are_inconclusive(self):
        gate = GOOD.replace("endmodule", "BUF_X1 other (.I(a), .Z(y));\nendmodule")
        self.assertEqual(self.check(GOLD, gate)[0], 2)

    def test_unknown_cell_is_inconclusive(self):
        self.assertEqual(self.check(GOLD, GOOD.replace("BUF_X1 out", "UNKNOWN out"))[0], 2)

    def test_unknown_literals_are_inconclusive(self):
        self.assertEqual(self.check(GOLD, GOOD.replace(".I(q)", ".I(1'bx)"))[0], 2)

    def test_three_state_functions_are_inconclusive(self):
        from _cmp import LibCell
        from linear_equiv import LinearChecker
        cell = LibCell("TBUF")
        cell.inputs = ["A"]
        cell.functions = {"Y": "A"}
        cell.three_state = True
        with self.assertRaisesRegex(ValueError, "three-state"):
            LinearChecker({"TBUF": cell}).form("TBUF", "Y")


if __name__ == "__main__":
    unittest.main()
