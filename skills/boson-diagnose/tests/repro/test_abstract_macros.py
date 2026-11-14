import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / "scripts" / "repro" / "abstract_macros.py"
spec = importlib.util.spec_from_file_location("abstract_macros", path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def fixture():
    return {"modules": {
        "top": {"ports": {"clk": {"direction": "input", "bits": [1]}}, "cells": {
            "ram": {"type": "memory", "connections": {"D": [2, 3], "Q": [4, 5], "CK": [1]}}
        }},
        "memory": {"attributes": {"blackbox": "0001"}, "ports": {
            "D": {"direction": "input"}, "Q": {"direction": "output"}, "CK": {"direction": "input"}
        }}
    }}


class MacroCutTests(unittest.TestCase):
    def test_cli_publishes_only_a_validated_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.json"
            candidate = root / "candidate.json"
            original.write_text(json.dumps(fixture()))
            for mismatch in (False, True):
                design = fixture()
                if mismatch:
                    design["modules"]["top"]["cells"]["ram"]["connections"]["D"] = [2]
                candidate.write_text(json.dumps(design))
                output = root / ("bad" if mismatch else "good")
                result = subprocess.run([sys.executable, str(path), str(original), str(candidate), str(output), "--top", "top"], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not mismatch)
                self.assertEqual(output.exists(), not mismatch)
                if not mismatch:
                    self.assertEqual(json.loads((output / "manifest.json").read_text())["instances"], 1)

    def test_memory_responses_become_inputs_and_requests_are_observed(self):
        design = fixture()
        signature = helper.cut_macros(design, "top")
        self.assertEqual(set(design["modules"]), {"top"})
        self.assertEqual(design["modules"]["top"]["cells"], {})
        ports = design["modules"]["top"]["ports"]
        for pin, direction, width, name in signature[0][2]:
            self.assertEqual(ports[name]["direction"], "input" if pin == "Q" else "output")
            self.assertEqual(len(ports[name]["bits"]), width)

    def test_signatures_ignore_internal_wire_numbers(self):
        original = fixture()
        candidate = copy.deepcopy(original)
        candidate["modules"]["top"]["cells"]["ram"]["connections"]["Q"] = [40, 50]
        self.assertEqual(helper.cut_macros(original, "top"), helper.cut_macros(candidate, "top"))

    def test_signatures_detect_missing_connections_and_changed_types(self):
        for mutation in ("width", "type"):
            original = fixture()
            candidate = copy.deepcopy(original)
            if mutation == "width":
                candidate["modules"]["top"]["cells"]["ram"]["connections"]["D"] = [2]
            else:
                candidate["modules"]["other"] = candidate["modules"].pop("memory")
                candidate["modules"]["top"]["cells"]["ram"]["type"] = "other"
            self.assertNotEqual(helper.cut_macros(original, "top"), helper.cut_macros(candidate, "top"))

    def test_unsupported_directions_and_constant_outputs_fail(self):
        for mutation in ("inout", "constant"):
            design = fixture()
            if mutation == "inout":
                design["modules"]["memory"]["ports"]["Q"]["direction"] = "inout"
            else:
                design["modules"]["top"]["cells"]["ram"]["connections"]["Q"] = ["0"]
            with self.assertRaises(ValueError):
                helper.cut_macros(design, "top")


if __name__ == "__main__":
    unittest.main()
