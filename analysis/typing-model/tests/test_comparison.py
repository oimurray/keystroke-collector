import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from compare_models import METHODS, Detector, aggregate, compare, markdown
from test_model import recording


def add_session(root, sid, day, label="normal", hold=80, count=600, text_type="fixed"):
    (root / f"P01_S{sid}.csv").write_text(
        recording(hold=hold, gap=350, count=count, text_type=text_type).replace("S1", f"S{sid}"), encoding="utf-8")
    (root / f"P01_S{sid}_meta.json").write_text(json.dumps({
        "participant_id": "P01", "session_id": f"S{sid}", "start": f"2026-01-{day:02d}T12:00:00Z",
        "state_label": label}), encoding="utf-8")


@unittest.skipUnless(importlib.util.find_spec("sklearn"), "Optional comparison dependencies are not installed")
class ComparisonTests(unittest.TestCase):
    def test_shared_day_splits_and_metrics_for_all_five_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid in (1, 2, 3):
                add_session(root, sid, sid, hold=75 + sid * 5)
            add_session(root, 4, 4, label="tired", hold=210)
            report = compare(root, size=100)
        profile = report["profiles"]["P01:fixed"]
        self.assertEqual(profile["validation"], "independent_days")
        self.assertEqual(profile["splits"]["training"][0]["session"], "S1")
        self.assertEqual(profile["splits"]["calibration"][0]["session"], "S2")
        self.assertEqual(profile["splits"]["baseline_test"][0]["session"], "S3")
        self.assertEqual(set(profile["models"]), set(METHODS))
        for model in profile["models"].values():
            self.assertEqual([r["session"] for r in model["evaluation"]], ["S3", "S4"])
            metrics = model["metrics"]["baseline_false_alerts"]
            self.assertEqual((metrics["sessions"], metrics["windows"], metrics["participant_days"]), (1, 6, 1))
            self.assertEqual(model["parameters"].get("n_neighbors", 5), 5)
        self.assertIn("Independent of reference days", markdown(report))
        json.dumps(report, allow_nan=False)

    def test_condition_and_test_data_cannot_change_fitting_or_thresholds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid in (1, 2, 3):
                add_session(root, sid, sid)
            add_session(root, 4, 4, label="tired", hold=200)
            before = compare(root, size=100)
            add_session(root, 3, 3, hold=300)
            add_session(root, 4, 4, label="tired", hold=320)
            after = compare(root, size=100)
        a, b = before["profiles"]["P01:fixed"], after["profiles"]["P01:fixed"]
        for method in METHODS:
            self.assertEqual(a["models"][method]["threshold"], b["models"][method]["threshold"])
            self.assertEqual(a["models"][method]["parameters"], b["models"][method]["parameters"])

    def test_missing_normal_test_is_unavailable_and_same_day_conditions_are_separated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            add_session(root, 1, 1)
            add_session(root, 2, 2)
            add_session(root, 3, 1, label="tired", hold=200)
            report = compare(root, size=100)
        for metrics in report["summary"].values():
            self.assertIsNone(metrics["baseline_false_alerts"]["session_rate"])
            self.assertEqual(metrics["comparison_conditions"]["tired"]["sessions"], 1)
            self.assertEqual(metrics["independent_comparison_conditions"]["tired"]["sessions"], 0)
        self.assertIn("Unavailable", markdown(report))

    def test_insufficient_profile_skipped_for_every_model_and_short_files_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            add_session(root, 1, 1, count=400)
            add_session(root, 2, 2)
            add_session(root, 3, 3, label="tired")
            add_session(root, 4, 4, label="tired", count=50)
            report = compare(root, size=100)
        self.assertEqual(report["profiles"]["P01:fixed"]["status"], "insufficient_data")
        self.assertEqual(report["profiles"]["P01:fixed"]["models"], {})
        self.assertEqual({r["reason"] for r in report["unscored_recordings"]}, {"no_trainable_profile", "no_complete_windows"})

    def test_deterministic_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid in (1, 2, 3):
                add_session(root, sid, sid)
            self.assertEqual(compare(root, size=100), compare(root, size=100))

    def test_virtual_environment_fixtures_are_excluded_from_source_inventory(self):
        from keystroke_model import load_sessions
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            add_session(root, 1, 1)
            fixtures = root / ".venv-comparison" / "fixtures"
            fixtures.mkdir(parents=True)
            add_session(fixtures, 2, 2)
            (fixtures / "library.csv").write_text("not a collector export", encoding="utf-8")
            sessions, skipped = load_sessions(root, 100)
            self.assertEqual([s["session"] for s in sessions], ["S1"])
            self.assertEqual(skipped, [])

    def test_estimators_and_scaling_receive_only_training_windows(self):
        from keystroke_model import extract, read_csv
        windows, _ = extract(read_csv(recording(hold=80, count=600)), 100)
        held_out, _ = extract(read_csv(recording(hold=200)), 100)
        for method in ("lof", "isolation_forest"):
            model = Detector(windows, method)
            self.assertEqual(model.profile["center"]["hold_median_ms"], 80)
            before = dict(model.profile["scale"])
            model.scores(held_out)
            self.assertEqual(model.profile["scale"], before)
            if method == "lof":
                self.assertEqual(model.estimator.n_samples_fit_, len(windows))
                self.assertEqual(model.estimator._fit_X.shape, (len(windows), 11))
                self.assertTrue(model.estimator.novelty)
            else:
                self.assertEqual(model.estimator.max_samples_, len(windows))

    def test_rate_denominators_and_condition_separation(self):
        base = dict(participant="P01", day="2026-01-01", window_count=4, flagged_windows=1,
                    unusual=False, independent_of_reference_days=True)
        rows = [{**base, "role": "baseline_test", "label": "normal"},
                {**base, "role": "comparison", "label": "tired", "unusual": True},
                {**base, "role": "comparison", "label": "other"}]
        summary = aggregate(rows)
        self.assertEqual(summary["baseline_false_alerts"]["window_rate"], .25)
        self.assertEqual(summary["baseline_false_alerts"]["session_rate"], 0)
        self.assertEqual(summary["comparison_conditions"]["tired"]["session_rate"], 1)
        self.assertEqual(summary["comparison_conditions"]["other"]["session_rate"], 0)


if __name__ == "__main__":
    unittest.main()
