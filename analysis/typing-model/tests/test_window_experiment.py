import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from compare_models import METHODS, calibrate
from keystroke_model import load_sessions
from test_comparison import add_session
from window_experiment import evaluation_rows, experiment, experiment_markdown, plan_splits, write_run


@unittest.skipUnless(importlib.util.find_spec("sklearn"), "Optional comparison dependencies are not installed")
class WindowExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Tiny synthetic matrices do not benefit from many BLAS/OpenMP threads.
        from threadpoolctl import threadpool_limits
        cls.thread_limit = threadpool_limits(limits=1)

    @classmethod
    def tearDownClass(cls):
        cls.thread_limit.restore_original_limits()

    def test_real_four_model_sweep_keeps_splits_and_matches_recordings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            add_session(root, 1, 1, count=2400)
            add_session(root, 2, 2, count=800, hold=90)
            add_session(root, 3, 3, count=800, hold=100)
            add_session(root, 4, 4, count=800, label="tired", hold=200)
            add_session(root, 5, 4, count=150, label="tired", hold=200)
            result = experiment(root)
            self.assertEqual(len(result["matched_cohort"]), 2)
            self.assertEqual(result["coverage"]["100"]["scored_session_tasks"], 3)
            self.assertEqual(result["coverage"]["400"]["scored_session_tasks"], 2)
            self.assertEqual(result["excluded_from_matched_cohort"][0]["session"], "S5")
            self.assertEqual(result["excluded_from_matched_cohort"][0]["missing_at_sizes"],
                             {"200": "no_complete_window", "400": "no_complete_window"})
            for size in (100, 200, 400):
                report = result["reports"][str(size)]
                profile = report["profiles"]["P01:fixed"]
                self.assertEqual(profile["splits"], result["split_plan"]["P01:fixed"]["splits"])
                self.assertEqual(profile["training_windows"], 2400 // size)
                for method in METHODS:
                    metrics = result["matched_metrics"][str(size)][method]["overall"]
                    self.assertEqual(metrics["baseline_false_alerts"]["sessions"], 1)
                    self.assertEqual(metrics["comparison_conditions"]["tired"]["sessions"], 1)
                    self.assertEqual(metrics["comparison_conditions"]["tired"]["windows"], 800 // size)
                    self.assertEqual(set(evaluation_rows(report, method)), set(evaluation_rows(report)))
            # Thresholds are actually calibrated separately at each size.
            from compare_models import Detector
            for size in (100, 200, 400):
                sessions, _ = load_sessions(root, size)
                train = next(s for s in sessions if s["session"] == "S1")["windows"]
                calibration = next(s for s in sessions if s["session"] == "S2")["windows"]
                detector = Detector(train, "baseline")
                expected = calibrate(detector.scores(calibration), .05)
                self.assertEqual(result["reports"][str(size)]["profiles"]["P01:fixed"]["models"]["baseline"]["threshold"], expected)
            text = experiment_markdown(result)
            self.assertIn("Paired results", text)
            self.assertIn("Median span", text)
            json.dumps(result, allow_nan=False)
            target = root / "reports" / "first"
            write_run(result, target)
            original = (target / "window_experiment.json").read_bytes()
            with self.assertRaises(FileExistsError):
                write_run(result, target)
            write_run(result, root / "reports" / "second")
            self.assertEqual((target / "window_experiment.json").read_bytes(), original)
            self.assertTrue((target / "size_400.md").exists())

    def test_large_size_cannot_replace_a_short_calibration_day(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            add_session(root, 1, 1, count=2400)
            add_session(root, 2, 2, count=200)
            add_session(root, 3, 3, count=800)
            add_session(root, 4, 4, count=800, label="tired")
            result = experiment(root, sizes=(100, 400))
        small = result["reports"]["100"]["profiles"]["P01:fixed"]
        large = result["reports"]["400"]["profiles"]["P01:fixed"]
        self.assertEqual(small["status"], "compared")
        self.assertEqual(large["status"], "insufficient_data")
        self.assertEqual(large["calibration_windows"], 0)
        self.assertEqual(large["splits"], small["splits"])
        self.assertEqual(large["splits"]["baseline_test"][0]["session"], "S3")
        self.assertEqual(result["matched_cohort"], [])
        self.assertIsNone(result["matched_metrics"]["100"]["knn"]["overall"]["baseline_false_alerts"]["session_rate"])
        self.assertIn("No common cohort", experiment_markdown(result))

    def test_new_data_changes_only_new_run_plan_and_invalid_sizes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid in (1, 2, 3):
                add_session(root, sid, sid)
            sessions, _ = load_sessions(root, 100)
            old = plan_splits(sessions, "normal")
            frozen = json.dumps(old, sort_keys=True)
            add_session(root, 4, 4)
            sessions, _ = load_sessions(root, 100)
            new = plan_splits(sessions, "normal")
            self.assertEqual(old["P01:fixed"]["splits"]["baseline_test"][0]["session"], "S3")
            self.assertEqual(new["P01:fixed"]["splits"]["baseline_test"][0]["session"], "S4")
            self.assertEqual(json.dumps(old, sort_keys=True), frozen)
            for sizes in ((100,), (100, 100), (49, 200)):
                with self.assertRaises(ValueError):
                    experiment(root, sizes=sizes)


if __name__ == "__main__":
    unittest.main()
