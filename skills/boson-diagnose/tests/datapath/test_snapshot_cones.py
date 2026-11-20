import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "datapath"))
from snapshot_trace import ConeQuery, fanin, trace


def graph():
    return {"kinds": [{"name": "PORT_IN", "class": "input"},
                      {"name": "ADD_U", "class": "arith"},
                      {"name": "WIRE", "class": "other"},
                      {"name": "PORT_OUT", "class": "output"},
                      {"name": "DFF", "class": "register"}],
            "nodes": {"kind": [0, 1, 2, 3, 4, 1], "width": [4, 4, 4, 4, 4, 4],
                      "name": ["input", "sum", "result[3]", "result[3]", "state", "unused"],
                      "detail": [""] * 6},
            "edges": {"src": [0, 4, 1, 2, 5], "dst": [1, 1, 2, 3, 4]},
            "provenance": {"node": [0] * 6, "records": [{"origins": [0]}], "strings": ["unit.sv:1"]}}


def archive(directory, snapshots):
    entries = []
    for sequence, snapshot in enumerate(snapshots):
        filename = f"{sequence}.js"
        (directory / filename).write_text(f"boson_snapshot({sequence},{json.dumps(snapshot)});\n")
        entries.append({"seq": sequence, "file": filename, "level": "datapath_compiler",
                        "stage": "fold", "main": True, "probe": False})
    (directory / "index.js").write_text(f"boson_index({json.dumps(entries)});\n")


class ConeTests(unittest.TestCase):
    def test_follows_aliases_and_cuts_register_data(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            archive(directory, [graph()])
            report = fanin(directory, ConeQuery("result[3]", "fold", kind="PORT_OUT"))
            self.assertEqual(report["node_count"], 5)
            self.assertEqual(report["kinds"]["ADD_U"], 1)
            self.assertEqual(report["bit_count"], 20)
            self.assertEqual(report["nodes"][-1]["inputs"], [])
            self.assertNotIn("unused", [node["name"] for node in report["nodes"]])

    def test_directed_path_uses_data_pin_and_cuts_registers(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            snapshot = graph()
            snapshot["edges"] = {"src": [0, 4, 1, 2, 5, 2], "dst": [1, 1, 2, 3, 4, 4],
                                 "pins": ["", "D", "CP"], "dst_pin": [0, 0, 0, 0, 2, 1]}
            archive(directory, [snapshot])
            data = fanin(directory, ConeQuery("state", "fold", launch="state", capture_pin="D"))
            self.assertEqual([node["id"] for node in data["path"]], [4, 1, 2, 4])
            self.assertEqual(data["path"][2]["fanout"], 2)
            clock = fanin(directory, ConeQuery("state", "fold", launch="state", capture_pin="CP"))
            self.assertIsNone(clock["path"])
            with self.assertRaisesRegex(ValueError, "no edges into capture pin"):
                fanin(directory, ConeQuery("state", "fold", launch="input", capture_pin="Q"))

    def test_names_are_literal_and_ambiguous_names_fail(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            archive(directory, [graph()])
            for signal in ["result*", "result[3]"]:
                with self.assertRaisesRegex(ValueError, "literal node-name match"):
                    fanin(directory, ConeQuery(signal, "fold"))

    def test_repeated_passes_require_sequence_and_probes_are_excluded(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            archive(directory, [graph(), graph()])
            with self.assertRaisesRegex(ValueError, "matching sequences \\[0, 1\\]"):
                fanin(directory, ConeQuery("sum", "fold"))
            self.assertEqual(fanin(directory, ConeQuery("sum", sequence=1))["seq"], 1)
            path = directory / "index.js"
            text = path.read_text().replace('"probe": false', '"probe": true', 1)
            path.write_text(text)
            self.assertEqual(fanin(directory, ConeQuery("sum", "fold"))["seq"], 1)

    def test_rejects_truncated_edges_and_invalid_indices(self):
        for mutate in [lambda g: g["edges"]["src"].append(0),
                       lambda g: g["edges"]["src"].__setitem__(0, -1),
                       lambda g: g["nodes"]["kind"].__setitem__(0, True),
                       lambda g: g["nodes"]["width"].pop()]:
            with tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                snapshot = graph()
                mutate(snapshot)
                archive(directory, [snapshot])
                with self.assertRaisesRegex(ValueError, "0.js:0: invalid fanin graph"):
                    fanin(directory, ConeQuery("sum", "fold"))

    def test_cycles_are_reported_once(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            snapshot = graph()
            snapshot["edges"] = {"src": [1], "dst": [1]}
            archive(directory, [snapshot])
            report = fanin(directory, ConeQuery("sum", "fold"))
            self.assertEqual(report["node_count"], 1)
            self.assertEqual(report["nodes"][0]["inputs"], [1])

    def test_native_origins_can_be_traced_without_assuming_node_identity(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            first = graph()
            second = copy.deepcopy(first)
            second["nodes"]["kind"] = list(reversed(first["nodes"]["kind"]))
            archive(directory, [first, second])
            rows = trace(directory, ["unit.sv:1"], "datapath_compiler")
            self.assertEqual([row["seq"] for row in rows], [0, 1])

    def test_symlink_cannot_escape_archive(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            directory = root / "archive"
            directory.mkdir()
            archive(directory, [graph()])
            (root / "outside.js").write_text((directory / "0.js").read_text())
            (directory / "0.js").unlink()
            (directory / "0.js").symlink_to(root / "outside.js")
            with self.assertRaisesRegex(ValueError, "escapes archive"):
                fanin(directory, ConeQuery("sum", "fold"))


if __name__ == "__main__":
    unittest.main()
