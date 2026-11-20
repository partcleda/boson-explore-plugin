import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "datapath"))
from snapshot_path import join_path, word_index


class SnapshotPathTests(unittest.TestCase):
    def fixtures(self):
        mapped = {"nodes": {"name": ["u/a", "repair"], "kind": [0, 0]},
                  "kinds": [{"name": "AND"}],
                  "provenance": {"node": [0, -1], "records": [{"uid": 42, "origins": [0]}],
                                 "strings": ["unit.sv:5"]}}
        graph = {"nodes": {"kind": [0, 0], "width": [8, 8], "detail": ["left", "right"]},
                 "kinds": [{"name": "Add"}], "provenance": {"uid": [42, 42]}}
        path = {"points": [{"point": "u/a/B", "increment_ns": 0, "arrival_ns": .1},
                           {"point": "u/a/Z", "increment_ns": .02, "arrival_ns": .12},
                           {"point": "repair/Z", "increment_ns": .01, "arrival_ns": .13}]}
        return mapped, graph, path

    def test_hierarchical_names_repeated_uids_and_inserted_cells(self):
        mapped, graph, path = self.fixtures()
        rows = join_path(mapped, word_index(graph), path)
        self.assertEqual(rows[0]["cell"], "u/a")
        self.assertEqual(rows[0]["increment_ps"], 20)
        self.assertEqual([word["id"] for word in rows[0]["words"]], [0, 1])
        self.assertEqual(rows[1]["words"], [])

    def test_refuses_a_mismatched_netlist(self):
        mapped, graph, path = self.fixtures()
        mapped["nodes"]["name"][0] = "other"
        with self.assertRaisesRegex(ValueError, "no mapped snapshot cell"):
            join_path(mapped, word_index(graph), path)

    def test_refuses_duplicate_names_and_truncated_word_columns(self):
        mapped, graph, path = self.fixtures()
        mapped["nodes"]["name"][1] = "u/a"
        with self.assertRaisesRegex(ValueError, "duplicate cell names"):
            join_path(mapped, word_index(graph), path)
        graph["nodes"]["width"] = []
        with self.assertRaisesRegex(ValueError, "invalid column index"):
            word_index(graph)


if __name__ == "__main__":
    unittest.main()
