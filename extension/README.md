# Chrome extension

This folder contains the complete unpacked Chrome extension. For a **new install**:

1. Open `chrome://extensions` and enable Developer mode.
2. Click **Load unpacked** and select this `extension/` folder.
3. Pin Keystroke Collector, then reload any already-open LLM tabs.

If you already loaded the **repository root**, keep that existing install and
click **Reload** on its card in `chrome://extensions`, then reload the LLM tabs.
The root compatibility manifest points into this folder while keeping the same
unpacked load path. Do not remove/reinstall that entry just to update the code.
Recordings remain in the existing extension's local browser storage. A new
install loaded from a different folder is a separate install and does not
automatically inherit those stored recordings.

The authoritative manifest is `extension/manifest.json`. All HTML, CSS and scripts
live here; the repository-root manifest is generated compatibility configuration.
After editing the folder manifest, run from the repository root:

```powershell
npm run extension:sync
npm run check:extension
```

The checks validate both load layouts, page/script assets, popup navigation, and
service-worker session storage behaviour using synthetic browser API stubs.
Existing analysis HTTP tests also check the live demo's recorder asset route.

See the [repository README](../README.md) for recording/export instructions and
`npm run share` usage. Run sharing commands from the **repository root**, not here.
P02's existing exports are under `data/elias/`; to put future P02 exports there:

```powershell
npm run share -- --user elias --dry-run
npm run share -- --user elias
```

The share command publishes data when run without `--dry-run`/`--no-push`, as
documented in the repository README. This reorganisation itself does not commit
or push data.
