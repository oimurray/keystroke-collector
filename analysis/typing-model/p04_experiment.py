"""P04-focused kNN identity, feature-ablation and fixed-passage experiments."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
from pathlib import Path
import statistics as st
import sys

from aligned_typing import extract_aligned
from compare_models import calibrate, cell, fraction, rates
from keystroke_model import FEATURES, fingerprint, load_sessions, read_csv, save_json, select_windows, split_baseline


TIMING = tuple(name for name in FEATURES if name.endswith("_ms"))
FLOORS = {**FEATURES, "reference_error_fraction": .01, "extra_press_fraction": .01}
VARIANTS = {
    "raw_timing": (False, TIMING),
    "raw_backspace": (False, TIMING + ("backspace_fraction",)),
    "aligned_timing": (True, TIMING),
    "aligned_backspace": (True, TIMING + ("backspace_fraction",)),
    "aligned_errors": (True, TIMING + ("backspace_fraction", "reference_error_fraction", "extra_press_fraction")),
}
LABELS = {"raw_timing": "200 keypresses: timings", "raw_backspace": "200 keypresses: + backspaces",
          "aligned_timing": "200 reference characters: timings", "aligned_backspace": "200 reference characters: + backspaces",
          "aligned_errors": "200 reference characters: + backspaces/errors"}


class FeatureKNN:
    def __init__(self, windows, names, k=5):
        if len(windows) < k:
            raise ValueError("Not enough training windows for k.")
        self.names, self.k = tuple(names), k
        self.center = {n: st.median(w["features"][n] for w in windows) for n in self.names}
        self.scale = {n: max(FLOORS[n], 1.4826 * st.median(abs(w["features"][n] - self.center[n]) for w in windows)) for n in self.names}
        self.examples = [{n: w["features"][n] for n in self.names} for w in windows]

    def score(self, window):
        f = window["features"]
        distances = [math.sqrt(st.mean(((f[n] - e[n]) / self.scale[n]) ** 2 for n in self.names)) for e in self.examples]
        return st.mean(sorted(distances)[:self.k])


def load_recordings(root, size):
    sessions, skipped = load_sessions(root, size)
    by_hash = {s["hash"]: s for s in sessions}
    seen = set()
    for path in sorted(Path(root).rglob("*_meta.json")):
        if {"older_versions", ".git", ".venv", ".venv-comparison", "venv", "__pycache__"}.intersection(path.parts):
            continue
        csv_path = path.with_name(path.name.replace("_meta.json", ".csv"))
        try:
            text = csv_path.read_text(encoding="utf-8-sig")
            digest = fingerprint(text)
            if digest in by_hash and digest not in seen:
                by_hash[digest]["rows"] = read_csv(text)
                seen.add(digest)
        except OSError:
            continue
    if seen != set(by_hash):
        raise ValueError("Source data changed during loading; rerun with a stable dataset.")
    return sessions, skipped


def identity_split(normal):
    if len({s["day"] for s in normal}) >= 3:
        return split_baseline(normal)
    if len(normal) < 3:
        return normal, [], [], "insufficient_recordings"
    # Reserve normal recordings for testing, independently of comparison outcomes.
    first = max(1, int(len(normal) * .6))
    second = min(len(normal) - 1, max(first + 1, int(len(normal) * .8)))
    return normal[:first], normal[first:second], normal[second:], "provisional_recording_split"


def fit_variant(training, calibration, variant, k, false_alarm):
    aligned, names = VARIANTS[variant]
    models, audit = {}, {}
    sections = sorted({w["section"] for s in training for w in s["aligned"]}) if aligned else [0]
    for section in sections:
        def windows(group):
            return [w for s in group for w in (s["aligned"] if aligned else select_windows([s], "fixed"))
                    if not aligned or w["section"] == section]
        tw, cw = windows(training), windows(calibration)
        if len(tw) < k or len(cw) < 2:
            audit[str(section)] = {"status": "insufficient_data", "training": len(tw), "calibration": len(cw)}
            continue
        model = FeatureKNN(tw, names, k)
        threshold = calibrate([model.score(w) for w in cw], false_alarm)
        models[section] = model, threshold
        audit[str(section)] = {"status": "trained", "training": len(tw), "calibration": len(cw),
                               "threshold": threshold, "features": list(names), "center": model.center, "scale": model.scale}
    return models, audit


def evaluate_variant(session, variant, models, role, reference_days):
    aligned = VARIANTS[variant][0]
    windows = session["aligned"] if aligned else select_windows([session], "fixed")
    predictions = []
    for w in windows:
        section = w["section"] if aligned else 0
        if section not in models:
            continue
        model, threshold = models[section]
        score = model.score(w)
        predictions.append({"section": section, "score": score, "threshold": threshold, "unusual": score > threshold,
                            "margin": (score - threshold) / max(abs(threshold), 1e-6),
                            "physical_keypresses": w.get("physical_keypresses", 200),
                            "reference_characters": w.get("reference_characters"),
                            "features": {n: w["features"][n] for n in model.names}})
    if not predictions:
        return None
    return {**{n: session[n] for n in ("participant", "session", "day", "label", "hash")},
            "role": role, "independent_of_reference_days": session["day"] not in reference_days,
            "window_count": len(predictions), "flagged_windows": sum(w["unusual"] for w in predictions),
            "unusual": st.median(w["margin"] for w in predictions) > 0, "windows": predictions}


def summarize(rows):
    summary = {role: rates([r for r in rows if r["role"] == role])
               for role in ("target_normal", "other_normal", "target_condition")}
    summary["conditions_by_label"] = {label: rates([r for r in rows if r["role"] == "target_condition" and r["label"] == label])
                                      for label in sorted({r["label"] for r in rows if r["role"] == "target_condition"})}
    summary["other_by_participant"] = {pid: rates([r for r in rows if r["role"] == "other_normal" and r["participant"] == pid])
                                        for pid in sorted({r["participant"] for r in rows if r["role"] == "other_normal"})}
    return summary


def run(root, reference, target="P04", k=5, false_alarm=.05):
    if k < 1 or not 0 < false_alarm < .5 or len(reference) < 200:
        raise ValueError("Use positive k, 0 < false alarm < 0.5, and a reference at least 200 characters long.")
    sessions, skipped = load_recordings(root, 200)
    target_normal = [s for s in sessions if s["participant"] == target and s["label"] == "normal" and select_windows([s], "fixed")]
    training, calibration, testing, validation = identity_split(target_normal)
    reference_days = {s["day"] for s in training + calibration}
    other = [s for s in sessions if s["participant"] != target and s["label"] == "normal" and select_windows([s], "fixed")]
    conditions = [s for s in sessions if s["participant"] == target and s["label"] != "normal" and select_windows([s], "fixed")]
    audit = []
    for s in sessions:
        aligned, diagnostics = extract_aligned(s.pop("rows"), reference)
        s["aligned"] = aligned
        audit.append({**{n: s[n] for n in ("participant", "session", "day", "label", "hash")},
                      "aligned_windows": len(aligned), "samples": diagnostics})
    results = {}
    for variant in VARIANTS:
        models, model_audit = fit_variant(training, calibration, variant, k, false_alarm)
        rows = []
        missing = []
        for role, group in (("target_normal", testing), ("other_normal", other), ("target_condition", conditions)):
            for s in group:
                row = evaluate_variant(s, variant, models, role, reference_days)
                if row:
                    rows.append(row)
                else:
                    missing.append({"participant": s["participant"], "session": s["session"], "hash": s["hash"],
                                    "role": role, "reason": "no_supported_window_or_section"})
        results[variant] = {"models": model_audit, "evaluation": rows, "unscored": missing,
                            "all_available": summarize(rows)}
    # Identical recording cohorts for the primary table; event/section coverage still differs.
    common = set.intersection(*(set(r["hash"] for r in results[v]["evaluation"]) for v in VARIANTS))
    for variant, result in results.items():
        selected = [r for r in result["evaluation"] if r["hash"] in common]
        result["paired"] = summarize(selected)
        result["other_participants_paired"] = {pid: rates([r for r in selected if r["role"] == "other_normal" and r["participant"] == pid])
                                               for pid in sorted({s["participant"] for s in other})}
    free_normal = sum(len(select_windows([s], "free")) for s in sessions if s["participant"] == target and s["label"] == "normal")
    return {"created_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(), "target": target, "k": k,
            "window_size": 200, "reference_characters": len(reference),
            "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(), "false_alarm_target_per_window": false_alarm,
            "validation": validation, "independent_normal_test_days": sorted({s["day"] for s in testing} - reference_days),
            "splits": {role: [{n: s[n] for n in ("participant", "session", "day", "hash")} for s in group]
                       for role, group in (("training", training), ("calibration", calibration), ("normal_test", testing))},
            "paired_recording_hashes": sorted(common), "results": results, "alignment_audit": audit,
            "free_text": {"target_normal_windows": free_normal, "status": "no_matching_normal_baseline" if not free_normal else "not_evaluated_in_fixed_text_pilot"},
            "skipped_files": skipped,
            "source_code_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                   for name in ("p04_experiment.py", "aligned_typing.py", "keystroke_model.py", "compare_models.py")},
            "limitations": [
                "Other participants' normal recordings are offline takeover proxies, not observed live handovers.",
                "Keyboard/device and recording-day differences can confound participant discrimination.",
                "Target condition alerts are false takeover alerts for a known same-person recording, not evidence of another typist.",
                "Without independent normal test days, normal false-alert results are provisional recording holdouts.",
                "Aligned windows contain 200 reference characters with variable physical press counts. Raw windows contain 200 usable presses.",
                "Aligned neighbours and calibration are restricted to the same reference section of the target participant.",
                "Eight millisecond timing summaries form the timing-only baseline. Backspace and alignment-error features are added explicitly.",
                "Alignment presets require >=90% match and complete sections; complex edits, caret mismatches, paste and invalid presses are excluded.",
                "Missing caret fields permit append/backspace replay as an assumption and are counted as unverified in diagnostics.",
                "Timing pairs use only genuinely adjacent retained presses; corrections are never stitched into clean transitions.",
                "Session decisions use median threshold-relative margins; aligned sections have their own thresholds.",
                "All scales, neighbours and thresholds use target normal training/calibration only; no comparison outcomes tune settings.",
                "Paired tables share recordings, but alignment changes which events and sections are retained. Coverage is part of the result.",
                "This is exploratory. Reserve untouched future normal days and new participants for final evaluation.",
            ]}


def concise_markdown(report):
    def metric(m):
        return fraction(m["flagged_sessions"], m["sessions"])
    lines = [f"# {report['target']} kNN pilot", "",
             f"k={report['k']}; 200 keypresses or 200 aligned reference characters. Session-level alerts below.", "",
             "Normal = known author; other participants = takeover proxies; condition recordings = same author under another label.", "",
             "## Same-recording comparison", "",
             "| Features / windowing | Normal author falsely flagged | Other authors flagged | Same-author condition falsely flagged |",
             "| --- | ---: | ---: | ---: |"]
    for variant, result in report["results"].items():
        m = result["paired"]
        lines.append(f"| {LABELS[variant]} | {metric(m['target_normal'])} | {metric(m['other_normal'])} | {metric(m['target_condition'])} |")
    if not report["paired_recording_hashes"]:
        lines += ["", "No cohort was scoreable by all variants. See all-available results below."]
    common = set(report["paired_recording_hashes"])
    raw = {r["hash"]: r["unusual"] for r in report["results"]["raw_timing"]["evaluation"] if r["hash"] in common}
    added = {r["hash"]: r["unusual"] for r in report["results"]["raw_backspace"]["evaluation"] if r["hash"] in common}
    sections = [s for s, model in report["results"]["aligned_timing"]["models"].items() if model["status"] == "trained"]
    paired_people = sorted({r["participant"] for r in report["results"]["aligned_timing"]["evaluation"]
                            if r["hash"] in common and r["role"] == "other_normal"})
    lines += ["", f"Paired other-author participants: {', '.join(paired_people) or 'None'}. Supported aligned passage sections: {', '.join(sections) or 'None'} (of four)."]
    if raw and raw == added:
        lines += ["", "Adding backspaces changed no raw-window session decisions in the paired cohort."]
    lines += ["", "## All available recordings (cohorts differ)", "",
              "| Variant | Normal author falsely flagged | Other authors flagged | Same-author condition falsely flagged | Aligned/pooled models trained |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for variant, result in report["results"].items():
        m = result["all_available"]
        lines.append(f"| {LABELS[variant]} | {metric(m['target_normal'])} | {metric(m['other_normal'])} | {metric(m['target_condition'])} | "
                     f"{sum(x['status']=='trained' for x in result['models'].values())} |")
    lines += ["", "## What these results support", "",
              f"- Normal split: {len(report['splits']['training'])} training / {len(report['splits']['calibration'])} calibration / {len(report['splits']['normal_test'])} test recordings.",
              f"- Independent normal test days: {len(report['independent_normal_test_days'])}. "
              + ("False-alert estimates are provisional; no feature set is established as best." if not report["independent_normal_test_days"] else "This remains an exploratory pilot."),
              f"- Free-text normal windows for {report['target']}: {report['free_text']['target_normal_windows']}; status: {report['free_text']['status']}.",
              "- Backspace additions are compared within each windowing method. Alignment comparisons also change retained event coverage.",
              "- Same-author condition alerts are identity errors, not successful takeover detections.", "",
              "Other-author recordings are offline takeover proxies; keyboard/device and recording-day differences may contribute to their separation.", "",
              "Condition labels and individual other-author results remain separate in the JSON; pooled columns above are only compact summaries.", "",
              "## Alignment coverage", "", "| Participant | Accepted attempts / fixed attempts | Accepted 200-character sections | Main exclusion reasons |",
              "| --- | ---: | ---: | --- |"]
    for pid in sorted({a["participant"] for a in report["alignment_audit"]}):
        recordings = [a for a in report["alignment_audit"] if a["participant"] == pid]
        samples = [s for a in recordings for s in a["samples"]]
        reasons = Counter(s["status"] for s in samples if s["status"] != "accepted")
        lines.append(f"| {pid} | {sum(s['status']=='accepted' for s in samples)}/{len(samples)} | "
                     f"{sum(a['aligned_windows'] for a in recordings)} | {cell(', '.join(f'{r}: {n}' for r,n in reasons.most_common(3)) or 'None')} |")
    lines += ["", "Full numerical results, splits, per-participant rates, feature lists and exclusion diagnostics: [results.json](results.json).", "",
              "Use kNN as the primary model. Collect independent normal days and repeat this preset experiment before selecting features.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--target", default="P04")
    parser.add_argument("--reference", type=Path, default=Path(__file__).with_name("fixed_passage.txt"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--false-alarm-target", type=float, default=.05)
    args = parser.parse_args()
    directory = args.output_dir or Path("reports/identity_experiments") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        if directory.exists():
            raise ValueError("Choose a new output directory; previous results are preserved.")
        reference = args.reference.read_text(encoding="utf-8").strip()
        report = run(args.data, reference, args.target, args.k, args.false_alarm_target)
        directory.mkdir(parents=True)
        save_json(directory / "results.json", report)
        (directory / "summary.md").write_text(concise_markdown(report), encoding="utf-8")
        print(f"Report: {directory / 'summary.md'}")
        print(f"Paired recordings: {len(report['paired_recording_hashes'])}. Independent normal test days: {len(report['independent_normal_test_days'])}.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
