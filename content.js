// Runs on the LLM sites. Records only while a session is active and this site is ticked in the popup.
let active = null, sites = {}, session = null, keystrokes = 0, badge = null;

const recorder = KS.createRecorder({
  findTarget,
  origin: () => session.start_epoch,
  onRows: rows => {
    try {
      chrome.runtime.sendMessage({ type: 'rows', uid: session.uid, rows }).catch(() => {});
    } catch { /* extension was reloaded; this tab needs a refresh */ }
  },
});

// Only the chat box: textareas and rich-text editors. Never <input>, so never password fields.
function findTarget(t) {
  if (!(t instanceof Element) || t.closest('input')) return null;
  return t.closest('textarea, [contenteditable]:not([contenteditable="false"])');
}

function siteEnabled() {
  const h = location.hostname;
  return Object.entries(sites).some(([d, on]) => on && (h === d || h.endsWith('.' + d)));
}

function update() {
  const want = active && siteEnabled() ? active : null;
  if (session && session.uid !== want?.uid) { recorder.stop(); session = null; }
  if (want && !session) { session = want; recorder.start(); }
  renderBadge();
}

function renderBadge() {
  if (!session) { badge?.remove(); badge = null; return; }
  if (!badge) {
    badge = document.createElement('div');
    badge.style.cssText = 'position:fixed;bottom:12px;right:12px;z-index:2147483647;pointer-events:none;'
      + 'background:#c62828;color:#fff;font:600 12px/1 system-ui,sans-serif;padding:7px 11px;'
      + 'border-radius:999px;box-shadow:0 2px 8px rgba(0,0,0,.25)';
    document.documentElement.appendChild(badge);
  }
  badge.textContent = `● REC  ${session.participant_id} ${session.session_id} · ${keystrokes} keys`;
}

chrome.storage.local.get(['active', 'sites', 'sessions']).then(s => {
  active = s.active ?? null;
  sites = s.sites ?? KS.DEFAULT_SITES;
  keystrokes = s.sessions?.[active?.uid]?.keystrokes ?? 0;
  update();
});

chrome.storage.onChanged.addListener((c, area) => {
  if (area !== 'local') return;
  if (c.active) active = c.active.newValue ?? null;
  if (c.sites) sites = c.sites.newValue ?? {};
  if (c.sessions && active) keystrokes = c.sessions.newValue?.[active.uid]?.keystrokes ?? 0;
  if (c.active || c.sites) update();
  else renderBadge();
});
