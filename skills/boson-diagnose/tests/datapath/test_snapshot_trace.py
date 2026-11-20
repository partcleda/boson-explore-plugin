import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "datapath"))
from snapshot_trace import summarize, trace


def graph(kind="Add", origin="unit.sv:12 u0", width=8):
    return {"nodes": {"kind": [0], "width": [width], "detail": ["choice"]},
            "kinds": [{"name": kind}],
            "provenance": {"node": [0], "records": [{"origins": [0]}], "strings": [origin]}}


class SnapshotTraceTests(unittest.TestCase):
    def test_summary_tracks_width_count_and_disappearance_without_detail_noise(self):
        def row(sequence, nodes):
            return {"seq": sequence, "stage": f"pass{sequence}", "file": f"{sequence}.js", "nodes": nodes}

        add = {"kind": "Add", "width": 8, "detail": "first"}
        rows = [row(0, [add, add]), row(1, [dict(add, detail="second"), add]),
                row(2, [add]), row(3, [dict(add, width=16)]), row(4, [])]
        summaries = summarize(rows)
        self.assertEqual([entry["seq"] for entry in summaries], [0, 2, 3, 4])
        self.assertEqual(summaries[0]["operators"], [{"kind": "Add", "width": 8, "count": 2}])
        self.assertEqual(summaries[1]["operators"], [{"kind": "Add", "width": 8, "count": 1}])
        self.assertEqual(summaries[2]["operators"], [{"kind": "Add", "width": 16, "count": 1}])
        self.assertEqual(summaries[3]["operators"], [])

    def archive(self, directory, graphs):
        entries = []
        for sequence, snapshot in enumerate(graphs):
            filename = f"{sequence}.js"
            (directory / filename).write_text(f"boson_snapshot({sequence},{json.dumps(snapshot)});\n")
            entries.append({"seq": sequence, "file": filename,
                            "level": "datapath", "stage": f"pass{sequence}"})
        (directory / "index.js").write_text(f"boson_index({json.dumps(entries)});\n")

    def test_records_changes_and_disappearance_without_repeating_unchanged_stages(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.archive(directory, [graph(), graph(), graph("AddTree"), graph(origin="other.sv:1")])
            rows = trace(directory, ["unit.sv:12"])
            self.assertEqual([row["seq"] for row in rows], [0, 2, 3])
            self.assertEqual(rows[1]["nodes"][0]["kind"], "AddTree")
            self.assertEqual(rows[-1]["nodes"], [])

    def test_rejects_missing_origins_and_malformed_snapshot_calls(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.archive(directory, [graph()])
            with self.assertRaisesRegex(ValueError, "no provenance nodes match"):
                trace(directory, ["absent.sv"])
            (directory / "0.js").write_text('boson_snapshot(0, {"broken":);')
            with self.assertRaisesRegex(ValueError, r"0.js:\d+:"):
                trace(directory, ["unit.sv"])

    def test_rejects_mismatched_sequences_and_truncated_columns(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.archive(directory, [graph()])
            (directory / "0.js").write_text(f"boson_snapshot(4,{json.dumps(graph())});")
            with self.assertRaisesRegex(ValueError, "sequence differs"):
                trace(directory, ["unit.sv"])
            snapshot = graph()
            snapshot["nodes"]["width"] = []
            self.archive(directory, [snapshot])
            with self.assertRaisesRegex(ValueError, "different lengths"):
                trace(directory, ["unit.sv"])
            snapshot = graph()
            snapshot["provenance"]["node"] = [-2]
            self.archive(directory, [snapshot])
            with self.assertRaisesRegex(ValueError, "invalid column index"):
                trace(directory, ["unit.sv"])

    def test_native_missing_provenance_does_not_hide_other_origins(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            snapshot = graph()
            snapshot["nodes"] = {"kind": [0, 0], "width": [8, 8], "detail": ["missing", "choice"]}
            snapshot["provenance"]["node"] = [-1, 0]
            self.archive(directory, [snapshot])
            rows = trace(directory, ["unit.sv"])
            self.assertEqual([node["id"] for node in rows[0]["nodes"]], [1])

    def test_rejects_paths_outside_archive(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            entries = [{"seq": 0, "file": "../outside.js", "level": "datapath", "stage": "pass"}]
            (directory / "index.js").write_text(f"boson_index({json.dumps(entries)});")
            with self.assertRaisesRegex(ValueError, "escapes archive"):
                trace(directory, ["unit.sv"])


if __name__ == "__main__":
    unittest.main()
