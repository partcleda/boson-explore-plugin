import gzip
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts/repro/timing_profile.py"
spec = importlib.util.spec_from_file_location("timing_profile", SCRIPT)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class TimingProfileTest(unittest.TestCase):
    def test_nested_phases_stay_separate_and_reporting_cost_is_visible(self):
        lines = [
            "partcl_timing_profile +0.2s update_timing_total\t30.0 ms\n",
            "partcl_timing_profile +0.3s profile_report_write\\t20.0 ms\n",
            "partcl_timing_profile +0.4s update_timing_total\\t40.0 ms\n",
            "partcl_timing_profile +0.5s profile_report_write\\t25.0 ms\n",
            "partcl_timing_profile +0.6s tcl_script_command[compile]\\t90.0 ms\n",
            "[synth_profile] compile=0.09s\n",
        ]
        result = profile.summarize(iter(lines), "run.log")
        stages = {stage["label"]: stage for stage in result["stages"]}
        self.assertEqual(stages["profile_report_write"]["calls"], 2)
        self.assertEqual(stages["profile_report_write"]["total_ms"], 45)
        self.assertEqual(stages["update_timing_total"]["total_ms"], 70)
        self.assertEqual(result["reported_compile_ms"], 90)
        self.assertEqual(result["compile_completions"], 1)

    def test_partial_log_has_no_invented_compile_wall_or_success(self):
        result = profile.summarize([
            "2026-11-13T20:00:01.000Z partcl_timing_profile +1.0s repair\\t12.5 ms\n",
            "partcl_timing_profile +1.1s counter_add runs+=1 total=2\n",
            "partcl_timing_profile +1.1s prima_max_transient_steps\\t0\n",
            "partcl_timing_profile +1.2s report_paths_select\\tcandidates=1 scanned=1 group_ms=0.0\n",
        ], "partial.log")
        self.assertEqual(result["compile_completions"], 0)
        self.assertIsNone(result["reported_compile_ms"])
        self.assertEqual(result["stages"][0]["total_ms"], 12.5)
        self.assertEqual(len(result["stages"]), 1)

    def test_invalid_durations_name_the_input_line(self):
        for duration in ["NaN", "inf", "-1", "broken"]:
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, "bad.log:2:"):
                profile.summarize(["header\n", f"partcl_timing_profile +1s repair\\t{duration} ms\n"], "bad.log")

    def test_schedule_attributes_do_not_split_one_phase_into_many_labels(self):
        result = profile.summarize([
            "partcl_timing_profile +1s run_raw_schedule levels=18 arcs=9748\\t6.170 ms gpu_free_mb=NA\n",
            "partcl_timing_profile +2s run_raw_schedule levels=20 arcs=9500\\t4.000 ms gpu_free_mb=100\n",
        ], "schedule.log")
        self.assertEqual(len(result["stages"]), 1)
        stage = result["stages"][0]
        self.assertEqual(stage["label"], "run_raw_schedule")
        self.assertEqual(stage["calls"], 2)
        self.assertAlmostEqual(stage["total_ms"], 10.17)

    def test_no_phases_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no timing phase records"):
            profile.summarize(["ordinary log\n"], "empty.log")

    def test_gzip_cli_reads_real_records_without_counting_the_rendered_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "run.log.gz"
            with gzip.open(path, "wt") as output:
                output.write("partcl_timing_profile +1s report\\t1 ms\n| report | 100 | 999 |\n")
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            row = json.loads(result.stdout)["stages"][0]
            self.assertEqual((row["calls"], row["total_ms"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
