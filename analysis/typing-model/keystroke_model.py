"""Personal typing anomaly detector. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics as st
import sys

VERSION = 1
FEATURES = {
    "hold_median_ms": 5.0, "hold_iqr_ms": 5.0, "hold_p90_ms": 5.0,
    "dd_median_ms": 10.0, "dd_iqr_ms": 10.0, "dd_p90_ms": 10.0,
    "ud_median_ms": 10.0, "ud_iqr_ms": 10.0,
    "overlap_fraction": .02, "backspace_fraction": .01,
    "pause_fraction": .01,
}
MODIFIERS = {"Shift", "Control", "Alt", "AltGraph", "Meta", "CapsLock"}
BREAKS = {"blur", "visibility_hidden", "paste"}


def quantile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def read_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    required = {"participant_id", "session_id", "sample_id", "event",
                "timestamp_ms", "press_id", "key", "text_type"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
    rows = list(reader)
    identities = {(r["participant_id"], r["session_id"]) for r in rows}
    if len(identities) != 1 or not all(next(iter(identities), ("", ""))):
        raise ValueError("CSV must contain exactly one participant and one session.")
    for r in rows:
        try:
            r["timestamp_ms"] = float(r["timestamp_ms"])
        except (ValueError, TypeError):
            raise ValueError("CSV contains an invalid timestamp.") from None
        # Older collectors can export a negative session-relative origin.
        # Only differences enter the model; a constant offset is harmless.
        if not math.isfinite(r["timestamp_ms"]):
            raise ValueError("CSV timestamps must be finite.")
        if r["event"] not in {"down", "up", "marker"}:
            raise ValueError("Unknown event type: " + r["event"])
    return sorted(rows, key=lambda r: r["timestamp_ms"])


def features(presses):
    holds = [p["hold"] for p in presses]
    pairs = [(a, b) for a, b in zip(presses, presses[1:])
             if a["block"] == b["block"]]
    # Gaps over two seconds are retained as a separate pause measure.
    # Never form timing pairs across messages, focus breaks, or text-type changes.
    active = [(a, b) for a, b in pairs if 0 < b["t"] - a["t"] <= 2000]
    if len(active) < max(10, len(presses) // 5):
        return None
    dd = [b["t"] - a["t"] for a, b in active]
    ud = [b["t"] - a["up"] for a, b in active]
    return {
        "hold_median_ms": st.median(holds),
        "hold_iqr_ms": quantile(holds, .75) - quantile(holds, .25),
        "hold_p90_ms": quantile(holds, .9),
        "dd_median_ms": st.median(dd),
        "dd_iqr_ms": quantile(dd, .75) - quantile(dd, .25),
        "dd_p90_ms": quantile(dd, .9),
        "ud_median_ms": st.median(ud),
        "ud_iqr_ms": quantile(ud, .75) - quantile(ud, .25),
        "overlap_fraction": sum(v < 0 for v in ud) / len(ud),
        "backspace_fraction": sum(p["key"] == "Backspace" for p in presses) / len(presses),
        "pause_fraction": sum(b["t"] - a["t"] > 2000 for a, b in pairs) / max(1, len(pairs)),
    }


def extract(rows, window_size=200):
    if window_size < 50:
        raise ValueError("Window size must be at least 50.")
    quality = collections.Counter()
    quality["negative_timestamp_events"] = sum(r["timestamp_ms"] < 0 for r in rows)
    bad_samples = {r["sample_id"] for r in rows
                   if r.get("detail") == "paste" or r.get("input_type") == "insertFromPaste"}
    ups = collections.defaultdict(list)
    down_counts = collections.Counter(r["press_id"] for r in rows if r["event"] == "down")
    for r in rows:
        if r["event"] == "up":
            ups[r["press_id"]].append(r)
    presses = []
    segment = 0
    previous_type = None
    for r in rows:
        if r.get("detail") in BREAKS:
            segment += 1
        if r["event"] != "down":
            continue
        quality["raw_keypresses"] += 1
        text_type = r["text_type"]
        if text_type != previous_type:
            segment += 1
            previous_type = text_type
        if text_type not in {"fixed", "free"}:
            quality["unknown_text_type"] += 1
            segment += 1
            continue
        if r["sample_id"] in bad_samples:
            quality["pasted_sample_keypresses"] += 1
            segment += 1
            continue
        if r["key"] in MODIFIERS:
            continue
        releases = ups[r["press_id"]]
        if not r["sample_id"] or not r["press_id"] or len(releases) != 1 or down_counts[r["press_id"]] != 1:
            quality["unpaired_or_duplicate_presses"] += 1
            segment += 1
            continue
        up = releases[0]
        hold = up["timestamp_ms"] - r["timestamp_ms"]
        if (up.get("detail") == "forced_release" or not 0 < hold <= 5000
                or up["sample_id"] != r["sample_id"] or up["key"] != r["key"]
                or up["text_type"] != text_type):
            quality["invalid_or_forced_releases"] += 1
            segment += 1
            continue
        if int(up.get("repeat_count") or 0) > 0:
            quality["auto_repeated_presses"] += 1
            segment += 1
            continue
        presses.append({"t": r["timestamp_ms"], "up": up["timestamp_ms"],
                        "hold": hold, "key": r["key"], "type": text_type,
                        "segment": segment, "block": (segment, r["sample_id"])})
    quality["usable_keypresses"] = len(presses)
    windows = []
    # Combine short messages into windows within a continuous task segment.
    # Pair statistics still never cross a message boundary.
    groups = collections.defaultdict(list)
    for p in presses:
        groups[(p["segment"], p["type"])].append(p)
    for (_, text_type), group in groups.items():
        for i in range(0, len(group) - window_size + 1, window_size):
            chunk = group[i:i + window_size]
            f = features(chunk)
            if f is None:
                quality["rejected_sparse_windows"] += 1
                continue
            windows.append({"text_type": text_type, "start_ms": chunk[0]["t"],
                            "end_ms": chunk[-1]["up"], "features": f})
    quality["window_keypresses"] = len(windows) * window_size
    quality["unused_usable_keypresses"] = len(presses) - quality["window_keypresses"]
    return windows, dict(quality)


def fingerprint(text):
    # Normalize newline conventions so browser File.text() and local reads agree.
    return hashlib.sha256(text.lstrip("\ufeff").replace("\r\n", "\n").encode()).hexdigest()


def load_sessions(root, size):
    sessions, skipped, seen = [], [], set()
    for path in sorted(Path(root).rglob("*_meta.json")):
        if "older_versions" in path.parts or ".git" in path.parts:
            continue
        csv_path = path.with_name(path.name.replace("_meta.json", ".csv"))
        try:
            meta = json.loads(path.read_text(encoding="utf-8-sig"))
            text = csv_path.read_text(encoding="utf-8-sig")
            digest = fingerprint(text)
            if digest in seen:
                skipped.append({"file": str(path), "reason": "duplicate CSV"})
                continue
            rows = read_csv(text)
            pid, sid = rows[0]["participant_id"], rows[0]["session_id"]
            if (meta["participant_id"], meta["session_id"]) != (pid, sid):
                raise ValueError("CSV and metadata identities disagree")
            # UTC date is consistently used as a conservative recording-day group.
            date = str(meta["start"])[:10]
            from datetime import date as date_type
            date_type.fromisoformat(date)
            windows, quality = extract(rows, size)
            seen.add(digest)
            sessions.append({"participant": pid, "session": sid, "day": date,
                             "start": meta["start"], "label": meta["state_label"],
                             "hash": digest, "windows": windows, "quality": quality})
        except (OSError, ValueError, KeyError, TypeError) as e:
            skipped.append({"file": str(path), "reason": str(e)})
    for path in sorted(Path(root).rglob("*.csv")):
        if "older_versions" in path.parts or ".git" in path.parts:
            continue
        if not path.with_name(path.stem + "_meta.json").exists():
            skipped.append({"file": str(path), "reason": "missing matching metadata; condition label unknown"})
    return sorted(sessions, key=lambda s: s["start"]), skipped


def fit_profile(windows, method="baseline", k=5):
    if method not in {"baseline", "knn"}:
        raise ValueError("Method must be baseline or knn.")
    if method == "knn" and (not isinstance(k, int) or k < 1 or k > len(windows)):
        raise ValueError("k must be a positive integer no larger than the training window count.")
    center, scale = {}, {}
    for name, floor in FEATURES.items():
        vals = [w["features"][name] for w in windows]
        center[name] = st.median(vals)
        scale[name] = max(floor, 1.4826 * st.median(abs(v - center[name]) for v in vals))
    profile = {"center": center, "scale": scale, "method": method}
    if method == "knn":
        profile.update(k=k, training_examples=[dict(w["features"]) for w in windows])
    return profile


def score(profile, f):
    if profile.get("method", "baseline") == "knn":
        distances = []
        for example in profile["training_examples"]:
            distance = math.sqrt(st.mean(((f[n] - example[n]) / profile["scale"][n]) ** 2 for n in FEATURES))
            distances.append((distance, example))
        nearest = sorted(distances, key=lambda item: item[0])[:profile["k"]]
        value = st.mean(distance for distance, _ in nearest)
        # Explanations compare against the same neighbours used for the score.
        contributions = {n: math.sqrt(st.mean(((f[n] - ex[n]) / profile["scale"][n]) ** 2
                                             for _, ex in nearest)) for n in FEATURES}
        reasons = sorted(contributions, key=contributions.get, reverse=True)[:3]
        return value, [{"feature": n, "deviation": round(contributions[n], 3),
                        "observed": round(f[n], 3),
                        "baseline": round(st.mean(ex[n] for _, ex in nearest), 3)} for n in reasons]
    contributions = {name: abs(f[name] - profile["center"][name]) / profile["scale"][name]
                     for name in FEATURES}
    value = math.sqrt(st.mean(v * v for v in contributions.values()))
    reasons = sorted(contributions, key=contributions.get, reverse=True)[:3]
    return value, [{"feature": n, "deviation": round(contributions[n], 3),
                    "observed": round(f[n], 3), "baseline": round(profile["center"][n], 3)} for n in reasons]


def split_baseline(sessions):
    days = sorted({s["day"] for s in sessions})
    if len(days) >= 3:
        return ([s for s in sessions if s["day"] < days[-2]],
                [s for s in sessions if s["day"] == days[-2]],
                [s for s in sessions if s["day"] == days[-1]], "independent_days")
    if len(days) == 2:
        return ([s for s in sessions if s["day"] == days[0]],
                [s for s in sessions if s["day"] == days[1]], [], "no_baseline_test_day")
    # A runnable provisional model, explicitly without independent-day validation.
    if len(sessions) < 2:
        return sessions, [], [], "insufficient_calibration"
    cut = max(1, int(len(sessions) * .75))
    return sessions[:cut], sessions[cut:], [], "same_day_provisional"


def select_windows(sessions, text_type):
    return [w for s in sessions for w in s["windows"] if w["text_type"] == text_type]


def summarize_predictions(profile, windows):
    predictions = []
    for w in windows:
        value, reasons = score(profile, w["features"])
        predictions.append({"start_ms": w["start_ms"], "end_ms": w["end_ms"],
                            "score": round(value, 4), "unusual": value > profile["threshold"],
                            "top_changes": reasons})
    values = [p["score"] for p in predictions]
    return {"status": ("unusual_typing" if st.median(values) > profile["threshold"] else "within_baseline") if values else "insufficient_data",
            "median_score": round(st.median(values), 4) if values else None,
            "threshold": profile["threshold"], "window_count": len(predictions),
            "flagged_windows": sum(p["unusual"] for p in predictions), "windows": predictions}


def train(root, size=200, false_alarm=.05, baseline_label="normal", method="baseline", k=5):
    if method not in {"baseline", "knn"} or not isinstance(k, int) or k < 1:
        raise ValueError("Choose baseline or knn with a positive integer k.")
    if not 0 < false_alarm < .5:
        raise ValueError("False-alarm target must be between 0 and 0.5.")
    sessions, skipped = load_sessions(root, size)
    if not sessions:
        raise ValueError("No readable sessions found. Check --data and matching CSV/metadata files.")
    profiles, report = {}, {"method": method, "window_size": size, "sessions": [], "profiles": {}, "skipped": skipped}
    for s in sessions:
        report["sessions"].append({**{k: v for k, v in s.items() if k != "windows"},
                                   "windows_by_text_type": dict(collections.Counter(w["text_type"] for w in s["windows"]))})
    for pid in sorted({s["participant"] for s in sessions}):
        for text_type in ("fixed", "free"):
            key = f"{pid}:{text_type}"
            baseline = [s for s in sessions if s["participant"] == pid and s["label"] == baseline_label
                        and select_windows([s], text_type)]
            training, calibration, testing, validation = split_baseline(baseline)
            tw, cw = select_windows(training, text_type), select_windows(calibration, text_type)
            minimum_training = max(3, k) if method == "knn" else 3
            if len(tw) < minimum_training or len(cw) < 2:
                report["profiles"][key] = {"status": "insufficient_data", "training_windows": len(tw),
                                           "calibration_windows": len(cw),
                                           "reason": f"Need at least {minimum_training} training and 2 separate-session calibration windows."}
                continue
            profile = fit_profile(tw, method, k)
            calibration_scores = sorted(score(profile, w["features"])[0] for w in cw)
            # Conservative empirical quantile; this is a target, not a guaranteed FPR.
            rank = min(len(cw) - 1, math.ceil((len(cw) + 1) * (1 - false_alarm)) - 1)
            profile.update({"participant": pid, "text_type": text_type,
                            "threshold": max(.1, calibration_scores[rank]), "validation": validation,
                            "training_windows": len(tw), "calibration_windows": len(cw),
                            "training_days": sorted({s["day"] for s in training}),
                            "calibration_days": sorted({s["day"] for s in calibration}),
                            "baseline_test_days": sorted({s["day"] for s in testing}),
                            "reference_hashes": [s["hash"] for s in training + calibration],
                            "reference_ids": [[s["participant"], s["session"]] for s in training + calibration]})
            profiles[key] = profile
            condition_sessions = [s for s in sessions if s["participant"] == pid and s["label"] != baseline_label
                                  and select_windows([s], text_type)]
            evaluation = []
            for s in testing + condition_sessions:
                result = summarize_predictions(profile, select_windows([s], text_type))
                evaluation.append({"session": s["session"], "day": s["day"], "label": s["label"],
                                   **{k: v for k, v in result.items() if k != "windows"}})
            profiles_report = {k: v for k, v in profile.items()
                               if k not in {"center", "scale", "reference_hashes", "reference_ids", "training_examples"}}
            profiles_report["evaluation"] = evaluation
            profiles_report["status"] = "trained"
            report["profiles"][key] = profiles_report
    if not profiles:
        raise ValueError("No trainable profiles. Collect more labeled baseline sessions with known text_type.")
    report["unscored_condition_recordings"] = []
    for s in sessions:
        if s["label"] == baseline_label:
            continue
        supported = [w for w in s["windows"] if f"{s['participant']}:{w['text_type']}" in profiles]
        if not supported:
            report["unscored_condition_recordings"].append({
                "participant": s["participant"], "session": s["session"], "label": s["label"],
                "usable_keypresses": s["quality"]["usable_keypresses"],
                "reason": "no_complete_windows" if not s["windows"] else "no_matching_text_type_baseline"})
    model = {"version": VERSION, "method": method, "window_size": size, "baseline_label": baseline_label,
             "false_alarm_target": false_alarm, "profiles": profiles,
             "limitations": ["Anomaly scores are not probabilities or diagnoses.",
                             "Normal labels are assumed to mean rested and sober; verify them.",
                             "Same-day calibration cannot establish generalization to a new day.",
                             "Condition comparisons are exploratory; no condition labels tune the model."]}
    return model, report


def predict(model, text):
    if model.get("version") != VERSION:
        raise ValueError("Unsupported model version; retrain using this tool.")
    rows = read_csv(text)
    pid, sid = rows[0]["participant_id"], rows[0]["session_id"]
    windows, quality = extract(rows, model["window_size"])
    results = {}
    present_types = sorted({r["text_type"] for r in rows if r["event"] == "down"})
    for text_type in present_types:
        profile = model["profiles"].get(f"{pid}:{text_type}")
        if profile is None:
            results[text_type or "unknown"] = {"status": "no_matching_baseline",
                 "message": "Collect and train a baseline for this participant and text type."}
            continue
        result = summarize_predictions(profile, [w for w in windows if w["text_type"] == text_type])
        result["validation"] = profile["validation"]
        result["reference_recording"] = (fingerprint(text) in profile["reference_hashes"]
                                         or [pid, sid] in profile["reference_ids"])
        if result["reference_recording"]:
            result["warning"] = "This recording helped train or calibrate the model; its result is not an independent test."
        results[text_type] = result
    return {"participant": pid, "session": sid, "method": model.get("method", "baseline"), "window_size": model["window_size"],
            "quality": quality, "results": results,
            "interpretation": "Unusual typing is a change from a personal baseline, not proof of tiredness or alcohol impairment."}


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train", help="Train personal baseline profiles and write an evaluation report")
    t.add_argument("--data", required=True, type=Path)
    t.add_argument("--model", type=Path, help="Defaults to models/baseline.json or models/knn.json")
    t.add_argument("--report", type=Path, help="Defaults to reports/evaluation.json or reports/evaluation_knn.json")
    t.add_argument("--method", choices=["baseline", "knn"], default="baseline")
    t.add_argument("--k", type=int, default=5, help="Number of neighbours for knn (default 5)")
    t.add_argument("--window-size", type=int, default=200)
    t.add_argument("--false-alarm-target", type=float, default=.05)
    t.add_argument("--baseline-label", default="normal")
    p = sub.add_parser("predict", help="Score a collector CSV")
    p.add_argument("csv", type=Path)
    p.add_argument("--model", type=Path, default=Path("models/baseline.json"))
    p.add_argument("--output", type=Path)
    s = sub.add_parser("serve", help="Open the local CSV upload interface")
    s.add_argument("--model", type=Path, default=Path("models/baseline.json"))
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--knn-model", type=Path, help="Optional kNN model for the website model selector")
    args = parser.parse_args()
    try:
        if args.command == "train":
            args.model = args.model or Path(f"models/{args.method}.json")
            args.report = args.report or Path("reports/evaluation_knn.json" if args.method == "knn" else "reports/evaluation.json")
            model, report = train(args.data, args.window_size, args.false_alarm_target, args.baseline_label, args.method, args.k)
            save_json(args.model, model)
            save_json(args.report, report)
            print(f"Saved {len(model['profiles'])} profiles to {args.model}")
            for key, profile in model["profiles"].items():
                print(f"  {key}: {profile['training_windows']} training / {profile['calibration_windows']} calibration windows; {profile['validation']}")
            print(f"Evaluation: {args.report}")
        else:
            model = json.loads(args.model.read_text(encoding="utf-8"))
            if args.command == "serve":
                from app import serve
                others = {}
                knn_path = args.knn_model
                if knn_path is None and args.model.name == "baseline.json":
                    candidate = args.model.with_name("knn.json")
                    if candidate.exists():
                        knn_path = candidate
                if knn_path is not None:
                    knn_model = json.loads(knn_path.read_text(encoding="utf-8"))
                    if knn_model.get("method") != "knn":
                        raise ValueError("--knn-model must point to a trained knn model.")
                    others["knn"] = knn_model
                serve(model, args.port, others)
            else:
                result = predict(model, args.csv.read_text(encoding="utf-8-sig"))
                if args.output:
                    save_json(args.output, result)
                print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
