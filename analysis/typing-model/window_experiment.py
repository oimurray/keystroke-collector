"""Paired window-size experiment with fixed recording splits and saved run snapshots."""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import statistics as st
import sys

from compare_models import METHODS, LABELS, aggregate, cell, compare_sessions, fraction, markdown
from keystroke_model import load_sessions, save_json, select_windows, split_baseline


ROLES = ("training", "calibration", "baseline_test")


def plan_splits(sessions, baseline_label):
    """Choose splits once using the smallest requested window size."""
    plan = {}
    for pid in sorted({s["participant"] for s in sessions}):
        for text_type in ("fixed", "free"):
            normal = [s for s in sessions if s["participant"] == pid and s["label"] == baseline_label
                      and select_windows([s], text_type)]
            training, calibration, testing, validation = split_baseline(normal)
            plan[f"{pid}:{text_type}"] = {
                "validation": validation,
                "splits": {role: [{"session": s["session"], "day": s["day"], "hash": s["hash"]} for s in group]
                           for role, group in zip(ROLES, (training, calibration, testing))}}
    return plan


def row_key(row, text_type):
    return row["participant"], row["recording_hash"], text_type, row["role"]


def evaluation_rows(report, method="baseline"):
    rows = {}
    for key, profile in report["profiles"].items():
        if profile["status"] == "compared":
            text_type = key.split(":", 1)[1]
            for row in profile["models"][method]["evaluation"]:
                rows[row_key(row, text_type)] = {**row, "text_type": text_type, "profile": key}
    return rows


def experiment(root, sizes=(100, 200, 400), false_alarm=.05, baseline_label="normal", k=5,
               lof_neighbors=20, seed=42):
    sizes = sorted(set(sizes))
    if len(sizes) < 2 or any(not isinstance(n, int) or n < 50 for n in sizes):
        raise ValueError("Choose at least two different window sizes, each >= 50 keypresses.")
    sessions, skipped = load_sessions(root, sizes[0])
    if not sessions:
        raise ValueError("No readable recordings found.")
    plan = plan_splits(sessions, baseline_label)
    def inventory(items):
        return {(s["hash"], s["participant"], s["session"], s["start"], s["label"]) for s in items}
    initial_inventory = inventory(sessions)
    reports = {}
    coverage = {}
    for size in sizes:
        extracted, exclusions = (sessions, skipped) if size == sizes[0] else load_sessions(root, size)
        if inventory(extracted) != initial_inventory:
            raise ValueError("Source recordings changed during the experiment. Rerun on a stable dataset.")
        report = compare_sessions(extracted, exclusions, size, false_alarm, baseline_label, k, lof_neighbors, seed,
                                  split_plan=plan)
        reports[str(size)] = report
        rows = evaluation_rows(report)
        coverage[str(size)] = {
            "trainable_profiles": sum(p["status"] == "compared" for p in report["profiles"].values()),
            "scored_session_tasks": len(rows), "evaluated_windows": sum(r["window_count"] for r in rows.values()),
            "usable_keypresses": sum(s["quality"].get("usable_keypresses", 0) for s in extracted),
            "extracted_keypresses": sum(s["quality"].get("window_keypresses", 0) for s in extracted),
            "extracted_windows": sum(len(s["windows"]) for s in extracted)}
    # Restrict the paired table to exactly the same recordings/tasks at every size.
    by_size = {size: evaluation_rows(reports[str(size)]) for size in sizes}
    shared = set.intersection(*(set(rows) for rows in by_size.values()))
    union = set.union(*(set(rows) for rows in by_size.values()))
    matched = {}
    for size in sizes:
        report = reports[str(size)]
        matched[str(size)] = {}
        for method in METHODS:
            rows = evaluation_rows(report, method)
            selected = [rows[key] for key in sorted(shared)]
            by_profile = {key: aggregate([r for r in selected if r["profile"] == key])
                          for key in report["profiles"]}
            matched[str(size)][method] = {"overall": aggregate(selected), "by_profile": by_profile}
        coverage[str(size)]["matched_session_tasks"] = len(shared)
        coverage[str(size)]["matched_windows"] = sum(by_size[size][key]["window_count"] for key in shared)
    cohort = []
    excluded = []
    for key in sorted(union):
        row = next(rows[key] for rows in by_size.values() if key in rows)
        identity = {name: row[name] for name in ("participant", "session", "day", "label", "recording_hash", "text_type", "role")}
        if key in shared:
            cohort.append(identity)
        else:
            reasons = {}
            for size in sizes:
                if key not in by_size[size]:
                    profile = reports[str(size)]["profiles"][row["profile"]]
                    reasons[str(size)] = "no_complete_window" if profile["status"] == "compared" else "insufficient_training_or_calibration"
            excluded.append({**identity, "missing_at_sizes": reasons})
    # Profile and zero-window exclusions are also preserved in each size's detailed report.
    return {"version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
            "window_sizes": sizes, "split_anchor_size": sizes[0], "split_plan": plan,
            "configuration": {"baseline_label": baseline_label, "false_alarm_target_per_window": false_alarm,
                              "k": k, "lof_neighbors": lof_neighbors, "seed": seed},
            "source_code_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                   for name in ("window_experiment.py", "compare_models.py", "keystroke_model.py")},
            "coverage": coverage, "matched_cohort": cohort, "excluded_from_matched_cohort": excluded,
            "matched_metrics": matched, "reports": reports,
            "limitations": [
                "Splits are chosen once at the smallest requested size and held fixed across all sizes.",
                "The paired results use only session-tasks scored by all four models at every requested size.",
                "All-available results can include different cohorts; use the paired table when comparing sizes.",
                "Every size refits normal training scales/models and recalibrates its threshold on normal calibration windows.",
                "Window count, training sample count and resolved LOF neighbours change with size; this measures the whole pipeline's response.",
                "No overlap is used. Larger sizes can drop recordings and incomplete tails or dilute short-lived changes.",
                "Window counts are correlated observations, not independent people or visits.",
                "Normal false-alert rates are unavailable without held-out normal test days. No best size is selected.",
                "On each new run, splits are recomputed for the current dataset once. Old runs remain snapshots; new runs may use different splits.",
                "These runs are exploratory. Reserve untouched future days for final evaluation after selecting a size.",
                "This experiment does not align windows to matching positions in the fixed passage.",
            ]}


