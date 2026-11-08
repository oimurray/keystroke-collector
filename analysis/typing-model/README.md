# Typing models, experiments and author demo

## Current entry point and experiment history - 8 November 2026

For the current multi-person fixed-text demo, run **identity-demo.cmd** and open
**http://127.0.0.1:8768**. This trains the local profiles and writes a new evaluation
before starting the server. The older baseline explorer below remains available
as a separate workflow on port 8765; its generated model files are not shipped
with the source and must be trained locally.

Read [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md) for the chronological experiments,
measured results, exact run IDs and reproduction commands. It is checked in so
teammates and their agents can understand the work even though detailed reports
and numerical model artifacts remain ignored by Git.

| Experiment on 8 Nov | Features / scope | Main observation |
| --- | --- | --- |
| Four-model benchmark | 11 features, 200 keypresses; personal anomaly task | Baseline/kNN/LOF flagged 5/5 comparison sessions; Isolation Forest 3/5. Normal test-day false-alert rates unavailable. |
| Window-size sweep | Same 11 features, 100/200/400; fixed recording splits | Baseline/kNN/LOF flagged 5/5 at each size. Retained 200 for the working demo, not as a validated optimum. |
| P04 ablations | 8 timing features, then backspaces; raw vs aligned sections | Backspaces changed no paired raw-window session decisions. Alignment reduced coverage and was not established as better. |
| Per-member identity evaluation | 8 timing features, kNN, 200 presses; expected-author task | Separate normal false alerts, other-author detections and same-author condition false alerts for P01-P04. All normal test sets remain provisional. |

The anomaly and identity tasks have different meanings for a flag: an impaired-
labelled recording may be an interesting anomaly, but if it is still the expected
person it is a **false takeover alert**. Keep those results separate. An expected
author is selected explicitly; the demo does not guess which person typed.

A working offline model for exports from `C:\Vs_repos\keystroke-collector`.
It learns a personal normal-typing baseline and scores new recordings for unusual
timing. A local browser interface accepts CSV uploads. Core models and demos
require no third-party Python packages, cloud service, API key or GPU; the
optional LOF/Isolation Forest benchmarks require scikit-learn. Python 3.10+ is required.

## Start using the trained model

1. Double-click **start.cmd** in this folder. Keep its terminal open.
2. Open **http://127.0.0.1:8765** in Chrome or another browser.
3. Choose **Personal baseline** or **kNN neighbours (k=5)** in the model selector.
4. Choose a CSV exported by the collector and click **Compare with baseline**.

Training creates `models/baseline.json`; it is not included in the code checkout.
On the development dataset it contains fixed-text profiles for P01, P02, P03,
and P04. No usable free-text profile could
be trained from the available baseline data. A free-text upload therefore reports
**No matching baseline**. Do not relabel free text as fixed to obtain a score.

Results mean:

- **Within baseline:** the median window distance is below the alert threshold.
- **Unusual typing:** the median window distance is above the alert threshold.
- **More typing needed:** no complete usable window was extracted.
- **No matching baseline:** that participant/text type has no supported model.

Each result includes window scores, the threshold, unusual-window count, and
the features contributing most to the distance. Scores are distances, not
probabilities. They are not calibrated measures of alcohol level or fatigue.
Ordinary distraction, keyboard changes, and other factors can change typing.
A result cannot establish fitness to drive or perform other safety-critical tasks.

The results dashboard plots each window against the model's threshold. Use
**Inspect a window** to see its largest contributors and all eleven feature
values alongside their baseline references. For kNN, the dashboard also shows
the actual selected reference-window distances; their mean is that window's
score. The kNN diagram is a conceptual illustration, not a projection of the
uploaded recording. Expand the validation and recording-quality sections for
baseline provenance and extraction counts, or use **Download result JSON**
to save the complete numerical output locally.

HTML/CSS changes appear after refreshing the page. Restart the server after
changing Python code or trained models.

Baseline recordings used for training/calibration are explicitly marked when
uploaded again. Their scores are not independent test results. The UI does not
require the condition metadata for prediction, so the true condition is not a
model input. Uploaded CSVs are processed in memory and not saved by the server.

