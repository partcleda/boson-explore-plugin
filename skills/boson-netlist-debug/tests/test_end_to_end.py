#!/usr/bin/env python3
"""End-to-end check of the netlist-debug scripts on the synthetic fixtures.

    python3 skills/boson-netlist-debug/tests/test_end_to_end.py

Everything in fixtures/ is fake ("acme", "jdoe", "secret_sauce_sum" are the
names that must never reach a bundle).
"""
import json
import re
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


# ---- synthetic placed report in boson 1.823's full_clock_expanded column layout (fake cells, fake names) ----
COLS = {"Fanout": 67, "Cap": 75, "DTrans": 83, "Trans": 90, "Derate": 98, "Delta": 105, "Incr": 115, "Path": 127}
HEADER = ("  Point" + " " * 54 + "Fanout     Cap  DTrans  Trans  Derate  Delta      Incr        Path    Location")


def _row(obj, cell, vals, edge, loc):
    line = f"  {obj} ({cell})"
    for col in ("DTrans", "Trans", "Derate", "Delta", "Incr", "Path"):
        if col in vals:
            v = f"{vals[col]:.3f}"
            line = line.ljust(COLS[col] - len(v)) + v
            if col == "Incr":
                line += " &"
    return line + f" {edge}  ({loc[0]:.3f},{loc[1]:.3f})"


def _net(name, fo, cap):
    line = f"  {name} (net)"
    line = line.ljust(COLS["Fanout"] - len(str(fo))) + str(fo)
    return line.ljust(COLS["Cap"] - 5) + f"{cap:.3f}"


def _clk(text, incr, path):
    return f"  {text}".ljust(COLS["Incr"] - 5) + f"{incr:.3f}" + f"{path:.3f}".rjust(COLS["Path"] - COLS["Incr"])


