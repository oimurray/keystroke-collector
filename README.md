# Keystroke Collector

Chrome extension (Manifest V3) that records key press/release timings while you chat with an LLM, for our keystroke-dynamics project (INSA Lyon, Data Mining).

## Current project status - 8 November 2026

The active demo is **fixed-text expected-author verification**, using a separate
**kNN profile per member (k=5), 200 usable keypresses per window, and eight timing
features**. Select an expected author and type live, upload a CSV, or replay a
clearly labelled recorded example. The model flags a change from that author's
baseline; it does not identify the new author or diagnose impairment.

With Python 3.10+ installed, from the repository root:

```powershell
cd analysis/typing-model
.\identity-demo.cmd
```

Open **http://127.0.0.1:8768**. The launcher trains from the available collector
exports and writes a fresh per-member evaluation. Generated models and detailed
reports are local and ignored by Git; teammates regenerate them from their clone's
data. Use the extension for study collection; the live demo does not save recordings.

| Development stage | What was tested / decided |
| --- | --- |
| Initial prototype | Personal baseline and kNN; local CSV results dashboard. |
| 8 Nov: model comparison | Baseline, kNN, LOF and Isolation Forest on shared splits; no independent normal test days, so no accuracy winner established. |
| 9 Nov: covariance whitening | Optional shrinkage-whitened kNN added to the identity demo and five-model benchmark; original models remain available. |
| 8 Nov: window sizes | 100/200/400 keypresses with fixed recording assignments; retained 200 as a working preset, not a proven optimum. |
| 8 Nov: P04 feature/alignment pilot | Timing-only vs backspaces and aligned passage/error features; backspaces did not change paired raw-window decisions; alignment was not established as an improvement. |
| 8 Nov: member demo | Profiles for P01-P04, live/upload/replay modes, explicit expected author and separate latest-window/session scores. |

The checked-in [experiment log](analysis/typing-model/EXPERIMENT_LOG.md) contains
the actual counts, protocol changes, run IDs, limitations and reproduction commands.
Read it before interpreting or extending the analysis. The
[analysis README](analysis/typing-model/README.md) documents the scripts and UI;
[team setup notes](analysis/typing-model/SHARE.md) explain what to pull and run.

**Current evidence is exploratory:** all normal test sets lack independent test
days; repeated other-author recordings are not independent live takeovers.
Same-author tired/impaired recordings can also trigger alerts. The next priority
is repeated normal typing on new days per member, with untouched future days
reserved for final evaluation. The current deliverable is a 20-minute
presentation/demo followed by 10 minutes of questions; no slide deck is included.

## Install

Extension code is in **`extension/`**. The root `manifest.json` is a compatibility
entry point for existing unpacked installs; it references the same files inside
`extension/`. Keeping the existing root-loaded entry preserves its load path and
local browser storage. After pulling this reorganisation, click **Reload** on
that entry in `chrome://extensions`, then reload already-open LLM tabs. Do not
remove/reinstall it just to apply the update.

For a new install:

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and select the **`extension/` subfolder**.
3. Pin the extension, then **reload any LLM tabs that were already open**.

Supported sites (tick or untick them in the popup): chatgpt.com, chat.openai.com, claude.ai, gemini.google.com, chat.mistral.ai.

See [extension setup notes](extension/README.md) for both load layouts. A new
install in a different folder does not automatically inherit another install's
stored recordings.

## Repository layout

```text
extension/                 Chrome extension source and authoritative manifest
data/elias/                P02 current CSV/metadata pairs
data/elias/older_versions/ Archived P02 pair; excluded from model training
data/blaise-newman/        P04 exports
data/oimurray/             P01 exports
data/xia-jin/              P03 exports
data/archive/collected_data/ Remaining legacy archive; older_versions stays excluded
analysis/typing-model/     Models, experiments, demo and synthetic tests
scripts/                   Sharing and extension verification tools
manifest.json              Generated compatibility entry point for root-loaded installs
```

On 8 November, 20 current P02 pairs and one archived pair were relocated without
changing their contents. The remaining legacy `collected_data/` directory was
archived under `data/archive/`. Participant IDs and recording metadata remain
unchanged. Existing generated reports retain their historical source paths;
regenerated reports use the new layout.

From the repository root, run `npm run check:extension` to check both extension
load layouts, resource paths, popup navigation and worker storage behaviour. If
you edit `extension/manifest.json`, run `npm run extension:sync` to update the
root compatibility manifest, then rerun the checks.

