import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/compare/snapshot_stages.py"
SPEC = importlib.util.spec_from_file_location("snapshot_stages", SCRIPT)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


def write_snapshot(directory, target, probe=False):
    directory.mkdir()
    graph = {"stage": "select", "level": "datapath", "nodes": {"kind": [0, 1]}, "edges": {"target": [target]}}
    index = [{"seq": 4, "file": "stage.js", "main": True, "probe": probe, "level": "datapath", "stage": "select"}]
    (directory / "index.js").write_text("boson_index(" + json.dumps(index) + ");\n")
    (directory / "stage.js").write_text("boson_snapshot(4," + json.dumps(graph) + ");\n")


class SnapshotComparison(unittest.TestCase):
    def test_equal_counts_do_not_hide_changed_connectivity(self):
        with tempfile.TemporaryDirectory() as temporary:
            left, right = Path(temporary) / "left", Path(temporary) / "right"
            write_snapshot(left, 0)
            write_snapshot(right, 1)
            result = COMPARE.compare_stages(left, right, "datapath")
            self.assertFalse(result["equal"])
            self.assertEqual(result["matched_prefix"], 0)
            self.assertEqual(result["first_difference"]["position"], 0)
            write = (right / "stage.js")
            write.write_text((left / "stage.js").read_text())
            self.assertTrue(COMPARE.compare_stages(left, right, "datapath")["equal"])

    def test_probe_interleaving_and_missing_main_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            left, right = Path(temporary) / "left", Path(temporary) / "right"
            write_snapshot(left, 0)
            write_snapshot(right, 0)
            index = json.loads((right / "index.js").read_text()[12:-3])
            probe = dict(index[0], probe=True, file="missing-probe.js")
            (right / "index.js").write_text("boson_index(" + json.dumps([probe] + index) + ");\n")
            self.assertTrue(COMPARE.compare_stages(left, right, "all")["equal"])
            (left / "index.js").write_text("boson_index([]);\n")
            result = COMPARE.compare_stages(left, right, "datapath")
            self.assertFalse(result["equal"])
            self.assertIsNone(result["first_difference"]["baseline"])
            (right / "index.js").write_text("boson_index([]);\n")
            with self.assertRaisesRegex(ValueError, "no main-flow stages"):
                COMPARE.compare_stages(left, right, "datapath")

    def test_malformed_javascript_has_file_and_offset(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.js"
            path.write_text("boson_index([)\n")
            with self.assertRaisesRegex(ValueError, r"index.js: .*offset 13"):
                COMPARE.read_call(path, "boson_index")
            path.write_text("boson_index([]); extra")
            with self.assertRaisesRegex(ValueError, r"offset 14"):
                COMPARE.read_call(path, "boson_index")


if __name__ == "__main__":
    unittest.main()
