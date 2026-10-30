import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from datapath_audit import audit, stages


def block(number=1, instance="u0", file="rtl/unit.sv", op="Add"):
    return {"block": number, "dp_node": number, "op": op, "width": 32,
            "lowering": "HanCarlson adder", "origins": [
                {"file": file, "line": 12, "col": 3, "instance": instance}]}


def story(cell, blocks, stage="technology mapping"):
    return {"cell": cell, "blocks": blocks, "mapped_in": stage, "aig_passes": ["dc2 -l", "&nf -K 6"]}


def timing(*cells):
    points = []
    for cell in cells:
        points.extend([{"point": cell + "/A", "increment_ns": 0},
                       {"point": cell + "/Y", "increment_ns": .01},
                       {"point": "hier/net", "increment_ns": None}])
    return {"schema_version": 1, "timing_complete": True, "warnings": "", "message": None,
            "paths": [{"startpoint": "in", "endpoint": "out", "slack_ns": -.1,
                       "unconstrained": False, "points": points}]}


class AuditTests(unittest.TestCase):
    def test_instances_and_ids_do_not_merge_at_same_source_line(self):
        records = [story("a", [block(1)]), story("b", [block(2, "u1")])]
        rows, coverage = audit(records, timing("a", "b"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["cells_per_path_max"] for r in rows}, {1})
        self.assertEqual(coverage["paths"][0]["matched_cells"], 2)

    def test_full_paths_and_instances_survive_missing_block_ids(self):
        a, b = block(file="one/unit.sv"), block(file="two/unit.sv")
        for item in (a, b):
            item.pop("block")
            item.pop("dp_node")
        rows, _ = audit([story("a", [a]), story("b", [b])], timing("a", "b"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["rtl"] for r in rows}, {"one/unit.sv:12", "two/unit.sv:12"})

    def test_duplicate_blocks_and_input_output_pins_count_once(self):
        rows, _ = audit([story("a", [block(), block()])], timing("a"))
        self.assertEqual(rows[0]["cells_per_path_max"], 1)
        self.assertEqual(rows[0]["rewritten_share"], {"dc2": 1.0})

    def test_missing_cells_and_repair_stages_visible(self):
        rows, coverage = audit([story("a", [block()]), story("b", [], "repair")], timing("a", "b", "c"))
        path = coverage["paths"][0]
        self.assertEqual(path["missing_cells"], ["c"])
        self.assertEqual(path["without_blocks"], ["b"])
        self.assertEqual(path["other_stages"], {"repair": 1})
        self.assertEqual(path["cell_candidates"], 3)
        self.assertEqual(len(rows), 1)

    def test_control_logic_is_available_without_claiming_arithmetic(self):
        records = [story("mux", [block(op="Mux")])]
        rows, coverage = audit(records, timing("mux"))
        self.assertEqual(rows, [])
        self.assertEqual(coverage["paths"][0]["arithmetic_attributed_cells"], 0)
        rows, _ = audit(records, timing("mux"), all_blocks=True)
        self.assertEqual(rows[0]["op"], "Mux")

    def test_summary_empty_and_mismatched_provenance_refused(self):
        for prov in ({"summary": {}}, [], [story("other", [block()])]):
            with self.subTest(prov=prov), self.assertRaises(ValueError):
                audit(prov, timing("a"))

    def test_unusable_timing_refused(self):
        base = timing("a")
        invalid = []
        for key, value in (("schema_version", 2), ("timing_complete", False), ("paths", [])):
            item = copy.deepcopy(base)
            item[key] = value
            invalid.append(item)
        item = copy.deepcopy(base)
        item["paths"][0]["slack_ns"] = None
        invalid.append(item)
        for item in invalid:
            with self.subTest(timing=item), self.assertRaises(ValueError):
                audit([story("a", [block()])], item)

    def test_shared_attribution_counts_unique_cells_per_block(self):
        rows, coverage = audit([story("a", [block(1), block(2)])], timing("a"))
        self.assertEqual([r["cells_per_path_max"] for r in rows], [1, 1])
        self.assertEqual(coverage["paths"][0]["arithmetic_attributed_cells"], 1)

    def test_final_adder_label_does_not_bound_multiplier_or_tree_depth(self):
        for op in ("Mul", "AddTree"):
            b = block(op=op)
            b["lowering"] = "KoggeStone adder, Booth multiplier"
            names = [f"c{i}" for i in range(20)]
            rows, _ = audit([story(n, [b]) for n in names], timing(*names))
            self.assertIsNone(rows[0]["ideal_cells"])
            self.assertFalse(rows[0]["deeper_than_architecture"])

    def test_inferred_labels_are_counted_apart_from_exact_ones(self):
        exact, inferred = dict(block(), exact=2, share=2), dict(block(), exact=0, share=1)
        records = [story(f"c{i}", [exact if i < 2 else inferred]) for i in range(16)]
        rows, _ = audit(records, timing(*[f"c{i}" for i in range(16)]))
        self.assertEqual(rows[0]["cells_per_path_max"], 16)
        self.assertEqual(rows[0]["exact_cells_per_path_max"], 2)
        self.assertTrue(rows[0]["deeper_than_architecture"])
        self.assertTrue(rows[0]["deeper_only_by_inference"])

    def test_stages_fold_consecutive_cells_of_one_block(self):
        a = dict(block(1, op="Sub"), exact=1, share=1)
        b = dict(block(2, op="AddTree"), exact=0, share=3)
        records = [story("s0", [a]), story("s1", [a, b]), story("t0", [b])]
        t = timing("s0", "s1", "t0")
        arrival = 0.0
        for pt in t["paths"][0]["points"]:
            arrival += pt["increment_ns"] or 0
            pt["arrival_ns"] = arrival
        (path,) = stages(records, t)
        self.assertEqual([r["exact"] for r in path["stages"]], [True, True, False])
        self.assertEqual([(g["cells"], g["exact_cells"]) for g in path["segments"]], [(2, 2), (1, 0)])
        self.assertAlmostEqual(sum(g["ps"] for g in path["segments"]), 30.0)