## Recording a session
1. Open the popup and choose your **participant**. Session files contain only P01–P04; the shared parent folder uses your Git username.
2. **First time only:** click **Run test**, then type `.tie5Roanl` + Enter 10 times. This checks that the recorder works on your machine. After it passes, it becomes optional.
3. Choose a **state** (or add a new label with **+ Add**) and your **alertness** (1–5).
   Set **Text type** to **Free text** or **Fixed text** for the passage you are about to type. You can switch it while recording, so change it whenever the LLM gives you a different kind of text. The REC badge shows the current type.
4. Click **Start recording**. A red **● REC** badge with a keystroke counter appears on the chat page.
5. Chat in **English** for about 15 minutes, with at least 2,000 keystrokes. Type every message yourself: no paste, no autocomplete.
6. Click **Stop recording**, then **View / export data**, then **Export**. Keep each CSV beside its matching `_meta.json` in your Downloads folder.
7. In this repository, run `npm run share`. This copies the exported sessions into `data/<username>/`, commits only that folder, rebases on the remote branch, and pushes the commit. Delete the session from the extension only after the push succeeds.

Session numbers (S1, S2, …) count up automatically for each participant on each machine.

## Sharing data through Git

The share command requires **Node.js 18 or newer**, Git, and push access to the configured remote. No npm packages need to be installed. It uses `~/Downloads` and your Git `user.name` by default, turning spaces and punctuation into hyphens in the folder name. For example, `Xia JIN` becomes `data/xia-jin/`.

```sh
# Preview the files and destination without changing anything
npm run share -- --dry-run

# Share exports from the default Downloads folder
npm run share

# Use another export folder or username
npm run share -- --source "/path/to/exports" --user "Xia JIN"

# Put P02 exports in the established Elias folder
npm run share -- --user elias

# Organise and commit locally, without pulling or pushing
npm run share -- --no-push
```

Only files named exactly `Pxx_Sn.csv` and `Pxx_Sn_meta.json` are collected, and both files must be present. Existing identical files are skipped; the command refuses to overwrite a same-named file with different content. Other modified or staged files in the repository are not included in the data commit. The automatic pull uses `--rebase --autostash`; if Git reports a conflict, the data commit remains local so you can resolve it and push manually.

**Warning:** the CSV contains typed text. Running the push command publishes it to the Git remote and its parent folder reveals the configured username. Use only harmless study text and make sure all participants consent to the repository's visibility.

## What is recorded
Only keys typed in the chat box of the ticked sites while recording is on. `<input>` fields (including passwords) are never recorded.

**CSV** (one row per key press, release or marker). The first 8 columns are the class's common format:

| column | meaning |
|---|---|
| participant_id, session_id | P01–P04, S1… |
| sample_id | one message (a burst of typing ended by Enter or by sending) |
| event | `down`, `up` or `marker` |
| key_code | physical key (`KeyA`, `ShiftLeft`…) |
| timestamp_ms | ms since session start (sub-ms precision) |
| press_id | links an `up` to its `down` |
| key | character produced |
| t_epoch_ms | absolute time (Unix ms) |
| shift, ctrl, alt, meta, capslock | modifier state at the event (0/1) |
| location | 0 standard, 1 left, 2 right, 3 numpad |
| repeat_count | auto-repeats while the key was held (on the `up` row) |
| input_type | what the press did: `insertText`, `deleteContentBackward`, `insertFromPaste`… |
| text_len, caret_pos | length of the message and caret position at the event |
| detail | marker name (`sample_start`, `sample_end:enter`, `sample_end:cleared`, `blur`, `focus`, `visibility_hidden`, `paste`) or `forced_release` on an `up` row synthesised when the window lost focus |
| text_type | `free` or `fixed`, as set in the popup when the row was recorded (`fixed` for the collector test) |

**meta.json** holds the participant, session, state label, alertness, language, start/end time, duration and keystroke count.

## Notes for analysis
- Split free and fixed text with `text_type`. If it was switched mid-message, the sample's rows will have mixed values.
- Hold = `up.timestamp_ms − down.timestamp_ms` for the same `press_id`. Latencies (DD/UD/UU/DU) come from consecutive `down` rows.
- Drop or flag samples that contain a `paste` marker or `insertFromPaste`.
- Use `blur`/`visibility_hidden` markers and long gaps to remove reading or thinking pauses.
- `sample_end:cleared` marks a message sent with the send button. It is logged at the next keypress, so don't use its timestamp.
- Language is English (the brief asks for French; we note this in the report).

## Privacy
Data stays in `chrome.storage.local` in this browser until you export it. The `key` column contains what you typed, so keep conversations to harmless small talk, and turn recording off for anything else. Exported files remain local until you explicitly run the Git share command; pushed data is visible to everyone who can access the remote repository.
