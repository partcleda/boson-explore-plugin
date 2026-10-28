import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import skill_feedback as sf  # noqa: E402

SECRET = ["u_acme_core/alu_i/add_x_12", "/home/jdoe/acme/rtl/top.sv", "jdoe@acme.com", "AcmeFpu_lane[3]"]


def run(tmp, *args):
    return sf.main(["-f", str(tmp / "skill_feedback.json"), *args])


class SkillFeedback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        run(self.tmp, "init", "--skill", "boson-dc-datapath-compare", "--question", f"gap in {SECRET[0]}?")
        run(self.tmp, "add", "off_script", "--what", f"grep DP_OP in {SECRET[1]}", "--why", "no DC label method")
        run(self.tmp, "add", "missing_framework", "--what", "DC netlist ungrouped; could not label DW cells")
        run(self.tmp, "add", "wrong_guidance", "--what", "collect.tcl", "--error", f"link failed for {SECRET[3]}")
        (self.tmp / "split.json").write_text(json.dumps({"label_balance": 0.164, "timing": {"paired": 974}}))
        run(self.tmp, "coverage", "provenance=1.0", "--from-json", str(self.tmp / "split.json"),
            "--pick", "label_balance,timing.paired,timing.missing")

    def test_render_has_all_five_sections(self):
        run(self.tmp, "outcome", "partly", "--iterations", "3")
        md = sf.render(sf.load(self.tmp / "skill_feedback.json"))
        for title in list(sf.KINDS.values()) + ["Outcome"]:
            self.assertIn(title, md)
        self.assertIn("label_balance=0.164", md)
        self.assertIn("timing.paired=974", md)
        self.assertIn("partly, 3 iteration(s)", md)

    def test_share_requires_outcome(self):
        self.assertEqual(run(self.tmp, "share"), 1)

    def test_share_scrubs_names_and_sends_nothing(self):
        run(self.tmp, "outcome", "no", "--note", f"contact {SECRET[2]}")
        self.assertEqual(run(self.tmp, "share"), 0)
        anon = (self.tmp / "skill_feedback.share" / "skill_feedback.anon.json").read_text()
        for s in SECRET + ["acme", "jdoe"]:
            self.assertNotIn(s, anon)
        data = json.loads(anon)
        self.assertEqual(data["skill"], "boson-dc-datapath-compare")
        self.assertIn("collect.tcl", anon)            # tool names survive
        self.assertEqual(data["coverage"]["label_balance"], 0.164)
        tcl = (self.tmp / "skill_feedback.share" / "submit.tcl").read_text()
        self.assertIn("report_feedback -category docs -message $msg", tcl)
        self.assertEqual(os.stat(self.tmp / "skill_feedback.map.json").st_mode & 0o777, 0o600)

    def test_message_fits_report_feedback(self):
        for i in range(60):
            run(self.tmp, "add", "off_script", "--what", "x" * 300, "--why", "y" * 300)
        run(self.tmp, "outcome", "yes")
        fb = sf.load(self.tmp / "skill_feedback.json")
        self.assertLessEqual(len(sf.compact(fb)), sf.MAX_MESSAGE)

    @unittest.skipUnless(os.environ.get("NETLIST_DEBUG_ANONYMIZER"), "set NETLIST_DEBUG_ANONYMIZER=<anonymize.py>")
    def test_netlist_debug_name_map(self):
        anon = Path(os.environ["NETLIST_DEBUG_ANONYMIZER"])
        net = self.tmp / "n.v"
        net.write_text("module AcmeTop(input clk, output y);\n  wire n1;\n  AND2x2 u_acme_core (.A(clk), .B(clk), .Y(y));\nendmodule\n")
        subprocess.run([sys.executable, str(anon), "--map", str(self.tmp / "m.json"), "--netlist", str(net),
                        "--out", str(self.tmp / "anon")], check=True, capture_output=True)
        sf.ANONYMIZER = anon
        run(self.tmp, "add", "missing_input", "--what", "no timing for u_acme_core in AcmeTop")
        run(self.tmp, "outcome", "partly")
        self.assertEqual(run(self.tmp, "share", "--map", str(self.tmp / "m.json")), 0)
        out = (self.tmp / "skill_feedback.share" / "skill_feedback.anon.json").read_text()
        self.assertEqual(json.loads(out)["anonymized"], "netlist-debug name map")
        for s in SECRET + ["AcmeTop", "u_acme_core", "acme"]:
            self.assertNotIn(s, out)


if __name__ == "__main__":
    unittest.main()
