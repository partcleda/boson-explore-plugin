import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "compare"
sys.path.insert(0, str(SCRIPTS))
import _cmp
import buffer_trees

LIB = '''library(test) {
 cell(BUF) { area:1; pin(A) { direction:input; } pin(Y) { direction:output; function:"A"; } }
 cell(AND2) { area:1; pin(A) { direction:input; } pin(B) { direction:input; } pin(Y) { direction:output; function:"A&B"; } }
 cell(SPLIT) { area:1; pin(A) { direction:input; } pin(Y) { direction:output; function:"A"; } pin(Z) { direction:output; function:"!A"; } }
 cell(DFF) { area:1; ff(IQ,IQN) { clocked_on:"CK"; next_state:"D"; }
  pin(CK) { direction:input; clock:true; } pin(D) { direction:input; } pin(Q) { direction:output; function:"IQ"; } }
}'''
NETLIST = '''module top(input clk,a,b,output y,y2,p);
 wire n0,n1,n2,n3,alias,cclk,q,q2;
 BUF clone_buf(.A(a),.Y(n0));
 AND2 clone_gate(.A(n0),.B(b),.Y(n1));
 assign alias=n1;
 BUF sink0(.A(n1),.Y(n2));
 BUF sink1(.A(alias),.Y(y));
 SPLIT clone_multi(.A(n2),.Y(p),.Z(n3));
 BUF sink2(.A(n3),.Y(y2));
 BUF clone_clock(.A(clk),.Y(cclk));
 DFF clock0(.CK(clk),.D(n0),.Q(q));
 DFF clock1(.CK(cclk),.D(n0),.Q(q2));
endmodule'''


class DriverFanoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = self.root / "test.lib"
        self.netlist = self.root / "test.v"
        self.lib.write_text(LIB)
        self.netlist.write_text(NETLIST)
        self.g = _cmp.load(str(self.netlist), [str(self.lib)], quiet=True)

    def test_aliases_buffers_multiple_outputs_and_clock_exclusion(self):
        report = buffer_trees.selected_output_fanouts(self.g, re.compile("^clone_"), 10)
        self.assertEqual(report["count"], 4)
        self.assertEqual(report["fanout_histogram"], {0: 1, 1: 1, 2: 1, 3: 1})
        self.assertEqual([(r["driver"], r["loads"]) for r in report["largest"]],
                         [("clone_buf", 3), ("clone_gate", 2), ("clone_multi", 1), ("clone_multi", 0)])

    def test_empty_selection(self):
        report = buffer_trees.selected_output_fanouts(self.g, re.compile("absent"), 5)
        self.assertEqual(report["count"], 0)
        self.assertEqual(report["largest"], [])

    def test_unknown_cell_definitions_are_rejected(self):
        self.g.unknown_types.add("MISSING")
        with self.assertRaisesRegex(ValueError, "Liberty definitions.*MISSING"):
            buffer_trees.selected_output_fanouts(self.g, re.compile("clone"), 5)

    def test_cli_json_markdown_and_invalid_pattern(self):
        output = self.root / "report.json"
        args = [sys.executable, str(SCRIPTS / "buffer_trees.py"), "--liberty", str(self.lib),
                "--top", "top", f"ours={self.netlist}", "--out-json", str(output), "--driver-pattern"]
        result = subprocess.run(args + ["^clone_"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selected driver outputs", result.stdout)
        self.assertIn("clone_multi", result.stdout)
        self.assertEqual(json.loads(output.read_text())["ours"]["selected_outputs"]["count"], 4)
        invalid = subprocess.run(args + ["["], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid --driver-pattern", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