## Train again after collecting more data

Keep each export CSV beside its matching `_meta.json`. Double-click **train.cmd**,
to train both models, then restart **start.cmd** to load them. The server keeps its models in
memory until restarted. Existing model/report outputs are replaced by training.

From PowerShell in this folder:

```powershell
python keystroke_model.py train --data "C:\Vs_repos\keystroke-collector"
python keystroke_model.py train --data "C:\Vs_repos\keystroke-collector" --method knn --k 5
python keystroke_model.py serve
python keystroke_model.py predict "C:\path\to\P04_S30.csv" --output "reports\prediction.json"
python keystroke_model.py predict "C:\path\to\P04_S30.csv" --model models\knn.json --output "reports\prediction_knn.json"
```

`train.cmd "C:\another\export-folder"` uses another source directory. The tool
reads that directory recursively but never edits it. `older_versions` is excluded;
duplicate CSV content is skipped. Files lacking the `text_type` column are skipped
instead of guessing their task. The evaluation report records all skipped files.

To compare window lengths, keep separate artifacts:

```powershell
python keystroke_model.py train --data "C:\Vs_repos\keystroke-collector" --window-size 100 --model models\baseline100.json --report reports\evaluation100.json
python keystroke_model.py serve --model models\baseline100.json --port 8766
```

## Method

Two models are available. The **Personal baseline** method compares a window with
the median normal feature vector. **kNN neighbours** compares it with its five
closest individual normal training windows. Both use exactly the same features,
robust training-only scales, recording splits, and calibration procedure.

For kNN, each neighbour distance is the root mean square of feature differences
divided by their training scales. The score is the arithmetic mean of the five
smallest distances. Training examples come from the same participant and text
type only. kNN can represent several normal typing patterns instead of assuming
one central pattern. It may or may not improve detection on your data.

The five-neighbour setting is a preset, not selected using impaired test results.
Change it with `--k`, and use separate model/report paths for experiments. A
profile needs at least `max(3, k)` training windows and two calibration windows.
kNN stores numerical feature vectors in `models/knn.json`; it stores no typed
characters. Keep this artifact private like the original baseline model.

Each model has its own calibrated threshold. Compare a score with that model's
threshold, rather than comparing raw scores between models. kNN feature
explanations describe changes relative to its selected neighbours. Calibration
windows and comparison-condition windows never become kNN reference examples.
An uploaded training recording can find itself among its neighbours; the existing
reference-recording warning still marks its result as unsuitable for evaluation.

The default server automatically offers both models when `models/baseline.json`
and `models/knn.json` exist. For custom files use:

```powershell
python keystroke_model.py serve --model models\baseline100.json --knn-model models\knn100.json
```

The website clears the previous result when switching models. Select a model
and click **Compare with baseline** again to rescore the same selected CSV.

The model trains only on recordings with metadata `state_label: normal` by
default. Verify that these really are rested, sober recordings: the existing
`normal` label does not guarantee this. `--baseline-label rested_sober` lets you
use an explicitly defined new baseline label instead.

1. Match down/up events by press ID within a recording; reject ambiguous,
   incomplete, forced-release, auto-repeat, and pasted data. Exclude modifiers.
2. Keep fixed/free tasks separate. Segment at focus interruptions, task changes,
   or invalid presses. Windows contain 200 usable keypresses by default, without
   overlap. Short messages may be combined within a task segment, but interkey
   timing never spans message boundaries. Incomplete final windows are unused.
3. Extract eleven features: hold median/IQR/p90; press-to-press median/IQR/p90;
   release-to-press median/IQR; overlap, backspace, and long-pause fractions.
   Gaps above two seconds are excluded from ordinary latency statistics and
   counted in the pause fraction. Negative flight times are valid key overlaps.
   Holds over five seconds are excluded. These are explicit pilot assumptions.
4. Learn feature medians and MAD-based scales from baseline training windows.
   Minimum scales avoid numerical instability when baseline variability is tiny.
5. Score using the root mean square of absolute standardized feature deviations.
   Feature correlations are not modeled; this is an explainable first baseline.
