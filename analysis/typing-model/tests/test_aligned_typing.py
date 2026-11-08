import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aligned_typing import align_text, extract_aligned, replay
from keystroke_model import features, read_csv
from p04_experiment import FeatureKNN, TIMING, concise_markdown, identity_split, run


REFERENCE = Path(__file__).resolve().parents[1].joinpath("fixed_passage.txt").read_text(encoding="utf-8").strip()


def recording(operations, pid="P04", sid="S1", gap=160, hold=80, sample="1", text_type="fixed"):
    fields = ["participant_id", "session_id", "sample_id", "event", "timestamp_ms", "press_id", "key", "text_type",
              "detail", "repeat_count", "caret_pos", "ctrl", "alt", "meta", "input_type"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    length = 0
    for i, key in enumerate(operations):
        for event, timestamp in (("down", i * gap), ("up", i * gap + hold)):
            writer.writerow(dict(participant_id=pid, session_id=sid, sample_id=sample, event=event,
                                 timestamp_ms=timestamp, press_id=str(i+1), key=key, text_type=text_type,
                                 caret_pos=length, ctrl=0, alt=0, meta=0))
        if key == "Backspace":
            length = max(0, length-1)
        elif len(key) == 1:
            length += 1
    return out.getvalue()


def add(root, sid, pid="P04", label="normal", day=1, gap=160, hold=80, text_type="fixed"):
    (root / f"{pid}_S{sid}.csv").write_text(recording(REFERENCE, pid, f"S{sid}", gap, hold, text_type=text_type), encoding="utf-8")
    (root / f"{pid}_S{sid}_meta.json").write_text(json.dumps({"participant_id": pid, "session_id": f"S{sid}",
                                                          "state_label": label, "start": f"2026-01-{day:02d}T12:{sid:02d}:00Z"}), encoding="utf-8")


class AlignedTypingTests(unittest.TestCase):
    def test_exact_and_partial_reference_alignment(self):
        exact = align_text(REFERENCE, REFERENCE)
        self.assertEqual(exact["mapping"], list(range(len(REFERENCE))))
        self.assertEqual(exact["error_rate"], 0)
        part = align_text(REFERENCE[300:], REFERENCE)
        self.assertEqual((part["start"], part["end"]), (300, 800))
        self.assertEqual(part["error_rate"], 0)
        windows, _ = extract_aligned(read_csv(recording(REFERENCE)), REFERENCE)
        self.assertEqual([w["section"] for w in windows], [1, 2, 3, 4])

    def test_corrected_error_retained_without_synthetic_timing_pair(self):
        ref = "cat " + REFERENCE[:196]
        operations = ["c", "a", "x", "Backspace", "t"] + list(ref[3:])
        rows = read_csv(recording(operations))
        buffer, _, _, _ = replay(rows)
        self.assertEqual("".join(char for char, _ in buffer), ref)
        captured = []
        def capture(presses):
            captured.extend(presses)
            return features(presses)
        with patch("aligned_typing.features", capture):
            windows, _ = extract_aligned(rows, ref)
        f = windows[0]["features"]
        self.assertEqual(windows[0]["physical_keypresses"], 202)
        self.assertAlmostEqual(f["backspace_fraction"], 1/202)
        self.assertAlmostEqual(f["extra_press_fraction"], 2/200)
        self.assertEqual(f["reference_error_fraction"], 0)
        self.assertNotEqual(captured[1]["block"], captured[2]["block"])

    def test_uncorrected_error_is_measured_and_not_shifted_into_next_section(self):
        typed = list(REFERENCE)
        typed[100] = "#"
        windows, _ = extract_aligned(read_csv(recording(typed)), REFERENCE)
        self.assertEqual([w["section"] for w in windows], [1, 2, 3, 4])
        self.assertEqual(windows[0]["features"]["reference_error_fraction"], 1/200)
        self.assertEqual(windows[1]["features"]["reference_error_fraction"], 0)

    def test_ambiguous_edit_and_invalid_events_are_rejected(self):
        for change, reason in ((lambda r: r[10].update(caret_pos="999"), "caret_mismatch"),
                               (lambda r: r[10].update(key="ArrowLeft"), "complex_edit_or_composition"),
                               (lambda r: r[10].update(detail="paste"), "paste"),
                               (lambda r: r[11].update(detail="forced_release"), "invalid_or_repeated_press")):
            rows = read_csv(recording(REFERENCE))
            change(rows)
            windows, audit = extract_aligned(rows, REFERENCE)
            self.assertEqual(windows, [])
            self.assertEqual(audit[0]["status"], reason)

    def test_message_boundary_does_not_create_a_complete_reference_section(self):
        first = read_csv(recording(REFERENCE[:300], sample="1"))
        second = read_csv(recording(REFERENCE[300:], sample="2"))
        for row in second:
            row["press_id"] = "second-" + row["press_id"]
            row["timestamp_ms"] += 100000
        windows, _ = extract_aligned(first + second, REFERENCE)
        self.assertEqual([w["section"] for w in windows], [1, 3, 4])

    def test_missing_caret_is_explicitly_unverified(self):
        rows = read_csv(recording(REFERENCE))
        for row in rows:
            row["caret_pos"] = ""
        windows, audit = extract_aligned(rows, REFERENCE)
        self.assertEqual(len(windows), 4)
        self.assertEqual(audit[0]["unverified_caret_events"], 800)

    def test_feature_selection_and_knn_distance(self):
        windows = [{"features": {"hold_median_ms": value, "backspace_fraction": 0}} for value in (0, 10)]
        model = FeatureKNN(windows, ("hold_median_ms",), k=2)
        query = {"features": {"hold_median_ms": 5, "backspace_fraction": 1}}
        scale = model.scale["hold_median_ms"]
        self.assertAlmostEqual(model.score(query), 5/scale)
        before = dict(model.scale)
        model.score({"features": {"hold_median_ms": 500}})
        self.assertEqual(model.scale, before)
        self.assertEqual(len(TIMING), 8)

    def test_full_pipeline_splits_ablation_and_no_comparison_leakage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for sid in range(1, 13):
                add(root, sid)
            add(root, 13, label="impaired", day=2, gap=350)
            add(root, 1, pid="P02", day=2, gap=250)
            before = run(root, REFERENCE)
            self.assertEqual([len(before["splits"][role]) for role in ("training", "calibration", "normal_test")], [7, 2, 3])
            role_hashes = [{r["hash"] for r in before["splits"][role]} for role in ("training", "calibration", "normal_test")]
            self.assertTrue(all(not role_hashes[i] & role_hashes[j] for i in range(3) for j in range(i+1, 3)))
            self.assertEqual(len(before["paired_recording_hashes"]), 5)
            self.assertEqual(before["independent_normal_test_days"], [])
            for result in before["results"].values():
                self.assertEqual(result["paired"]["target_normal"]["sessions"], 3)
                self.assertEqual(result["paired"]["other_normal"]["sessions"], 1)
                self.assertEqual(result["paired"]["target_condition"]["sessions"], 1)
            self.assertEqual(len(before["results"]["aligned_errors"]["models"]), 4)
            add(root, 13, label="impaired", day=2, gap=600)
            add(root, 1, pid="P02", day=2, gap=800)
            after = run(root, REFERENCE)
            for variant in before["results"]:
                self.assertEqual(before["results"][variant]["models"], after["results"][variant]["models"])
            text = json.dumps(before, allow_nan=False)
            self.assertNotIn("Can we tell", text)
            self.assertIn("provisional", concise_markdown(before))


if __name__ == "__main__":
    unittest.main()
