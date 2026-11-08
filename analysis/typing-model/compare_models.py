"""Compare four personal anomaly detectors on identical recording splits.

Only this optional benchmark requires scikit-learn. Nothing is pickled or uploaded.
"""
from __future__ import annotations

import argparse
import collections
import importlib.metadata
import math
from pathlib import Path
import platform
import statistics as st
import sys

from keystroke_model import FEATURES, fit_profile, load_sessions, save_json, score, select_windows, split_baseline


METHODS = ("baseline", "knn", "lof", "isolation_forest")
LABELS = {"baseline": "Personal baseline", "knn": "kNN", "lof": "LOF", "isolation_forest": "Isolation Forest"}


class Detector:
    """Fit scales and estimator on training windows only; larger scores are unusual."""

    def __init__(self, windows, method, k=5, lof_neighbors=20, seed=42):
        self.method = method
        self.profile = fit_profile(windows, "knn" if method == "knn" else "baseline", k)
        self.parameters = {}
        self.estimator = None
        if method == "knn":
            self.parameters = {"k": k}
        elif method == "lof":
            from sklearn.neighbors import LocalOutlierFactor
            effective = min(lof_neighbors, len(windows) - 1)
            self.parameters = {"n_neighbors": effective, "requested_neighbors": lof_neighbors, "novelty": True}
            self.estimator = LocalOutlierFactor(n_neighbors=effective, novelty=True, contamination="auto")
        elif method == "isolation_forest":
            from sklearn.ensemble import IsolationForest
            self.parameters = {"n_estimators": 200, "max_samples": min(256, len(windows)), "random_state": seed}
            self.estimator = IsolationForest(**self.parameters, contamination="auto", n_jobs=1)
        elif method != "baseline":
            raise ValueError(f"Unknown method: {method}")
        if self.estimator is not None:
            self.estimator.fit(self.matrix(windows))

    def matrix(self, windows):
        return [[(w["features"][n] - self.profile["center"][n]) / self.profile["scale"][n]
                 for n in FEATURES] for w in windows]

    def scores(self, windows):
        if not windows:
            return []
        if self.estimator is not None:
            # score_samples (not predict/decision_function): use our separate calibration.
            values = [-float(v) for v in self.estimator.score_samples(self.matrix(windows))]
        else:
            values = [score(self.profile, w["features"])[0] for w in windows]
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"{self.method} produced a non-finite score.")
        return values


def calibrate(values, false_alarm):
    """Same empirical upper-quantile rule for every detector, in its own units."""
    ordered = sorted(values)
    rank = min(len(ordered) - 1, math.ceil((len(ordered) + 1) * (1 - false_alarm)) - 1)
    return ordered[rank]


def evaluate(detector, session, windows, threshold, role, reference_days):
    values = detector.scores(windows)
    median = st.median(values)
    return {"participant": session["participant"], "session": session["session"],
            "recording_hash": session["hash"],
            "day": session["day"], "label": session["label"], "role": role,
            "independent_of_reference_days": session["day"] not in reference_days,
            "window_count": len(values), "flagged_windows": sum(v > threshold for v in values),
            "median_score": median, "unusual": median > threshold, "window_scores": values,
            "window_spans_seconds": [(w["end_ms"] - w["start_ms"]) / 1000 for w in windows]}


def rates(rows):
    sessions = len(rows)
    windows = sum(r["window_count"] for r in rows)
    flagged_sessions = sum(r["unusual"] for r in rows)
    flagged_windows = sum(r["flagged_windows"] for r in rows)
    return {"sessions": sessions, "participant_days": len({(r["participant"], r["day"]) for r in rows}),
            "participants": len({r["participant"] for r in rows}), "windows": windows,
            "flagged_sessions": flagged_sessions, "flagged_windows": flagged_windows,
            "session_rate": flagged_sessions / sessions if sessions else None,
            "window_rate": flagged_windows / windows if windows else None}


