"""The reference-compare scripts on a hand-built pair of netlists of one design.

boson.v (flat): a 4-bit a == b from four XNOR2 and a NAND4, a full-adder bit from
    a separate sum cell and carry cell, three buffers in series on a 450 um net,
    and a clock NAND2 used in data logic.
reference.v (hierarchical): the compare from four AND-OR-invert cells with paired
    inputs (each an XNOR) in a submodule, a library full adder, no buffers.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "compare"))
import _cmp  # noqa: E402
import buffer_trees  # noqa: E402
import cell_mix  # noqa: E402
import logic_patterns  # noqa: E402
import path_families  # noqa: E402
import run_ab  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
LIB = str(FIX / "lib.lib")


def graph(name):
    return _cmp.load(str(FIX / name), [LIB], quiet=True)


class FunctionClassTest(unittest.TestCase):
    def test_cells_are_classed_by_function_not_name(self):
        lib = _cmp.read_liberty([LIB])
        expect = {"CLKNAND2_X1": "simple", "CLKBUF_X1": "buffer", "INV_X1": "inverter", "XNOR2_X1": "xor_xnor",
                  "MUX2_X1": "mux", "AOI22_X1": "complex", "AO2N2_X1": "complex", "FA_X1": "full_adder",
                  "HA_X1": "half_adder", "SUM3_X1": "adder_sum", "MAJI3_X1": "adder_carry",
                  "DFF_X1": "sequential", "ICG_X1": "clock_gate", "SRAM_MACRO": "macro", "NOR4_X1": "simple"}
        self.assertEqual({k: lib[k].category for k in expect}, expect)
        self.assertEqual(lib["DFF_X1"].clock_pins, {"CP"})

    def test_tied_inputs_turn_an_aoi_into_an_xnor(self):
        lib = _cmp.read_liberty([LIB])
        self.assertEqual(_cmp.tied_function(lib["AO2N2_X1"], [["A1", "B1"], ["A2", "B2"]]), "xor_xnor")

    def test_liberty_operators(self):
        for fn, cat in (("A1 A2", "simple"), ("(A1+A2)'", "simple"), ("!(A1^A2)", "xor_xnor"),
                        ("(I0&!S)|(I1&S)", "mux"), ("A1|(A2&B1)", "complex"), ("1", "tie")):
            tt, n = _cmp.truth_table(fn, ["A1", "A2", "B1", "I0", "I1", "S"])
            self.assertEqual(_cmp.classify_function(tt, n), cat, fn)


class NetlistTest(unittest.TestCase):
    def test_hierarchy_is_flattened_through_bus_ports(self):
        g = graph("reference.v")
        names = set(g.nl.inst_name)
        self.assertIn("u_eq/e3", names)
        e3 = g.nl.inst_name.index("u_eq/e3")
        self.assertEqual({g.nl.net_name[n] for _, n in g.inputs[e3]}, {"aq[3]", "bq[3]"})

    def test_clock_network_is_traced_from_clock_pins(self):
        g = graph("boson.v")
        ck = next(n for n, name in enumerate(g.nl.net_name) if name == "ck")
        self.assertIn(ck, g.clock_nets)


class CellMixTest(unittest.TestCase):
    def test_gap_by_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mix.json"
            cell_mix.main(["--liberty", LIB, f"boson={FIX / 'boson.v'}", f"ref={FIX / 'reference.v'}",
                           "--out-json", str(out), "--out-md", str(Path(tmp) / "mix.md")])
            d = json.loads(out.read_text())
        b, r = d["runs"]["boson"], d["runs"]["ref"]
        self.assertEqual(b["adders"]["split_full_adder_bits"], 1)
        self.assertEqual(r["adders"]["full_adder_cells"], 1)
        self.assertEqual(r["tied_inputs"]["complex -> xor_xnor"]["cells"], 4)
        self.assertEqual(b["clock_class_on_data"]["on_data_by_category"]["simple"]["cells"], 1)
        self.assertEqual(b["clock_class_on_data"]["on_clock_network"], 1)
        gap = b["gap"]
        self.assertAlmostEqual(gap["std_area"], b["std_area"] - r["std_area"])
        self.assertAlmostEqual(sum(v["delta_area"] for v in gap["by_pattern"].values()), gap["std_area"])
        self.assertAlmostEqual(gap["by_pattern"]["xor/xnor"]["delta_area"], 4.8)


class LogicPatternsTest(unittest.TestCase):
    def test_xnors_are_compare_bits(self):
        d = logic_patterns.xor_usage(graph("boson.v"), 4, 3)
        self.assertEqual(d["classes"]["compare"]["cells"], 4)

    def test_cone_counts_exclusive_and_shared_cells(self):
        g = graph("boson.v")
        d = logic_patterns.cone(g, logic_patterns.find_net(g, "eq", None))
        self.assertEqual(d["exclusive_by_function"], {"XNOR2": 4, "NAND4": 1, "INV": 1})
        ref = graph("reference.v")
        d = logic_patterns.cone(ref, logic_patterns.find_net(ref, "eq", None))
        self.assertEqual(d["exclusive_by_function"], {"AO2N2": 4, "NAND4": 1, "INV": 1})
        g = graph("boson.v")
        d = logic_patterns.cone(g, logic_patterns.find_net(g, "co", None))
        self.assertEqual(d["shared"], 0)
        self.assertIn("CLKNAND2", d["exclusive_by_function"])


class BufferTreeTest(unittest.TestCase):
    def test_long_net_tree_levels_and_spacing(self):
        g = graph("boson.v")
        loc = _cmp.read_def_locations(str(FIX / "boson.def"))
        trees = {t["net"]: t for t in buffer_trees.walk_trees(g, loc)}
        t = trees["aq[2]"]
        self.assertEqual((t["levels"], t["buffers"], t["sinks"]), (3, 3, 2))
        self.assertEqual(t["far"], 450.0)
        self.assertEqual(t["edges"], [30.0, 30.0, 30.0])
        self.assertNotIn("ck", trees)
        s = buffer_trees.summarize(list(trees.values()), True, 3)
        self.assertEqual(s["by_distance"][">400"]["spacing_um"], 30.0)


class PathFamilyTest(unittest.TestCase):
    def test_buffer_delay_and_closable(self):
        lib = _cmp.read_liberty([LIB])
        g = _cmp.Graph(_cmp.read_netlist(str(FIX / "boson.v")), lib)
        paths = [path_families.annotate(p, g) for p in path_families.read_paths(FIX / "boson_paths.tsv")]
        far = next(p for p in paths if p["end"] == "far")
        self.assertEqual((far["buffers"], far["logic"]), (3, 1))
        self.assertAlmostEqual(far["buffer_delay"], 0.038 + 0.045 + 0.05)
        ref = _cmp.Graph(_cmp.read_netlist(str(FIX / "reference.v")), lib)
        ref_paths = [path_families.annotate(p, ref) for p in path_families.read_paths(FIX / "ref_timing.json")]
        report = path_families.compare({"boson": paths, "ref": ref_paths}, "ref", None)
        fam = report["runs"]["boson"]["families"]["aq_reg[#] -> far"]
        self.assertEqual(fam["run"]["closable"], 1)
        self.assertEqual(fam["reference"]["buffers_per_path"], 0)

    def test_family_names_collapse_numbers_and_pins(self):
        self.assertEqual(path_families.family_name("tile_3/u_alu/acc_reg[5]/D", None), "tile_#/u_alu/acc_reg[#]")
        self.assertEqual(path_families.family_name("tile_3/u_alu/acc_reg[5]/D", 1), "tile_#/...")


class RouteAndRunTest(unittest.TestCase):
    def test_route_layers(self):
        nets = {n: (use, lengths) for n, use, lengths, _ in _cmp.read_def_routing(str(FIX / "reference.def"))}
        self.assertEqual(nets["far_net"][1], {"M2": 2.0, "M7": 450.0})

    def test_wire_model_calibration_is_flagged(self):
        r = run_ab.read_log(FIX / "new.log")
        self.assertEqual(r["version"], "2.10.0")
        self.assertTrue(r["calibrations"][0]["at_hold"])
        j = run_ab.read_journal(FIX / "new.jsonl")
        self.assertEqual(j["app_vars"], {"structural_adders": "true"})
        self.assertEqual(j["checkpoints"][1]["d_tns_ns"], -780)
        md = run_ab.to_md({"old": run_ab.read_log(FIX / "old.log"), "new": {**r, **j}})
        self.assertIn("wire_price_route_calibration off", md)


if __name__ == "__main__":
    unittest.main()
