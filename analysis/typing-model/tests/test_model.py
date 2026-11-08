import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from keystroke_model import extract, features, fit_profile, predict, read_csv, score, split_baseline, train


def recording(hold=80, gap=160, count=400, text_type="fixed"):
    fields = ["participant_id", "session_id", "sample_id", "event", "timestamp_ms", "press_id", "key", "text_type", "detail", "repeat_count"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for i in range(count):
        for event, timestamp in [("down", i * gap), ("up", i * gap + hold)]:
            writer.writerow(dict(participant_id="P01", session_id="S1", sample_id="1", event=event,
                                 timestamp_ms=timestamp, press_id=str(i + 1), key="a", text_type=text_type))
    return out.getvalue()


class ModelTests(unittest.TestCase):
    def test_knn_averages_only_k_nearest_distances(self):
        constant = lambda value: {n: value for n in fit_profile(extract(read_csv(recording()), 100)[0])["scale"]}
        profile = {"method": "knn", "k": 2, "scale": constant(1),
                   "training_examples": [constant(0), constant(2), constant(10)]}
        value, reasons = score(profile, constant(1))
        self.assertAlmostEqual(value, 1)
        self.assertEqual(reasons[0]["baseline"], 1)
        # JSON is the actual persisted artifact used by CLI and server.
        self.assertEqual(score(json.loads(json.dumps(profile)), constant(1))[0], value)

    def test_knn_handles_multiple_normal_clusters(self):
        windows, _ = extract(read_csv(recording()), 100)
        names = list(windows[0]["features"])
        modes = [{"features": {n: value for n in names}} for value in (0, 0, 100, 100)]
        baseline = fit_profile(modes)
        knn = fit_profile(modes, method="knn", k=2)
        self.assertEqual(score(knn, modes[0]["features"])[0], 0)
        self.assertGreater(score(baseline, modes[0]["features"])[0], 0)
        self.assertGreater(score(knn, {n: 500 for n in names})[0], 2)
        with self.assertRaises(ValueError):
            fit_profile(modes, method="knn", k=5)

    def test_window_explanations_match_selected_neighbors(self):
        from keystroke_model import FEATURES, summarize_predictions
        windows, _ = extract(read_csv(recording()), 100)
        profile = fit_profile(windows, method="knn", k=2)
        profile["threshold"] = 1
        shifted, _ = extract(read_csv(recording(hold=200, gap=350)), 100)
        result = summarize_predictions(profile, shifted)
        window = result["windows"][0]
        self.assertEqual(len(window["neighbors"]), 2)
        self.assertAlmostEqual(sum(n["distance"] for n in window["neighbors"]) / 2,
                               window["score"], places=4)
        self.assertEqual({f["feature"] for f in window["feature_comparison"]}, set(FEATURES))
        hold = next(f for f in window["feature_comparison"] if f["feature"] == "hold_median_ms")
        self.assertEqual((hold["observed"], hold["baseline"]), (200, 80))

    def test_knn_fit_never_uses_calibration_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid, day, hold in [(1, 1, 80), (2, 1, 80), (3, 2, 250), (4, 3, 300)]:
                (root / f"P01_S{sid}.csv").write_text(recording(hold=hold, gap=400).replace("S1", f"S{sid}"), encoding="utf-8")
                (root / f"P01_S{sid}_meta.json").write_text(json.dumps({"participant_id": "P01", "session_id": f"S{sid}", "start": f"2026-01-0{day}T12:00:00Z", "state_label": "normal"}), encoding="utf-8")
            model, report = train(root, size=100, method="knn", k=5)
            p = model["profiles"]["P01:fixed"]
            self.assertEqual(len(p["training_examples"]), 8)
            self.assertEqual({ex["hold_median_ms"] for ex in p["training_examples"]}, {80})
            self.assertEqual(p["center"]["hold_median_ms"], 80)
            self.assertEqual(p["calibration_days"], ["2026-01-02"])
            self.assertEqual(p["baseline_test_days"], ["2026-01-03"])
            self.assertNotIn("training_examples", report["profiles"]["P01:fixed"])

    def test_condition_data_does_not_change_baseline_and_orphans_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for session, day, label in [(1, 1, "normal"), (2, 1, "normal"),
                                        (3, 2, "normal"), (4, 3, "normal"), (5, 4, "impaired")]:
                (root / f"P01_S{session}.csv").write_text(recording().replace("S1", f"S{session}"), encoding="utf-8")
                (root / f"P01_S{session}_meta.json").write_text(json.dumps({
                    "participant_id": "P01", "session_id": f"S{session}",
                    "start": f"2026-01-0{day}T12:00:00Z", "state_label": label}), encoding="utf-8")
            (root / "P01_S6.csv").write_text(recording().replace("S1", "S6"), encoding="utf-8")
            before, report = train(root, size=100)
            self.assertTrue(any("missing matching metadata" in s["reason"] for s in report["skipped"]))
            self.assertEqual(before["profiles"]["P01:fixed"]["baseline_test_days"], ["2026-01-03"])
            (root / "P01_S5.csv").write_text(recording(hold=200, gap=350).replace("S1", "S5"), encoding="utf-8")
            after, _ = train(root, size=100)
            self.assertEqual(before, after)

    def test_shifted_typing_scores_higher(self):
        baseline, _ = extract(read_csv(recording()), 100)
        shifted, _ = extract(read_csv(recording(hold=200, gap=350)), 100)
        profile = fit_profile(baseline)
        self.assertEqual(score(profile, baseline[0]["features"])[0], 0)
        self.assertGreater(score(profile, shifted[0]["features"])[0], 3)

    def test_overlap_is_preserved(self):
        windows, _ = extract(read_csv(recording(hold=200, gap=100)), 100)
        self.assertEqual(windows[0]["features"]["ud_median_ms"], -100)
        self.assertEqual(windows[0]["features"]["overlap_fraction"], 1)

    def test_negative_clock_origin_preserves_features(self):
        original = read_csv(recording())
        shifted = read_csv(recording())
        for row in shifted:
            row["timestamp_ms"] -= 9999999
        a, _ = extract(original, 100)
        b, quality = extract(shifted, 100)
        self.assertEqual(a[0]["features"], b[0]["features"])
        self.assertEqual(quality["negative_timestamp_events"], 800)

    def test_forced_releases_and_paste_are_not_training_data(self):
        rows = read_csv(recording(count=200))
        rows[1]["detail"] = "forced_release"
        windows, quality = extract(rows, 200)
        self.assertEqual(quality["invalid_or_forced_releases"], 1)
        self.assertEqual(windows, [])
        rows[1]["detail"] = "paste"
        _, quality = extract(rows, 200)
        self.assertEqual(quality["usable_keypresses"], 0)

    def test_no_latency_across_messages(self):
        rows = read_csv(recording(count=200))
        for row in rows[200:]:
            row["sample_id"] = "2"
            row["timestamp_ms"] += 100000
        windows, _ = extract(rows, 200)
        self.assertEqual(windows[0]["features"]["pause_fraction"], 0)
        self.assertEqual(windows[0]["features"]["dd_median_ms"], 160)

    def test_unknown_text_and_short_recordings_abstain(self):
        windows, quality = extract(read_csv(recording(text_type="")), 100)
        self.assertFalse(windows)
        self.assertEqual(quality["unknown_text_type"], 400)
        windows, _ = extract(read_csv(recording(count=99)), 100)
        self.assertFalse(windows)

    def test_split_keeps_days_separate_and_in_time_order(self):
        sessions = [{"day": d} for d in ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03"]]
        training, calibration, test, status = split_baseline(sessions)
        self.assertEqual({s["day"] for s in training}, {"2026-01-01"})
        self.assertEqual({s["day"] for s in calibration}, {"2026-01-02"})
        self.assertEqual({s["day"] for s in test}, {"2026-01-03"})
        self.assertEqual(status, "independent_days")

    def test_prediction_flags_reference_file_and_unknown_person(self):
        rows = read_csv(recording())
        windows, _ = extract(rows, 100)
        p = fit_profile(windows)
        p.update(threshold=1, validation="same_day_provisional", reference_hashes=[], reference_ids=[["P01", "S1"]])
        model = {"version": 1, "window_size": 100, "profiles": {"P01:fixed": p}}
        result = predict(model, recording())
        self.assertTrue(result["results"]["fixed"]["reference_recording"])
        result = predict(model, recording().replace("P01", "P99"))
        self.assertEqual(result["results"]["fixed"]["status"], "no_matching_baseline")

    def test_reject_nonfinite_timestamps_and_mixed_identity(self):
        for text in [recording().replace(",0,1,", ",nan,1,", 1), recording().replace("P01", "P99", 1)]:
            with self.assertRaises(ValueError):
                read_csv(text)


if __name__ == "__main__":
    unittest.main()