def aggregate(rows):
    normal = [r for r in rows if r["role"] == "baseline_test"]
    conditions = [r for r in rows if r["role"] == "comparison"]
    labels = sorted({r["label"] for r in conditions})
    return {"baseline_false_alerts": rates(normal),
            "comparison_conditions": {label: rates([r for r in conditions if r["label"] == label]) for label in labels},
            "independent_comparison_conditions": {
                label: rates([r for r in conditions if r["label"] == label and r["independent_of_reference_days"]])
                for label in labels}}


def compare(root, size=200, false_alarm=.05, baseline_label="normal", k=5, lof_neighbors=20, seed=42):
    sessions, skipped = load_sessions(root, size)
    return compare_sessions(sessions, skipped, size, false_alarm, baseline_label, k, lof_neighbors, seed)


def compare_sessions(sessions, skipped, size=200, false_alarm=.05, baseline_label="normal",
                     k=5, lof_neighbors=20, seed=42, split_plan=None):
    """Evaluate extracted data, optionally using preassigned recording hashes."""
    import sklearn
    if not 0 < false_alarm < .5 or k < 1 or lof_neighbors < 1:
        raise ValueError("Use 0 < false-alarm target < 0.5 and positive neighbour counts.")
    if not sessions:
        raise ValueError("No readable sessions found. Check --data and matching CSV/metadata files.")
    report = {"version": 1, "window_size": size, "baseline_label": baseline_label,
              "false_alarm_target_per_window": false_alarm, "seed": seed,
              "versions": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                           **{name: importlib.metadata.version(name) for name in ("numpy", "scipy", "joblib", "threadpoolctl")}},
              "features": list(FEATURES), "profiles": {}, "skipped_files": skipped,
              "unscored_recordings": [], "recordings": [], "summary": {}}
    for s in sessions:
        report["recordings"].append({name: s[name] for name in ("participant", "session", "day", "label", "hash", "quality")})
    all_rows = {method: [] for method in METHODS}
    for pid in sorted({s["participant"] for s in sessions}):
        for text_type in ("fixed", "free"):
            relevant = [s for s in sessions if s["participant"] == pid and select_windows([s], text_type)]
            normal = [s for s in relevant if s["label"] == baseline_label]
            training, calibration, testing, validation = split_baseline(normal)
            if split_plan is not None:
                planned = split_plan[f"{pid}:{text_type}"]
                by_hash = {s["hash"]: s for s in sessions}
                training, calibration, testing = [
                    [by_hash[s["hash"]] for s in planned["splits"][role]]
                    for role in ("training", "calibration", "baseline_test")]
                validation = planned["validation"]
            tw, cw = select_windows(training, text_type), select_windows(calibration, text_type)
            entry = {"validation": validation, "training_windows": len(tw), "calibration_windows": len(cw),
                     "splits": {role: [{"session": s["session"], "day": s["day"], "hash": s["hash"]} for s in group]
                                for role, group in (("training", training), ("calibration", calibration), ("baseline_test", testing))},
                     "models": {}}
            report["profiles"][f"{pid}:{text_type}"] = entry
            # Common eligibility prevents comparing models on different subsets.
            if len(tw) < max(3, k) or len(cw) < 2:
                entry.update(status="insufficient_data", reason=f"All four methods require >= {max(3, k)} training and 2 calibration windows on the shared split.")
            else:
                entry["status"] = "compared"
                reference_days = {s["day"] for s in training + calibration}
                for method in METHODS:
                    detector = Detector(tw, method, k, lof_neighbors, seed)
                    threshold = calibrate(detector.scores(cw), false_alarm)
                    rows = []
                    for s in testing + [s for s in relevant if s["label"] != baseline_label]:
                        role = "baseline_test" if s["label"] == baseline_label else "comparison"
                        windows = select_windows([s], text_type)
                        if windows:
                            rows.append(evaluate(detector, s, windows, threshold, role, reference_days))
                    entry["models"][method] = {"threshold": threshold, "parameters": detector.parameters,
                                               "evaluation": rows, "metrics": aggregate(rows)}
                    all_rows[method].extend({**r, "text_type": text_type} for r in rows)
            for s in relevant:
                if s["label"] != baseline_label and entry["status"] != "compared":
                    report["unscored_recordings"].append({"participant": pid, "session": s["session"], "label": s["label"],
                                                            "text_type": text_type, "reason": "no_trainable_profile"})
    # Include zero-window/unknown tasks, even if a different task from this file was scored.
    for s in sessions:
        types = {w["text_type"] for w in s["windows"]}
        if not types:
            report["unscored_recordings"].append({"participant": s["participant"], "session": s["session"],
                                                   "label": s["label"], "text_type": "none", "reason": "no_complete_windows"})
    report["summary"] = {method: aggregate(rows) for method, rows in all_rows.items()}
    report["limitations"] = [
        "No model ranking: comparison labels are exploratory and do not establish verified impairment.",
        "Missing baseline test days mean false-alert rates are unavailable, never zero.",
        "Same-day comparison results are reported separately from independent-day comparisons.",
        "Windows and repeated sessions are correlated; counts are not independent sample sizes.",
        "All scales and estimators use normal training windows only. Thresholds use normal calibration windows only.",
        "The 5% default is a per-window calibration target, not a measured session error rate.",
        "Settings are presets, not tuned on condition recordings. The final test must stay untouched during model selection.",
        "Splits follow the existing loader's metadata date-prefix grouping; verify study visit dates near midnight.",
        "LOF neighbours are capped at training_count - 1; tiny profiles and constant features may limit detection.",
        "The benchmark uses the same empirical quantile without the website's legacy 0.1 distance floor; its scores and thresholds are separate artifacts.",
    ]
    return report


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def fraction(flagged, total):
    return f"{flagged}/{total} ({flagged / total:.1%})" if total else "Unavailable"