6. Choose a conservative empirical threshold from separate baseline calibration
   recordings. The default false-alarm target is 5% **per window**, a calibration
   setting rather than a measured or guaranteed future false-alarm rate. A
   session result uses the median window score; its error rate must be evaluated
   separately. No tired/alcohol labels tune the score or threshold.

Signed session-relative timestamps are accepted: older exports have negative
origins. Features use time differences, so a constant clock offset has no effect.
Negative-event counts appear in recording quality diagnostics. This does not
repair a clock that changes offset within a recording.

## Evaluation and present limits

Training writes `reports/evaluation.json`, including the session inventory,
extraction quality, exclusions, data split, and scores on comparison conditions.
Condition labels other than the baseline are reported separately and are not
automatically interpreted as verified impairment.

Splits are chronological and keep complete recording days together when possible:

| Available baseline days | Training | Calibration | Baseline test |
| --- | --- | --- | --- |
| 3 or more | All but final two | Penultimate day | Final day |
| 2 | First day | Second day | Unavailable |
| 1 | Earlier 75% of recordings | Later recordings | Unavailable; provisional |

Dates use the metadata start time's UTC date; sessions close to midnight or from
the same study visit should be reviewed and assigned a proper visit ID before
a formal study. At least three training windows and two calibration windows are
required. These small minima make the prototype usable, not statistically validated.

The initial P01/P03/P04 profiles use same-day calibration. P02 has separate
training/calibration days but no independent baseline test day. Consequently,
none currently establishes an independent-day baseline false-alert rate. Available
tired/alcohol fixed-text recordings are flagged, but they represent few people
and comparison days. Do not interpret these exploratory results as an accuracy
claim. There is no supported three-way rested/tired/drunk classifier yet.

Next collect rested baseline and comparison visits on multiple days for the same
people, with the same keyboard and tasks in every condition. Reserve untouched
future days for a final test. Use the separate false-alert and condition detection
rates, per person and window length, as the next experimental deliverable.

## Files and privacy

- `keystroke_model.py`: feature extraction, training, prediction, and CLI.
- `app.py` / `index.html`: loopback-only browser interface.
- `models/baseline.json` / `models/knn.json`: trained models; no raw typed characters.
- `reports/evaluation_knn.json`: kNN evaluation on the same split as the baseline.
- `reports/knn_comparison.md`: initial comparison and interpretation limits.
- `reports/evaluation.json`: pseudonymous condition labels, dates, source paths
  for skipped files, data-quality counts, and evaluation results.

Model/report outputs are ignored by Git because they still contain personal
study metadata. Source recordings remain in the collector repository. The server
listens only on 127.0.0.1 and rejects foreign browser origins. Stop with Ctrl+C.

## Compare four models on identical data

The optional benchmark compares Personal baseline, kNN, Local Outlier Factor
(LOF), and Isolation Forest. It produces a readable Markdown report and full JSON
in `reports/model_comparison.*`. These private outputs are ignored by Git.
The website continues to offer its two existing models; this benchmark does not
replace their saved models or thresholds.

One-time setup, from this `analysis/typing-model` folder in PowerShell:

```powershell
python -m venv .venv-comparison
.\.venv-comparison\Scripts\python.exe -m pip install -r requirements-comparison.txt
```

Then double-click **compare.cmd**, or run:

```powershell
.\.venv-comparison\Scripts\python.exe compare_models.py --data ..\..
.\.venv-comparison\Scripts\python.exe -m unittest discover -s tests -v
```

`compare.cmd "C:\another\export-folder"` changes the input folder. The comparison
only reads source recordings. Use `--output` and `--markdown` to preserve reports
from different experiments. All four methods use the same eligible profiles,
eleven features, normal training/calibration/test splits and training-only robust
scales. kNN defaults to k=5; LOF uses novelty mode and min(20, training windows - 1)
neighbours; Isolation Forest uses 200 trees and seed 42. These are presets rather
than settings selected using comparison-condition results.

Each model receives its own empirical calibration threshold at the same per-window
false-alert target (5% by default). The benchmark does not apply the website's
legacy 0.1 distance-threshold floor, which would be inappropriate for other score
units. Compare alert rates rather than raw scores or website threshold values.