class CollectorTests(unittest.TestCase):
    def collect(self, setup="", assertions=""):
        script = r"""
set paths {path0}
set provenance_calls {}
proc update_timing {} {}
proc report_timing_status {args} { return complete }
proc report_timing {args} { set ::report_args $args }
proc get_timing_paths {args} {
    set ::path_args $args
    return $::paths
}
proc report_provenance {args} { lappend ::provenance_calls $args }
proc foreach_in_collection {var objects body} {
    uplevel 1 [list foreach $var $objects $body]
}
proc get_attribute {object attr} {
    if {$attr eq "points"} { return [list {u core/ge_reg[3]/D} {u core/add[7]/Y}] }
    if {$attr eq "object"} { return $object }
    error "unexpected attribute $attr"
}
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} { error $message }
}
""" + setup + r"""
if {[catch {source [lindex $argv 0]} message]} {
    puts stderr $message
    exit 1
}
""" + assertions
        with tempfile.TemporaryDirectory() as work:
            harness = Path(work) / "collect_test.tcl"
            harness.write_text(script)
            result = subprocess.run(
                ["tclsh", str(harness), str(Path(__file__).with_name("collect.tcl"))],
                cwd=work, capture_output=True, text=True, timeout=10)
        return result

    def test_global_defaults_stay_identical(self):
        result = self.collect(assertions=r"""
require {$audit_paths == 200 && $audit_path_args eq {}} "changed defaults"
require {$path_args eq {-max_paths 200 -nworst 1}} "unexpected path filters"
require {$report_args eq {-format json -max_paths 200 -nworst 1 -file datapath_audit/timing.json}} "unexpected report arguments"
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_target_filters_and_collections_reach_both_commands_identically(self):
        result = self.collect(setup=r"""
set audit_dir targeted
set audit_paths 20
set targets [list {u core/ge_reg[3]/D} {u core/ge_reg[7]/D}]
set audit_path_args [list -from {launch_reg*/Q} -through {u core/add[7]/Y} -to $targets]
""", assertions=r"""
require {[lrange $report_args 2 end-2] eq $path_args} "report and provenance sampled different paths"
require {[lrange $path_args 4 end] eq $audit_path_args} "filter arguments were split or re-evaluated"
require {$audit_cells eq {{u core/add[7]} {u core/ge_reg[3]}}} "literal cell names changed"
require {[lindex $provenance_calls end] eq [list -json $audit_cells > targeted/prov_paths.json]} "cell provenance differs from the selected paths"
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_targeted_sample_still_fails(self):
        result = self.collect(setup=r"""
set audit_path_args {-to missing/D}
set paths {}
""")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No path cells collected", result.stderr)

    def test_native_filter_error_stops_the_audit(self):
        result = self.collect(setup=r"""
set audit_path_args {-invalid_filter nope}
proc report_timing {args} { error "unknown timing option -invalid_filter" }
""")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown timing option -invalid_filter", result.stderr)


if __name__ == "__main__":
    unittest.main()