def markdown(report):
    lines = ["# Four-model comparison", "", "Exploratory benchmark; no accuracy winner is selected.", "",
             f"Window: {report['window_size']} keypresses. Baseline label: {cell(report['baseline_label'])}. "
             f"Calibration target: {report['false_alarm_target_per_window']:.1%} per window.", "",
             "## Overall results", "", "Rows pool only profiles eligible for all four models. Fixed/free tasks are separate evaluations; "
             "a mixed-task recording can contribute two session-task results. Participant-days count unique participant/date pairs.", "",
             "| Model | Evaluation | Session-task alerts | Window alerts | Participant-days |",
             "| --- | --- | ---: | ---: | ---: |"]
    def metric_row(method, title, metrics):
        return f"| {LABELS[method]} | {cell(title)} | {fraction(metrics['flagged_sessions'], metrics['sessions'])} | " \
               f"{fraction(metrics['flagged_windows'], metrics['windows'])} | {metrics['participant_days']} |"
    for method, summary in report["summary"].items():
        lines.append(metric_row(method, "Normal test: false alerts", summary["baseline_false_alerts"]))
        for label, metrics in summary["comparison_conditions"].items():
            lines.append(metric_row(method, f"{label}: all comparisons (exploratory)", metrics))
            lines.append(metric_row(method, f"{label}: independent reference days only", summary["independent_comparison_conditions"][label]))
    lines += ["", "## Profiles and shared splits", "", "| Profile | Status | Training windows | Calibration windows | Normal test days | Validation |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for key, profile in report["profiles"].items():
        days = {s["day"] for s in profile["splits"]["baseline_test"]}
        lines.append(f"| {cell(key)} | {profile['status']} | {profile['training_windows']} | {profile['calibration_windows']} | {len(days)} | {profile['validation']} |")
    for key, profile in report["profiles"].items():
        lines += ["", f"## {cell(key)}", ""]
        for role, sessions in profile["splits"].items():
            lines.append(f"- {role.replace('_', ' ').title()}: " + (", ".join(f"{cell(s['session'])} ({s['day']})" for s in sessions) or "Unavailable"))
        if profile["status"] != "compared":
            lines += ["", profile["reason"]]
            continue
        lines += ["", "### Metrics", "", "| Model | Evaluation | Session-task alerts | Window alerts | Participant-days |",
                  "| --- | --- | ---: | ---: | ---: |"]
        for method, model in profile["models"].items():
            lines.append(metric_row(method, "Normal test: false alerts", model["metrics"]["baseline_false_alerts"]))
            for label, metrics in model["metrics"]["comparison_conditions"].items():
                lines.append(metric_row(method, f"{label}: all comparisons", metrics))
                lines.append(metric_row(method, f"{label}: independent reference days only", model["metrics"]["independent_comparison_conditions"][label]))
        lines += ["", "### Scores", "", "Scores have different units; compare alert rates, not raw score magnitudes.", "",
                  "| Model | Session | Condition | Day | Independent of reference days | Median | Threshold | Result |",
                  "| --- | --- | --- | --- | --- | ---: | ---: | --- |"]
        for method, model in profile["models"].items():
            for row in model["evaluation"]:
                lines.append(f"| {LABELS[method]} | {cell(row['session'])} | {cell(row['label'])} | {row['day']} | "
                             f"{'Yes' if row['independent_of_reference_days'] else 'No'} | {row['median_score']:.4f} | "
                             f"{model['threshold']:.4f} | {'Unusual' if row['unusual'] else 'Within baseline'} |")
    lines += ["", "## Coverage and exclusions", "", f"Readable recordings: {len(report['recordings'])}. Skipped files: {len(report['skipped_files'])}.", "",
              "| Participant | Session | Condition | Text type | Unscored reason |", "| --- | --- | --- | --- | --- |"]
    for r in report["unscored_recordings"]:
        lines.append("| " + " | ".join(cell(r[n]) for n in ("participant", "session", "label", "text_type", "reason")) + " |")
    if not report["unscored_recordings"]:
        lines.append("| — | — | — | — | None |")
    if report["skipped_files"]:
        lines += ["", "Skipped-file reasons (full paths are in the local JSON report):", ""]
        for reason, count in sorted(collections.Counter(r["reason"] for r in report["skipped_files"]).items()):
            lines.append(f"- {cell(reason)}: {count}")
    lines += ["", "## Interpretation and reproducibility", ""]
    lines.extend(f"- {text}" for text in report["limitations"])
    lines += [f"- Versions: Python {report['versions']['python']}; scikit-learn {report['versions']['scikit_learn']}. Seed: {report['seed']}.",
              "- JSON includes exact splits, training-file hashes, resolved parameters, quality diagnostics and window scores.",
              "- Method references: [LOF](https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.LocalOutlierFactor.html), "
              "[Isolation Forest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html).", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/model_comparison.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/model_comparison.md"))
    parser.add_argument("--window-size", type=int, default=200)
    parser.add_argument("--false-alarm-target", type=float, default=.05)
    parser.add_argument("--baseline-label", default="normal")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--lof-neighbors", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        if args.output.resolve() == args.markdown.resolve():
            raise ValueError("JSON and Markdown outputs must be different files.")
        report = compare(args.data, args.window_size, args.false_alarm_target, args.baseline_label,
                         args.k, args.lof_neighbors, args.seed)
        save_json(args.output, report)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(report), encoding="utf-8")
        print(f"Reports: {args.markdown} and {args.output}")
        compared = sum(p["status"] == "compared" for p in report["profiles"].values())
        print(f"Compared {compared} profiles; skipped {len(report['skipped_files'])} files.")
        baseline = report["summary"]["baseline"]["baseline_false_alerts"]
        if not baseline["sessions"]:
            print("Independent normal test results unavailable. Collect normal typing on new days before ranking models.")
    except ImportError:
        print("Install the comparison dependencies first: python -m pip install -r requirements-comparison.txt", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
