"""lib_inventory against boson's real model of the fixture (recorded once from boson
1.896.2 with dump_model.tcl into fixtures/model/), and against copies of that model
mutated the way a lossy reader would change it."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "liberty"))
import lib_inventory as inv  # noqa: E402

FIX = HERE / "fixtures"
LIB = FIX / "shapes_fixture.lib"


class Inventory(unittest.TestCase):
    def model(self, edit=None, file=None):
        d = Path(tempfile.mkdtemp()) / "model"
        shutil.copytree(FIX / "model", d)
        if edit:
            p = d / (file or "model.txt")
            p.write_text(edit(p.read_text()))
        return d

    def findings(self, model_dir, lib=LIB):
        return inv.compare(model_dir, [lib])["findings"]

    def test_recorded_model_matches_the_file(self):
        r = inv.compare(FIX / "model", [LIB])
        self.assertEqual(r["findings"], {})
        self.assertEqual(r["constraint_tables_compared"], 4)   # 2-D setup and the 3-D nochange cube

    def test_dropped_arc(self):
        m = self.model(lambda t: re.sub(r"(cell INV_TL[^\n]*\n(?:  [^\n]*\n)*?)    A -> Y[^\n]*\n", r"\1", t, count=1))
        self.assertIn("timing groups dropped", self.findings(m))

    def test_merged_groups(self):
        text = LIB.read_text()
        cell = text[text.index("cell (INV_TL)"):text.index("cell (INV_LT)")]
        group = cell[cell.index("      timing ()"):cell.index("    }\n  }\n")]
        extra = group.replace('related_pin : "A";', 'related_pin : "A"; when : "A";')
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d) / "merged.lib"
            lib.write_text(text.replace(cell, cell.replace(group, group + extra), 1))
            f = self.findings(FIX / "model", lib)
        self.assertIn("timing groups merged", f)
        self.assertIn("when condition lost", f)

    def test_constraint_table_stored_smaller(self):
        m = self.model(lambda t: t.replace("shape=2x2", "shape=2x1", 1).replace("values_ns=[0.03, 0.04, 0.05, 0.06]",
                                                                               "values_ns=[0.03, 0.04]", 1))
        self.assertIn("constraint table smaller in boson", self.findings(m))

    def test_changed_value_and_3d_cube_are_compared(self):
        m = self.model(lambda t: t.replace("0.06]", "0.061]", 1))
        self.assertIn("constraint table values differ", self.findings(m))
        m = self.model(lambda t: t.replace("0.553,", "0.5531,", 1))
        f = self.findings(m)
        self.assertIn("constraint table values differ", f)
        self.assertTrue(any("NoChange" in x["detail"] or "Nochange" in x["detail"] for x in f["constraint table values differ"]))

    def test_missing_pin_and_field(self):
        m = self.model(lambda t: re.sub(r"(cell INV_1D[^\n]*\n)  pin A [^\n]*\n", r"\1", t, count=1))
        self.assertIn("pin missing in boson", self.findings(m))
        m = self.model(lambda t: t.replace("INV_TL\t1\t", "INV_TL\t1.5\t", 1), "cells.tsv")
        self.assertIn("field differs", self.findings(m))

    def test_query_collapse(self):
        m = self.model(lambda t: "\n".join(l for l in t.splitlines() if not l.startswith("INV_LT/A->Y")) + "\n", "arcs.tsv")
        self.assertIn("query collapses arcs", self.findings(m))


if __name__ == "__main__":
    unittest.main()
