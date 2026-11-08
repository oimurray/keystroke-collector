# Experiment timeline and handoff

Updated **8 November 2026 (Europe/Paris)**. This is the checked-in summary for
teammates and analysis agents. Detailed numerical reports are generated locally
under ignored `reports/`; they are not included when this source is pushed.
The tables below preserve the observed aggregate results from this development
dataset. Counts can change when teammates regenerate reports with different data.

## Current working decision

- Task: **fixed-text expected-author verification** for P01-P04.
- Main model: **kNN, k=5, 200 usable physical keypresses per non-overlapping window**.
- Main features: eight timing summaries - hold median/IQR/p90, press-to-press
  median/IQR/p90, release-to-press median/IQR.
- Each expected author has their own normal training set, robust feature scales,
  calibration data and threshold. CSV participant IDs and condition labels do
  not select the model or enter its feature vector.
- Keep backspace/alignment/LOF/Isolation Forest results as exploratory comparisons.
  We did not establish them as improvements over the working preset.
- The demo signals a **change**, not a confirmed takeover, guessed identity or
  impairment diagnosis. Same-author condition changes are a known failure mode.
- Deliverable context: 20-minute presentation/demo plus 10-minute Q&A. This change
  supplies the demo, experiments and documentation, not a presentation deck.

## 1. Initial prototype and UI

The original analysis compared each person's normal typing with new recordings
using a personal median-distance baseline and kNN. The baseline explorer at
port 8765 gained window-score charts, neighbour distances, feature comparisons,
quality/validation details and JSON export. Work was initially developed outside
the collector, then applied to `analysis/typing-model` in this active repo.

The original workflow uses **11 features**: the eight timing summaries above,
plus overlap, backspace and long-pause fractions. This differs from the final
eight-feature identity demo. Do not compare their raw scores as if their feature
spaces or thresholds were identical.

## 2. Four-model benchmark - 8 November

Entry point: `compare_models.py` / `compare.cmd`.

Protocol: baseline, kNN, LOF and Isolation Forest shared the same eligible
participant/text-type profiles, 200-keypress extraction and normal recording
splits. Training-only robust scales; normal-only calibration at a nominal 5%
per-window target; no condition-based hyperparameter search. LOF uses novelty
mode and min(20, training_count - 1) neighbours; Isolation Forest uses 200 trees
and seed 42. Each model gets a threshold in its own score units.

| Model | Tired-labelled sessions flagged | Impaired-labelled sessions flagged |
| --- | ---: | ---: |
| Personal baseline | 3/3 | 2/2 |
| kNN | 3/3 | 2/2 |
| LOF | 3/3 | 2/2 |
| Isolation Forest | 3/3 | 0/2 |

These were **condition/anomaly comparisons**, not impersonation accuracy. There
were no independent normal baseline test days, so normal false-alert rates were
unavailable and no best model was established. Main output:
`reports/model_comparison.{md,json}`. This runner overwrites those default paths;
pass separate `--output` and `--markdown` paths to preserve another run.

## 3. Window-size experiment - 8 November

Entry point: `window_experiment.py` / `window-experiment.cmd`.
Recorded snapshot: `reports/window_experiments/20261108T171616296712Z/`.
Folder timestamps are **UTC run identifiers**, not local recording times.

Protocol: 100/200/400 usable keypresses, the same 11-feature four-model benchmark.
Splits were assigned once using the smallest requested size, then held fixed
across sizes. Each size refitted its own scales/models and recalibrated thresholds.
The primary table uses exactly the same five comparison recording/task pairs.
Separate coverage-dependent tables retain all available results.

| Size | Baseline flagged | kNN flagged | LOF flagged | Isolation Forest flagged | Evaluated windows | Usable typing retained in complete windows* |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 5/5 | 5/5 | 5/5 | 5/5 | 39 | 92.1% |
| 200 | 5/5 | 5/5 | 5/5 | 3/5 | 19 | 87.6% |
| 400 | 5/5 | 5/5 | 5/5 | 2/5 | 7 | 83.6% |

