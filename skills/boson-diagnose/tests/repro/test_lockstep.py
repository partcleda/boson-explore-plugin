import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/repro/check_lockstep.py"
SPEC = importlib.util.spec_from_file_location("check_lockstep", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class LockstepCompletion(unittest.TestCase):
    def test_complete_run_accepts_simulator_finish_noise(self):
        text = "SIMEQ checked 2999 cycles, 0 mismatches\nbench.v:48: $finish called\n"
        self.assertEqual(CHECKER.check_summary(text, 2999)["checked_cycles"], 2999)

    def test_no_summary_zero_work_partial_and_multiple_runs_fail(self):
        for text in [
            "",
            "SIMEQ checked 0 cycles, 0 mismatches\n",
            "SIMEQ checked 12 cycles, 0 mismatches\n",
            "SIMEQ checked 2999 cycles, 0 mismatches\n" * 2,
            "SIMEQ checked 2999 cycles, 0 mismatches (partial)\n",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                CHECKER.check_summary(text, 2999)

    def test_mismatch_with_successful_simulator_exit_fails_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "simulation.log"
            simulator = subprocess.run(
                [sys.executable, "-c", "print('SIMEQ checked 2999 cycles, 1 mismatches')"],
                capture_output=True, text=True, check=True,
            )
            log.write_text(simulator.stdout, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--expected-cycles", "2999", str(log)],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["passed"])

    def test_invalid_encoding_reports_its_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "simulation.log"
            log.write_bytes(b"ab\xff")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--expected-cycles", "2999", str(log)],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["reason"], "invalid UTF-8 at byte 2")


if __name__ == "__main__":
    unittest.main()
