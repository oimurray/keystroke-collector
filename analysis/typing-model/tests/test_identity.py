import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from identity_model import build, predict_identity, public_description, replay_identity, score_windows, summary_markdown
from keystroke_model import extract, read_csv
from test_model import recording


def add(root, pid, sid, gap=160, hold=80, label="normal", day=1, count=800):
    text = recording(gap=gap, hold=hold, count=count).replace("P01", pid).replace("S1", f"S{sid}")
    (root / f"{pid}_S{sid}.csv").write_text(text, encoding="utf-8")
    (root / f"{pid}_S{sid}_meta.json").write_text(json.dumps({"participant_id": pid, "session_id": f"S{sid}",
        "state_label": label, "start": f"2026-01-{day:02d}T12:{sid:02d}:00Z"}), encoding="utf-8")


def fixture(root):
    for sid in range(1, 11):
        add(root, "P01", sid)
        add(root, "P02", sid, gap=350, hold=200)
    add(root, "P01", 11, gap=350, hold=200, label="impaired", day=2)
    add(root, "P03", 1, count=400)


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        fixture(cls.root)
        cls.model, cls.report = build(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_each_member_has_own_disjoint_split_and_calibration(self):
        self.assertEqual(set(self.model["profiles"]), {"P01", "P02"})
        self.assertIn("P03", self.model["unavailable_profiles"])
        for pid, profile in self.model["profiles"].items():
            member = self.report["members"][pid]
            roles = [{s["hash"] for s in member["splits"][r]} for r in ("training", "calibration", "normal_test")]
            self.assertTrue(all(not roles[a] & roles[b] for a in range(3) for b in range(a+1,3)))
            self.assertEqual(profile["training_windows"], 24)
            self.assertEqual(len(profile["features"]), 8)
            self.assertEqual(member["metrics"]["normal_author"]["flagged_sessions"], 0)
            self.assertEqual(len(member["splits"]["normal_test"]), 2)
            self.assertEqual(profile["independent_normal_test_days"], [])
        self.assertIn("provisional", summary_markdown(self.report))

    def test_expected_author_overrides_csv_identity_metadata(self):
        text = recording(gap=350, hold=200, count=800).replace("P01", "P02")
        self.assertEqual(predict_identity(self.model, text, "P01")["status"], "change_detected")
        self.assertEqual(predict_identity(self.model, text, "P02")["status"], "consistent_with_expected_author")
        renamed = text.replace("P02", "P01").replace("S1", "S999")
        a, b = predict_identity(self.model,text,"P01"), predict_identity(self.model,renamed,"P01")
        self.assertEqual(a["median_score"], b["median_score"])
        self.assertEqual(a["status"], b["status"])
        self.assertEqual(a["windows"], b["windows"])
        self.assertTrue(all(w["likely_participant"] == "P02" for w in a["windows"]))

    def test_author_guess_requires_one_other_matching_profile(self):
        recording_text = recording(gap=350, hold=200, count=200)
        profiles = self.model["profiles"]
        for alternatives in ({}, {"P02": profiles["P02"], "P03": profiles["P02"]}):
            model = {**self.model, "profiles": {"P01": profiles["P01"], **alternatives}}
            window, = predict_identity(model, recording_text, "P01")["windows"]
            self.assertTrue(window["unusual"])
            self.assertIsNone(window["likely_participant"])
        window, = predict_identity(self.model, recording(count=200), "P01")["windows"]
        self.assertFalse(window["unusual"])
        self.assertNotIn("likely_participant", window)

    def test_latest_window_can_alert_before_session_median(self):
        normal, _ = extract(read_csv(recording(count=600)), 200)
        other, _ = extract(read_csv(recording(gap=350,hold=200,count=200)), 200)
        result = score_windows(self.model["profiles"]["P01"], normal + other)
        self.assertEqual(result["status"], "consistent_with_expected_author")
        self.assertEqual(result["latest_status"], "change_detected")
        self.assertEqual(result["flagged_windows"], 1)

    def test_fixed_only_and_short_inputs_abstain(self):
        for text in (recording(count=199), recording(count=800,text_type="free")):
            result = predict_identity(self.model,text,"P01")
            self.assertEqual(result["status"], "insufficient_data")
            self.assertEqual(result["window_count"], 0)
        free = predict_identity(self.model,recording(count=800,text_type="free"),"P01")
        self.assertEqual(free["ignored_nonfixed_keypresses"], 800)

    def test_marked_handover_does_not_join_incomplete_segments(self):
        first = read_csv(recording(count=150))
        second = read_csv(recording(count=150,gap=350,hold=200))
        for row in second:
            row["sample_id"] = "2"
            row["press_id"] = "second-" + row["press_id"]
            row["timestamp_ms"] += 100000
        marker = dict.fromkeys(first[0], "")
        marker.update(participant_id="P01",session_id="S1",event="marker",timestamp_ms=99999,text_type="fixed",detail="blur")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output,fieldnames=list(first[0]))
        writer.writeheader()
        writer.writerows(first + [marker] + second)
        result = predict_identity(self.model,output.getvalue(),"P01")
        self.assertEqual(result["quality"]["usable_keypresses"],300)
        self.assertEqual(result["quality"]["next_window_keypresses"], 150)
        self.assertEqual(result["window_count"],0)
        self.assertEqual(result["status"],"insufficient_data")

    def test_live_progress_waits_for_release_and_excludes_modifiers(self):
        text = recording(count=199)
        row = next(r for r in csv.DictReader(io.StringIO(text)) if r["event"] == "down")
        row.update(timestamp_ms="99990", press_id="shift", key="Shift")
        extra = io.StringIO(newline="")
        writer = csv.DictWriter(extra, fieldnames=list(row))
        writer.writerow(row)
        writer.writerow({**row, "event": "up", "timestamp_ms": "99991"})
        row.update(timestamp_ms="99992", press_id="pending", key="a")
        writer.writerow(row)
        pending = text.rstrip("\r\n") + "\n" + extra.getvalue()
        result = predict_identity(self.model, pending, "P01", live=True)
        self.assertEqual(result["quality"]["next_window_keypresses"], 199)
        self.assertEqual(result["window_count"], 0)
        writer.writerow({**row, "event": "up", "timestamp_ms": "100000"})
        settled = text.rstrip("\r\n") + "\n" + extra.getvalue()
        result = predict_identity(self.model, settled, "P01", live=True)
        self.assertEqual(result["quality"]["next_window_keypresses"], 0)
        self.assertEqual(result["window_count"], 1)

    def test_replay_is_numerical_and_scores_against_selected_author(self):
        replay = next(r for r in self.model["replays"] if r["participant"] == "P02")
        result = replay_identity(self.model,replay["id"],"P01")
        self.assertEqual(result["source"], "recorded_replay")
        self.assertTrue(all(w["likely_participant"] == "P02" for w in result["windows"]))
        self.assertEqual(result["status"], "change_detected")
        description = public_description(self.model)
        self.assertNotIn('"examples"', json.dumps(description))
        self.assertNotIn('"reference_hashes"', json.dumps(description))
        self.assertNotIn('"key"', json.dumps(self.model["replays"]))
        self.assertTrue(all(r["hash"] not in self.model["profiles"][r["participant"]]["reference_hashes"]
                            for r in self.model["replays"] if r["label"] == "normal"))

    def test_reference_warning_and_separate_condition_metrics(self):
        text = (self.root / "P01_S1.csv").read_text()
        self.assertTrue(predict_identity(self.model,text,"P01")["reference_recording"])
        member = self.report["members"]["P01"]
        self.assertEqual(member["by_condition"]["impaired"]["sessions"], 1)
        self.assertEqual(member["by_condition"]["impaired"]["flagged_sessions"], 1)
        self.assertEqual(member["matrix"]["P02"]["sessions"], 10)
        for expected in (None,"P99",[]):
            with self.assertRaises(ValueError):
                predict_identity(self.model,text,expected)

    def test_comparison_and_heldout_changes_do_not_retrain_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture(root)
            before, _ = build(root)
            add(root,"P01",11,gap=800,hold=400,label="impaired",day=2)
            add(root,"P01",10,gap=700,hold=300)
            after, _ = build(root)
            for pid in ("P01", "P02"):
                for key in ("threshold", "scale", "examples"):
                    self.assertEqual(before["profiles"][pid][key],after["profiles"][pid][key])

    def test_http_identity_routes_and_origin_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "identity.json"
            path.write_text(json.dumps(self.model),encoding="utf-8")
            process = subprocess.Popen([sys.executable,"identity_model.py","serve","--model",str(path),"--port","18768"],
                                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                base = "http://127.0.0.1:18768"
                for _ in range(50):
                    try:
                        page = urllib.request.urlopen(base,timeout=1).read()
                        break
                    except urllib.error.URLError:
                        if process.poll() is not None:
                            self.fail(process.stderr.read().decode())
                        time.sleep(.1)
                else:
                    self.fail("Identity server did not become available")
                self.assertIn(b"Expected author", page)
                with urllib.request.urlopen(base+"/api/identity/profiles") as response:
                    self.assertEqual(len(json.load(response)["profiles"]),2)
                with urllib.request.urlopen(base+"/identity/recorder.js") as response:
                    self.assertIn(b"createRecorder",response.read())
                def post(route,data,origin=base):
                    return urllib.request.urlopen(urllib.request.Request(base+route,data=json.dumps(data).encode(),
                        headers={"Content-Type":"application/json","Origin":origin}),timeout=5)
                with post('/api/identity/predict',{"expected_participant":"P01","csv":recording(gap=350,hold=200)}) as response:
                    self.assertEqual(json.load(response)["status"],"change_detected")
                with post('/api/identity/replay',{"expected_participant":"P01","replay_id":self.model["replays"][0]["id"]}) as response:
                    self.assertEqual(json.load(response)["source"],"recorded_replay")
                for route,body in (("/api/identity/predict",{"expected_participant":"P99","csv":recording()}),
                                   ("/api/identity/replay",{"expected_participant":"P01","replay_id":"unknown"}),
                                   ("/api/identity/predict",[])):
                    with self.assertRaises(urllib.error.HTTPError) as bad:
                        post(route,body)
                    self.assertEqual(bad.exception.code,400)
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    post('/api/identity/predict',{"expected_participant":"P01","csv":recording()},"https://example.com")
                self.assertEqual(bad.exception.code,403)
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
