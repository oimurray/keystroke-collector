# Share the model with the group

The model code currently lives in a separate local folder. It is not yet part of
the shared `keystroke-collector` GitHub repository.

## Recommended location

Add the contents of the code-only ZIP under:

```text
keystroke-collector/
  analysis/
    typing-model/
      .gitignore
      README.md
      SHARE.md
      app.py
      index.html
      keystroke_model.py
      start.cmd
      train.cmd
      tests/
```

Keep the supplied `.gitignore`; it excludes generated `models/`, `reports/`, and
Python caches. The ZIP deliberately contains no collected typing data, trained
feature vectors, or participant evaluation reports. Review repository visibility
and participant agreement before sharing any study data separately.

## Add it to the existing repository

Extract the ZIP's `typing-model` folder into `analysis/` in a local clone of the
collector repository. Run these commands from the collector repository root:

```powershell
git status --short
git switch -c codex/typing-models
git add -- analysis/typing-model
git diff --cached --stat
git commit -m "Add personal baseline and kNN typing detectors"
git push -u origin codex/typing-models
```

Review the staged files before committing: only the model source and synthetic
tests should appear. Create a pull request from `codex/typing-models` into `main`
on GitHub, and send its link to the group. The group can also check out that
branch and use it before merging. Do not force-push or include unrelated changes.

## Teammate quick start

After pulling the merged change, with Python 3.10+ installed:

```powershell
cd analysis/typing-model
python keystroke_model.py train --data ../..
python keystroke_model.py train --data ../.. --method knn --k 5
python keystroke_model.py serve
```

On Windows, double-clicking `train.cmd` trains both models and automatically
finds the collector root when installed in the structure above. Then run
`start.cmd`. No additional Python packages are needed.

Open http://127.0.0.1:8765 in a browser. Select **Personal baseline** or
**kNN neighbours (k=5)**, choose a collector CSV, and run the comparison.
Each teammate runs their own local server; localhost links cannot be used to
reach another person's computer. Restart the server after retraining.

For Linux/macOS, use the Python commands above with `python3` if necessary.
Source study data must already be present in the clone. Baseline training requires
matching CSV/metadata pairs and sufficient normal recordings with known text types.

## Current interpretation

The two methods learn personal normal baselines. Both flag the five currently
scorable tired/alcohol comparison recordings, but there is not yet an independent
baseline test day for any participant. This is an exploratory result, not an
accuracy claim. The next collection priority is repeated rested/sober typing on
fresh days, plus matched tasks in comparison conditions. P01's normal recordings
are included; the alcohol recordings are too short and lack a matching free-text
baseline. These limitations should accompany the demo.
