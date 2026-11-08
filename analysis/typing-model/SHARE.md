# Team setup and sharing

The analysis code now lives directly in this repository at
`analysis/typing-model`. The earlier instructions for copying a separate ZIP
are obsolete. Pull the code and use the collector exports available in your clone.

Read [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md) first for the experiment timeline,
observed counts, protocol changes and limitations. Detailed generated reports
are ignored by Git; the checked-in log preserves the aggregate development results.

## Teammate quick start

With Python 3.10+ installed, from the repository root:

```powershell
cd analysis/typing-model
.\identity-demo.cmd
```

Open **http://127.0.0.1:8768**. Keep the terminal open. Select the expected author,
then use live typing, CSV upload or labelled recorded replay. kNN uses k=5,
200 usable keypresses and eight timing summaries. Each member's profile is trained
and calibrated separately. Use the extension to collect further study data;
the demo does not save live recordings or uploaded files.

For macOS/Linux or to run the steps separately:

```sh
cd analysis/typing-model
python3 identity_model.py train --data ../..
python3 identity_model.py serve --port 8768
```

The train command also writes a fresh per-member evaluation. Source exports need
matching `_meta.json` files, normal labels and known text types. If a profile is
unavailable, collect more supported normal data; do not relabel another task.
Each person runs their own localhost server. A localhost URL does not connect to
another teammate's computer. Restart the server after retraining.

## What belongs in the code commit

- Analysis source, fixed reference passage, launchers, synthetic tests and docs.
- The local `.gitignore`, which excludes models, detailed reports, environments
  and Python caches.
- No new raw study recordings as part of this code-only update.

From the repository root, review before committing/pushing:

```powershell
git status --short
git add -- README.md analysis/typing-model
git diff --cached --stat
git diff --cached --name-only
git commit -m "Add multi-person kNN demo and reproducible typing experiments"
git push
```

These commands use the current branch and its configured upstream. Do not force
push. Data sharing remains a separate workflow (`npm run share`) and requires
the group's existing visibility/consent arrangements.

## Interpretation to keep with the demo

All current normal-author holdouts lack independent normal test days. Other-
author recordings are offline takeover proxies, and device/day differences may
help separate people. Same-author condition recordings also trigger alerts: this
is a limitation for identity verification, not proof of impairment detection.
Collect independent normal days and preserve untouched final tests before making
an accuracy claim. See the experiment log for all observed results and reruns.
