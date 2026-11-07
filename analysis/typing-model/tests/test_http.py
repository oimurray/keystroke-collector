"""End-to-end loopback test; run outside a network-blocking sandbox."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from keystroke_model import extract, fit_profile, read_csv
from test_model import recording


class HttpTests(unittest.TestCase):
    def test_upload_and_reject_invalid_requests(self):
        windows, _ = extract(read_csv(recording()), 100)
        profile = fit_profile(windows)
        profile.update(participant="P01", text_type="fixed", threshold=1,
                       validation="same_day_provisional", training_windows=4,
                       reference_hashes=[], reference_ids=[])
        model = {"version": 1, "window_size": 100, "profiles": {"P01:fixed": profile}}
        knn_profile = fit_profile(windows, method="knn", k=3)
        knn_profile.update({k: v for k, v in profile.items() if k not in {"center", "scale", "method"}})
        knn_model = {"version": 1, "method": "knn", "window_size": 100, "profiles": {"P01:fixed": knn_profile}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            path.write_text(json.dumps(model), encoding="utf-8")
            knn_path = Path(folder) / "knn.json"
            knn_path.write_text(json.dumps(knn_model), encoding="utf-8")
            process = subprocess.Popen([sys.executable, "keystroke_model.py", "serve", "--model", str(path), "--knn-model", str(knn_path), "--port", "18765"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                base = "http://127.0.0.1:18765"
                for _ in range(40):
                    try:
                        page = urllib.request.urlopen(base, timeout=1).read()
                        break
                    except urllib.error.URLError:
                        if process.poll() is not None:
                            self.fail(process.stderr.read().decode())
                        time.sleep(.1)
                else:
                    self.fail("Local server did not become available")
                self.assertIn(b"Compare with baseline", page)
                with urllib.request.urlopen(base + "/api/profiles") as response:
                    self.assertEqual({m["id"] for m in json.load(response)["models"]}, {"baseline", "knn"})
                def post(data, origin=base):
                    return urllib.request.urlopen(urllib.request.Request(
                        base + "/api/predict", data=json.dumps(data).encode(),
                        headers={"Content-Type": "application/json", "Origin": origin}), timeout=5)
                with post({"csv": recording(hold=200, gap=350)}) as response:
                    result = json.load(response)
                self.assertEqual(result["results"]["fixed"]["status"], "unusual_typing")
                with post({"csv": recording(hold=200, gap=350), "model": "knn"}) as response:
                    result = json.load(response)
                self.assertEqual(result["method"], "knn")
                self.assertEqual(result["results"]["fixed"]["status"], "unusual_typing")
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    post({"csv": recording(), "model": "missing"})
                self.assertEqual(bad.exception.code, 400)
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    post({"csv": "invalid"})
                self.assertEqual(bad.exception.code, 400)
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    post({"csv": recording()}, "https://example.com")
                self.assertEqual(bad.exception.code, 403)
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