\*Coverage includes extraction across the source dataset, including training,
calibration and unsupported tasks; it is not a detection rate. Normal false-alert
rates remained unavailable. The 200-keypress setting was retained as a practical
working preset, **not proven optimal**. More windows do not mean more independent
participants or visits.

## 4. Fixed passage, corrections and P04 feature pilot - 8 November

Entry point: `p04_experiment.py` / `p04-experiment.cmd`.
Recorded snapshots: `reports/identity_experiments/20261108T180315668400Z/` and
`20261108T180510418009Z/` (the latter adds clearer summary interpretation).

P04 was the primary development case because it has normal and impaired-labelled
fixed-text recordings. It did not have the most normal windows: P02 had 80,
versus P04's 65 at the original 200-keypress extraction.

`fixed_passage.txt` contains the 800-character prose reference from the supplied
recording instructions, with PDF layout whitespace collapsed to single spaces.
The random alphanumeric exercises are excluded from this reference.

Alignment is a separate extraction mode: four sections of **200 reference
characters**, with variable physical press counts when errors/corrections occur.
Only simple end-of-buffer typing/Backspace is replayed. Complex edits, caret
mismatches, invalid/repeated presses and paste are rejected. Missing caret fields
are counted as unverified rather than silently treated as proof of correct replay.
Complete sections require >=90% character matches and no focus interruption.
Clean timing pairs never bridge a removed error or correction.

Compared variants:

1. Eight timing features on ordinary 200-keypress windows.
2. The same features plus backspace fraction.
3. Eight timing features on aligned sections.
4. Aligned timings plus backspace fraction.
5. Aligned timings/backspaces plus residual reference-error and extra-press fractions.

The same P04 normal recording assignments were used for every variant:
**10 training / 3 calibration / 4 test**, all on one normal recording day.
Aligned kNN/calibration references must come from the same passage section.
Only sections **1 and 3** had enough training/calibration examples (>=5 and >=2).

The fair, same-recording table contains **3 P04 normal tests, 22 other-author
normal recordings (P01: 6, P02: 16), and 1 P04 impaired-labelled recording**:

| Variant | Normal P04 false takeover alerts | Other-author detections | Same-author condition false takeover alerts |
| --- | ---: | ---: | ---: |
| Raw timings | 0/3 | 22/22 | 1/1 |
| Raw timings + backspaces | 0/3 | 22/22 | 1/1 |
| Aligned timings | 2/3 | 22/22 | 1/1 |
| Aligned timings + backspaces | 2/3 | 22/22 | 1/1 |
| Aligned timings + backspaces/errors | 0/3 | 22/22 | 1/1 |

All-available raw variants scored 4 P04 normal tests (0 flagged), 34 other-author
normal recordings (34 flagged), and 2 P04 impaired-labelled recordings (2 flagged).
Those denominators differ from the aligned cohort and are **not a controlled
alignment comparison**. All P03 attempts were excluded by conservative alignment
because of complex edits. Aligned models therefore did not establish broader
participant coverage or improved performance.

Takeaway: adding backspaces changed no paired raw-window session decisions.
Alignment alone increased normal false alerts in this small sample; the error
variant changed that result but is not a validated improvement. Keep ordinary
200-keypress timing-only kNN as the working control.

## 5. Per-member identity evaluation and demo - 8 November

Entry point: `identity_model.py` / `identity-demo.cmd`.
Recorded snapshot: `reports/member_evaluation/20261108T183712901063Z/`.

This stage changes the **task** from detecting personal condition anomalies to
checking a claimed/expected identity. For each expected author:

- Fit only that person's normal training windows; calibrate only on their normal
  calibration recordings. Use the eight timing features, k=5 and 200 presses.
- Test held-out normal recordings of that author for false alerts.
- Score other members' normal recordings as offline takeover proxies.
- Score that author's non-normal-labelled recordings separately. Alerts here are
  **false takeover alerts**, since the recording still belongs to the same person.

With >=3 normal days, complete days are separated. Otherwise use the preset
chronological **60% training / 20% calibration / remainder test** recording split.
No participant currently has an independent normal test day under this protocol.