def experiment_markdown(result):
    sizes = result["window_sizes"]
    lines = ["# Window-size experiment", "", f"Run (UTC): {result['created_utc']}", "",
             "Exploratory results: no winning model or window size is selected.", "",
             f"Sizes: {', '.join(map(str, sizes))} usable keypresses. Recording splits fixed using the {result['split_anchor_size']}-keypress extraction.", "",
             f"Baseline label: {cell(result['configuration']['baseline_label'])}. Per-window calibration target: {result['configuration']['false_alarm_target_per_window']:.1%}. "
             f"kNN k={result['configuration']['k']}; requested LOF neighbours={result['configuration']['lof_neighbors']}; seed={result['configuration']['seed']}.", "",
             "## Coverage", "", "Scored sessions are session-task pairs (fixed/free are separate). Extracted coverage includes training, calibration and unsupported tasks.", "",
             "| Size | Trainable profiles | All scored session-tasks | Paired session-tasks | Evaluated windows (all / paired) | Usable typing in complete windows |",
             "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for size in sizes:
        c = result["coverage"][str(size)]
        lines.append(f"| {size} | {c['trainable_profiles']} | {c['scored_session_tasks']} | {c['matched_session_tasks']} | "
                     f"{c['evaluated_windows']} / {c['matched_windows']} | {fraction(c['extracted_keypresses'], c['usable_keypresses'])} |")
    labels = sorted({r["label"] for r in result["matched_cohort"] if r["role"] == "comparison"})

    def metrics_table(summaries):
        output = ["| Size | Model | Evaluation | Session-task alerts | Window alerts | Participant-days |",
                  "| ---: | --- | --- | ---: | ---: | ---: |"]
        for size in sizes:
            for method in METHODS:
                summary = summaries[str(size)][method]
                items = [("Normal test: false alerts", summary["baseline_false_alerts"])]
                for label in labels:
                    for group, suffix in (("comparison_conditions", "all comparisons"),
                                          ("independent_comparison_conditions", "independent reference days")):
                        metric = summary[group].get(label, aggregate([])["baseline_false_alerts"])
                        items.append((f"{label}: {suffix}", metric))
                for title, m in items:
                    output.append(f"| {size} | {LABELS[method]} | {cell(title)} | {fraction(m['flagged_sessions'], m['sessions'])} | "
                                  f"{fraction(m['flagged_windows'], m['windows'])} | {m['participant_days']} |")
        return output
    lines += ["", "## Paired results: same recordings at every size", "",
              f"Shared cohort: {len(result['matched_cohort'])} session-task pairs. Session-task rates are the primary comparison; window denominators change with size.", ""]
    if not result["matched_cohort"]:
        lines += ["No common cohort is available. Collect more data or reduce the requested sizes.", ""]
    lines += metrics_table({str(size): {m: result["matched_metrics"][str(size)][m]["overall"] for m in METHODS} for size in sizes})
    lines += ["", "## All available results: coverage-dependent cohorts", "",
              "This table includes every scored recording at each size, including recordings excluded from the paired table. Do not interpret different-cohort rates as a controlled size comparison.", ""]
    all_labels = sorted({r["label"] for report in result["reports"].values()
                         for r in evaluation_rows(report).values() if r["role"] == "comparison"})
    labels = all_labels
    lines += metrics_table({str(size): result["reports"][str(size)]["summary"] for size in sizes})
    lines += ["", "## Paired results by participant and text type", ""]
    labels = sorted({r["label"] for r in result["matched_cohort"] if r["role"] == "comparison"})
    for profile in sorted({f"{r['participant']}:{r['text_type']}" for r in result["matched_cohort"]}):
        lines += [f"### {cell(profile)}", ""]
        lines += metrics_table({str(size): {m: result["matched_metrics"][str(size)][m]["by_profile"][profile] for m in METHODS} for size in sizes})
        lines.append("")
    lines += ["## Recording spans in the paired cohort", "",
              "A keypress window is not a fixed duration. These are median first-down to last-up spans of evaluated windows (including pauses within each window), not prediction latency.", "",
              "| Size | Median span (seconds) |", "| ---: | ---: |"]
    shared = {(r["participant"], r["recording_hash"], r["text_type"], r["role"]) for r in result["matched_cohort"]}
    for size in sizes:
        spans = [span for key, row in evaluation_rows(result["reports"][str(size)]).items() if key in shared
                 for span in row["window_spans_seconds"]]
        lines.append(f"| {size} | {st.median(spans):.2f} |" if spans else f"| {size} | Unavailable |")
    lines.append("")
    lines += ["## Paired cohort exclusions", "", "| Participant | Session | Task | Condition | Missing size / reason |",
              "| --- | --- | --- | --- | --- |"]
    for row in result["excluded_from_matched_cohort"]:
        missing = "; ".join(f"{size}: {reason}" for size, reason in row["missing_at_sizes"].items())
        lines.append(f"| {cell(row['participant'])} | {cell(row['session'])} | {row['text_type']} | {cell(row['label'])} | {missing} |")
    if not result["excluded_from_matched_cohort"]:
        lines.append("| — | — | — | — | None |")
    lines += ["", "Profiles never scored at any size and recordings with no complete windows appear in the per-size detailed reports.", "",
              "## Detailed reports", ""]
    for size in sizes:
        lines.append(f"- [{size}-keypress report](size_{size}.md): splits, thresholds, parameters, exclusions and per-session scores.")
    lines += ["- [Split manifest](splits.json)", "- [Full experiment JSON](window_experiment.json)", "",
              "## Limits and rerunning", ""]
    lines.extend(f"- {text}" for text in result["limitations"])
    lines += ["- Rerun window-experiment.cmd after adding data; every run gets a new directory and preserves past results.", ""]
    return "\n".join(lines)


def write_run(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    save_json(directory / "window_experiment.json", result)
    save_json(directory / "splits.json", result["split_plan"])
    (directory / "window_experiment.md").write_text(experiment_markdown(result), encoding="utf-8")
    for size, report in result["reports"].items():
        save_json(directory / f"size_{size}.json", report)
        (directory / f"size_{size}.md").write_text(markdown(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 200, 400])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--false-alarm-target", type=float, default=.05)
    parser.add_argument("--baseline-label", default="normal")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--lof-neighbors", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    directory = args.output_dir or Path("reports/window_experiments") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        if directory.exists():
            raise ValueError("Output directory already exists. Choose a new directory to preserve previous runs.")
        result = experiment(args.data, args.sizes, args.false_alarm_target, args.baseline_label,
                            args.k, args.lof_neighbors, args.seed)
        write_run(result, directory)
        print(f"Report: {directory / 'window_experiment.md'}")
        print(f"Paired cohort: {len(result['matched_cohort'])} session-task pairs. Splits fixed across sizes.")
        if not any(r["role"] == "baseline_test" for r in result["matched_cohort"]):
            print("Independent normal false-alert rates unavailable; no best size can be established.")
    except ImportError:
        print("Install requirements-comparison.txt in the comparison environment first.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
