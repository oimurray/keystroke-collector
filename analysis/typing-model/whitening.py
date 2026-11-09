"""Training-only robust scaling and shrinkage-covariance whitening."""
from __future__ import annotations

import math
import statistics as st

from keystroke_model import fit_profile


DEFAULT_SHRINKAGE = 0.1


def cholesky(matrix):
    n = len(matrix)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if value <= 0:
                    raise ValueError("Covariance matrix is not positive definite.")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    return lower


def forward_substitution(lower, values):
    result = []
    for i, row in enumerate(lower):
        result.append((values[i] - sum(row[j] * result[j] for j in range(i))) / row[i])
    return result


def whiten_features(model, features, scale):
    names = model["names"]
    standardized = [(features[name] - model["center"][name]) / scale[name] for name in names]
    centered = [value - mean for value, mean in zip(standardized, model["mean"])]
    values = forward_substitution(model["cholesky"], centered)
    return dict(zip(names, values))


class WhitenedFeatureKNN:
    def __init__(self, windows, names, k=5, shrinkage=DEFAULT_SHRINKAGE):
        if len(windows) < max(2, k):
            raise ValueError("Not enough training windows for k and covariance estimation.")
        if not 0 <= shrinkage <= 1:
            raise ValueError("Covariance shrinkage must be in [0, 1].")
        self.names = tuple(names)
        self.k = k
        profile = fit_profile(windows, "knn", k)
        self.center = profile["center"]
        self.scale = profile["scale"]
        matrix = [[(w["features"][name] - self.center[name]) / self.scale[name] for name in self.names]
                  for w in windows]
        mean = [st.mean(row[j] for row in matrix) for j in range(len(self.names))]
        centered = [[value - mean[j] for j, value in enumerate(row)] for row in matrix]
        covariance = [[sum(row[i] * row[j] for row in centered) / (len(centered) - 1)
                       for j in range(len(self.names))] for i in range(len(self.names))]
        shrunken = [[(1 - shrinkage) * covariance[i][j] + (shrinkage if i == j else 0.0)
                     for j in range(len(self.names))] for i in range(len(self.names))]
        jitter = 1e-10 * max(1.0, max(shrunken[i][i] for i in range(len(self.names))))
        for i in range(len(self.names)):
            shrunken[i][i] += jitter
        self.model = {
            "names": self.names,
            "center": self.center,
            "mean": mean,
            "cholesky": cholesky(shrunken),
            "shrinkage": shrinkage,
        }
        self.examples = [whiten_features(self.model, w["features"], self.scale) for w in windows]

    def score(self, window):
        features = whiten_features(self.model, window["features"], self.scale)
        distances = [math.sqrt(st.mean((features[name] - example[name]) ** 2 for name in self.names))
                     for example in self.examples]
        return st.mean(sorted(distances)[:self.k])
