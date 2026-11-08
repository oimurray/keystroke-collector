const store = chrome.storage.local;
const $ = id => document.getElementById(id);
const names = Object.fromEntries(KS.PARTICIPANTS);

async function rowsFor(uid) {
  const all = await store.get(null);
  const chunks = Object.keys(all).filter(k => k.startsWith(`ev_${uid}_`)).sort();
  return KS.normalise(chunks.flatMap(k => all[k]));
}

const fileBase = s => `${s.participant_id}_${s.session_id}`;

const meta = s => ({
  participant_id: s.participant_id, session_id: s.session_id, state_label: s.state_label, alertness: s.alertness,
  language: s.language, start: s.start, end: s.end, duration_s: s.duration_s, keystrokes: s.keystrokes,
});

async function exportSession(s) {
  KS.download(`${fileBase(s)}.csv`, KS.toCSV(await rowsFor(s.uid)));
  KS.download(`${fileBase(s)}_meta.json`, JSON.stringify(meta(s), null, 2) + '\n', 'application/json');
}

async function preview(s) {
  const rows = await rowsFor(s.uid);
  const shown = rows.slice(0, 300);
  $('previewWrap').innerHTML = `<h1>${fileBase(s)} <span class="muted">(${shown.length} of ${rows.length} rows)</span></h1>
    <div class="scroll"><table id="preview"><tr>${KS.COLUMNS.map(c => `<th>${c}</th>`).join('')}</tr></table></div>`;
  for (const r of shown) {
    const tr = $('preview').insertRow();
    for (const c of KS.COLUMNS) tr.insertCell().textContent = r[c] ?? '';
  }
}

async function render() {
  const { sessions = {}, active } = await store.get(['sessions', 'active']);
  const list = Object.values(sessions).sort((a, b) => b.start_epoch - a.start_epoch);
  const t = $('sessions');
  t.innerHTML = '<tr><th>Participant</th><th>Session</th><th>State</th><th>Alertness</th><th>Start</th>'
    + '<th>Duration</th><th>Keystrokes</th><th></th></tr>';
  if (!list.length) t.insertRow().insertCell().textContent = 'No sessions yet.';
  for (const s of list) {
    const tr = t.insertRow();
    const live = active?.uid === s.uid;
    const cells = [
      `${names[s.participant_id] ?? ''} (${s.participant_id})`, s.session_id, s.state_label, s.alertness,
      new Date(s.start).toLocaleString(),
      live ? 'recording…' : `${Math.floor(s.duration_s / 60)} min ${s.duration_s % 60} s`,
      s.keystrokes.toLocaleString(),
    ];
    for (const c of cells) tr.insertCell().textContent = c;
    const actions = document.createElement('div');
    actions.className = 'row';
    const btn = (text, fn, cls = '') => {
      const b = Object.assign(document.createElement('button'), { textContent: text, className: cls, onclick: fn });
      actions.append(b);
      return b;
    };
    btn('View', () => preview(s));
    btn('Export', () => exportSession(s)).disabled = live;
    btn('Delete', async () => {
      if (!confirm(`Permanently delete ${fileBase(s)} (${s.keystrokes} keystrokes)?`)) return;
      await chrome.runtime.sendMessage({ type: 'delete', uid: s.uid });
      $('previewWrap').innerHTML = '';
    }, 'danger');
    tr.insertCell().append(actions);
  }
}

$('exportAll').onclick = async () => {
  const { sessions = {}, active } = await store.get(['sessions', 'active']);
  for (const s of Object.values(sessions)) if (s.uid !== active?.uid) await exportSession(s);
};

chrome.storage.onChanged.addListener((c, area) => {
  if (area === 'local' && (c.sessions || c.active)) render();
});

render();
