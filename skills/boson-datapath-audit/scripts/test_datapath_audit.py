import copy
import unittest

from datapath_audit import audit


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


if __name__ == "__main__":
    unittest.main()