| Expected author | Normal false alerts | Other-author detections | Same-author condition false alerts | Normal train / calibration / test recordings |
| --- | ---: | ---: | ---: | ---: |
| P01 | 0/2 | 41/41 | Unavailable | 6 / 2 / 2 |
| P02 | 0/4 | 31/31 | Unavailable | 12 / 4 / 4 |
| P03 | 0/1 | 47/47 | 3/3 tired-labelled | 2 / 1 / 1 |
| P04 | 0/4 | 34/34 | 2/2 impaired-labelled | 10 / 3 / 4 |

Other-author recordings are reused across expected-author profiles. Do not pool
the off-diagonal counts into an independent sample size or claim general 100%
takeover accuracy. Keyboard/device and recording-day differences may contribute
to separation. P01's comparison recordings and free-text-only conditions that
have no complete supported fixed-text windows are unscored, not successful cases.

Demo features: explicit expected-author selection; live capture only in its
typing box; CSV upload; clearly labelled numerical replays; actual kNN neighbours;
separate latest-window and session-median status; reference-recording warnings;
JSON results. The CSV's claimed participant is context, not a model-selection
input. Mark handover clears the typing box and starts a new segment, retaining
previous results but preventing incomplete windows from joining across people.

Live scoring, replay and narrow-screen rendering were checked in the browser.
CSV prediction, author selection and request validation are covered by HTTP tests.
The full synthetic/HTTP suite passed **43 tests**. The 200-keypress latest-window
status may alert before the cumulative session median; neither proves impairment.

## Reproduce after pulling

Run from `analysis/typing-model`, with Python 3.10+ and matching collector CSV /
`_meta.json` pairs available under the chosen data root. Source paths are read
only. The current clone's recordings, labels and timestamps determine results.

```powershell
# Current demo + fresh per-member evaluation; no third-party packages required.
.\identity-demo.cmd

# Train/evaluate without starting the server.
python identity_model.py train --data ..\..

# P04 timing/backspace/alignment pilot; no third-party packages required.
python p04_experiment.py --data ..\..

# Optional four-model and window-size benchmarks.
python -m venv .venv-comparison
.\.venv-comparison\Scripts\python.exe -m pip install -r requirements-comparison.txt
.\.venv-comparison\Scripts\python.exe compare_models.py --data ..\..
.\.venv-comparison\Scripts\python.exe window_experiment.py --data ..\.. --sizes 100 200 400

# Full suite, including optional model tests and loopback HTTP tests.
.\.venv-comparison\Scripts\python.exe -m unittest discover -s tests -v
```

Plain `python -m unittest discover -s tests -v` also works; optional scikit-learn
tests skip if the dependency is absent. The browser demo uses port **8768**;
the legacy baseline explorer uses **8765** after its own models are trained.

Window/P04/member runners preserve timestamped run folders. Adding data causes
new runs to recompute splits for the expanded dataset; compare settings **within
one run** and use the saved manifests to explain changes between runs.
`models/identity.json` is the latest numerical demo artifact and is replaced by
retraining. It contains reference/replay features and study metadata, not typed
characters. Neither it nor detailed reports or virtual environments are pushed.

## Next work and interpretation rules

1. Collect normal fixed-text typing on new days per member (3-5 days is a practical
   next pilot target, not an established statistical sample-size requirement).
2. Keep passage, keyboard/device and collection procedure comparable; record
   actual study visits and review date boundaries near midnight.
3. Reserve untouched future days and new takeover trials for the final evaluation.
   Today's holdouts have been inspected during development and are exploratory,
   even though their windows do not fit the model or calibration threshold.
4. Rerun the member evaluation and judge normal false alerts alongside other-author
   detections. Keep condition-specific same-author errors separate.
5. Fixed-text results do not establish performance in unrestricted chat. The model
   does not distinguish fatigue, alcohol, distraction or another cause of change.

For agents: check the relevant runner's feature set, split protocol, denominator
and task before comparing tables. Do not relabel free text, train on comparison
conditions, reuse another feature space's threshold, or erase corrections/slow
typing merely to make the data look more consistent. Preserve original exports
and report the coverage cost of preprocessing.