The report separates normal-test false alerts from comparison-condition flag
rates, counts both session-task and window results, and shows participant-days,
per-person/text-type results, shared splits, and unscored recordings. Conditions
on training/calibration days are explicitly separated from independent-day
comparisons. Missing normal test days produce **Unavailable**, never 0%.
Repeated windows are correlated; these counts do not establish an independent
sample size. Reports do not rank a winner or interpret condition labels as
verified impairment. Keep future test days untouched while developing models.

The original commands still run without third-party dependencies. Comparison
tests skip when scikit-learn is absent; run the full suite using the environment
above to exercise all four methods.

## Experiment with window sizes

Double-click **window-experiment.cmd** to compare **100, 200 and 400 usable
keypresses** across all four models. It uses the comparison environment described
above. An optional first argument selects another export folder.

From this folder in PowerShell:

```powershell
.\.venv-comparison\Scripts\python.exe window_experiment.py --data ..\..
# Optional custom sizes (minimum 50) and a new output directory:
.\.venv-comparison\Scripts\python.exe window_experiment.py --data ..\.. --sizes 50 100 200 400 --output-dir reports\my-window-study
```

Every run creates a new timestamped directory in `reports/window_experiments/`
containing `window_experiment.md`, full JSON, a split manifest, and detailed
Markdown/JSON reports for each size. Existing output directories are refused
to preserve previous results. These local outputs remain ignored by Git.

The experiment selects recording splits once using the smallest requested size,
then fixes those exact recordings for every size, even if some produce no large
windows. Each model and threshold is refitted independently at every size.
The primary **paired** results include only recording/text-type pairs scoreable
by every model at every size. Separate all-available results and coverage tables
show how many recordings, windows and usable keypresses are lost as size grows.
The report includes per-participant/text-type results, comparison labels kept
separate, and window duration summaries. Incomplete windows are discarded;
windows do not overlap or align with particular passage positions.

Run it now and again after adding new data. Past results stay intact. New runs
recompute splits once for the expanded dataset, so changes between run folders
can reflect new data and new assignments as well as model performance. Compare
sizes within one run. Rerunning old test days during development makes them
exploratory; reserve untouched future days for the final test after selecting a
window size. Missing normal test days are reported as **Unavailable**, not 0%.

## P04 identity and feature experiments

Double-click **p04-experiment.cmd**, or run from this folder:

```powershell
python p04_experiment.py --data ..\..
```

This standard-library-only pilot uses kNN (k=5) and focuses on P04. It compares
eight timing summaries against timings plus backspace fraction, then repeats
that feature comparison on aligned 200-character passage sections. A fifth
variant adds residual reference-error and extra-press fractions. The existing
website/model artifacts are unchanged.

The committed `fixed_passage.txt` is the 800-character prose passage from the
supplied recording instructions, with PDF layout whitespace collapsed to single
spaces. The random alphanumeric tasks are not part of this reference.
No participant recordings are copied into it.

**Aligned windows are 200 reference characters, not exactly 200 physical presses.**
Corrections remain counted. Matched-character timing pairs never bridge removed
errors or backspaces. Only ordinary end-of-buffer typing and Backspace are
replayed; complex edits, caret mismatches, paste and invalid presses are rejected.
Absent caret information is explicitly counted as unverified. Complete sections
require at least 90% character matches and no focus interruption within the
section. Every aligned section needs >=5 normal training examples and >=2
calibration examples; unsupported sections are left unscored.

Training/calibration/testing use the same target recordings for every variant.
With three or more baseline days, complete days are split as in the main model.
Otherwise, chronological normal recordings are split 60% / 20% / remainder for
a **provisional recording-holdout** test. Normal test days overlapping reference
days are not called independent. No test/comparison labels select features,
neighbours or thresholds. Each variant has its own normally calibrated threshold
(per passage section for alignment). The median threshold-relative margin makes
the session decision; it is not a probability.

