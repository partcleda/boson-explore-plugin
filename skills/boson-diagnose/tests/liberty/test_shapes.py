"""shape_census and shape_probe on the hand-written fixture, with a fake boson."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "scripts" / "liberty"
FIXTURE = HERE / "fixtures" / "shapes_fixture.lib"
sys.path.insert(0, str(SCRIPTS))
import shape_census  # noqa: E402
import shape_probe  # noqa: E402


def delay(t, c):  # the fixture's delay surface
    return 0.01 + 0.5 * t + 20 * c


class Census(unittest.TestCase):
    def setUp(self):
        self.r = shape_census.census([FIXTURE])

    def test_every_shape_is_a_class(self):
        cls = self.r["classes"]
        self.assertEqual(len(cls), 28)
        dims = {tuple(c["dims"]) for c in cls}
        self.assertTrue({(5, 5, 5), (4, 4), (2, 2), (4,), ()} <= dims)
        cube = [c for c in cls if c["dims"] == [5, 5, 5]]
        self.assertEqual({c["timing_type"] for c in cube}, {"nochange_high_high"})
        self.assertEqual(cube[0]["overrides"], [1, 2, 3])
        swapped = [c for c in cls if c["variables"][:1] == ["total_output_net_capacitance"] and len(c["dims"]) == 2]
        self.assertEqual(len(swapped), 4)
        self.assertEqual(self.r["problems"], [])

    def test_value_count_off_the_grid_is_a_problem(self):
        text = FIXTURE.read_text().replace('"0.03, 0.04", "0.05, 0.06"', '"0.03, 0.04"', 1)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.lib"
            p.write_text(text)
            probs = shape_census.census([p])["problems"]
        self.assertEqual(len(probs), 1)
        self.assertEqual((probs[0]["values"], probs[0]["expected"]), (2, 4))

    def test_probe_point_follows_the_template_axis_order(self):
        for c in self.r["classes"]:
            if c["table"] != "cell_rise" or c["timing_type"] != "combinational" or len(c["dims"]) != 2:
                continue
            probes, why = shape_probe.probe_plan(c, 1.0)
            self.assertEqual(why, "")
            for p in probes:
                self.assertAlmostEqual(p["expected_ns"], delay(p["slew"], p["load"]), places=9,
                                       msg=f"{c['example']['cell']} {p['point']}")


class Probe(unittest.TestCase):
    def run_probe(self, mode, value="0.05"):
        d = Path(tempfile.mkdtemp())
        shapes = d / "shapes.json"
        shapes.write_text(json.dumps(shape_census.census([FIXTURE])))
        env = dict(os.environ, FAKE_MODE=mode, FAKE_VALUE=value)
        subprocess.run([sys.executable, str(SCRIPTS / "shape_probe.py"), str(shapes), "--boson",
                        str(HERE / "fake_boson.py"), "--out", str(d / "out"), "--jobs", "4"],
                       env=env, capture_output=True, text=True, timeout=300)
        rows = json.loads((d / "out" / "results.json").read_text())
        return {r["class"]: r for r in rows}, d / "out"

    def test_old_reader_rejecting_3d_constraints_is_a_load_error(self):
        rows, _ = self.run_probe("old")
        bad = {r["timing_type"] for r in rows.values() if r["verdict"] == "LOAD ERROR"}
        self.assertEqual(bad, {"nochange_high_high"})
        msg = next(r for r in rows.values() if r["verdict"] == "LOAD ERROR")["messages"][0]
        self.assertEqual(msg["id"], "LIB-130")

    def test_wrong_value_is_a_mismatch_and_right_value_passes(self):
        rows, _ = self.run_probe("value", "0.05")
        scalar = [r for r in rows.values() if r["dims"] == [] and r["table"] == "cell_rise"][0]
        self.assertEqual(scalar["verdict"], "OK (timed exactly)")
        grid = [r for r in rows.values() if r["dims"] == [4, 4] and r["table"] == "cell_rise"
                and r["timing_type"] == "combinational"][0]
        self.assertEqual(grid["verdict"], "MISMATCH")

    def test_no_value_is_probe_failed_not_mismatch(self):
        rows, _ = self.run_probe("empty")
        probed = [r for r in rows.values() if r["probes"]]
        self.assertTrue(probed)
        self.assertEqual({r["verdict"] for r in probed}, {"PROBE FAILED"})

    def test_shareable_summary_has_no_names_or_values(self):
        _, out = self.run_probe("old")
        text = (out / "shapes_summary.json").read_text()
        for name in ("shapes_fixture", "INV_TL", "DFF_NOCHANGE", "cnst_rtin_ctin_rload_5x5x5", "tr_load_4x4", "0.03"):
            self.assertNotIn(name, text)
        self.assertIn("nochange_high_high", text)
        self.assertIn("LIB-130", text)


if __name__ == "__main__":
    unittest.main()


class Aggregation(unittest.TestCase):
    """judge_units names the rule boson used when several groups share a pin pair."""

    def judge(self, by_group, got):
        unit = {"key": ("f.lib", "XOR", "A", "Y", "combinational"), "groups": len(by_group), "probes": [1],
                "skipped": "", "line": 1, "senses": ["negative_unate", "positive_unate"], "whens": ["", ""]}
        probes = [{"unit": 0, "table": "cell_rise", "point": {"p": i}, "by_group": dict(enumerate(bg)), "got_ns": g}
                  for i, (bg, g) in enumerate(zip(by_group, got))]
        done = {("arcs", "f.lib", "XOR"): {"key": ("arcs", "f.lib", "XOR"), "probes": probes}}
        unit["probes"] = probes
        return shape_probe.judge_units([unit], done)[0]["verdict"]

    def test_rules(self):
        self.assertEqual(self.judge([[0.1, 0.2], [0.3, 0.4]], [0.2, 0.4]), "combined: max of groups (2)")
        self.assertTrue(self.judge([[0.1, 0.2], [0.3, 0.4]], [0.1, 0.3]).startswith("combined: min of groups"))
        self.assertEqual(self.judge([[0.1, 0.2], [0.3, 0.4]], [0.2, 0.35]), "MISMATCH")
        self.assertEqual(self.judge([[0.1], [0.3]], [0.1, 0.3]), "exact")
        self.assertEqual(self.judge([[0.1], [0.3]], [0.1, None]), "PROBE FAILED")