def make_placed_report(path: Path) -> dict:
    """One violating reg->reg path through two buffers, a long wire and an AOI; returns the expected digest."""
    L = ["****************************************", "Report : timing", "    -path_type full_clock_expanded",
         "    -max_paths 1", "Design : zorp_math_top", "Tool   : boson 1.823.9", "****************************************", "", "",
         "  Startpoint: zorp_src_reg[3] (rising edge-triggered flip-flop clocked by clk)",
         "  Endpoint: zlane[1].u_zl.zdst_reg (rising edge-triggered flip-flop clocked by clk)",
         "  Path Group: clk", "  Path Type: max", "", HEADER, "  " + "-" * 137,
         _clk("clock clk (rise edge)", 0.0, 0.0), _clk("clock network delay (ideal)", 0.0, 0.0),
         _row("zorp_src_reg[3]/CP", "DFQD1ZQ7SVT", {"Derate": 1, "Delta": 0, "Incr": 0, "Path": 0}, "r", (48.678, 1.840)),
         _row("zorp_src_reg[3]/Q", "DFQD1ZQ7SVT", {"Trans": .009, "Derate": 1, "Incr": .044, "Path": .044}, "f", (48.336, 1.800)),
         _net("zorp_src[3]", 1, .001),
         _row("fanout_repair_b1/I", "BUFFD5ZQ7ULVT", {"DTrans": .009, "Trans": .009, "Derate": 1, "Delta": 0, "Incr": 0, "Path": .044}, "f", (48.507, 2.320)),
         _row("fanout_repair_b1/Z", "BUFFD5ZQ7ULVT", {"Trans": .007, "Derate": 1, "Incr": .012, "Path": .056}, "f", (48.735, 2.280)),
         _net("net", 4, .005),
         _row("fanout_repair_b2/I", "BUFFD8ZQ7ULVT", {"DTrans": .007, "Trans": .024, "Derate": 1, "Delta": 0, "Incr": .009, "Path": .065}, "f", (31.065, 38.480)),
         _row("fanout_repair_b2/Z", "BUFFD8ZQ7ULVT", {"Trans": .009, "Derate": 1, "Incr": .015, "Path": .080}, "f", (31.407, 38.540)),
         _net("fanout_repair_n2", 2, .009),
         _row("gs50300/C1", "AOI222D1ZQ7LVT", {"DTrans": .009, "Trans": .038, "Derate": 1, "Delta": 0, "Incr": .014, "Path": .094}, "f", (30.894, 78.400)),
         _row("gs50300/ZN", "AOI222D1ZQ7LVT", {"Trans": .027, "Derate": 1, "Incr": .024, "Path": .118}, "r", (30.552, 78.440)),
         _net("n13236", 1, .000),
         _row("zlane[1].u_zl.zdst_reg/D", "DFQD2ZQ7SVT", {"DTrans": .027, "Trans": .027, "Derate": 1, "Delta": 0, "Incr": 0, "Path": .118}, "r", (30.324, 78.480)),
         "  data arrival time".ljust(COLS["Path"] - 5) + "0.118", "",
         _clk("clock clk (rise edge)", .100, .100), _clk("clock network delay (ideal)", 0.0, .100),
         _row("zlane[1].u_zl.zdst_reg/CP", "DFQD2ZQ7SVT", {"Derate": 1, "Delta": 0, "Incr": 0, "Path": .100}, "r", (30.0, 78.0)),
         _clk("clock uncertainty", -.020, .080), _clk("library setup time", -.007, .073),
         "  data required time".ljust(COLS["Path"] - 5) + "0.073", "  " + "-" * 137,
         "  slack (VIOLATED)".ljust(COLS["Path"] - 6) + "-0.045", ""]
    path.write_text("\n".join(L) + "\n")
    return {"arrival_ns": 0.118, "slack_ns": -0.045, "stages": 3, "slowest": 0.024, "skew_ns": 0.0,
            "longest_wire_um": round(abs(48.735 - 31.065) + abs(2.280 - 38.480), 3), "fanout_net": 4}


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

    def test_placed_report_columns_and_report_vocabulary(self):
        """Regression (boson 1.823.9 physical run): the Location '(x,y)' column must not be read as delay, fanout
        comes from the (net) rows, wire lengths come from Location; and RTL identifiers that are report / unit
        words (net, ohm, res, load, limit, clear, signal) must not be mapped inside report or log prose, while a
        real net named `net` is still mapped in structured positions."""
        t = self.tmp / "placed"
        t.mkdir()
        rpt = t / "timing.rpt"
        exp = make_placed_report(rpt)
        rtl = t / "zorp.v"
        rtl.write_text("module zorp_math_top (input clk, input zorp_in, output zorp_out);\n"
                       "  wire net, ohm, res, load, limit, clear, signal, sinks, fF;\nendmodule\n")
        net = t / "netlist.v"
        net.write_text("module zorp_math_top (clk, zorp_in, zorp_out);\n  input clk;\n  input zorp_in;\n  output zorp_out;\n"
                       "  wire net;\n  BUFFD5ZQ7ULVT fanout_repair_b1 (.I(zorp_in), .Z(net));\n"
                       "  BUFFD8ZQ7ULVT fanout_repair_b2 (.I(net), .Z(zorp_out));\nendmodule\n")
        log = t / "boson.log"
        log.write_text("set_layer_rc: layer M2 registered at cap 0.2640 fF/um, res 68.5000 ohm/um\n"
                       "set_wire_rc: clock-network wire RC set; signal nets keep their own model; load limit 0.08\n"
                       "Information: library preset/clear arc ignored; 12 sinks\n"
                       "Warning: net 'net' has 4 loads\n")
        work, mp = t / "work", t / "map.json"
        run(S / "make_bundle.py", "--work", work, "--map", mp, "--netlist", net, "--timing", rpt, "--log", log,
            "--rtl", rtl, "--lib-tag", "(?P<tag>ZQ7)", "--bundle-dir", t / "bundle")
        anon = (work / "anon" / "timing_1.rpt").read_text()
        self.assertEqual(anon.count("(net)"), 4)
        self.assertIn("(rise edge)", anon)
        self.assertIn("slack (VIOLATED)", anon)
        for line in anon.splitlines():         # anonymized rows keep their columns: Path still ends under 'Path'
            m = re.search(r"(-?\d+\.\d{3}) [rf]  \(", line)
            if m:
                self.assertEqual(m.end(1), COLS["Path"], line)
        alog = (work / "anon" / "boson_1.log").read_text()
        for phrase in ("fF/um, res 68.5000 ohm/um", "signal nets keep their own model", "load limit 0.08",
                       "preset/clear arc", "12 sinks"):
            self.assertIn(phrase, alog)
        self.assertNotIn("'net'", alog)          # quoted object name: mapped
        self.assertNotIn("(net)", (work / "anon" / "netlist.v").read_text())
        self.assertRegex((work / "anon" / "netlist.v").read_text(), r"\.Z\(w\d+\)")
        d = json.loads((work / "digests" / "timing_digest.json").read_text())["paths"][0]
        raw = json.loads(run(S / "timing_digest.py", "--timing", rpt, "--out-json", t / "raw.json").returncode == 0
                         and (t / "raw.json").read_text())["paths"][0]
        for k in ("arrival_ns", "slack_ns", "stages", "skew_ns", "total_wire_um", "cell_delay_ns", "max_fanout"):
            self.assertEqual(d[k], raw[k], k)
        self.assertAlmostEqual(d["arrival_ns"], exp["arrival_ns"])
        self.assertAlmostEqual(d["slack_ns"], exp["slack_ns"])
        self.assertEqual(d["stages"], exp["stages"])
        self.assertAlmostEqual(d["slowest"][0]["delay_ns"], exp["slowest"])
        self.assertAlmostEqual(d["skew_ns"], exp["skew_ns"])
        self.assertAlmostEqual(d["longest_wires"][0]["wire_um"], exp["longest_wire_um"])
        self.assertEqual(d["longest_wires"][0]["fanout"], exp["fanout_net"])
        self.assertTrue(d["placed"])

    def test_clock_cells_by_function(self):
        v = self.tmp / "ck.v"
        v.write_text("module ck_top (clk, a, b, y);\n  input clk; input a; input b; output y;\n  wire gclk, x, q;\n"
                     "  CKBD4BWP99LVT ckb (.I(clk), .Z(gclk));\n"
                     "  CKND2D4BWP99ULVT ckn2 (.A1(a), .A2(b), .ZN(x));\n"
                     "  CKND4BWP99LVT cki (.I(x), .ZN(y));\n"
                     "  DFQD1BWP99SVT r_reg (.CP(gclk), .D(x), .Q(q));\nendmodule\n")
        n = json.loads(run(S / "netlist_stats.py", v, "--out-json", self.tmp / "ck.json").returncode == 0
                       and (self.tmp / "ck.json").read_text())
        self.assertEqual(n["by_class"].get("clock_logic"), 1)       # CKND2 = clock NAND2, not an inverter
        self.assertEqual(n["by_class"].get("clock_inverter"), 1)
        ck = n["clock_network"]
        self.assertEqual(ck["cells_on_clock"], 1)                    # the CKBD buffer
        self.assertEqual(ck["clock_class_cells_on_data_nets"], 2)    # CKND2 and CKND on data
        self.assertEqual(ck["clock_class_on_data_by_function"], {"CKND2": 1, "CKN": 1})

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
