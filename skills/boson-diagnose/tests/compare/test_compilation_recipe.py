import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/compare/run_ab.py"
SPEC = importlib.util.spec_from_file_location("compilation_recipe", SCRIPT)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


class CompilationRecipe(unittest.TestCase):
    def test_actual_effort_and_retiming_are_distinct_from_requested_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = root / "normal.log"
            normal.write_text("requested: compile -retime -effort medium\n"
                              "Information: Optimizing logic, effort fast. (SYN-103)\n"
                              "2026-11-13T23:00:00Z netlist retime: period 500 -> 400 ps\n"
                              "compile: synthesized x.v at effort Fast [one-shot map] (map result: 20 cells)\n")
            ablated = root / "ablated.log"
            ablated.write_text("requested: compile -retime -effort medium\n"
                               "Information: Optimizing logic, effort medium. (SYN-103)\n"
                               "compile: synthesized x.v at effort Medium [one-shot map] (map result: 25 cells)\n")
            left, right = COMPARE.read_log(normal), COMPARE.read_log(ablated)
            self.assertEqual(left["compile_recipes"], [{"effort": "fast", "mode": "one-shot map"}])
            self.assertEqual(right["compile_recipes"], [{"effort": "medium", "mode": "one-shot map"}])
            self.assertEqual((left["synthesis_phases"], right["synthesis_phases"]), (1, 1))
            self.assertEqual((left["mapped_retime_messages"], right["mapped_retime_messages"]), (1, 0))
            report = COMPARE.to_md({"normal": left, "ablated": right})
            self.assertIn("fast [one-shot map]", report)
            self.assertIn("not observed", report)


if __name__ == "__main__":
    unittest.main()
