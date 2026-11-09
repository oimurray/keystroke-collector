import json
import math
from pathlib import Path
import tempfile
import unittest

from compare_models import Detector
from identity_model import build, predict_identity, public_description
from keystroke_model import FEATURES
from test_identity import fixture
from test_model import recording
from whitening import WhitenedFeatureKNN, whiten_features


def sample_features(index, correlated=False):
    values = {}
    for j, name in enumerate(FEATURES):
        values[name] = math.sin(index * (j + 1) * 0.17) + 0.01 * index * (j + 1)
    if correlated:
        values["hold_p90_ms"] = 3 * values["hold_median_ms"] + 2
        values["dd_p90_ms"] = -2 * values["dd_median_ms"] + 1
    return values


def windows(count=100, correlated=False):
    return [{"features": sample_features(index, correlated)} for index in range(count)]


def covariance(rows, names):
    means = [sum(row[name] for row in rows) / len(rows) for name in names]
    centered = [[row[name] - mean for name, mean in zip(names, means)] for row in rows]
    return [[sum(row[i] * row[j] for row in centered) / (len(centered) - 1)
             for j in range(len(names))] for i in range(len(names))]


class WhiteningTests(unittest.TestCase):
    def test_whitened_training_covariance_is_identity(self):
        names = tuple(FEATURES)
        estimator = WhitenedFeatureKNN(windows(), names, k=2, shrinkage=0)
        transformed = [whiten_features(estimator.model, w["features"], estimator.scale)
                       for w in windows()]
        result = covariance(transformed, names)
        for i in range(len(names)):
            self.assertAlmostEqual(result[i][i], 1, places=6)
            for j in range(i):
                self.assertAlmostEqual(result[i][j], 0, places=6)

    def test_shrinkage_handles_constant_training_windows(self):
        constant = [{"features": {name: 1.0 for name in FEATURES}} for _ in range(10)]
        estimator = WhitenedFeatureKNN(constant, tuple(FEATURES), shrinkage=0.1)
        self.assertEqual(estimator.score(constant[0]), 0)
        json.dumps(estimator.model)

    def test_held_out_data_does_not_change_whitening(self):
        estimator = WhitenedFeatureKNN(windows(correlated=True), tuple(FEATURES))
        before = json.dumps(estimator.model)
        estimator.score(windows(1, correlated=True)[0])
        self.assertEqual(json.dumps(estimator.model), before)

    def test_detector_supports_whitened_knn(self):
        model = Detector(windows(correlated=True), "whitened_knn", k=2)
        self.assertTrue(all(math.isfinite(value) for value in model.scores(windows(3))))
        self.assertEqual(model.parameters["covariance_shrinkage"], 0.1)

    def test_identity_demo_supports_optional_whitening(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture(root)
            model, _ = build(root, whitening=True)
            result = predict_identity(model, recording(), "P01")
            self.assertEqual(model["method"], "identity_whitened_knn")
            self.assertTrue(math.isfinite(result["median_score"]))
            self.assertTrue(public_description(model)["covariance_whitening"])


if __name__ == "__main__":
    unittest.main()
