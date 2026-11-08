"""Fixed-text, expected-author kNN demo and recording-held-out member evaluation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics as st
import sys

from compare_models import calibrate, cell, fraction, rates
from keystroke_model import FEATURES, extract, fingerprint, load_sessions, read_csv, save_json, select_windows
from p04_experiment import FeatureKNN, TIMING, identity_split


VERSION = 1


def score_window(profile, features):
    names = profile["features"]
    distances = [(math.sqrt(st.mean(((features[n] - ex[n]) / profile["scale"][n]) ** 2 for n in names)), i)
                 for i, ex in enumerate(profile["examples"])]
    nearest = sorted(distances)[:profile["k"]]
    score = st.mean(d for d, _ in nearest)
    changes = []
    for n in names:
        reference = st.mean(profile["examples"][i][n] for _, i in nearest)
        deviation = math.sqrt(st.mean(((features[n] - profile["examples"][i][n]) / profile["scale"][n]) ** 2 for _, i in nearest))
        changes.append({"feature": n, "observed": features[n], "baseline": reference, "deviation": deviation})
    return {"score": score, "unusual": score > profile["threshold"],
            "top_changes": sorted(changes, key=lambda c: c["deviation"], reverse=True)[:3],
            "neighbors": [{"reference_window": i+1, "distance": d} for d, i in nearest]}


def score_windows(profile, windows):
    predictions = [{**score_window(profile, w["features"]), "window": i+1,
                    "start_ms": w["start_ms"], "end_ms": w["end_ms"]} for i, w in enumerate(windows)]
    median = st.median(w["score"] for w in predictions) if predictions else None
    def status(flag):
        return "change_detected" if flag else "consistent_with_expected_author"
    return {"status": status(median > profile["threshold"]) if median is not None else "insufficient_data",
            "latest_status": status(predictions[-1]["unusual"]) if predictions else "insufficient_data",
            "median_score": median, "threshold": profile["threshold"], "window_count": len(predictions),
            "flagged_windows": sum(w["unusual"] for w in predictions), "windows": predictions}


def get_profile(model, expected):
    if model.get("version") != VERSION or model.get("method") != "identity_knn":
        raise ValueError("Unsupported identity model. Run identity-demo.cmd to rebuild it.")
    if not isinstance(expected, str) or expected not in model["profiles"]:
        raise ValueError("Choose an expected author with a trained fixed-text baseline.")
    return model["profiles"][expected]


def predict_identity(model, text, expected):
    profile = get_profile(model, expected)
    rows = read_csv(text)
    # Preserve task transitions and interruptions, while counting only fixed presses as usable.
    fixed_rows = [{**r, "text_type": ""} if r["text_type"] != "fixed" else r for r in rows]
    windows, quality = extract(fixed_rows, model["window_size"])
    result = score_windows(profile, windows)
    reference = fingerprint(text) in profile["reference_hashes"] or [rows[0]["participant_id"], rows[0]["session_id"]] in profile["reference_ids"]
    return {**result, "expected_participant": expected, "source": "csv", "window_size": model["window_size"],
            "recording_participant": rows[0]["participant_id"], "recording_session": rows[0]["session_id"],
            "reference_recording": reference, "validation": profile["validation"], "quality": quality,
            "ignored_nonfixed_keypresses": sum(r["event"] == "down" and r["text_type"] != "fixed" for r in rows),
            "interpretation": "A change can reflect another author or a change in the same author; it does not identify impairment."}


def replay_identity(model, replay_id, expected):
    profile = get_profile(model, expected)
    replay = next((r for r in model["replays"] if r["id"] == replay_id), None)
    if replay is None:
        raise ValueError("Choose an available recorded replay.")
    return {**score_windows(profile, replay["windows"]), "expected_participant": expected,
            "source": "recorded_replay", "window_size": model["window_size"],
            "recording_participant": replay["participant"], "recording_session": replay["session"],
            "recording_label": replay["label"], "reference_recording": replay["hash"] in profile["reference_hashes"],
            "validation": profile["validation"], "quality": {"usable_keypresses": len(replay["windows"])*model["window_size"],
            "window_keypresses": len(replay["windows"])*model["window_size"]}, "ignored_nonfixed_keypresses": 0,
            "interpretation": "Recorded numerical windows, not live typing. Source labels do not enter the score."}


def public_description(model, live_available=True):
    return {"window_size": model["window_size"], "k": model["k"], "features": list(TIMING),
            "reference": Path(__file__).with_name("fixed_passage.txt").read_text(encoding="utf-8").strip(),
            "trained_utc": model["trained_utc"], "live_available": live_available,
            "profiles": [{"participant": pid, **{n: p[n] for n in
                          ("validation", "training_windows", "calibration_windows", "normal_test_recordings", "independent_normal_test_days")}}
                         for pid, p in model["profiles"].items()],
            "unavailable_profiles": model["unavailable_profiles"], "evaluation": model["evaluation_summary"],
            "replays": [{n: r[n] for n in ("id", "participant", "session", "label", "window_count")} for r in model["replays"]]}


def build(root, k=5, false_alarm=.05):
    if not isinstance(k, int) or k < 1 or not 0 < false_alarm < .5:
        raise ValueError("Use positive k and 0 < false-alarm target < 0.5.")
    sessions, skipped = load_sessions(root, 200)
    if not sessions:
        raise ValueError("No readable recordings found.")
    model = {"version": VERSION, "method": "identity_knn", "window_size": 200, "k": k,
             "trained_utc": datetime.now(timezone.utc).isoformat(), "profiles": {}, "replays": [],
             "unavailable_profiles": {}, "evaluation_summary": {}}
    report = {"created_utc": model["trained_utc"], "python_version": platform.python_version(), "k": k,
              "window_size": 200, "features": list(TIMING), "false_alarm_target_per_window": false_alarm,
              "members": {}, "skipped_files": skipped,
              "source_code_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("identity_model.py", "p04_experiment.py", "keystroke_model.py", "compare_models.py")},
              "limitations": ["Recording-held-out results are provisional without independent normal test days.",
                              "Other-author recordings are offline takeover proxies; keyboards and recording days can confound separation.",
                              "Same-author condition alerts are false identity alerts, not successful takeover detections or diagnoses.",
                              "The 5% default is a per-window calibration target, not a guaranteed window or session false-alert rate.",
                              "Only expected-author normal training/calibration data fit each profile; participant labels in scored CSVs do not select its profile.",
                              "Each latest-window alert and the session median are reported separately; a session median can hide a recent handover.",
                              "No model uses free text. New independent-day normal data is needed before a final accuracy claim."]}
    for pid in sorted({s["participant"] for s in sessions}):
        normal = [s for s in sessions if s["participant"] == pid and s["label"] == "normal" and select_windows([s], "fixed")]
        training, calibration, testing, validation = identity_split(normal)
        tw, cw = select_windows(training, "fixed"), select_windows(calibration, "fixed")
        splits = {role: [{n: s[n] for n in ("participant", "session", "day", "hash")} for s in group]
                  for role, group in (("training", training), ("calibration", calibration), ("normal_test", testing))}
        if len(tw) < k or len(cw) < 2:
            reason = f"Need >= {k} training and 2 calibration windows; found {len(tw)} and {len(cw)}."
            model["unavailable_profiles"][pid] = reason
            report["members"][pid] = {"status": "insufficient_data", "reason": reason, "splits": splits}
            continue
        estimator = FeatureKNN(tw, TIMING, k)
        threshold = calibrate([estimator.score(w) for w in cw], false_alarm)
        reference_days = {s["day"] for s in training + calibration}
        profile = {"features": list(TIMING), "k": k, "center": estimator.center, "scale": estimator.scale,
                   "examples": estimator.examples, "threshold": threshold, "validation": validation,
                   "training_windows": len(tw), "calibration_windows": len(cw), "normal_test_recordings": len(testing),
                   "independent_normal_test_days": sorted({s["day"] for s in testing} - reference_days),
                   "reference_hashes": [s["hash"] for s in training + calibration],
                   "reference_ids": [[pid, s["session"]] for s in training + calibration]}
        model["profiles"][pid] = profile
        other = [s for s in sessions if s["participant"] != pid and s["label"] == "normal" and select_windows([s], "fixed")]
        conditions = [s for s in sessions if s["participant"] == pid and s["label"] != "normal" and select_windows([s], "fixed")]
        evaluation = []
        for role, group in (("normal_author", testing), ("other_author", other), ("same_author_condition", conditions)):
            for s in group:
                result = score_windows(profile, select_windows([s], "fixed"))
                evaluation.append({**{n: s[n] for n in ("participant", "session", "label", "day", "hash")},
                                   "role": role, "window_count": result["window_count"], "flagged_windows": result["flagged_windows"],
                                   "unusual": result["status"] == "change_detected", "median_score": result["median_score"],
                                   "independent_of_reference_days": s["day"] not in reference_days,
                                   "window_scores": [w["score"] for w in result["windows"]]})
        metrics = {role: rates([r for r in evaluation if r["role"] == role])
                   for role in ("normal_author", "other_author", "same_author_condition")}
        matrix = {source: rates([r for r in evaluation if r["participant"] == source and r["role"] != "same_author_condition"])
                  for source in sorted({s["participant"] for s in sessions})}
        by_condition = {label: rates([r for r in evaluation if r["role"] == "same_author_condition" and r["label"] == label])
                        for label in sorted({s["label"] for s in conditions})}
        model["evaluation_summary"][pid] = {"metrics": metrics, "matrix": matrix, "by_condition": by_condition,
                                             "validation": validation, "independent_normal_test_days": profile["independent_normal_test_days"]}
        report["members"][pid] = {"status": "evaluated", "splits": splits, "threshold": threshold,
                                    "training_windows": len(tw), "calibration_windows": len(cw),
                                    **model["evaluation_summary"][pid], "evaluation": evaluation,
                                    "unscored_same_author_conditions": [{"session": s["session"], "label": s["label"],
                                         "reason": "no_complete_fixed_window"} for s in sessions if s["participant"] == pid
                                         and s["label"] != "normal" and not select_windows([s], "fixed")]}
        # Preset choice: first held-out normal recording, first complete recording per other condition.
        replay_sessions = testing[:1] + [next(s for s in conditions if s["label"] == label) for label in by_condition]
        for s in replay_sessions:
            ws = select_windows([s], "fixed")
            model["replays"].append({"id": f"{pid}-{s['hash'][:16]}",
                **{n: s[n] for n in ("participant", "session", "label", "hash")}, "window_count": len(ws),
                "windows": [{"features": {n: w["features"][n] for n in TIMING}, "start_ms": w["start_ms"], "end_ms": w["end_ms"]} for w in ws]})
    if not model["profiles"]:
        raise ValueError("No trainable fixed-text identity profiles. Collect more normal recordings.")
    return model, report


def summary_markdown(report):
    def f(metric):
        return fraction(metric["flagged_sessions"], metric["sessions"])
    lines = ["# Per-member fixed-text kNN evaluation", "",
             f"k={report['k']}; 200 usable keypresses; eight timing features. Rates below count whole recordings.", "",
             "| Expected author | Normal-author false alerts | Other-author detections | Same-author condition false alerts | Independent normal test days |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for pid, member in report["members"].items():
        if member["status"] != "evaluated":
            lines.append(f"| {pid} | Unavailable | Unavailable | Unavailable | 0 |")
            continue
        m = member["metrics"]
        lines.append(f"| {pid} | {f(m['normal_author'])} | {f(m['other_author'])} | {f(m['same_author_condition'])} | {len(member['independent_normal_test_days'])} |")
    people = sorted(report["members"])
    lines += ["", "## Expected author versus recording author", "",
              "Diagonal: normal-author false alerts. Other cells: other-author detections. This is an alert matrix, not a guessed-identity confusion matrix.", "",
              "| Expected author | " + " | ".join(people) + " |", "| --- | " + " | ".join("---:" for _ in people) + " |"]
    for pid, member in report["members"].items():
        lines.append("| " + pid + " | " + " | ".join(f(member["matrix"][source]) if member["status"] == "evaluated" else "Unavailable" for source in people) + " |")
    lines += ["", "## Same-author changes, kept separate", "", "| Author | Condition label | False takeover alerts |", "| --- | --- | ---: |"]
    for pid, member in report["members"].items():
        for label, metric in member.get("by_condition", {}).items():
            lines.append(f"| {pid} | {cell(label)} | {f(metric)} |")
    lines += ["", "## Split and coverage", "", "| Author | Normal training / calibration / test recordings | Training / calibration windows |",
              "| --- | ---: | ---: |"]
    for pid, m in report["members"].items():
        counts = " / ".join(str(len(m["splits"][role])) for role in ("training", "calibration", "normal_test"))
        lines.append(f"| {pid} | {counts} | {m.get('training_windows', 0)} / {m.get('calibration_windows', 0)} |")
    lines += ["", "## Interpretation", ""] + ["- " + text for text in report["limitations"]]
    lines += ["", "[Full results and splits](results.json). Rerun identity-demo.cmd after adding data; each evaluation run is preserved.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--data", required=True, type=Path)
    train.add_argument("--model", type=Path, default=Path("models/identity.json"))
    train.add_argument("--report-dir", type=Path)
    train.add_argument("--k", type=int, default=5)
    train.add_argument("--false-alarm-target", type=float, default=.05)
    serve = sub.add_parser("serve")
    serve.add_argument("--model", type=Path, default=Path("models/identity.json"))
    serve.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    try:
        if args.command == "train":
            directory = args.report_dir or Path("reports/member_evaluation") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            if directory.exists():
                raise ValueError("Choose a new report directory; earlier evaluations are preserved.")
            model, report = build(args.data, args.k, args.false_alarm_target)
            directory.mkdir(parents=True)
            save_json(directory / "results.json", report)
            (directory / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
            save_json(args.model, model)
            print(f"Trained members: {', '.join(model['profiles'])}. Report: {directory / 'summary.md'}")
        else:
            from app import serve as run_server
            model = json.loads(args.model.read_text(encoding="utf-8"))
            run_server(None, args.port, identity_model=model)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