The identity evaluation includes normal recordings from other participants as
offline takeover proxies. Target impaired/tired recordings are still the same
author, so their alerts count as false takeover alerts, reported separately from
other-author detections. Results are kept per condition and participant in JSON.
The experiment reports free-text availability; a fixed-text model is never used
as a free-text baseline.

Every run creates a new `reports/identity_experiments/<UTC timestamp>/` folder
with a short `summary.md` and detailed `results.json`. Paired results share the
same recordings across all variants; all-available results and alignment audit
counts show the coverage cost. Source CSVs remain untouched and raw typed text
is not written into reports. To study another target, pass `--target P02`.
Rerun after collecting independent normal days and preserve untouched future
recordings for final evaluation.

## Multi-person fixed-text demo and evaluation

Double-click **identity-demo.cmd** from this folder. It trains a separate kNN
profile for each supported member, writes a new evaluation snapshot, and starts
the local demo at **http://127.0.0.1:8768**. Keep the terminal open; stop with
Ctrl+C. An optional first argument chooses another collector data folder.
No third-party packages are needed for this workflow.

The demo uses **k=5, 200 usable keypresses, eight timing features**, matching the
timing-only control from the P04 experiment. It does not use aligned sections,
backspace counts or condition labels as input features.

1. Select the **expected author**. That selection determines the profile; a
   participant ID inside a CSV does not select the profile.
2. Choose **Live typing**, **CSV upload**, or **Replay**.
3. For live typing, start a session and copy the displayed passage in the typing
   box. Timing is collected only in that box while recording is active. Complete
   200-keypress windows are scored automatically. Stop & score processes the
   remaining events, but incomplete windows still receive no score.
4. To demonstrate a handover, keep the expected author unchanged and give the
   keyboard to another member. **Mark handover** ends the old timing segment so
   a new window cannot join typing across the marked boundary. It clears the
   typing box while retaining earlier timing results, so the next person starts
   the passage again. Any incomplete tail is unused. The next member needs 200
   usable keypresses in a fresh segment.
5. **Replay** uses stored numerical windows from the first held-out normal
   recording per member and first complete recording per comparison condition.
   It is explicitly labelled prerecorded. Scores are recomputed for the chosen
   expected author; use Next window to step through the example. Actual source
   author/condition labels are context, not scoring inputs.

The result prominently shows the **latest completed window**. Its status can
change before the session median if a handover occurs late in a session. Both
measures and the underlying scores/nearest neighbours are visible. A change can
reflect another person or variation in the same person; it is not a verified
takeover or impairment diagnosis. Source recordings used for that profile's
training/calibration are explicitly marked when uploaded again.

Live capture is a demo, not an additional study-data collector: source CSVs are
processed in memory and uploads/live recordings are not saved by the server.
Use the extension and its metadata export for further study collection. Clear
the session before another test. Keep keyboard/task conditions comparable and
avoid paste/autocomplete, which are excluded by extraction.

Each run writes `reports/member_evaluation/<UTC timestamp>/summary.md` and
`results.json`, and replaces `models/identity.json` with the latest profiles.
Model/report artifacts are ignored by Git. The model contains numerical training
and replay features with study metadata, but no typed characters. Reports show
normal-author false alerts, other-author detections, same-author condition
alerts by label, an expected-versus-source alert matrix, exact splits and coverage.

Normal training/calibration/test recordings are separated for each member. With
>=3 baseline days, complete days are held apart; otherwise the preset 60/20/rest
chronological recording split is explicitly provisional. Other members' normal
recordings act as offline takeover proxies. Device/day differences can confound
separation, and no final accuracy claim is made without new independent-day tests.

To train/evaluate without starting the demo, or start existing profiles:

```powershell
python identity_model.py train --data ..\..
python identity_model.py serve --port 8768
```

The older baseline website still works. Its **Open author demo** link goes to
`/identity`; restart its server after building the identity model to load it.

## Verify

```powershell
python -m unittest discover -s tests -v
```

Tests cover timing shifts, negative clock origins, overlapping keys, data rejection,
message boundaries, day separation, reference-data warnings, unknown participants,
and a real HTTP upload through the local server. The HTTP test requires loopback
network access and uses temporary model data; no real typed text is transmitted.
