# Keystroke Collector

Chrome extension (Manifest V3) that records key press/release timings while you chat with an LLM, for our keystroke-dynamics project (INSA Lyon, Data Mining).

## Install
1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and select this folder.
3. Pin the extension, then **reload any LLM tabs that were already open**.

Supported sites (tick or untick them in the popup): chatgpt.com, chat.openai.com, claude.ai, gemini.google.com, chat.mistral.ai.

## Recording a session
1. Open the popup and choose your **participant**. Names are shown only in the popup; files only contain P01–P04.
2. **First time only:** click **Run test**, then type `.tie5Roanl` + Enter 10 times. This checks that the recorder works on your machine. After it passes, it becomes optional.
3. Choose a **state** (or add a new label with **+ Add**) and your **alertness** (1–5).
4. Click **Start recording**. A red **● REC** badge with a keystroke counter appears on the chat page.
5. Chat in **English** for about 15 minutes, with at least 2,000 keystrokes. Type every message yourself: no paste, no autocomplete.
6. Click **Stop recording**, then **View / export data**, then **Export**.
7. Upload `Pxx_Sn.csv` and `Pxx_Sn_meta.json` to the shared folder. Delete the session from the extension once it has been uploaded.

Session numbers (S1, S2, …) count up automatically for each participant on each machine.

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

**meta.json** holds the participant, session, state label, alertness, language, start/end time, duration and keystroke count.

## Notes for analysis
- Hold = `up.timestamp_ms − down.timestamp_ms` for the same `press_id`. Latencies (DD/UD/UU/DU) come from consecutive `down` rows.
- Drop or flag samples that contain a `paste` marker or `insertFromPaste`.
- Use `blur`/`visibility_hidden` markers and long gaps to remove reading or thinking pauses.
- `sample_end:cleared` marks a message sent with the send button. It is logged at the next keypress, so don't use its timestamp.
- Language is English (the brief asks for French; we note this in the report).

## Privacy
Data stays in `chrome.storage.local` in this browser until you export it. The `key` column contains what you typed, so keep conversations to harmless small talk, and turn recording off for anything else.
