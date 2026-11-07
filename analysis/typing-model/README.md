# Typing baseline detector

A working offline model for exports from `C:\Vs_repos\keystroke-collector`.
It learns a personal normal-typing baseline and scores new recordings for unusual
timing. A local browser interface accepts CSV uploads. No third-party Python
packages, cloud service, API key, or GPU is required. Python 3.10+ is required.

## Start using the trained model

1. Double-click **start.cmd** in this folder. Keep its terminal open.
2. Open **http://127.0.0.1:8765** in Chrome or another browser.
3. Choose **Personal baseline** or **kNN neighbours (k=5)** in the model selector.
4. Choose a CSV exported by the collector and click **Compare with baseline**.

The initial trained model is `models/baseline.json`. It currently contains
fixed-text profiles for P01, P02, P03, and P04. No usable free-text profile could
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

## Verify

```powershell
python -m unittest discover -s tests -v
```

Tests cover timing shifts, negative clock origins, overlapping keys, data rejection,
message boundaries, day separation, reference-data warnings, unknown participants,
and a real HTTP upload through the local server. The HTTP test requires loopback
network access and uses temporary model data; no real typed text is transmitted.
