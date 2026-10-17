#!/usr/bin/env python3
"""End-to-end check of the netlist-debug scripts on the synthetic fixtures.

    python3 skills/boson-netlist-debug/tests/test_end_to_end.py

Everything in fixtures/ is fake ("acme", "jdoe", "secret_sauce_sum" are the
names that must never reach a bundle).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = HERE.parent / "scripts"
F = HERE / "fixtures"
SECRETS = ["acme", "jdoe", "secret_sauce_sum", "acc_q", "u_acme_dsp", "core_clk", "clk_core", "din_a",
           "dout_valid", "hf_enable_net", "ASAP7", "buildbox7", "/home/"]


def run(*args, ok=True):
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise AssertionError(f"{args[0]} exited {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="bnd_test_"))
        cls.args = ["--map", cls.tmp / "name_map.json", "--netlist", F / "netlist.v", "--sdc", F / "constraints.sdc",
                    "--timing", F / "timing.rpt", "--timing-json", F / "timing.json", "--qor", F / "qor.rpt",
                    "--check-timing", F / "check_timing.rpt", "--log", F / "boson.log", "--journal", F / "decisions.jsonl",
                    "--rtl", F / "acme_dsp.sv", "--literal", "acme", "--literal", "buildbox7", "--pdk-node", "7 nm",
                    "--work", cls.tmp / "work", "--bundle-dir", cls.tmp / "boson-debug-bundle"]
        run(S / "make_bundle.py", *cls.args)
        (cls.tmp / "REPORT.md").write_text(
            "# Summary\nP1 `u1/r1_reg[0]/QN` -> `u1/r1_reg[1]/D` fails by 0.084 ns.\n"
            "A raw name that slipped in: `secret_sauce_sum` (the safety net must map it).\n")
        run(S / "make_bundle.py", *cls.args, "--report", cls.tmp / "REPORT.md")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_bundle_has_no_secrets(self):
        tgz = self.tmp / "boson-debug-bundle.tar.gz"
        self.assertTrue(tgz.exists())
        for p in (self.tmp / "boson-debug-bundle").rglob("*"):
            if p.is_file():
                t = p.read_text()
                for s in SECRETS:
                    self.assertNotIn(s, t, f"{s!r} leaked into {p.name}")
        self.assertFalse(any("name_map" in p.name for p in (self.tmp / "boson-debug-bundle").rglob("*")))
        self.assertFalse((self.tmp / "boson-debug-bundle" / "netlist").exists(), "netlist must be opt-in")

    def test_check_catches_leak(self):
        leaky = self.tmp / "leaky"
        shutil.copytree(self.tmp / "boson-debug-bundle", leaky)
        with open(leaky / "REPORT.md", "a") as f:
            f.write("the slow cone is secret_sauce_sum\n")
        p = run(S / "anonymize.py", "--map", self.tmp / "name_map.json", "--check", leaky, ok=False)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("secret_sauce_sum", p.stdout)
        p = run(S / "anonymize.py", "--map", self.tmp / "name_map.json", "--check", self.tmp / "boson-debug-bundle.tar.gz")
        self.assertIn("PASSED", p.stdout)

    def test_cross_references_survive(self):
        anon = self.tmp / "work" / "anon"
        net = (anon / "netlist.v").read_text()
        rpt = (anon / "timing_1.rpt").read_text()
        jr = (anon / "decisions.jsonl").read_text()
        enc = run(S / "anonymize.py", "--map", self.tmp / "name_map.json", "--encode", "u_acme_dsp/acc_q_reg[1]").stdout.strip()
        self.assertRegex(enc, r"^u\d+/r\d+_reg\[1\]$")
        self.assertIn(enc, net)
        self.assertIn(enc, rpt)
        self.assertIn(enc, jr)
        op = run(S / "anonymize.py", "--map", self.tmp / "name_map.json", "--encode", "u_acme_dsp/add_17").stdout.strip()
        self.assertIn(op + "_gs1", net)          # operator subject links to its mapped cells
        self.assertIn("_LIBX_R", net)            # library tag mapped, drive/VT kept
        self.assertIn("NAND2xp33", net)
        dec = run(S / "anonymize.py", "--map", self.tmp / "name_map.json", "--decode", enc).stdout.strip()
        self.assertEqual(dec, "u_acme_dsp/acc_q_reg[1]")

    def test_digests_flag_the_planted_problems(self):
        d = json.loads((self.tmp / "work" / "digests" / "journal_digest.json").read_text())
        self.assertEqual(d["worst_decisions"][0]["seq"], 3)                      # ripple adder lost WNS
        self.assertIn(13, [b["seq"] for b in d["rolled_back"]])                  # setup repair rolled back
        self.assertEqual({b["seq"] for b in d["alternative_beat_chosen"]}, {2, 3})
        self.assertEqual(d["hold_on_tight_setup"][0]["seq"], 12)
        self.assertEqual(d["flip_flops"][0]["n"], 4)
        self.assertEqual(d["probe_wins_not_shipped"][0]["seq"], 5)
        self.assertIn("WNS lost", d["checkpoints"][1]["flags"])
        self.assertTrue(any("P1" in b["paths"] for b in d["critical_path_decisions"]))
        t = json.loads((self.tmp / "work" / "digests" / "timing_digest.json").read_text())
        p1 = t["paths"][0]
        self.assertEqual((p1["slack_ns"], p1["stages"], p1["buffers"]), (-0.084, 5, 3))
        self.assertAlmostEqual(p1["skew_ns"], -0.01)
        n = json.loads((self.tmp / "work" / "digests" / "netlist_stats.json").read_text())
        self.assertEqual(n["buffers"]["max_chain"], 4)
        self.assertEqual(n["sequential"]["total"], 2)
        self.assertEqual(n["nets"]["undriven"], 0)


    def test_generic_rtl_words_and_names_in_chosen(self):
        """Regression (real picorv32 run): RTL identifiers that are ordinary words (debug, clk, running) must not
        fail the check on the scripts' own boilerplate, names inside journal `chosen` must be mapped, and a
        generic word in a STRUCTURED position must still fail."""
        t = self.tmp / "generic"
        t.mkdir()
        rtl = t / "words.sv"
        rtl.write_text("module acme_words (input clk, input debug, output running, output report);\n"
                       "  reg decoded_imm_j; assign running = debug; assign report = decoded_imm_j;\nendmodule\n")
        jr = t / "decisions.jsonl"
        lines = (F / "decisions.jsonl").read_text().splitlines()
        lines.insert(-2, json.dumps({"kind": "decision", "seq": 99, "t_s": 6.2, "stage": "medium: fast baseline",
                                     "domain": "sequential", "action": "register_removed",
                                     "subjects": ["u_acme_dsp/acc_q_reg[1]"], "chosen": "merged into decoded_imm_j[20]",
                                     "alternatives": [{"option": "keep", "verdict": "rejected"}], "inputs": {"kind": "merged"},
                                     "reason": "register is equivalent to another register"}))
        jr.write_text("\n".join(lines) + "\n")
        args = [a for a in self.args]
        args[args.index("--journal") + 1] = jr
        args[args.index("--rtl") + 1] = rtl
        for flag, val in (("--map", t / "name_map.json"), ("--work", t / "work"), ("--bundle-dir", t / "boson-debug-bundle")):
            args[args.index(flag) + 1] = val
        args += ["--rtl", F / "acme_dsp.sv"]
        report = t / "REPORT.md"
        report.write_text("# Summary\nThe debug bundle shows the flow still running hold repair on the clk domain.\n")
        p = run(S / "make_bundle.py", *args, "--report", report)
        self.assertIn("PASSED", p.stdout)
        self.assertNotIn("WARN", p.stdout)                      # no warnings on the bundle's own file names
        b = t / "boson-debug-bundle"
        alltext = "".join(f.read_text() for f in b.rglob("*") if f.is_file())
        self.assertNotIn("decoded_imm_j", alltext)
        self.assertRegex((b / "journal" / "decisions.jsonl").read_text(), r'"chosen":"merged into [a-z]+\d+\[20\]"')
        # a generic word that is a design name, in a structured position: must fail
        sdc = next((b / "constraints").glob("*.sdc"))
        with open(sdc, "a") as f:
            f.write("set_false_path -to [get_ports running]\n")
        p = run(S / "anonymize.py", "--map", t / "name_map.json", "--check", b, ok=False)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("'running' (structured position)", p.stdout)

    def test_hierarchical_netlist(self):
        v = self.tmp / "hier.v"
        v.write_text("module zorg_leaf (a, b, y);\n  input a; input b; output y;\n"
                     "  sky130_fd_sc_hd__nand2_1 u_n (.A(a), .B(b), .Y(y));\nendmodule\n"
                     "module zorg_top (clk, x, z);\n  input clk; input [1:0] x; output z;\n  wire mid, z_int;\n"
                     "  zorg_leaf u_leaf0 (.a(x[0]), .b(x[1]), .y(mid));\n"
                     "  zorg_leaf u_leaf1 (.a(mid), .b(x[1]), .y(z_int));\n"
                     "  sky130_fd_sc_hd__dfxtp_1 state_q_reg (.CLK(clk), .D(z_int), .Q(z));\nendmodule\n")
        out, mp = self.tmp / "hier_anon", self.tmp / "hier_map.json"
        run(S / "anonymize.py", "--out", out, "--map", mp, "--netlist", v)
        t = (out / "netlist.v").read_text()
        for s in ("zorg", "u_leaf", "mid", "state_q", "sky130"):
            self.assertNotIn(s, t)
        self.assertIn("LIBX__dfxtp_1", t)
        self.assertRegex(t, r"module top \(in\d+, in\d+, out\d+\)")
        n = json.loads(run(S / "netlist_stats.py", out / "netlist.v", "--out-json", self.tmp / "h.json").returncode == 0
                       and (self.tmp / "h.json").read_text())
        self.assertEqual(n["nets"]["undriven"], 0)
        self.assertEqual({r["instantiations"] for r in n["modules_tree"]}, {1, 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
